from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from uuid import UUID

from domain.library.repositories import IVideoRepository
from domain.shared.ports import IEventBus, IMediaSource
from domain.song.aggregates import SongInfoAggregate
from domain.song.entities import LyricsSource
from domain.song.ports import ILyricsProvider, ITranslator, LyricsResult
from domain.song.repositories import ISongRepository
from domain.song.value_objects import LyricsLine, SongSourceRef

logger = logging.getLogger(__name__)

# 제목에서 흔히 붙는 부가 표기 — 노래 제목 추출 시 제거한다.
_TITLE_NOISE_RE = re.compile(
    r"""\s*(?:
        [\(\[\{][^\)\]\}]*?(?:official|mv|m/v|music\ video|audio|lyric[s]?|
        가사|뮤직비디오|비디오|live|버전|ver\.?|feat\.?|ft\.?|remaster|hd|4k)[^\)\]\}]*?[\)\]\}]
    )""",
    re.IGNORECASE | re.VERBOSE,
)
_TOPIC_SUFFIX_RE = re.compile(r"\s*-\s*topic\s*$", re.IGNORECASE)


def _clean_title_noise(text: str) -> str:
    prev = None
    out = text
    while prev != out:
        prev = out
        out = _TITLE_NOISE_RE.sub("", out)
    return out.strip(" -–—·|")


def _clean_channel(name: str) -> str:
    """'Artist - Topic' 형태의 자동 생성 채널명에서 아티스트만 남긴다."""
    return _TOPIC_SUFFIX_RE.sub("", name or "").strip()


def parse_artist_title(video_title: str, channel_name: str = "") -> tuple[str, str]:
    """영상 제목/채널명에서 (artist, song_title)을 추정한다.

    'Artist - Title' 패턴을 우선 분리하고, 없으면 채널명을 아티스트로,
    노이즈를 제거한 제목을 곡명으로 쓴다.
    """
    title = _clean_title_noise(video_title or "")
    artist = _clean_channel(channel_name)
    # "Artist - Title" / "Artist – Title"
    m = re.match(r"^(.{1,80}?)\s*[-–—]\s*(.+)$", title)
    if m:
        left, right = m.group(1).strip(), m.group(2).strip()
        if left and right:
            return left, _clean_title_noise(right)
    return artist, title


def detect_is_song(meta: dict) -> bool:
    """yt-dlp info/prefetch dict로 노래 영상 여부를 추정한다.

    YouTube Music 카테고리(categories에 'Music') 또는 music 메타데이터
    (track/artist/album) 존재 시 노래로 본다.
    """
    cats = [str(c).lower() for c in (meta.get("categories") or [])]
    if any("music" in c for c in cats):
        return True
    return bool(meta.get("track") or meta.get("artist") or meta.get("album"))


def _music_meta_from_info(info: dict) -> dict:
    """yt-dlp info dict에서 노래 감지·기본 메타데이터에 필요한 필드만 추출한다."""
    ry = info.get("release_year")
    return {
        "track": info.get("track") or "",
        "artist": info.get("artist") or info.get("creator") or "",
        "album": info.get("album") or "",
        "release_year": str(ry) if ry else "",
        "categories": list(info.get("categories") or []),
        "title": info.get("title") or "",
        "channel": info.get("uploader") or info.get("channel") or "",
        "duration": info.get("duration"),
    }


# ------------------------------------------------------------------
# Commands
# ------------------------------------------------------------------

@dataclass
class FetchSongInfoCommand:
    """노래 정보를 조회해 저장한다(등록 시 / 상세화면 ⟳ 갱신 시).

    prefetch: 등록 시 yt-dlp가 이미 조회한 info에서 뽑은 music 메타데이터 dict.
              (없으면 media_source로 재조회 — 갱신 버튼 경로)
    force:    True면 가사가 있어도 재조회한다.
    """
    video_id: UUID
    prefetch: dict | None = None
    force: bool = False
    fetch_lyrics: bool = True   # False면 감지+메타데이터만(가사 네트워크 조회 생략)


@dataclass
class SetSongFlagCommand:
    video_id: UUID
    is_song: bool


@dataclass
class UpdateSongFieldCommand:
    video_id: UUID
    field: str            # artist | album | song_title | release_year
    value: str


@dataclass
class UpdateSongLyricsCommand:
    video_id: UUID
    lines: list[LyricsLine] = field(default_factory=list)


@dataclass
class AddLyricsSourceCommand:
    name: str
    provider_key: str
    base_url: str = ""


@dataclass
class UpdateLyricsSourceCommand:
    source_id: UUID
    name: str | None = None
    enabled: bool | None = None
    base_url: str | None = None


@dataclass
class DeleteLyricsSourceCommand:
    source_id: UUID


@dataclass
class ReorderLyricsSourcesCommand:
    ordered_ids: list[UUID]


# ------------------------------------------------------------------
# Handlers
# ------------------------------------------------------------------

class FetchSongInfoHandler:
    """노래 메타데이터·가사를 수집한다.

    출처 체인: song_repo의 활성 LyricsSource를 priority 순으로 순회하며 부족한
    항목(가사·가수·앨범·제목·발매년도)을 채운다. 가사가 비한국어면 번역기로 한글
    번역을 붙여 원문/번역 병행 LyricsLine을 만든다. 실패는 격리한다.
    """

    def __init__(
        self,
        song_repo: ISongRepository,
        video_repo: IVideoRepository,
        event_bus: IEventBus,
        lyrics_providers: dict[str, ILyricsProvider] | None = None,
        translator: ITranslator | None = None,
        media_source: IMediaSource | None = None,
    ) -> None:
        self._songs = song_repo
        self._videos = video_repo
        self._bus = event_bus
        self._providers = lyrics_providers or {}
        self._translator = translator
        self._media = media_source

    def handle(self, cmd: FetchSongInfoCommand) -> SongInfoAggregate | None:
        video_agg = self._videos.get_by_id(cmd.video_id)
        if video_agg is None:
            return None
        video = video_agg.video

        agg = self._songs.get(cmd.video_id) or SongInfoAggregate.create(cmd.video_id)

        # 1) 기본 메타데이터 확보 (prefetch 우선, 없으면 yt-dlp 재조회)
        meta = dict(cmd.prefetch or {})
        if not meta and self._media is not None:
            try:
                info = self._media.fetch_metadata(str(video.url))
                meta = _music_meta_from_info(info or {})
            except Exception:
                logger.exception("노래 정보용 메타데이터 재조회 실패: %s", cmd.video_id)
                meta = {}

        detected = detect_is_song(meta) if meta else False
        is_song = detected or agg.info.is_song
        if not is_song:
            # 노래가 아니면 감지 결과만 반영(플래그 False 유지)하고 종료.
            agg.set_song_flag(False)
            self._songs.save(agg)
            self._bus.publish_all(agg.pull_events())
            return agg

        # 2) 검색·표시 기준값 — **현재 노래 정보에 입력된 값(수동 편집 포함)을 최우선**으로
        #    쓰고, 비어 있으면 yt-dlp 메타데이터, 마지막으로 영상 제목 파싱으로 채운다.
        #    사용자가 노래 제목/가수를 고쳤다면 그 값을 기반으로 가사를 검색한다.
        existing = agg.info
        vid_title = meta.get("title") or video.title
        channel = meta.get("channel") or (video.channel.name if video.channel else "")
        artist = existing.artist.strip() or (meta.get("artist") or "").strip()
        title = existing.song_title.strip() or (meta.get("track") or "").strip()
        album = existing.album.strip() or (meta.get("album") or "").strip()
        year = existing.release_year.strip() or (meta.get("release_year") or "").strip()
        if not artist or not title:
            pa, pt = parse_artist_title(vid_title, channel)
            artist = artist or pa
            title = title or pt
        duration = meta.get("duration")
        if duration is None and video.duration is not None:
            duration = video.duration.seconds

        # 3) 출처 체인으로 가사·부족분 조회 (수동 편집 필드는 최종 apply에서 보존)
        lyrics_lines: list[str] = []
        lyrics_lang = ""
        source: SongSourceRef | None = None
        need_lyrics = cmd.fetch_lyrics and (cmd.force or not agg.info.lyrics_lines)
        if need_lyrics:
            lyrics_lines, lyrics_lang, source, artist, album, title, year = self._run_chain(
                artist, title, album, year, duration
            )

        # 4) 번역 (비한국어 가사에 한글 병행)
        line_objs = self._build_lyrics_lines(lyrics_lines, lyrics_lang)

        # 5) 반영·저장
        agg.apply_fetched(
            artist=artist or None,
            album=album or None,
            song_title=title or None,
            release_year=year or None,
            lyrics_lines=line_objs or None,
            lyrics_language=lyrics_lang or None,
            source=source,
            mark_song=True,
        )
        self._songs.save(agg)
        self._bus.publish_all(agg.pull_events())
        return agg

    def _run_chain(
        self,
        artist: str,
        title: str,
        album: str,
        year: str,
        duration: int | None,
    ) -> tuple[list[str], str, SongSourceRef | None, str, str, str, str]:
        """활성 출처를 순서대로 시도해 가사와 부족한 메타데이터를 채운다."""
        lyrics: list[str] = []
        lang = ""
        source: SongSourceRef | None = None
        try:
            sources = [s for s in self._songs.list_lyrics_sources() if s.enabled]
        except Exception:
            logger.exception("가사 출처 목록 조회 실패")
            sources = []

        for src in sources:
            provider = self._providers.get(src.provider_key)
            if provider is None:
                continue
            try:
                result: LyricsResult | None = provider.fetch(artist, title, duration)
            except Exception:
                logger.exception("가사 조회 실패: provider=%s", src.provider_key)
                continue
            if result is None:
                continue
            # 부족한 메타데이터 보강(빈 값만 채움)
            artist = artist or result.artist
            album = album or result.album
            title = title or result.title
            year = year or result.release_year
            # 가사는 처음 확보한 출처 것을 채택
            if not lyrics and result.lines:
                lyrics = [ln for ln in result.lines]
                lang = result.language or lang
                source = SongSourceRef(
                    name=result.source_name or src.name,
                    url=result.source_url,
                )
            # 가사 + 핵심 메타가 모두 채워졌으면 조기 종료
            if lyrics and artist and title and album:
                break
        return lyrics, lang, source, artist, album, title, year

    def _build_lyrics_lines(self, lines: list[str], language: str) -> list[LyricsLine]:
        if not lines:
            return []
        lang = (language or "").lower()
        # 언어 미상이면 번역기로 추정 시도
        if not lang and self._translator is not None:
            try:
                sample = next((ln for ln in lines if ln.strip()), "")
                lang = (self._translator.detect_language(sample) or "").lower()
            except Exception:
                logger.exception("가사 언어 감지 실패")
        # 한국어면 번역 없이 원문만
        if lang == "ko" or self._translator is None:
            return [LyricsLine(original=ln, translation="") for ln in lines]
        try:
            translations = self._translator.translate(lines, target="ko")
        except Exception:
            logger.exception("가사 번역 실패 — 원문만 표시")
            translations = lines
        if len(translations) != len(lines):
            translations = lines
        return [
            LyricsLine(original=o, translation=(t if t != o else ""))
            for o, t in zip(lines, translations)
        ]


class SetSongFlagHandler:
    def __init__(self, song_repo: ISongRepository, event_bus: IEventBus) -> None:
        self._songs = song_repo
        self._bus = event_bus

    def handle(self, cmd: SetSongFlagCommand) -> None:
        agg = self._songs.get(cmd.video_id) or SongInfoAggregate.create(cmd.video_id)
        agg.set_song_flag(cmd.is_song)
        self._songs.save(agg)
        self._bus.publish_all(agg.pull_events())


class UpdateSongFieldHandler:
    def __init__(self, song_repo: ISongRepository, event_bus: IEventBus) -> None:
        self._songs = song_repo
        self._bus = event_bus

    def handle(self, cmd: UpdateSongFieldCommand) -> None:
        agg = self._songs.get(cmd.video_id) or SongInfoAggregate.create(
            cmd.video_id, is_song=True
        )
        agg.edit_field(cmd.field, cmd.value)
        self._songs.save(agg)
        self._bus.publish_all(agg.pull_events())


class UpdateSongLyricsHandler:
    def __init__(self, song_repo: ISongRepository, event_bus: IEventBus) -> None:
        self._songs = song_repo
        self._bus = event_bus

    def handle(self, cmd: UpdateSongLyricsCommand) -> None:
        agg = self._songs.get(cmd.video_id) or SongInfoAggregate.create(
            cmd.video_id, is_song=True
        )
        agg.edit_lyrics(cmd.lines)
        self._songs.save(agg)
        self._bus.publish_all(agg.pull_events())


# ── 가사 출처 레지스트리 ─────────────────────────────────────────────

class AddLyricsSourceHandler:
    def __init__(self, song_repo: ISongRepository) -> None:
        self._songs = song_repo

    def handle(self, cmd: AddLyricsSourceCommand) -> None:
        existing = self._songs.list_lyrics_sources()
        next_priority = max((s.priority for s in existing), default=0) + 10
        src = LyricsSource.create(
            name=cmd.name.strip(),
            provider_key=cmd.provider_key.strip(),
            base_url=cmd.base_url.strip(),
            priority=next_priority,
        )
        self._songs.save_lyrics_source(src)


class UpdateLyricsSourceHandler:
    def __init__(self, song_repo: ISongRepository) -> None:
        self._songs = song_repo

    def handle(self, cmd: UpdateLyricsSourceCommand) -> None:
        sources = {s.id: s for s in self._songs.list_lyrics_sources()}
        src = sources.get(cmd.source_id)
        if src is None:
            raise KeyError(f"가사 출처 {cmd.source_id} 없음")
        if cmd.name is not None:
            src.name = cmd.name.strip()
        if cmd.enabled is not None:
            src.enabled = cmd.enabled
        if cmd.base_url is not None:
            src.base_url = cmd.base_url.strip()
        self._songs.save_lyrics_source(src)


class DeleteLyricsSourceHandler:
    def __init__(self, song_repo: ISongRepository) -> None:
        self._songs = song_repo

    def handle(self, cmd: DeleteLyricsSourceCommand) -> None:
        self._songs.delete_lyrics_source(cmd.source_id)


class ReorderLyricsSourcesHandler:
    def __init__(self, song_repo: ISongRepository) -> None:
        self._songs = song_repo

    def handle(self, cmd: ReorderLyricsSourcesCommand) -> None:
        self._songs.set_lyrics_sources_order(cmd.ordered_ids)
