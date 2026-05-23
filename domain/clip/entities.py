from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from domain.clip.value_objects import TimeRange


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Clip:
    id: UUID
    source_video_id: UUID
    title: str
    file_path: str
    thumbnail_path: str
    time_range: TimeRange
    created_at: datetime

    @classmethod
    def create(
        cls,
        source_video_id: UUID,
        title: str,
        time_range: TimeRange,
    ) -> Clip:
        return cls(
            id=uuid4(),
            source_video_id=source_video_id,
            title=title,
            file_path="",
            thumbnail_path="",
            time_range=time_range,
            created_at=_now(),
        )
