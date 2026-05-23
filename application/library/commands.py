from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from domain.library.aggregates import VideoAggregate
from domain.library.entities import Category, Tag
from domain.library.repositories import IVideoRepository
from domain.library.services import DuplicateDetectionService
from domain.library.value_objects import ChannelInfo, Duration, VideoUrl
from infrastructure.event_bus import EventBus
from infrastructure.downloader.ytdlp_adapter import YtDlpAdapter

from datetime import datetime


@dataclass
class AddVideoCommand:
    url: str
    favorite: bool = False
    category_id: UUID | None = None
    tags: list[str] = field(default_factory=list)
    fetch_metadata: bool = True


@dataclass
class UpdateVideoCommand:
    video_id: UUID
    title: str | None = None
    notes: str | None = None
    favorite: bool | None = None
    category_id: UUID | None = None
    tags: list[str] | None = None


@dataclass
class DeleteVideoCommand:
    video_id: UUID


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
        event_bus: EventBus,
        ytdlp: YtDlpAdapter | None = None,
    ) -> None:
        self._repo = repo
        self._bus = event_bus
        self._ytdlp = ytdlp
        self._dup = DuplicateDetectionService(repo)

    def handle(self, cmd: AddVideoCommand) -> VideoAggregate:
        self._dup.assert_unique(cmd.url)

        url = VideoUrl(cmd.url)
        title = cmd.url
        channel: ChannelInfo | None = None
        duration: Duration | None = None
        published_at: datetime | None = None
        view_count: int | None = None

        if cmd.fetch_metadata and self._ytdlp:
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

        tag_ids: list[UUID] = []
        for tag_name in cmd.tags:
            tag = self._repo.get_or_create_tag(tag_name)
            tag_ids.append(tag.id)

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
        agg.set_tags(tag_ids)
        self._repo.save(agg)
        self._bus.publish_all(agg.pull_events())
        return agg


class UpdateVideoHandler:
    def __init__(self, repo: IVideoRepository, event_bus: EventBus) -> None:
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
        )
        if cmd.category_id is not None:
            agg.assign_category(cmd.category_id)

        if cmd.tags is not None:
            tag_ids = [self._repo.get_or_create_tag(t).id for t in cmd.tags]
            agg.set_tags(tag_ids)

        self._repo.save(agg)
        self._bus.publish_all(agg.pull_events())


class DeleteVideoHandler:
    def __init__(self, repo: IVideoRepository, event_bus: EventBus) -> None:
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
    def __init__(self, repo: IVideoRepository, event_bus: EventBus) -> None:
        self._repo = repo
        self._bus = event_bus

    def handle(self, cmd: MarkWatchedCommand) -> None:
        agg = self._repo.get_by_id(cmd.video_id)
        if agg is None:
            raise KeyError(f"Video {cmd.video_id} not found")
        agg.mark_watched()
        self._repo.save(agg)
        self._bus.publish_all(agg.pull_events())


class ImportPlaylistHandler:
    """Imports a playlist in chunks of 50 to limit memory usage."""

    CHUNK_SIZE = 50

    def __init__(
        self,
        add_handler: AddVideoHandler,
        ytdlp: YtDlpAdapter,
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
                    pass  # duplicate or fetch error — skip silently
            if self._on_progress:
                self._on_progress(min(i + self.CHUNK_SIZE, total), total)

        return imported
