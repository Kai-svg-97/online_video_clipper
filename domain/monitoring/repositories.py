from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from domain.monitoring.aggregates import ChannelMonitorAggregate


class IChannelRepository(ABC):
    @abstractmethod
    def save(self, aggregate: ChannelMonitorAggregate) -> None: ...

    @abstractmethod
    def get_by_id(self, subscription_id: UUID) -> ChannelMonitorAggregate | None: ...

    @abstractmethod
    def get_by_channel_id(self, channel_id: str) -> ChannelMonitorAggregate | None: ...

    @abstractmethod
    def list_active(self) -> list[ChannelMonitorAggregate]: ...

    @abstractmethod
    def delete(self, subscription_id: UUID) -> None: ...
