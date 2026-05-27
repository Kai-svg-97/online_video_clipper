from __future__ import annotations

from uuid import UUID

from PyQt6.QtCore import QObject, pyqtSignal

from application.monitoring.commands import (
    SetMonitoringRuleHandler,
    SubscribeChannelCommand,
    SubscribeChannelHandler,
    UnsubscribeChannelCommand,
    UnsubscribeChannelHandler,
)
from application.monitoring.dtos import SubscriptionDTO
from application.monitoring.queries import GetSubscriptionsHandler


class MonitoringViewModel(QObject):
    subscriptions_changed = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        subscribe_handler: SubscribeChannelHandler,
        unsubscribe_handler: UnsubscribeChannelHandler,
        set_rule_handler: SetMonitoringRuleHandler,
        get_subs_handler: GetSubscriptionsHandler,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._subscribe = subscribe_handler
        self._unsubscribe = unsubscribe_handler
        self._set_rule = set_rule_handler
        self._get_subs = get_subs_handler
        self._subscriptions: list[SubscriptionDTO] = []

    @property
    def subscriptions(self) -> list[SubscriptionDTO]:
        return self._subscriptions

    def load(self) -> None:
        try:
            self._subscriptions = self._get_subs.handle()
            self.subscriptions_changed.emit()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def subscribe_channel(self, channel_url: str) -> None:
        try:
            self._subscribe.handle(SubscribeChannelCommand(channel_url=channel_url))
            self.load()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def unsubscribe_channel(self, subscription_id: UUID) -> None:
        try:
            self._unsubscribe.handle(UnsubscribeChannelCommand(subscription_id=subscription_id))
            self._subscriptions = [s for s in self._subscriptions if s.id != subscription_id]
            self.subscriptions_changed.emit()
        except Exception as exc:
            self.error_occurred.emit(str(exc))
