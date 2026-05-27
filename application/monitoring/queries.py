from __future__ import annotations

from application.monitoring.dtos import SubscriptionDTO
from domain.monitoring.aggregates import ChannelMonitorAggregate
from domain.monitoring.repositories import IChannelRepository


def _to_dto(agg: ChannelMonitorAggregate) -> SubscriptionDTO:
    s = agg.subscription
    return SubscriptionDTO(
        id=agg.id,
        channel_id=s.channel_id,
        channel_name=s.channel_name,
        channel_url=s.channel_url,
        auto_download=s.rule.auto_download,
        is_active=s.is_active,
    )


class GetSubscriptionsHandler:
    def __init__(self, repo: IChannelRepository) -> None:
        self._repo = repo

    def handle(self) -> list[SubscriptionDTO]:
        return [_to_dto(agg) for agg in self._repo.list_active()]
