from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from domain.library.aggregates import VideoAggregate
from domain.library.repositories import IVideoRepository, SearchQuery
from domain.library.value_objects import ChannelInfo, Duration, VideoUrl
from infrastructure.event_bus import EventBus
from infrastructure.downloader.ytdlp_adapter import YtDlpAdapter


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

    def handle(self, cmd: AddVideoCommand) -> VideoAggregate:
        title: str = cmd.url
        channel: ChannelInfo | None = None
        duration: Duration | None = None
        published_at: datetime | None = None
        view_count: int | None = None
        meta_tags: list[str] = []
        thumbnail_url: str = ""
        description: str = ""

        if cmd.fetch_metadata and self._ytdlp:
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
            except Exception:
                pass  # proceed with URL-as-title if metadata fetch fails

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
            if thumbnail_url and self._ytdlp and not existing.video.thumbnail_path:
                thumb_path = self._ytdlp.download_thumbnail(existing.id, thumbnail_url)
                if thumb_path:
                    existing.update_metadata(thumbnail_path=thumb_path)
            self._repo.save(existing)
            self._bus.publish_all(existing.pull_events())
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
        agg.set_tags(tag_ids)

        if thumbnail_url and self._ytdlp:
            thumb_path = self._ytdlp.download_thumbnail(agg.id, thumbnail_url)
            if thumb_path:
                agg.update_metadata(thumbnail_path=thumb_path)

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


# ------------------------------------------------------------------
# Video category assignment
# ------------------------------------------------------------------

@dataclass
class AssignCategoryCommand:
    video_id: UUID
    category_id: UUID | None   # None = remove from category


class AssignCategoryHandler:
    def __init__(self, repo: IVideoRepository, event_bus: EventBus) -> None:
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


@dataclass
class RefreshCategoryMetadataCommand:
    category_ids: list[UUID]  # empty list = refresh all videos


class RefreshCategoryMetadataHandler:
    """Re-fetches full metadata (title, description, tags, view count, thumbnail)
    for every video in the specified categories. Pass empty category_ids to
    refresh all videos in the library.
    """

    CHUNK_SIZE = 50

    def __init__(
        self,
        repo: IVideoRepository,
        event_bus: EventBus,
        ytdlp: YtDlpAdapter,
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
                    info = self._ytdlp.fetch_metadata(str(agg.video.url))
                    title = info.get("title") or agg.video.title
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

                    full_agg = self._repo.get_by_id(agg.id)
                    if full_agg is None:
                        continue

                    tag_ids = [self._repo.get_or_create_tag(t).id for t in tag_names]
                    full_agg.update_metadata(
                        title=title,
                        description=desc or None,
                        channel=channel,
                        duration=duration,
                        published_at=published_at,
                        view_count=view_count,
                    )
                    full_agg.set_tags(tag_ids)

                    if thumbnail_url:
                        thumb_path = self._ytdlp.download_thumbnail(full_agg.id, thumbnail_url, force=True)
                        if thumb_path:
                            full_agg.update_metadata(thumbnail_path=thumb_path)

                    self._repo.save(full_agg)
                    self._bus.publish_all(full_agg.pull_events())
                    refreshed += 1
                except Exception:
                    pass

            if on_progress:
                try:
                    on_progress(min(offset + len(batch), total), total)
                except Exception:
                    pass
            offset += self.CHUNK_SIZE
            if len(batch) < self.CHUNK_SIZE:
                break

        self._repo.delete_zero_count_tags()
        return refreshed
