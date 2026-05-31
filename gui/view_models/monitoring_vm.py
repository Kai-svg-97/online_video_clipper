from __future__ import annotations

from uuid import UUID

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from application.monitoring.commands import (
    ImportYouTubeSubscriptionsCommand,
    ImportYouTubeSubscriptionsHandler,
    SetMonitoringRuleCommand,
    SetMonitoringRuleHandler,
    SubscribeChannelCommand,
    SubscribeChannelHandler,
    UnsubscribeChannelCommand,
    UnsubscribeChannelHandler,
)
from domain.monitoring.value_objects import MonitoringRule
from application.monitoring.dtos import SubscriptionDTO
from application.monitoring.queries import GetSubscriptionsHandler

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from infrastructure.auth.youtube_auth import YouTubeAuthService


class _ImportYTSubsWorker(QThread):
    finished_ok = pyqtSignal(int)
    finished_err = pyqtSignal(str)

    def __init__(
        self,
        handler: ImportYouTubeSubscriptionsHandler,
        cookie_opts: dict,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._handler = handler
        self._cookie_opts = cookie_opts

    def run(self) -> None:
        try:
            count = self._handler.handle(
                ImportYouTubeSubscriptionsCommand(cookie_opts=self._cookie_opts)
            )
            self.finished_ok.emit(count)
        except Exception as exc:
            self.finished_err.emit(str(exc))


class MonitoringViewModel(QObject):
    subscriptions_changed = pyqtSignal()
    error_occurred = pyqtSignal(str)
    import_yt_finished = pyqtSignal(int)   # 가져온 채널 수

    def __init__(
        self,
        subscribe_handler: SubscribeChannelHandler,
        unsubscribe_handler: UnsubscribeChannelHandler,
        set_rule_handler: SetMonitoringRuleHandler,
        get_subs_handler: GetSubscriptionsHandler,
        import_yt_handler: ImportYouTubeSubscriptionsHandler | None = None,
        auth_service: "YouTubeAuthService | None" = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._subscribe = subscribe_handler
        self._unsubscribe = unsubscribe_handler
        self._set_rule = set_rule_handler
        self._get_subs = get_subs_handler
        self._import_yt = import_yt_handler
        self._auth = auth_service
        self._subscriptions: list[SubscriptionDTO] = []
        self._import_workers: list[_ImportYTSubsWorker] = []

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

    def set_rule(self, subscription_id: UUID, rule: MonitoringRule) -> None:
        try:
            self._set_rule.handle(SetMonitoringRuleCommand(subscription_id=subscription_id, rule=rule))
            self.load()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def import_from_youtube(self) -> None:
        if self._import_yt is None:
            self.error_occurred.emit("YouTube 구독 가져오기 기능이 초기화되지 않았습니다.")
            return
        if self._import_workers:
            return  # 이미 실행 중
        cookie_opts = self._auth.get_ytdlp_opts() if self._auth else {}
        worker = _ImportYTSubsWorker(self._import_yt, cookie_opts, self)
        worker.finished_ok.connect(self._on_import_ok)
        worker.finished_err.connect(self.error_occurred)
        worker.finished.connect(lambda: self._import_workers.remove(worker))
        self._import_workers.append(worker)
        worker.start()

    def _on_import_ok(self, count: int) -> None:
        self.load()
        self.import_yt_finished.emit(count)
