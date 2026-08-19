"""앨범 보기 유스케이스 — 목록(그리드)·상세·자동 채우기.

설계 요지
---------
* **앨범은 파생이다.** 저장된 앨범 엔티티가 없고, 카테고리 안 영상들의 노래 정보를
  `domain.song.album`의 순수 규칙으로 묶어 만든다. 그래서 목록 조회는 네트워크를 쓰지
  않는다(캐시된 자켓만 붙인다) — 카테고리를 옮길 때마다 외부 API를 때리면 안 된다.
* **외부 조회는 상세를 열 때만.** 수록곡 전체 목록·자켓·발매일은 그때 가져와 캐시한다.
* **라이브러리에 없는 곡 채우기는 별도 커맨드**다. 곡마다 yt-dlp 검색 1회라 비싸고,
  진행 상황을 곡 단위로 흘려보내야 하므로 콜백을 받는다.
* 목록 조회는 카테고리 영상을 **50건씩 끊어서** 읽는다(메모리 규칙). 노래 정보는
  `list_song_fields`로 일괄 조회해 영상당 쿼리를 만들지 않는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from uuid import UUID

from application.song.album_dtos import (
    TRACK_ORIGIN_AUTO,
    TRACK_ORIGIN_LIBRARY,
    TRACK_ORIGIN_MISSING,
    AlbumCardDTO,
    AlbumDetailDTO,
    AlbumTrackDTO,
)
from domain.library.repositories import IVideoRepository, SearchQuery
from domain.song.album import (
    NO_ALBUM_TITLE,
    AlbumGroup,
    SongRef,
    earliest_registered,
    group_songs_into_albums,
    make_album_key,
    match_track_to_songs,
    normalize_name,
    pick_official_audio,
)
from domain.song.album_repository import AlbumCacheRecord, AlbumTrackLink, IAlbumRepository
from domain.song.ports import AlbumTrackInfo
from domain.song.repositories import ISongRepository

logger = logging.getLogger(__name__)

_PAGE = 50          # 카테고리 영상 스캔 청크 (메모리 규칙)
_MAX_SCAN = 2000    # 방어적 상한 — 한 카테고리에 이보다 많으면 앨범 보기는 의미가 없다


@dataclass
class GetAlbumsQuery:
    category_id: UUID | None = None
    category_ids: list[UUID] = field(default_factory=list)   # 하위 카테고리 포함용


@dataclass
class GetAlbumDetailQuery:
    album_key: str
    category_id: UUID | None = None
    category_ids: list[UUID] = field(default_factory=list)
    refresh: bool = False        # True면 캐시를 무시하고 외부에서 다시 받아온다


@dataclass
class FillAlbumTracksCommand:
    """라이브러리에 없는 수록곡에 official 음원 영상을 붙인다(곡마다 검색 1회)."""

    album_key: str
    category_id: UUID | None = None
    category_ids: list[UUID] = field(default_factory=list)
    cookie_opts: dict = field(default_factory=dict)
    max_tracks: int = 30


@dataclass
class AddAlbumTracksCommand:
    """앨범 수록곡을 카테고리에 한꺼번에 담는다."""

    album_title: str
    artist: str = ""
    category_id: UUID | None = None
    tracks: list = field(default_factory=list)   # list[AlbumTrackDTO]


@dataclass
class RemoveAlbumTrackLinkCommand:
    """자동 매핑된 수록곡 연결을 지운다(잘못 붙은 음원을 사용자가 직접 제거)."""

    album_key: str
    disc_no: int
    track_no: int


@dataclass
class ResolveUnknownAlbumsCommand:
    """앨범 값이 빈 노래의 앨범을 외부 조회로 추정해 채운다."""

    category_id: UUID | None = None
    category_ids: list[UUID] = field(default_factory=list)
    limit: int = 20      # 한 번에 시도할 곡 수 — 곡마다 외부 조회 1회라 상한을 둔다


def _collect_song_refs(
    video_repo: IVideoRepository,
    song_repo: ISongRepository,
    category_id: UUID | None,
    category_ids: list[UUID],
) -> list[SongRef]:
    """카테고리(및 하위)의 영상을 훑어 노래 정보를 붙인 SongRef 목록을 만든다."""
    refs: list[SongRef] = []
    offset = 0
    while offset < _MAX_SCAN:
        page = video_repo.search(
            SearchQuery(
                category_id=category_id if not category_ids else None,
                category_ids=list(category_ids),
                limit=_PAGE,
                offset=offset,
                sort_by="created_at",
                sort_asc=False,
            )
        )
        if not page:
            break
        fields = song_repo.list_song_fields([v.video.id for v in page])
        for agg in page:
            video = agg.video
            sf = fields.get(video.id)
            refs.append(
                SongRef(
                    video_id=video.id,
                    video_title=video.title,
                    song_title=sf.song_title if sf else "",
                    artist=sf.artist if sf else "",
                    album=sf.album if sf else "",
                    thumbnail_path=video.thumbnail_path or "",
                    duration_sec=(
                        video.duration.seconds if getattr(video, "duration", None) else None
                    ),
                    created_at=video.created_at,
                )
            )
        if len(page) < _PAGE:
            break
        offset += _PAGE
    return refs


def _group_for_key(groups: list[AlbumGroup], album_key: str) -> AlbumGroup | None:
    for group in groups:
        if group.key == album_key:
            return group
    return None


class GetAlbumsHandler:
    """카테고리 안의 노래를 앨범 카드 목록으로 묶는다(네트워크 없음)."""

    def __init__(
        self,
        video_repo: IVideoRepository,
        song_repo: ISongRepository,
        album_repo: IAlbumRepository,
    ) -> None:
        self._videos = video_repo
        self._songs = song_repo
        self._albums = album_repo

    def handle(self, query: GetAlbumsQuery) -> list[AlbumCardDTO]:
        refs = _collect_song_refs(
            self._videos, self._songs, query.category_id, query.category_ids
        )
        groups = group_songs_into_albums(refs)
        cached = self._albums.list_albums([g.key for g in groups if g.key])
        cards: list[AlbumCardDTO] = []
        for group in groups:
            record = cached.get(group.key)
            first = group.songs[0] if group.songs else None
            cards.append(
                AlbumCardDTO(
                    key=group.key,
                    album_title=group.album_title or NO_ALBUM_TITLE,
                    artist=group.artist,
                    artwork_url=record.artwork_url if record else "",
                    artwork_path=record.artwork_path if record else "",
                    fallback_thumb_path=(first.thumbnail_path if first else ""),
                    library_count=len(group.songs),
                    track_count=(
                        record.track_count if record and record.track_count else len(group.songs)
                    ),
                    release_date=record.release_date if record else "",
                    first_video_id=first.video_id if first else None,
                )
            )
        logger.info("앨범 %d개 (노래 %d곡)", len(cards), len(refs))
        return cards


class GetAlbumDetailHandler:
    """앨범 상세 — 외부 수록곡 목록에 내 라이브러리 곡을 매핑한다.

    캐시가 있으면 그대로 쓰고, 없거나 ``refresh``면 외부에서 받아 저장한다. 외부 조회가
    실패해도 **내가 가진 곡만으로 앨범을 구성**해 돌려준다(그게 폴백이다 — 앨범 화면이
    네트워크 상태에 따라 통째로 비지 않게).
    """

    def __init__(
        self,
        video_repo: IVideoRepository,
        song_repo: ISongRepository,
        album_repo: IAlbumRepository,
        provider=None,   # IAlbumMetadataProvider | None
    ) -> None:
        self._videos = video_repo
        self._songs = song_repo
        self._albums = album_repo
        self._provider = provider

    def handle(self, query: GetAlbumDetailQuery) -> AlbumDetailDTO | None:
        refs = _collect_song_refs(
            self._videos, self._songs, query.category_id, query.category_ids
        )
        groups = group_songs_into_albums(refs)
        group = _group_for_key(groups, query.album_key)
        if group is None:
            logger.info("앨범 상세: 키에 해당하는 묶음이 없다 (%r)", query.album_key)
            return None

        record = None if query.refresh else self._albums.get_album(group.key)
        if record is None and group.key and self._provider is not None:
            record = self._fetch_and_cache(group)

        tracks = self._build_tracks(group, record)
        return AlbumDetailDTO(
            key=group.key,
            album_title=group.album_title or NO_ALBUM_TITLE,
            artist=group.artist,
            artwork_url=record.artwork_url if record else "",
            artwork_path=record.artwork_path if record else "",
            fallback_thumb_path=(group.songs[0].thumbnail_path if group.songs else ""),
            description=(record.description if record else "") or self._describe(record, group),
            release_date=record.release_date if record else "",
            genre=record.genre if record else "",
            source_name=record.source_name if record else "",
            source_url=record.source_url if record else "",
            tracks=tracks,
        )

    # ── 내부 ───────────────────────────────────────────────────────
    def _fetch_and_cache(self, group: AlbumGroup) -> AlbumCacheRecord | None:
        meta = self._resolve_metadata(group)
        if meta is None:
            logger.info("앨범 정보를 찾지 못했다 (%s - %s)", group.artist, group.album_title)
            return None
        record = AlbumCacheRecord(
            album_key=group.key,
            album_title=meta.album_title or group.album_title,
            artist=meta.artist or group.artist,
            artwork_url=meta.artwork_url,
            description=meta.description,
            release_date=meta.release_date,
            genre=meta.genre,
            copyright=meta.copyright,
            track_count=meta.track_count or len(meta.tracks),
            tracks=list(meta.tracks),
            source_name=meta.source_name,
            source_url=meta.source_url,
        )
        self._albums.save_album(record)
        return record

    def _resolve_metadata(self, group: AlbumGroup):
        """앨범을 어떻게 식별할지 — 가장 먼저 등록한 곡을 기준으로 먼저 시도한다.

        앨범명 텍스트로 검색하면(``fetch_album``) 표기 차이·동명 앨범(재발매·베스트
        앨범 등) 때문에 엉뚱한 앨범을 고를 수 있다. 사용자가 가장 먼저 등록한 곡은
        손대지 않은 원본 데이터라 가장 신뢰할 수 있으므로, 그 곡의 가수·제목으로
        정확히 그 곡을 iTunes에서 찾아(``find_album_of_track``) 앨범을 확정하는 편이
        훨씬 정확하다. 이 경로가 실패하거나(앵커 없음) 찾은 앨범이 실제로 그 곡을
        담고 있지 않을 때만(잘못된 collectionId 방어) 앨범명 검색으로 되돌아간다.
        """
        anchor = earliest_registered(group.songs)
        if anchor is not None and anchor.effective_title:
            try:
                meta = self._provider.find_album_of_track(anchor.artist, anchor.effective_title)
            except Exception:
                logger.exception(
                    "앨범 식별(곡 기준) 실패 (%s - %s)", anchor.artist, anchor.effective_title
                )
                meta = None
            if meta is not None and self._anchor_in_tracks(anchor, meta.tracks):
                return meta
            if meta is not None:
                logger.info(
                    "곡 기준으로 찾은 앨범이 그 곡을 담고 있지 않아 앨범명 검색으로 전환 (%s)",
                    anchor.effective_title,
                )
        try:
            return self._provider.fetch_album(group.artist, group.album_title)
        except Exception:
            logger.exception("앨범 정보 조회 실패 (%s - %s)", group.artist, group.album_title)
            return None

    @staticmethod
    def _anchor_in_tracks(anchor: SongRef, tracks: list) -> bool:
        """찾은 앨범이 정말 앵커 곡을 담고 있는지 확인 — 잘못된 collectionId 방어."""
        target = normalize_name(anchor.effective_title)
        if not target:
            return False
        return any(
            normalize_name(t.title) == target
            or (len(target) >= 3 and target in normalize_name(t.title))
            for t in tracks
        )

    @staticmethod
    def _describe(record: AlbumCacheRecord | None, group: AlbumGroup) -> str:
        """출처가 설명을 주지 않을 때 쓰는 요약 문구(장르·발매일·수록곡 수)."""
        parts: list[str] = []
        if group.artist:
            parts.append(group.artist)
        if record:
            if record.genre:
                parts.append(record.genre)
            if record.release_date:
                parts.append(f"{record.release_date} 발매")
            if record.track_count:
                parts.append(f"{record.track_count}곡")
            if record.copyright:
                parts.append(record.copyright)
        else:
            parts.append(f"내 라이브러리 {len(group.songs)}곡")
        return "  ·  ".join(p for p in parts if p)

    def _build_tracks(
        self, group: AlbumGroup, record: AlbumCacheRecord | None
    ) -> list[AlbumTrackDTO]:
        links = self._albums.get_track_links(group.key) if group.key else {}
        if record and record.tracks:
            return self._tracks_from_external(group, record.tracks, links)
        # 폴백 — 외부 정보가 없으면 내가 가진 곡만으로 목록을 만든다.
        return [
            AlbumTrackDTO(
                track_no=i + 1,
                title=song.effective_title,
                artist=song.artist or group.artist,
                duration_sec=song.duration_sec,
                origin=TRACK_ORIGIN_LIBRARY,
                video_id=song.video_id,
                thumbnail_path=song.thumbnail_path,
            )
            for i, song in enumerate(group.songs)
        ]

    @staticmethod
    def _next_slot(rows: list[AlbumTrackDTO]) -> tuple[int, int]:
        """목록 뒤에 덧붙일 자리(마지막 디스크의 다음 번호)."""
        if not rows:
            return (1, 1)
        last = max(rows, key=lambda t: t.slot)
        return (last.disc_no, last.track_no + 1)

    def _tracks_from_external(
        self,
        group: AlbumGroup,
        infos: list[AlbumTrackInfo],
        links: dict[tuple[int, int], AlbumTrackLink],
    ) -> list[AlbumTrackDTO]:
        remaining = list(group.songs)
        out: list[AlbumTrackDTO] = []
        for info in infos:
            song = match_track_to_songs(info.title, remaining, info.artist or group.artist)
            if song is not None:
                remaining.remove(song)
                out.append(
                    AlbumTrackDTO(
                        track_no=info.track_no or len(out) + 1,
                        disc_no=info.disc_no or 1,
                        title=info.title or song.effective_title,
                        artist=info.artist or song.artist or group.artist,
                        duration_sec=info.duration_sec or song.duration_sec,
                        origin=TRACK_ORIGIN_LIBRARY,
                        video_id=song.video_id,
                        thumbnail_path=song.thumbnail_path,
                    )
                )
                continue
            # 자동 매핑은 (디스크, 트랙)으로 찾는다 — 번호만 쓰면 2장짜리 앨범에서
            # disc1·disc2의 같은 번호가 같은 영상을 가리킨다.
            link = links.get((info.disc_no or 1, info.track_no))
            if link and link.stream_url:
                out.append(
                    AlbumTrackDTO(
                        track_no=info.track_no or len(out) + 1,
                        disc_no=info.disc_no or 1,
                        title=info.title,
                        artist=info.artist or group.artist,
                        duration_sec=info.duration_sec or link.duration_sec,
                        origin=TRACK_ORIGIN_AUTO,
                        stream_url=link.stream_url,
                        stream_title=link.stream_title,
                        stream_channel=link.stream_channel,
                        stream_yt_id=link.stream_yt_id,
                    )
                )
                continue
            out.append(
                AlbumTrackDTO(
                    track_no=info.track_no or len(out) + 1,
                    disc_no=info.disc_no or 1,
                    title=info.title,
                    artist=info.artist or group.artist,
                    duration_sec=info.duration_sec,
                    origin=TRACK_ORIGIN_MISSING,
                )
            )
        # 외부 목록에 없는 내 곡(보너스 트랙·라이브 버전 등)은 뒤에 붙인다 —
        # 가진 곡이 화면에서 사라지면 안 된다. 자리는 마지막 디스크의 다음 번호부터.
        disc_no, next_no = self._next_slot(out)
        for song in remaining:
            out.append(
                AlbumTrackDTO(
                    track_no=next_no,
                    disc_no=disc_no,
                    title=song.effective_title,
                    artist=song.artist or group.artist,
                    duration_sec=song.duration_sec,
                    origin=TRACK_ORIGIN_LIBRARY,
                    video_id=song.video_id,
                    thumbnail_path=song.thumbnail_path,
                )
            )
            next_no += 1
        return out


class FillAlbumTracksHandler:
    """빠진 수록곡에 official 음원 영상을 찾아 붙인다(곡마다 yt-dlp 검색 1회).

    비싸고 느린 작업이라 **곡 단위로 콜백**해 도착하는 대로 화면을 채울 수 있게 한다.
    이미 붙어 있는 곡은 건너뛰므로 다시 열어도 재검색하지 않는다.
    """

    def __init__(
        self,
        detail_handler: GetAlbumDetailHandler,
        album_repo: IAlbumRepository,
        media_source,   # IMediaSource
    ) -> None:
        self._detail = detail_handler
        self._albums = album_repo
        self._media = media_source

    def handle(
        self,
        cmd: FillAlbumTracksCommand,
        on_track=None,        # Callable[[AlbumTrackDTO], None]
        should_cancel=None,   # Callable[[], bool]
    ) -> int:
        detail = self._detail.handle(
            GetAlbumDetailQuery(
                album_key=cmd.album_key,
                category_id=cmd.category_id,
                category_ids=list(cmd.category_ids),
            )
        )
        if detail is None:
            return 0
        missing = [t for t in detail.tracks if t.origin == TRACK_ORIGIN_MISSING]
        if not missing:
            return 0
        filled = 0
        for track in missing[: cmd.max_tracks]:
            if should_cancel and should_cancel():
                logger.info("앨범 자동 채우기 취소됨 (%s)", cmd.album_key)
                break
            entry = self._search_official(
                track.artist or detail.artist, track.title,
                cmd.cookie_opts, track.duration_sec,
            )
            if entry is None:
                continue
            link = AlbumTrackLink(
                album_key=cmd.album_key,
                track_no=track.track_no,
                disc_no=track.disc_no,
                track_title=track.title,
                stream_url=entry.get("url", ""),
                stream_title=entry.get("title", ""),
                stream_channel=entry.get("channel_name", "") or entry.get("uploader", ""),
                stream_yt_id=entry.get("yt_video_id") or entry.get("id") or "",
                duration_sec=entry.get("duration_sec"),
            )
            self._albums.save_track_link(link)
            filled += 1
            if on_track:
                on_track(
                    AlbumTrackDTO(
                        track_no=track.track_no,
                        disc_no=track.disc_no,
                        title=track.title,
                        artist=track.artist,
                        duration_sec=track.duration_sec or link.duration_sec,
                        origin=TRACK_ORIGIN_AUTO,
                        stream_url=link.stream_url,
                        stream_title=link.stream_title,
                        stream_channel=link.stream_channel,
                        stream_yt_id=link.stream_yt_id,
                    )
                )
        logger.info("앨범 자동 채우기: %d/%d곡 (%s)", filled, len(missing), cmd.album_key)
        return filled

    # 검증 후 걸러지는 후보가 많으므로(커버·리액션·동명이곡) 넉넉히 받아 둔다.
    # 한 번의 ytsearchN: 호출이라 개수를 늘려도 요청 수는 그대로다.
    _SEARCH_POOL = 8

    def _search_official(
        self, artist: str, title: str, cookie_opts: dict,
        expected_duration_sec: int | None = None,
    ) -> dict | None:
        """official 음원 영상을 찾는다 — 검색어에 'official audio'를 붙여 뮤비·커버를 피한다.

        yt-dlp가 준 후보를 그대로 믿지 않고 ``pick_official_audio``로 제목·가수·길이를
        검증한다 — 그러지 않으면 동명이곡·커버·1시간 루프가 그대로 붙는다(실제로 그
        신고가 있었다). 검증을 통과한 후보가 하나도 없으면 ``None``을 돌려주고, 그
        수록곡은 계속 '없음'으로 남는다(틀린 음원보다 낫다).
        """
        query = " ".join(p for p in (artist, title, "official audio") if p).strip()
        if not query:
            return None
        try:
            found = self._media.fetch_search_videos(
                query=query, limit=self._SEARCH_POOL, cookie_opts=cookie_opts or {}
            )
        except Exception:
            logger.exception("수록곡 검색 실패 (%r)", query)
            return None
        return pick_official_audio(
            found, title=title, artist=artist, expected_duration_sec=expected_duration_sec
        )


class RemoveAlbumTrackLinkHandler:
    """자동 매핑된 수록곡 연결을 지운다 — 그 수록곡은 다시 '없음'으로 돌아간다.

    앨범 상세의 수정 모드에서 잘못 붙은 음원(동명이곡·커버 등)을 사용자가 직접 지울 때
    쓴다. DB 삭제 한 줄이라 네트워크 없이 즉시 처리된다.
    """

    def __init__(self, album_repo: IAlbumRepository) -> None:
        self._albums = album_repo

    def handle(self, cmd: RemoveAlbumTrackLinkCommand) -> None:
        self._albums.delete_track_link(cmd.album_key, cmd.disc_no, cmd.track_no)
        logger.info(
            "자동 매핑 삭제: %s (디스크%d-트랙%d)", cmd.album_key, cmd.disc_no, cmd.track_no
        )


class AddAlbumTracksHandler:
    """앨범의 수록곡을 현재 카테고리에 등록한다.

    대상은 **자동 매핑된(스트리밍) 곡**뿐이다 — 이미 라이브러리에 있는 곡은 담을 게 없고,
    아직 못 찾은 곡은 주소가 없다.

    등록 뒤에는 **노래 정보(가수·앨범·곡 제목)를 함께 기록한다.** 그러지 않으면 방금
    담은 영상이 앨범 값 없이 들어와 '앨범 미상'으로 떨어지고, 정작 그 앨범 화면에는
    나타나지 않는다(담았는데 안 보이는 것처럼 된다).

    ``AddVideoHandler``는 같은 URL이 이미 있으면 갱신+카테고리 지정만 하므로(upsert),
    중복 클릭이나 일부만 담긴 상태에서 다시 눌러도 안전하다.
    """

    def __init__(self, add_video, song_repo: ISongRepository) -> None:
        self._add = add_video          # AddVideoHandler
        self._songs = song_repo

    def handle(self, cmd: AddAlbumTracksCommand, on_progress=None, should_cancel=None) -> int:
        from application.library.commands import AddVideoCommand  # noqa: PLC0415

        targets = [
            t for t in cmd.tracks
            if getattr(t, "origin", "") == TRACK_ORIGIN_AUTO and getattr(t, "stream_url", "")
        ]
        if not targets:
            logger.info("앨범 곡 담기: 담을 곡이 없다 (앨범=%s)", cmd.album_title)
            return 0
        added = 0
        for index, track in enumerate(targets, start=1):
            if should_cancel and should_cancel():
                logger.info("앨범 곡 담기 취소됨 (앨범=%s)", cmd.album_title)
                break
            try:
                aggregate = self._add.handle(
                    AddVideoCommand(url=track.stream_url, category_id=cmd.category_id)
                )
            except Exception:
                # 한 곡이 실패해도 나머지는 계속 담는다(네트워크·비공개 영상 등).
                logger.exception("앨범 곡 등록 실패: %s", track.stream_url)
                continue
            self._write_song_info(aggregate.id, cmd, track)
            added += 1
            if on_progress:
                on_progress(index, len(targets))
        logger.info(
            "앨범 곡 담기: %d/%d곡 (앨범=%s, 카테고리=%s)",
            added, len(targets), cmd.album_title, cmd.category_id,
        )
        return added

    def _write_song_info(self, video_id: UUID, cmd: AddAlbumTracksCommand, track) -> None:
        """담은 영상에 이 앨범의 노래 정보를 붙인다(수동 편집분은 보존)."""
        from domain.song.aggregates import SongInfoAggregate  # noqa: PLC0415

        aggregate = self._songs.get(video_id)
        if aggregate is None:
            aggregate = SongInfoAggregate.create(video_id, is_song=True)
        aggregate.apply_fetched(
            artist=(getattr(track, "artist", "") or cmd.artist) or None,
            album=cmd.album_title or None,
            song_title=getattr(track, "title", "") or None,
            mark_song=True,
        )
        self._songs.save(aggregate)


class ResolveUnknownAlbumsHandler:
    """'앨범 미상' 노래의 앨범을 외부 조회로 추정해 노래 정보에 채운다.

    채워 넣으면 다음 조회부터 그 곡은 제 앨범 묶음으로 옮겨 간다. 못 찾은 곡은
    ``album_lookup_state``에 기록해 화면을 열 때마다 같은 조회를 반복하지 않는다.
    """

    def __init__(
        self,
        video_repo: IVideoRepository,
        song_repo: ISongRepository,
        album_repo: IAlbumRepository,
        provider=None,   # IAlbumMetadataProvider | None
    ) -> None:
        self._videos = video_repo
        self._songs = song_repo
        self._albums = album_repo
        self._provider = provider

    def handle(self, cmd: ResolveUnknownAlbumsCommand, on_resolved=None) -> int:
        if self._provider is None:
            return 0
        refs = _collect_song_refs(
            self._videos, self._songs, cmd.category_id, cmd.category_ids
        )
        unknown = [r for r in refs if not make_album_key(r.artist, r.album)]
        targets = self._albums.filter_unlooked([r.video_id for r in unknown])
        by_id = {r.video_id: r for r in unknown}
        resolved = 0
        for video_id in targets[: cmd.limit]:
            ref = by_id.get(video_id)
            if ref is None:
                continue
            meta = None
            try:
                meta = self._provider.find_album_of_track(ref.artist, ref.effective_title)
            except Exception:
                logger.exception("앨범 추정 조회 실패 (%s)", ref.effective_title)
            found = bool(meta and meta.album_title)
            self._albums.mark_album_lookup(video_id, found)
            if not found:
                continue
            if self._write_album(video_id, meta):
                resolved += 1
                if on_resolved:
                    on_resolved(video_id, meta.album_title)
        if resolved:
            logger.info("앨범 미상 %d곡의 앨범을 채웠다", resolved)
        return resolved

    def _write_album(self, video_id: UUID, meta) -> bool:
        """추정한 앨범(과 비어 있던 가수)을 노래 정보에 반영한다."""
        aggregate = self._songs.get(video_id)
        if aggregate is None:
            return False
        # apply_fetched는 수동 편집 필드를 건너뛰고 빈 값으로 덮어쓰지 않는다 —
        # 사용자가 직접 적어 둔 앨범/가수를 추정값이 밀어내지 않게 하는 기존 규칙을 그대로 쓴다.
        aggregate.apply_fetched(album=meta.album_title, artist=meta.artist or None)
        self._songs.save(aggregate)
        return True
