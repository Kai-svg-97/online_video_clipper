from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ClipCreated:
    clip_id: UUID
    source_video_id: UUID
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class ClipDeleted:
    clip_id: UUID
    occurred_at: datetime = field(default_factory=_now)
