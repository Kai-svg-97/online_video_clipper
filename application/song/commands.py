from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from uuid import UUID

from application.song.dtos import LyricsCandidateDTO
from domain.library.repositories import IVideoRepository
from domain.shared.ports import IEventBus, IMediaSource
from domain.song.aggregates import SongInfoAggregate
from domain.song.entities import LyricsSource
from domain.song.ports import (
    DEFAULT_LYRICS_SEARCH_LIMIT,
    ILyricsProvider,
    ITranslator,
    LyricsResult,
)
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


# 다중 아티스트 구분자 — yt-dlp `artist`는 협업/피처링을 콤마 등으로 이어 붙인다
# (예: "NIKI, Phil Collins"). 콤마/세미콜론/슬래시는 공백 없이, &·feat·ft·with·x는
# 이름 중간 글자를 오검출하지 않도록 앞뒤 공백을 요구한다.
_ARTIST_SEP_RE = re.compile(
    r"\s*,\s*|\s*;\s*|\s*/\s*|\s+&\s+|\s+feat\.?\s+|\s+ft\.?\s+|\s+with\s+|\s+x\s+",
    re.IGNORECASE,
)


def _primary_artist(artist: str) -> str:
    """다중 아티스트 문자열에서 주(첫) 아티스트만 뽑는다.

    가사 제공자는 정확한 아티스트명으로 매칭하므로 "NIKI, Phil Collins" 같은
    협업 표기로는 조회가 실패한다. 첫 아티스트("NIKI")로 재시도하기 위한 값이다.
    분리 대상이 없으면 원본을 그대로 반환한다.
    """
    parts = _ARTIST_SEP_RE.split((artist or "").strip(), maxsplit=1)
    return parts[0].strip() if parts and parts[0].strip() else (artist or "").strip()


def artist_search_candidates(artist: str) -> list[str]:
    """제공자에 넘길 아티스트 후보 — 전체 문자열 → 주(첫) 아티스트 순.

    체인 검색(`FetchSongInfoHandler`)과 후보 목록 검색(`SearchLyricsCandidatesHandler`)이
    같은 규칙을 써야 결과가 어긋나지 않으므로 한 곳에 둔다.
    """
    out = [artist]
    primary = _primary_artist(artist)
    if primary and primary != artist:
        out.append(primary)
    return out


def resolve_search_basis(
    info, video_title: str, channel: str, meta: dict | None = None
) -> tuple[str, str, str, str]:
    """가사 검색·표시의 기준값 (artist, title, album, year)을 정한다.

    **현재 노래 정보에 입력된 값(수동 편집 포함)이 최우선**이고, 비면 yt-dlp 메타데이터를
    쓴다. 사용자가 항목을 한 번이라도 고쳤으면(`manual_fields`) 그 입력값만으로 검색하고
    빈 항목은 채우지 않는다 — 영상 제목을 제목 기본값으로 억지로 넣어 검색이 실패하던
    문제를 막기 위함이다. 수정한 적이 없을 때만(자동 첫 조회) 영상 제목을 파싱해 보완한다.
    """
    meta = meta or {}
    manual = getattr(info, "manual_fields", frozenset()) if info is not None else frozenset()
    edited = bool(set(manual) & {"artist", "album", "song_title", "release_year"})
    artist = (info.artist.strip() if info else "") or (meta.get("artist") or "").strip()
    title = (info.song_title.strip() if info else "") or (meta.get("track") or "").strip()
    album = (info.album.strip() if info else "") or (meta.get("album") or "").strip()
    year = (info.release_year.strip() if info else "") or (meta.get("release_year") or "").strip()
    if not edited and (not artist or not title):
        pa, pt = parse_artist_title(
            meta.get("title") or video_title, meta.get("channel") or channel
        )
        artist = artist or pa
        title = title or pt
    return artist, title, album, year


def build_lyrics_lines(
    lines: list[str],
    language: str,
    timings: list[int | None] | None = None,
    translator: ITranslator | None = None,
) -> list[LyricsLine]:
    """원문 줄 목록을 (필요하면 한글 번역을 붙여) ``LyricsLine``으로 만든다.

    한국어 가사이거나 번역기가 없으면 원문만 담는다. 번역 실패는 격리하고 원문을 쓴다.
    """
    if not lines:
        return []
    # 타이밍은 lines와 길이가 같을 때만 신뢰한다(길이가 어긋나면 잘못 짝지어진다).
    stamps: list[int | None] = list(timings or [])
    if len(stamps) != len(lines):
        stamps = [None] * len(lines)
    lang = (language or "").lower()
    # 언어 미상이면 번역기로 추정 시도
    if not lang and translator is not None:
        try:
            sample = next((ln for ln in lines if ln.strip()), "")
            lang = (translator.detect_language(sample) or "").lower()
        except Exception:
            logger.exception("가사 언어 감지 실패")
    # 한국어면 번역 없이 원문만
    if lang == "ko" or translator is None:
        return [
            LyricsLine(original=ln, translation="", start_ms=ms)
            for ln, ms in zip(lines, stamps)
        ]
    try:
        translations = translator.translate(lines, target="ko")
    except Exception:
        logger.exception("가사 번역 실패 — 원문만 표시")
        translations = lines
    if len(translations) != len(lines):
        translations = lines
    return [
        LyricsLine(original=o, translation=(t if t != o else ""), start_ms=ms)
        for o, t, ms in zip(lines, translations, stamps)
    ]


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
    synced_only: True면 **시간 정보(LRC 타이밍)가 있는 가사만** 채택한다. 타이밍이 없는
              출처는 건너뛰고, 전 출처가 실패하면 기존 가사를 그대로 둔다(자막용 조회).
    """
    video_id: UUID
    prefetch: dict | None = None
    force: bool = False
    fetch_lyrics: bool = True   # False면 감지+메타데이터만(가사 네트워크 조회 생략)
    from_source_name: str | None = None  # 설정 시 이 출처 '다음'부터 검색(순환) — '다음 출처'
    synced_only: bool = False


@dataclass
class SearchLyricsCandidatesCommand:
    """활성 가사 출처를 **전부** 조회해 후보 목록을 만든다(저장하지 않음).

    체인 검색(`FetchSongInfoCommand`)이 첫 성공 출처를 곧바로 채택하는 것과 달리,
    사용자가 |출처|가수|제목|가사 첫째 줄|싱크| 목록에서 직접 고르게 하기 위한 조회다.

    per_source_limit: 출처 하나가 돌려줄 후보 수 상한(0 이하 = 무제한). 같은 제목의 다른
        가수 곡이 흔하므로 출처당 여러 건을 받는다. 무제한은 스크래핑 출처에서 곡마다
        상세 페이지를 긁어 매우 느려지므로 기본값은 유한하다.
    """
    video_id: UUID
    per_source_limit: int = DEFAULT_LYRICS_SEARCH_LIMIT


@dataclass
class ApplyLyricsCandidateCommand:
    """후보 목록에서 고른 가사를 실제로 반영한다(번역 포함)."""
    video_id: UUID
    candidate: LyricsCandidateDTO


@dataclass
class SetLyricsOffsetCommand:
    """자막 싱크 보정값을 저장한다(양수 = 자막을 늦게 띄움)."""
    video_id: UUID
    offset_ms: int


@dataclass
class TranslateSongLyricsCommand:
    """현재 등록된 가사를 한글로 (재)번역해 저장한다('번역' 버튼)."""
    video_id: UUID


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

@dataclass
class _ChainOutcome:
    """출처 체인 순회 결과 — 반환 튜플이 길어져 이름을 붙였다(내부 전용)."""
    lyrics: list[str] = field(default_factory=list)
    timings: list[int | None] = field(default_factory=list)
    language: str = ""
    source: SongSourceRef | None = None
    artist: str = ""
    album: str = ""
    title: str = ""
    year: str = ""


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

        # 2) 검색·표시 기준값 (규칙은 resolve_search_basis 주석 참조 — 후보 목록 검색과 공유)
        artist, title, album, year = resolve_search_basis(
            agg.info,
            video.title,
            video.channel.name if video.channel else "",
            meta,
        )
        duration = meta.get("duration")
        if duration is None and video.duration is not None:
            duration = video.duration.seconds

        # 3) 출처 체인으로 가사·부족분 조회 (수동 편집 필드는 최종 apply에서 보존)
        outcome = _ChainOutcome(artist=artist, album=album, title=title, year=year)
        need_lyrics = cmd.fetch_lyrics and (cmd.force or not agg.info.lyrics_lines)
        if need_lyrics:
            outcome = self._run_chain(
                artist, title, album, year, duration,
                start_after_name=cmd.from_source_name,
                synced_only=cmd.synced_only,
            )

        # 4) 번역 (비한국어 가사에 한글 병행) — 줄별 시각을 함께 싣는다
        line_objs = self._build_lyrics_lines(
            outcome.lyrics, outcome.language, outcome.timings
        )

        # 5) 반영·저장
        agg.apply_fetched(
            artist=outcome.artist or None,
            album=outcome.album or None,
            song_title=outcome.title or None,
            release_year=outcome.year or None,
            lyrics_lines=line_objs or None,
            lyrics_language=outcome.language or None,
            source=outcome.source,
            mark_song=True,
            force_lyrics=bool(cmd.from_source_name) or cmd.synced_only,
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
        start_after_name: str | None = None,
        synced_only: bool = False,
    ) -> _ChainOutcome:
        """활성 출처를 순서대로 시도해 가사와 부족한 메타데이터를 채운다.

        start_after_name이 주어지면(‘다음 출처’ 검색) 그 출처 **다음**부터 순회하도록 목록을
        회전한다. 끝에 도달하면 처음으로 순환한다(현재 출처는 맨 뒤로 밀려 마지막에만 재시도).

        synced_only면 시간 정보(timings)가 없는 결과는 가사로 채택하지 않고 다음 출처로
        넘어간다 — 자막용 '싱크 가사 찾기' 경로다.
        """
        out = _ChainOutcome(artist=artist, album=album, title=title, year=year)
        try:
            sources = [s for s in self._songs.list_lyrics_sources() if s.enabled]
        except Exception:
            logger.exception("가사 출처 목록 조회 실패")
            sources = []

        if start_after_name:
            idx = next((i for i, s in enumerate(sources) if s.name == start_after_name), -1)
            if idx >= 0:
                sources = sources[idx + 1:] + sources[: idx + 1]

        # 검색용 아티스트 후보: 전체 문자열 → 주(첫) 아티스트 순으로 시도한다.
        # 다중 아티스트 표기("NIKI, Phil Collins")로는 제공자 매칭이 실패하므로
        # 주 아티스트("NIKI")로 재시도해 유명곡 가사를 놓치지 않는다.
        artist_candidates = artist_search_candidates(out.artist)

        for src in sources:
            provider = self._providers.get(src.provider_key)
            if provider is None:
                continue
            result: LyricsResult | None = None
            for cand_artist in artist_candidates:
                try:
                    result = provider.fetch(cand_artist, out.title, duration)
                except Exception:
                    logger.exception("가사 조회 실패: provider=%s", src.provider_key)
                    result = None
                if result is not None:
                    break
            if result is None:
                continue
            # 싱크 전용 조회는 타이밍이 없는 결과를 아예 채택하지 않는다(메타데이터 보강도 생략).
            if synced_only and not any(t is not None for t in result.timings):
                logger.debug("싱크 전용 조회 — 타이밍 없는 출처 건너뜀: %s", src.name)
                continue
            # 부족한 메타데이터 보강(빈 값만 채움)
            out.artist = out.artist or result.artist
            out.album = out.album or result.album
            out.title = out.title or result.title
            out.year = out.year or result.release_year
            # 가사는 처음 확보한 출처 것을 채택
            if not out.lyrics and result.lines:
                out.lyrics = list(result.lines)
                out.timings = list(result.timings)
                out.language = result.language or out.language
                # 출처명은 DB 출처 이름(src.name)을 저장 — '다음 출처' 검색 시 정확히 매칭·순환.
                out.source = SongSourceRef(name=src.name, url=result.source_url)
            # 가사 + 핵심 메타가 모두 채워졌으면 조기 종료
            if out.lyrics and out.artist and out.title and out.album:
                break
        return out

    def _build_lyrics_lines(
        self, lines: list[str], language: str, timings: list[int | None] | None = None
    ) -> list[LyricsLine]:
        return build_lyrics_lines(lines, language, timings, self._translator)


class SearchLyricsCandidatesHandler:
    """활성 출처를 전부 훑어 가사 후보 목록을 만든다(DB 저장 없음).

    출처 하나를 끝낼 때마다 ``on_result``을 부르므로, 호출부(GUI)는 **전체가 끝나기를
    기다리지 않고** 확인되는 대로 목록에 채울 수 있다. 개별 출처 실패는 격리해
    (해당 출처는 결과 없음으로 통지하고) 나머지 출처를 계속 시도한다.
    """

    def __init__(
        self,
        song_repo: ISongRepository,
        video_repo: IVideoRepository,
        lyrics_providers: dict[str, ILyricsProvider] | None = None,
    ) -> None:
        self._songs = song_repo
        self._videos = video_repo
        self._providers = lyrics_providers or {}

    def list_source_names(self) -> list[str]:
        """조회할 출처 이름 목록 — GUI가 '조회중' 행을 미리 만드는 데 쓴다.

        ``handle``이 실제로 순회하는 목록과 **같은 조건**(활성 + 제공자 구현 존재)으로
        추려야 목록에 영영 채워지지 않는 행이 남지 않는다.
        """
        return [s.name for s in self._active_sources()]

    def _active_sources(self) -> list[LyricsSource]:
        try:
            return [
                s for s in self._songs.list_lyrics_sources()
                if s.enabled and s.provider_key in self._providers
            ]
        except Exception:
            logger.exception("가사 출처 목록 조회 실패")
            return []

    def handle(
        self,
        cmd: SearchLyricsCandidatesCommand,
        on_start=None,
        on_result=None,
        on_source_done=None,
        should_cancel=None,
    ) -> list[LyricsCandidateDTO]:
        """활성 출처를 순회하며 후보를 모은다.

        콜백은 세 단계다 — ``on_start(출처)``: 조회 시작, ``on_result(출처, DTO)``:
        후보 **한 건**(출처당 여러 번 불릴 수 있다), ``on_source_done(출처, 건수)``:
        그 출처 종료. GUI가 '조회중 → 후보 N행 / 결과 없음'을 구분하려면 종료 통지가
        따로 필요하다(후보가 0건인 출처는 on_result가 한 번도 안 불리기 때문).
        """
        video_agg = self._videos.get_by_id(cmd.video_id)
        if video_agg is None:
            return []
        video = video_agg.video
        agg = self._songs.get(cmd.video_id)
        artist, title, _album, _year = resolve_search_basis(
            agg.info if agg else None,
            video.title,
            video.channel.name if video.channel else "",
        )
        duration = video.duration.seconds if video.duration is not None else None
        artist_candidates = artist_search_candidates(artist)

        found: list[LyricsCandidateDTO] = []
        for src in self._active_sources():
            if should_cancel is not None and should_cancel():
                logger.debug("가사 후보 검색 취소됨: %s", cmd.video_id)
                break
            if on_start is not None:
                on_start(src.name)
            results = self._search_one(
                self._providers[src.provider_key],
                artist_candidates,
                title,
                duration,
                cmd.per_source_limit,
            )
            count = 0
            for result in results:
                if not result.lines:
                    continue
                dto = _to_candidate(src, result, artist, title)
                found.append(dto)
                count += 1
                if on_result is not None:
                    on_result(src.name, dto)
            if on_source_done is not None:
                on_source_done(src.name, count)
        logger.info(
            "가사 후보 검색 완료: video=%s artist=%r title=%r 후보=%d건",
            cmd.video_id, artist, title, len(found),
        )
        return found

    @staticmethod
    def _search_one(
        provider: ILyricsProvider,
        artist_candidates: list[str],
        title: str,
        duration: int | None,
        limit: int,
    ) -> list[LyricsResult]:
        """한 출처에서 후보를 모은다 — ``search``가 있으면 다건, 없으면 ``fetch`` 1건.

        아티스트 후보(전체 → 주 아티스트)는 결과가 나올 때까지 순서대로 시도한다.
        """
        search = getattr(provider, "search", None)
        for cand_artist in artist_candidates:
            try:
                if callable(search):
                    results = search(cand_artist, title, duration, limit) or []
                else:
                    one = provider.fetch(cand_artist, title, duration)
                    results = [one] if one is not None else []
            except Exception:
                logger.exception("가사 후보 조회 실패: provider=%s", getattr(provider, "key", "?"))
                results = []
            if results:
                return list(results)
        return []


def _to_candidate(
    src: LyricsSource, result: LyricsResult, fallback_artist: str, fallback_title: str
) -> LyricsCandidateDTO:
    lines = list(result.lines)
    return LyricsCandidateDTO(
        source_name=src.name,
        provider_key=src.provider_key,
        artist=result.artist or fallback_artist,
        title=result.title or fallback_title,
        album=result.album,
        release_year=result.release_year,
        first_line=next((ln.strip() for ln in lines if ln.strip()), ""),
        is_synced=any(t is not None for t in result.timings),
        line_count=sum(1 for ln in lines if ln.strip()),
        source_url=result.source_url,
        lines=tuple(lines),
        timings=tuple(result.timings),
        language=result.language,
    )


class ApplyLyricsCandidateHandler:
    """후보 목록에서 고른 가사를 반영한다(필요하면 한글 번역을 붙인다).

    사용자가 명시적으로 고른 것이므로 ``force_lyrics=True``로 수동편집 가드를 넘어
    교체한다. 가수·제목 등 메타데이터는 ``apply_fetched`` 규칙대로 **비어 있는 항목만**
    채우고 수동 편집한 항목은 보존한다.
    """

    def __init__(
        self,
        song_repo: ISongRepository,
        event_bus: IEventBus,
        translator: ITranslator | None = None,
    ) -> None:
        self._songs = song_repo
        self._bus = event_bus
        self._translator = translator

    def handle(self, cmd: ApplyLyricsCandidateCommand) -> SongInfoAggregate | None:
        cand = cmd.candidate
        if cand is None or not cand.lines:
            return None
        agg = self._songs.get(cmd.video_id) or SongInfoAggregate.create(
            cmd.video_id, is_song=True
        )
        lines = build_lyrics_lines(
            list(cand.lines), cand.language, list(cand.timings), self._translator
        )
        agg.apply_fetched(
            artist=cand.artist or None,
            album=cand.album or None,
            song_title=cand.title or None,
            release_year=cand.release_year or None,
            lyrics_lines=lines or None,
            lyrics_language=cand.language or None,
            source=SongSourceRef(name=cand.source_name, url=cand.source_url),
            mark_song=True,
            force_lyrics=True,
        )
        self._songs.save(agg)
        self._bus.publish_all(agg.pull_events())
        logger.info(
            "가사 후보 적용: video=%s 출처=%s 줄=%d 싱크=%s",
            cmd.video_id, cand.source_name, len(lines), cand.is_synced,
        )
        return agg


class TranslateSongLyricsHandler:
    """이미 등록된 가사를 한글로 (재)번역해 저장한다(조회와 분리된 '번역' 동작)."""

    def __init__(
        self,
        song_repo: ISongRepository,
        translator: ITranslator | None,
        event_bus: IEventBus,
    ) -> None:
        self._songs = song_repo
        self._translator = translator
        self._bus = event_bus

    def handle(self, cmd: TranslateSongLyricsCommand) -> SongInfoAggregate | None:
        agg = self._songs.get(cmd.video_id)
        if agg is None or not agg.info.lyrics_lines or self._translator is None:
            return agg
        originals = [ln.original for ln in agg.info.lyrics_lines]
        lang = (agg.info.lyrics_language or "").lower()
        if not lang:
            try:
                sample = next((o for o in originals if o.strip()), "")
                lang = (self._translator.detect_language(sample) or "").lower()
            except Exception:
                logger.exception("가사 언어 감지 실패")
        if lang == "ko":
            return agg   # 한국어 가사는 번역 대상 아님
        try:
            translations = self._translator.translate(originals, target="ko")
        except Exception:
            logger.exception("가사 번역 실패")
            return agg
        if len(translations) != len(originals):
            return agg
        new_lines = [
            LyricsLine(
                original=old.original,
                translation=(t if t != old.original else ""),
                start_ms=old.start_ms,
            )
            for old, t in zip(agg.info.lyrics_lines, translations)
        ]
        agg.set_lyrics_translations(new_lines)
        self._songs.save(agg)
        self._bus.publish_all(agg.pull_events())
        return agg


class SetLyricsOffsetHandler:
    """자막 싱크 보정값을 저장한다. 노래 정보가 없으면 새로 만든다."""

    def __init__(self, song_repo: ISongRepository, event_bus: IEventBus) -> None:
        self._songs = song_repo
        self._bus = event_bus

    def handle(self, cmd: SetLyricsOffsetCommand) -> None:
        agg = self._songs.get(cmd.video_id) or SongInfoAggregate.create(
            cmd.video_id, is_song=True
        )
        agg.set_lyrics_offset(cmd.offset_ms)
        self._songs.save(agg)
        self._bus.publish_all(agg.pull_events())


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
