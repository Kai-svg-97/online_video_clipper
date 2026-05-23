from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class VideoAdded:
    video_id: UUID
    url: str
    title: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class VideoUpdated:
    video_id: UUID
    changed_fields: tuple[str, ...]
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class VideoDeleted:
    video_id: UUID
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class VideoMarkedWatched:
    video_id: UUID
    occurred_at: datetime = field(default_factory=_now)
