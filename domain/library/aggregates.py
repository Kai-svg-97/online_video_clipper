from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from domain.library.entities import Video
from domain.library.events import VideoAdded, VideoDeleted, VideoMarkedWatched, VideoUpdated
from domain.library.value_objects import ChannelInfo, Duration, VideoUrl


def _now() -> datetime:
    return datetime.now(timezone.utc)


class VideoAggregate:
    def __init__(
        self,
        video: Video,
        category_id: UUID | None = None,
        tag_ids: list[UUID] | None = None,
    ) -> None:
        self._video = video
        self._category_id = category_id
        self._tag_ids: list[UUID] = tag_ids or []
        self._events: list = []

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        url: VideoUrl,
        title: str,
        *,
        channel: ChannelInfo | None = None,
        duration: Duration | None = None,
        published_at: datetime | None = None,
        view_count: int | None = None,
        favorite: bool = False,
        category_id: UUID | None = None,
    ) -> VideoAggregate:
        video = Video.create(
            url=url,
            title=title,
            channel=channel,
            duration=duration,
            published_at=published_at,
            view_count=view_count,
            favorite=favorite,
        )
        agg = cls(video, category_id=category_id)
        agg._raise(VideoAdded(video_id=video.id, url=str(url), title=title))
        return agg

    # ------------------------------------------------------------------
    # Read accessors
    # ------------------------------------------------------------------

    @property
    def id(self) -> UUID:
        return self._video.id

    @property
    def video(self) -> Video:
        return self._video

    @property
    def category_id(self) -> UUID | None:
        return self._category_id

    @property
    def tag_ids(self) -> list[UUID]:
        return list(self._tag_ids)

    # ------------------------------------------------------------------
    # State-mutating methods (all state changes go through here)
    # ------------------------------------------------------------------

    def mark_watched(self) -> None:
        if not self._video.watched:
            self._video.watched = True
            self._video.updated_at = _now()
            self._raise(VideoMarkedWatched(video_id=self._video.id))

    def update_metadata(
        self,
        *,
        title: str | None = None,
        notes: str | None = None,
        favorite: bool | None = None,
        thumbnail_path: str | None = None,
        description: str | None = None,
        channel: ChannelInfo | None = None,
        duration: Duration | None = None,
        published_at: datetime | None = None,
        view_count: int | None = None,
    ) -> None:
        changed: list[str] = []
        if title is not None and title != self._video.title:
            self._video.title = title
            changed.append("title")
        if notes is not None and notes != self._video.notes:
            self._video.notes = notes
            changed.append("notes")
        if favorite is not None and favorite != self._video.favorite:
            self._video.favorite = favorite
            changed.append("favorite")
        if thumbnail_path is not None and thumbnail_path != self._video.thumbnail_path:
            self._video.thumbnail_path = thumbnail_path
            changed.append("thumbnail_path")
        if description is not None and description != self._video.description:
            self._video.description = description
            changed.append("description")
        if channel is not None and channel != self._video.channel:
            self._video.channel = channel
            changed.append("channel")
        if duration is not None and duration != self._video.duration:
            self._video.duration = duration
            changed.append("duration")
        if published_at is not None and published_at != self._video.published_at:
            self._video.published_at = published_at
            changed.append("published_at")
        if view_count is not None and view_count != self._video.view_count:
            self._video.view_count = view_count
            changed.append("view_count")
        if changed:
            self._video.updated_at = _now()
            self._raise(VideoUpdated(video_id=self._video.id, changed_fields=tuple(changed)))

    def assign_category(self, category_id: UUID | None) -> None:
        if self._category_id != category_id:
            self._category_id = category_id
            self._video.updated_at = _now()
            self._raise(VideoUpdated(video_id=self._video.id, changed_fields=("category",)))

    def set_tags(self, tag_ids: list[UUID]) -> None:
        if set(self._tag_ids) != set(tag_ids):
            self._tag_ids = list(tag_ids)
            self._video.updated_at = _now()
            self._raise(VideoUpdated(video_id=self._video.id, changed_fields=("tags",)))

    def delete(self) -> None:
        self._raise(VideoDeleted(video_id=self._video.id))

    # ------------------------------------------------------------------
    # Event infrastructure
    # ------------------------------------------------------------------

    def _raise(self, event: object) -> None:
        self._events.append(event)

    def pull_events(self) -> list:
        events = list(self._events)
        self._events.clear()
        return events
