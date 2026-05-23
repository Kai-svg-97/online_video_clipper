from __future__ import annotations

from domain.monitoring.aggregates import ChannelMonitorAggregate
from domain.monitoring.repositories import IChannelRepository


class GetSubscriptionsHandler:
    def __init__(self, repo: IChannelRepository) -> None:
        self._repo = repo

    def handle(self) -> list[ChannelMonitorAggregate]:
        return self._repo.list_active()
