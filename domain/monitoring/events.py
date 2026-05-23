from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ChannelSubscribed:
    subscription_id: UUID
    channel_id: str
    channel_name: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class ChannelUnsubscribed:
    subscription_id: UUID
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class NewVideoDetected:
    channel_id: str
    video_url: str
    title: str
    duration_sec: int | None
    occurred_at: datetime = field(default_factory=_now)
