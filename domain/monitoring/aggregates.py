from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from domain.monitoring.entities import ChannelSubscription
from domain.monitoring.events import ChannelSubscribed, ChannelUnsubscribed, NewVideoDetected
from domain.monitoring.value_objects import MonitoringRule


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ChannelMonitorAggregate:
    def __init__(self, subscription: ChannelSubscription) -> None:
        self._sub = subscription
        self._events: list = []

    @classmethod
    def create(
        cls,
        channel_id: str,
        channel_name: str,
        channel_url: str,
        rule: MonitoringRule | None = None,
    ) -> ChannelMonitorAggregate:
        sub = ChannelSubscription.create(channel_id, channel_name, channel_url, rule)
        agg = cls(sub)
        agg._raise(
            ChannelSubscribed(
                subscription_id=sub.id,
                channel_id=channel_id,
                channel_name=channel_name,
            )
        )
        return agg

    @property
    def id(self) -> UUID:
        return self._sub.id

    @property
    def subscription(self) -> ChannelSubscription:
        return self._sub

    def update_rule(self, rule: MonitoringRule) -> None:
        self._sub.rule = rule

    def deactivate(self) -> None:
        self._sub.is_active = False
        self._raise(ChannelUnsubscribed(subscription_id=self._sub.id))

    def record_check(self, checked_at: datetime | None = None) -> None:
        self._sub.last_checked_at = checked_at or _now()

    def notify_new_video(
        self, video_url: str, title: str, duration_sec: int | None
    ) -> None:
        self._raise(
            NewVideoDetected(
                channel_id=self._sub.channel_id,
                video_url=video_url,
                title=title,
                duration_sec=duration_sec,
            )
        )

    def _raise(self, event: object) -> None:
        self._events.append(event)

    def pull_events(self) -> list:
        events = list(self._events)
        self._events.clear()
        return events
