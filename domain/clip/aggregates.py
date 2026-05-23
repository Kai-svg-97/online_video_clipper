from __future__ import annotations

from uuid import UUID

from domain.clip.entities import Clip
from domain.clip.events import ClipCreated, ClipDeleted
from domain.clip.value_objects import TimeRange


class ClipAggregate:
    def __init__(self, clip: Clip) -> None:
        self._clip = clip
        self._events: list = []

    @classmethod
    def create(
        cls,
        source_video_id: UUID,
        title: str,
        time_range: TimeRange,
    ) -> ClipAggregate:
        clip = Clip.create(source_video_id, title, time_range)
        agg = cls(clip)
        agg._raise(ClipCreated(clip_id=clip.id, source_video_id=source_video_id))
        return agg

    @property
    def id(self) -> UUID:
        return self._clip.id

    @property
    def clip(self) -> Clip:
        return self._clip

    def set_file_path(self, path: str) -> None:
        self._clip.file_path = path

    def set_thumbnail_path(self, path: str) -> None:
        self._clip.thumbnail_path = path

    def delete(self) -> None:
        self._raise(ClipDeleted(clip_id=self._clip.id))

    def _raise(self, event: object) -> None:
        self._events.append(event)

    def pull_events(self) -> list:
        events = list(self._events)
        self._events.clear()
        return events
