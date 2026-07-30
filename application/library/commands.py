from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from domain.library.aggregates import VideoAggregate
from domain.library.repositories import IVideoRepository, SearchQuery
from domain.library.value_objects import ChannelInfo, Duration, VideoUrl
from domain.shared.ports import IEventBus, IMediaSource, ISummarySource

logger = logging.getLogger(__name__)


@dataclass
class AddVideoCommand:
    url: str
    favorite: bool = False
    category_id: UUID | None = None
    tags: list[str] = field(default_factory=list)
    fetch_metadata: bool = True
    # 플레이리스트 일괄 가져오기용 사전 수집 메타데이터 (설정 시 yt-dlp 개별 조회 생략)
    prefetched_title: str | None = None
    prefetched_channel: str | None = None
    prefetched_duration_sec: int | None = None
    prefetched_thumbnail_url: str | None = None
    prefetched_upload_date: str | None = None
    prefetched_view_count: int | None = None
    initial_gemini_summary: str | None = None


@dataclass
class UpdateVideoCommand:
    video_id: UUID
    title: str | None = None
    notes: str | None = None
    favorite: bool | None = None
    category_id: UUID | None = None
    tags: list[str] | None = None
    gemini_summary: str | None = None
    # 요약 실패 사유. ""는 "지우기", None은 "건드리지 않음".
    summary_status: str | None = None


@dataclass
class DeleteVideoCommand:
    video_id: UUID


@dataclass
class EnrichVideoCommand:
    """등록 직후 요약/가사를 자동 보강한다(단건 등록 경로에서만 호출)."""
    video_id: UUID


@dataclass
class EnrichVideoResult:
    """보강 결과 — GUI 상태바 표시용.

    kind: "song"(가사 조회) | "summary"(요약 추출) | "skipped"(대상 아님·이미 있음)
    """
    kind: str
    ok: bool
    detail: str = ""


@dataclass
class MarkWatchedCommand:
    video_id: UUID


@dataclass
class ImportPlaylistCommand:
    playlist_url: str
    category_id: UUID | None = None
    favorite: bool = False


# ------------------------------------------------------------------
# Handlers
# ------------------------------------------------------------------

class AddVideoHandler:
    def __init__(
        self,
        repo: IVideoRepository,
        event_bus: IEventBus,
        ytdlp: IMediaSource | None = None,
        song_fetch: "object | None" = None,
    ) -> None:
        self._repo = repo
        self._bus = event_bus
        self._ytdlp = ytdlp
        # 등록 시 노래 감지·메타데이터 기록용 FetchSongInfoHandler (선택 주입).
        # 가사(외부 네트워크)는 대량 임포트를 막지 않도록 상세 진입 시 조회한다.
        self._song_fetch = song_fetch

    def handle(self, cmd: AddVideoCommand) -> VideoAggregate:
        title: str = cmd.url
        channel: ChannelInfo | None = None
        duration: Duration | None = None
        published_at: datetime | None = None
        view_count: int | None = None
        meta_tags: list[str] = []
        thumbnail_url: str = ""
        description: str = ""
        music_meta: dict = {}   # yt-dlp 조회 시 노래 감지·메타데이터 추출용

        # 사전 수집 메타데이터가 있으면 yt-dlp 개별 조회를 생략한다
        _has_prefetch = bool(cmd.prefetched_title or cmd.prefetched_thumbnail_url)
        if _has_prefetch:
            title = cmd.prefetched_title or cmd.url
            thumbnail_url = cmd.prefetched_thumbnail_url or ""
            if cmd.prefetched_channel:
                channel = ChannelInfo(name=cmd.prefetched_channel, url="", channel_id="")
            if cmd.prefetched_duration_sec is not None:
                duration = Duration(int(cmd.prefetched_duration_sec))
            if cmd.prefetched_upload_date:
                raw = cmd.prefetched_upload_date
                try:
                    if len(raw) == 8:
                        published_at = datetime(int(raw[:4]), int(raw[4:6]), int(raw[6:]))
                except (ValueError, TypeError):
                    pass
            view_count = cmd.prefetched_view_count

        if not _has_prefetch and cmd.fetch_metadata and self._ytdlp:
            try:
                info = self._ytdlp.fetch_metadata(cmd.url)
                title = info.get("title") or cmd.url
                if info.get("uploader"):
                    channel = ChannelInfo(
                        name=info.get("uploader", ""),
                        url=info.get("uploader_url") or "",
                        channel_id=info.get("channel_id") or info.get("uploader_id") or "",
                    )
                if info.get("duration"):
                    duration = Duration(int(info["duration"]))
                if info.get("upload_date"):
                    raw = info["upload_date"]
                    published_at = datetime(int(raw[:4]), int(raw[4:6]), int(raw[6:]))
                view_count = info.get("view_count")
                thumbnail_url = info.get("thumbnail") or ""
                # Collect tags: only native video tags and YouTube category labels.
                # artist/album/genre/track/creator are music metadata fields that
                # yt-dlp may back-fill with unrelated values on regular YouTube videos.
                raw_tags: list[str] = list(info.get("tags") or [])
                raw_tags += list(info.get("categories") or [])
                # Extract #hashtags from description; cap at 10 to prevent tag explosion.
                # Require ≥2 chars to filter single-letter noise.
                description = info.get("description") or ""
                desc_tags = re.findall(r"#([\w가-힣]{2,})", description)
                raw_tags += desc_tags[:10]
                meta_tags = list(dict.fromkeys(
                    t.strip() for t in raw_tags if isinstance(t, str) and t.strip()
                ))
                # 노래 감지·기본 메타데이터 추출 (등록 시 기록용)
                try:
                    from application.song.commands import _music_meta_from_info  # noqa: PLC0415
                    music_meta = _music_meta_from_info(info)
                except Exception:
                    logger.debug("노래 메타데이터 추출 건너뜀")
            except Exception:
                logger.exception("유튜브 메타데이터 조회 실패")  # proceed with URL-as-title if metadata fetch fails

        # Merge caller-supplied tags with metadata tags; preserve order, deduplicate
        all_tag_names = list(dict.fromkeys([*cmd.tags, *meta_tags]))
        tag_ids: list[UUID] = []
        for tag_name in all_tag_names:
            tag = self._repo.get_or_create_tag(tag_name)
            tag_ids.append(tag.id)

        # Upsert: update existing video if URL is already in library
        existing = self._repo.get_by_url(cmd.url)
        if existing is not None:
            existing.update_metadata(
                title=title if title != cmd.url else None,
                description=description or None,
                channel=channel,
                duration=duration,
                published_at=published_at,
                view_count=view_count,
            )
            if tag_ids:
                existing.set_tags(tag_ids)
            if cmd.category_id is not None:
                existing.assign_category(cmd.category_id)
            if thumbnail_url and self._ytdlp and not existing.video.thumbnail_path:
                thumb_path = self._ytdlp.download_thumbnail(existing.id, thumbnail_url)
                if thumb_path:
                    existing.update_metadata(thumbnail_path=thumb_path)
            # 기존 Gemini 요약이 비어있을 때만 initial_gemini_summary로 채운다
            if cmd.initial_gemini_summary and not existing.video.gemini_summary:
                existing.update_metadata(gemini_summary=cmd.initial_gemini_summary)
            self._repo.save(existing)
            self._bus.publish_all(existing.pull_events())
            self._register_song(existing.id, music_meta)
            return existing

        # New video
        url = VideoUrl(cmd.url)
        agg = VideoAggregate.create(
            url=url,
            title=title,
            channel=channel,
            duration=duration,
            published_at=published_at,
            view_count=view_count,
            favorite=cmd.favorite,
            category_id=cmd.category_id,
        )
        if description:
            agg.update_metadata(description=description)
        if cmd.initial_gemini_summary:
            agg.update_metadata(gemini_summary=cmd.initial_gemini_summary)
        agg.set_tags(tag_ids)

        if thumbnail_url and self._ytdlp:
            thumb_path = self._ytdlp.download_thumbnail(agg.id, thumbnail_url)
            if thumb_path:
                agg.update_metadata(thumbnail_path=thumb_path)

        self._repo.save(agg)
        self._bus.publish_all(agg.pull_events())
        self._register_song(agg.id, music_meta)
        return agg

    def _register_song(self, video_id: UUID, music_meta: dict) -> None:
        """등록 시 노래 감지·기본 메타데이터를 기록한다(가사 네트워크 조회 생략).

        실패는 완전히 격리해 영상 등록 결과에 영향을 주지 않는다.
        """
        if self._song_fetch is None or not music_meta:
            return
        try:
            from application.song.commands import FetchSongInfoCommand  # noqa: PLC0415
            self._song_fetch.handle(
                FetchSongInfoCommand(
                    video_id=video_id, prefetch=music_meta, fetch_lyrics=False
                )
            )
        except Exception:
            logger.exception("노래 정보 등록 실패(무시): %s", video_id)


class EnrichVideoHandler:
    """등록된 영상의 성격에 따라 가사 또는 요약 한쪽만 자동으로 채운다.

    분기 기준은 `song_info.is_song`이다 — 등록 시 `AddVideoHandler._register_song`이
    이미 기록해 두므로 yt-dlp를 다시 조회하지 않는다.

    - 노래 영상: 가사만 조회한다(메타데이터는 등록 시점에 채워져 있고, 체인은 빈 값만
      채우므로 실질적으로 가사만 추가된다). 가사를 못 찾아도 **요약으로 폴백하지 않는다.**
    - 그 외: Gemini 요약을 추출해 `gemini_summary`에 저장한다.

    모든 실패는 EnrichVideoResult(ok=False)로 변환해 등록 결과에 영향을 주지 않는다.
    """

    def __init__(
        self,
        repo: IVideoRepository,
        song_repo: "object",                   # ISongRepository
        song_fetch: "object | None" = None,    # FetchSongInfoHandler
        summary_source: ISummarySource | None = None,
        event_bus: IEventBus | None = None,
    ) -> None:
        self._repo = repo
        self._songs = song_repo
        self._song_fetch = song_fetch
        self._summary = summary_source
        self._bus = event_bus

    def is_song_video(self, video_id: UUID) -> bool:
        """상태바 라벨용 사전 판정.

        실제 실행 분기는 handle()이 단독으로 결정한다 — 이 값은 표시용일 뿐이다.
        """
        try:
            agg = self._songs.get(video_id)
        except Exception:
            logger.exception("노래 여부 조회 실패: %s", video_id)
            return False
        return bool(agg is not None and agg.info.is_song)

    def handle(self, cmd: EnrichVideoCommand) -> EnrichVideoResult:
        video_agg = self._repo.get_by_id(cmd.video_id)
        if video_agg is None:
            return EnrichVideoResult("skipped", False, "영상을 찾을 수 없습니다")

        try:
            song_agg = self._songs.get(cmd.video_id)
        except Exception:
            logger.exception("노래 정보 조회 실패: %s", cmd.video_id)
            song_agg = None

        if song_agg is not None and song_agg.info.is_song:
            return self._enrich_lyrics(cmd.video_id, song_agg)
        return self._enrich_summary(video_agg)

    # ------------------------------------------------------------------
    def _enrich_lyrics(self, video_id: UUID, song_agg) -> EnrichVideoResult:
        if song_agg.info.lyrics_lines:
            return EnrichVideoResult("song", True, "가사가 이미 있습니다")
        if self._song_fetch is None:
            return EnrichVideoResult("skipped", False, "가사 조회기가 설정되지 않았습니다")

        try:
            from application.song.commands import FetchSongInfoCommand  # noqa: PLC0415
            result = self._song_fetch.handle(
                FetchSongInfoCommand(video_id=video_id, fetch_lyrics=True)
            )
        except Exception as exc:
            logger.exception("가사 자동 조회 실패: %s", video_id)
            return EnrichVideoResult("song", False, str(exc))

        lines = list(result.info.lyrics_lines) if result is not None else []
        if not lines:
            # 폴백 없음 — 요약으로 넘어가지 않는다(확정된 정책).
            logger.warning("가사를 찾지 못했습니다: %s", video_id)
            return EnrichVideoResult("song", False, "가사를 찾지 못했습니다")
        return EnrichVideoResult("song", True, f"{len(lines)}줄")

    def _enrich_summary(self, video_agg) -> EnrichVideoResult:
        if video_agg.video.gemini_summary:
            return EnrichVideoResult("skipped", True, "요약이 이미 있습니다")
        if self._summary is None:
            return EnrichVideoResult("skipped", False, "요약 추출기가 설정되지 않았습니다")

        url = str(video_agg.video.url)
        # 실패 사유까지 받아 저장한다 — 상세 화면이 "질문하기 버튼이 없어 실패"와
        # 쿠키·네트워크 문제를 구분해 안내하기 위해 필요하다.
        reason = ""
        try:
            get_reason = getattr(self._summary, "extract_with_reason", None)
            if callable(get_reason):
                summary, reason = get_reason(url)
            else:
                summary = self._summary.extract(url)
        except Exception as exc:
            logger.exception("요약 자동 추출 실패: %s", url)
            self._record_summary_status(video_agg.id, "error")
            return EnrichVideoResult("summary", False, str(exc))

        if not summary:
            # 정상 실패가 두 가지다: ① YouTube가 그 영상에 요약 기능을 제공하지 않음
            # (조회수가 적거나 최근 업로드인 영상에서 관측됨) ② 쿠키 미설정·만료.
            self._record_summary_status(video_agg.id, reason or "error")
            if reason == "no_button":
                detail = "이 영상에는 '질문하기' 버튼이 없어 요약을 가져올 수 없습니다"
            elif reason == "not_signed_in":
                detail = "YouTube 로그인이 필요합니다(설정에서 쿠키 등록)"
            else:
                detail = "요약을 가져오지 못했습니다"
            logger.warning("%s: %s", detail, url)
            return EnrichVideoResult("summary", False, detail)

        video_agg.update_metadata(gemini_summary=summary)
        self._repo.save(video_agg)
        # 성공했으니 이전 실패 사유는 지운다(상세 안내 문구가 남지 않게).
        self._record_summary_status(video_agg.id, "")
        if self._bus is not None:
            self._bus.publish_all(video_agg.pull_events())
        return EnrichVideoResult("summary", True, f"{len(summary)}자")

    def _record_summary_status(self, video_id: UUID, status: str) -> None:
        """요약 실패 사유를 저장한다(빈 문자열이면 삭제). 실패는 격리한다."""
        try:
            if status:
                self._repo.set_summary_status(video_id, status)
            else:
                self._repo.clear_summary_status(video_id)
        except Exception:
            logger.exception("요약 상태 기록 실패(무시): %s", video_id)


class UpdateVideoHandler:
    def __init__(self, repo: IVideoRepository, event_bus: IEventBus) -> None:
        self._repo = repo
        self._bus = event_bus

    def handle(self, cmd: UpdateVideoCommand) -> None:
        agg = self._repo.get_by_id(cmd.video_id)
        if agg is None:
            raise KeyError(f"Video {cmd.video_id} not found")

        agg.update_metadata(
            title=cmd.title,
            notes=cmd.notes,
            favorite=cmd.favorite,
            gemini_summary=cmd.gemini_summary,
        )
        if cmd.category_id is not None:
            agg.assign_category(cmd.category_id)

        if cmd.tags is not None:
            tag_ids = [self._repo.get_or_create_tag(t).id for t in cmd.tags]
            agg.set_tags(tag_ids)

        self._repo.save(agg)

        # 요약 실패 사유는 videos 행이 아니라 별도 테이블에 있어 따로 처리한다.
        if cmd.summary_status is not None:
            if cmd.summary_status:
                self._repo.set_summary_status(cmd.video_id, cmd.summary_status)
            else:
                self._repo.clear_summary_status(cmd.video_id)

        self._bus.publish_all(agg.pull_events())


class DeleteVideoHandler:
    def __init__(self, repo: IVideoRepository, event_bus: IEventBus) -> None:
        self._repo = repo
        self._bus = event_bus

    def handle(self, cmd: DeleteVideoCommand) -> None:
        agg = self._repo.get_by_id(cmd.video_id)
        if agg is None:
            return
        agg.delete()
        self._repo.delete(cmd.video_id)
        self._bus.publish_all(agg.pull_events())


class MarkWatchedHandler:
    def __init__(self, repo: IVideoRepository, event_bus: IEventBus) -> None:
        self._repo = repo
        self._bus = event_bus

    def handle(self, cmd: MarkWatchedCommand) -> None:
        agg = self._repo.get_by_id(cmd.video_id)
        if agg is None:
            raise KeyError(f"Video {cmd.video_id} not found")
        agg.mark_watched()
        self._repo.save(agg)
        self._bus.publish_all(agg.pull_events())


# ------------------------------------------------------------------
# Video category assignment
# ------------------------------------------------------------------

@dataclass
class AssignCategoryCommand:
    video_id: UUID
    category_id: UUID | None   # None = remove from category


class AssignCategoryHandler:
    def __init__(self, repo: IVideoRepository, event_bus: IEventBus) -> None:
        self._repo = repo
        self._bus = event_bus

    def handle(self, cmd: AssignCategoryCommand) -> None:
        agg = self._repo.get_by_id(cmd.video_id)
        if agg is None:
            raise KeyError(f"Video {cmd.video_id} not found")
        if cmd.category_id is not None:
            agg.assign_category(cmd.category_id)
        else:
            agg.assign_category(None)
        self._repo.save(agg)
        self._bus.publish_all(agg.pull_events())


# ------------------------------------------------------------------
# Category commands
# ------------------------------------------------------------------

@dataclass
class CreateCategoryCommand:
    name: str
    parent_id: UUID | None = None


@dataclass
class RenameCategoryCommand:
    category_id: UUID
    new_name: str


@dataclass
class DeleteCategoryCommand:
    category_id: UUID


class CreateCategoryHandler:
    def __init__(self, repo: IVideoRepository) -> None:
        self._repo = repo

    def handle(self, cmd: CreateCategoryCommand) -> None:
        from domain.library.entities import Category
        cat = Category.create(cmd.name.strip(), parent_id=cmd.parent_id)
        self._repo.save_category(cat)


class RenameCategoryHandler:
    def __init__(self, repo: IVideoRepository) -> None:
        self._repo = repo

    def handle(self, cmd: RenameCategoryCommand) -> None:
        cats = self._repo.list_categories()
        target = next((c for c in cats if c.id == cmd.category_id), None)
        if target is None:
            raise KeyError(f"Category {cmd.category_id} not found")
        target.name = cmd.new_name.strip()
        self._repo.save_category(target)


class DeleteCategoryHandler:
    def __init__(self, repo: IVideoRepository) -> None:
        self._repo = repo

    def handle(self, cmd: DeleteCategoryCommand) -> None:
        self._repo.delete_category(cmd.category_id)


@dataclass
class MoveCategoryCommand:
    category_id: UUID
    new_parent_id: UUID | None


class MoveCategoryHandler:
    def __init__(self, repo: IVideoRepository) -> None:
        self._repo = repo

    def handle(self, cmd: MoveCategoryCommand) -> None:
        cats = self._repo.list_categories()
        target = next((c for c in cats if c.id == cmd.category_id), None)
        if target is None:
            raise KeyError(f"Category {cmd.category_id} not found")
        target.parent_id = cmd.new_parent_id
        self._repo.save_category(target)


@dataclass
class DeleteTagCommand:
    tag_id: UUID


class DeleteTagHandler:
    def __init__(self, repo: IVideoRepository) -> None:
        self._repo = repo

    def handle(self, cmd: DeleteTagCommand) -> None:
        self._repo.delete_tag(cmd.tag_id)


class ImportPlaylistHandler:
    """Imports a playlist in chunks of 50 to limit memory usage."""

    CHUNK_SIZE = 50

    def __init__(
        self,
        add_handler: AddVideoHandler,
        ytdlp: IMediaSource,
        on_progress: "Callable[[int, int], None] | None" = None,
    ) -> None:
        self._add = add_handler
        self._ytdlp = ytdlp
        self._on_progress = on_progress

    def handle(self, cmd: ImportPlaylistCommand) -> int:
        opts = {
            "quiet": True,
            "extract_flat": True,
            "skip_download": True,
        }
        import yt_dlp

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(cmd.playlist_url, download=False) or {}

        entries = info.get("entries") or []
        total = len(entries)
        imported = 0

        for i in range(0, total, self.CHUNK_SIZE):
            chunk = entries[i : i + self.CHUNK_SIZE]
            for entry in chunk:
                url = entry.get("url") or entry.get("webpage_url")
                if not url:
                    continue
                try:
                    add_cmd = AddVideoCommand(
                        url=url,
                        favorite=cmd.favorite,
                        category_id=cmd.category_id,
                        fetch_metadata=False,
                    )
                    self._add.handle(add_cmd)
                    imported += 1
                except Exception:
                    logger.exception("재생목록 영상 추가 실패")  # duplicate or fetch error — skip silently
            if self._on_progress:
                self._on_progress(min(i + self.CHUNK_SIZE, total), total)

        return imported


@dataclass
class RefreshCategoryMetadataCommand:
    category_ids: list[UUID]  # empty list = refresh all videos


@dataclass
class SetCategoryVideoOrderCommand:
    category_id: UUID
    video_ids: list[UUID]


class SetCategoryVideoOrderHandler:
    def __init__(self, repo: IVideoRepository) -> None:
        self._repo = repo

    def handle(self, cmd: SetCategoryVideoOrderCommand) -> None:
        self._repo.set_category_video_order(cmd.category_id, cmd.video_ids)


def _refetch_video_metadata(
    repo: IVideoRepository,
    bus: IEventBus,
    ytdlp: IMediaSource,
    agg_id: UUID,
    url: str,
) -> bool:
    """영상 1개의 메타데이터를 yt-dlp로 YouTube(웹) 기준 재수집해 저장한다.

    제목·설명·채널·길이·게시일·조회수·태그·썸네일을 갱신하며, 사용자가 직접 추가한
    태그는 병합해 보존한다. 실제로 갱신·저장되면 True. `RefreshCategoryMetadataHandler`
    (카테고리 일괄)와 `RefreshVideoMetadataHandler`(단건)가 공유한다.
    """
    info = ytdlp.fetch_metadata(url)
    if not info:
        return False
    full_agg = repo.get_by_id(agg_id)
    if full_agg is None:
        return False

    title = info.get("title") or full_agg.video.title
    desc = info.get("description") or ""
    channel = None
    if info.get("uploader"):
        channel = ChannelInfo(
            name=info.get("uploader", ""),
            url=info.get("uploader_url") or "",
            channel_id=info.get("channel_id") or info.get("uploader_id") or "",
        )
    duration = Duration(int(info["duration"])) if info.get("duration") else None
    published_at = None
    if info.get("upload_date"):
        raw = info["upload_date"]
        published_at = datetime(int(raw[:4]), int(raw[4:6]), int(raw[6:]))
    view_count = info.get("view_count")
    thumbnail_url = info.get("thumbnail") or ""

    raw_tags: list[str] = list(info.get("tags") or [])
    raw_tags += list(info.get("categories") or [])
    desc_tags = re.findall(r"#([\w가-힣]{2,})", desc)
    raw_tags += desc_tags[:10]
    tag_names = list(dict.fromkeys(
        t.strip() for t in raw_tags if isinstance(t, str) and t.strip()
    ))
    tag_ids = [repo.get_or_create_tag(t).id for t in tag_names]
    # 사용자가 직접 추가한 태그를 보존하기 위해 기존 태그와 병합
    merged_tag_ids = list(dict.fromkeys([*full_agg.tag_ids, *tag_ids]))

    full_agg.update_metadata(
        title=title,
        description=desc or None,
        channel=channel,
        duration=duration,
        published_at=published_at,
        view_count=view_count,
    )
    full_agg.set_tags(merged_tag_ids)

    if thumbnail_url:
        thumb_path = ytdlp.download_thumbnail(full_agg.id, thumbnail_url, force=True)
        if thumb_path:
            full_agg.update_metadata(thumbnail_path=thumb_path)

    repo.save(full_agg)
    bus.publish_all(full_agg.pull_events())
    return True


class RefreshCategoryMetadataHandler:
    """Re-fetches full metadata (title, description, tags, view count, thumbnail)
    for every video in the specified categories. Pass empty category_ids to
    refresh all videos in the library.
    """

    CHUNK_SIZE = 50

    def __init__(
        self,
        repo: IVideoRepository,
        event_bus: IEventBus,
        ytdlp: IMediaSource,
    ) -> None:
        self._repo = repo
        self._bus = event_bus
        self._ytdlp = ytdlp

    def handle(
        self,
        cmd: RefreshCategoryMetadataCommand,
        on_progress: "Callable[[int, int], None] | None" = None,
    ) -> int:
        total = self._repo.count(SearchQuery(category_ids=cmd.category_ids))
        refreshed = 0
        offset = 0

        while True:
            batch = self._repo.search(SearchQuery(
                category_ids=cmd.category_ids,
                limit=self.CHUNK_SIZE,
                offset=offset,
            ))
            if not batch:
                break

            for agg in batch:
                try:
                    if _refetch_video_metadata(
                        self._repo, self._bus, self._ytdlp,
                        agg.id, str(agg.video.url),
                    ):
                        refreshed += 1
                except Exception:
                    logger.exception("영상 메타데이터 갱신 실패")

            if on_progress:
                try:
                    on_progress(min(offset + len(batch), total), total)
                except Exception:
                    logger.exception("진행률 콜백 실행 실패")
            offset += self.CHUNK_SIZE
            if len(batch) < self.CHUNK_SIZE:
                break

        self._repo.delete_zero_count_tags()
        return refreshed


@dataclass
class RefreshVideoMetadataCommand:
    """영상 1개의 메타데이터를 YouTube(yt-dlp)에서 재수집해 갱신한다(상세화면 ⟳)."""
    video_id: UUID


class RefreshVideoMetadataHandler:
    """단일 영상 메타데이터 갱신 — 상세화면의 '상세 정보 갱신'(⟳) 버튼용.

    `RefreshCategoryMetadataHandler`와 동일한 재수집 로직(`_refetch_video_metadata`)을
    한 영상에만 적용해, DB에 저장된 오래된/부실한 메타데이터를 YouTube 웹 기준으로
    맞춘다. 갱신되면 True.
    """

    def __init__(
        self,
        repo: IVideoRepository,
        event_bus: IEventBus,
        ytdlp: IMediaSource,
    ) -> None:
        self._repo = repo
        self._bus = event_bus
        self._ytdlp = ytdlp

    def handle(self, cmd: RefreshVideoMetadataCommand) -> bool:
        agg = self._repo.get_by_id(cmd.video_id)
        if agg is None:
            return False
        return _refetch_video_metadata(
            self._repo, self._bus, self._ytdlp, agg.id, str(agg.video.url)
        )


# ── YouTube 재생목록 → 카테고리 가져오기 ──────────────────────────────────────

@dataclass
class ImportYouTubePlaylistToCategoryCommand:
    yt_playlist_id: str
    category_id: UUID | None
    cookie_opts: dict = field(default_factory=dict)
    on_progress: Callable[[int, int], None] | None = None


@dataclass
class RefreshVideoThumbnailCommand:
    """영상 1개의 썸네일을 갱신한다.

    YouTube 영상이면 video_url에서 video_id를 파생해 i.ytimg.com에서 재다운로드한다.
    파일이 max_age_days 이내이면 갱신을 생략한다.
    """
    video_id: UUID
    video_url: str
    max_age_days: int = 7


class RefreshVideoThumbnailHandler:
    def __init__(self, repo: IVideoRepository, ytdlp: IMediaSource) -> None:
        self._repo = repo
        self._ytdlp = ytdlp

    def handle(self, cmd: RefreshVideoThumbnailCommand) -> str | None:
        """썸네일을 갱신한다. 새 파일 경로를 반환하거나 갱신 불필요/실패 시 None."""
        agg = self._repo.get_by_id(cmd.video_id)
        if agg is None:
            return None

        # YouTube 영상 ID 추출 (비 YouTube면 갱신 생략)
        m = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", cmd.video_url)
        if not m:
            m = re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", cmd.video_url)
        if not m:
            return None

        vid = m.group(1)
        thumb_url = f"https://i.ytimg.com/vi/{vid}/maxresdefault.jpg"

        new_path = self._ytdlp.download_thumbnail(
            cmd.video_id, thumb_url, max_age_days=cmd.max_age_days
        )
        if new_path is None:
            # maxresdefault 실패 시 hqdefault fallback
            hq_url = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
            new_path = self._ytdlp.download_thumbnail(
                cmd.video_id, hq_url, max_age_days=cmd.max_age_days
            )
        if new_path is None:
            return None

        if new_path != agg.video.thumbnail_path:
            agg.update_metadata(thumbnail_path=new_path)
            self._repo.save(agg)
            logger.info("썸네일 갱신 완료: %s → %s", cmd.video_id, new_path)

        return new_path


class ImportYouTubePlaylistToCategoryHandler:
    """YouTube 재생목록의 영상들을 라이브러리의 특정 카테고리로 가져온다.

    재생목록 entry에 포함된 메타데이터를 최대한 활용해 빠르게 upsert한다.
    이미 라이브러리에 있는 영상은 카테고리만 재할당된다.
    """

    def __init__(
        self,
        video_repo: IVideoRepository,
        event_bus: IEventBus,
        ytdlp: IMediaSource,
        add_video_handler: "AddVideoHandler",
    ) -> None:
        self._repo = video_repo
        self._bus = event_bus
        self._ytdlp = ytdlp
        self._add_video = add_video_handler

    def handle(self, cmd: ImportYouTubePlaylistToCategoryCommand) -> int:
        """처리된 영상 수 반환."""
        _, entries = self._ytdlp.fetch_playlist_videos(
            cmd.yt_playlist_id, cmd.cookie_opts or {}
        )
        total = len(entries)
        count = 0
        for i, entry in enumerate(entries):
            url = entry.get("url") or ""
            if not url:
                continue
            try:
                existing = self._repo.get_by_url(url)
                if existing is not None:
                    existing.assign_category(cmd.category_id)
                    self._repo.save(existing)
                    self._bus.publish_all(existing.pull_events())
                else:
                    add_cmd = AddVideoCommand(
                        url=url,
                        category_id=cmd.category_id,
                        prefetched_title=entry.get("title"),
                        prefetched_channel=entry.get("channel_name"),
                        prefetched_duration_sec=entry.get("duration_sec"),
                        prefetched_thumbnail_url=entry.get("thumbnail_url"),
                        prefetched_upload_date=entry.get("upload_date"),
                        prefetched_view_count=entry.get("view_count"),
                    )
                    self._add_video.handle(add_cmd)
                count += 1
            except Exception:
                logger.exception("재생목록 영상 카테고리 가져오기 실패")
            if cmd.on_progress:
                cmd.on_progress(i + 1, total)
        return count
