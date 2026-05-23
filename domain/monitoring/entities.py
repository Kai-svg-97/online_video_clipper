from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from domain.monitoring.value_objects import MonitoringRule


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ChannelSubscription:
    id: UUID
    channel_id: str
    channel_name: str
    channel_url: str
    rule: MonitoringRule
    is_active: bool
    last_checked_at: datetime | None
    created_at: datetime

    @classmethod
    def create(
        cls,
        channel_id: str,
        channel_name: str,
        channel_url: str,
        rule: MonitoringRule | None = None,
    ) -> ChannelSubscription:
        return cls(
            id=uuid4(),
            channel_id=channel_id,
            channel_name=channel_name,
            channel_url=channel_url,
            rule=rule or MonitoringRule(),
            is_active=True,
            last_checked_at=None,
            created_at=_now(),
        )
