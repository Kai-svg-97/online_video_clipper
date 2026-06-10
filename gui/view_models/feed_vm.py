from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from application.library.dtos import ChannelInfoDTO, FeedVideoDTO
from application.library.playlist_queries import (
    GetChannelVideosHandler,
    GetChannelVideosQuery,
    GetSubscribedChannelInfosHandler,
    GetSubscribedChannelInfosQuery,
    GetSubscriptionFeedHandler,
    GetSubscriptionFeedQuery,
)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from infrastructure.auth.youtube_auth import YouTubeAuthService


class _FeedWorker(QThread):
    """임의의 조회 함수를 워커 스레드에서 실행해 결과/에러를 방출한다."""

    finished_ok = pyqtSignal(list)
    finished_err = pyqtSignal(str)

    def __init__(
        self,
        fetch: Callable[[], list[FeedVideoDTO]],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._fetch = fetch

    def run(self) -> None:
        try:
            result = self._fetch()
            self.finished_ok.emit(result)
        except Exception as exc:
            self.finished_err.emit(str(exc))


class FeedViewModel(QObject):
    feed_changed = pyqtSignal()
    channel_infos_changed = pyqtSignal()
    loading_changed = pyqtSignal(bool)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        handler: GetSubscriptionFeedHandler,
        channel_handler: GetChannelVideosHandler | None = None,
        channel_infos_handler: GetSubscribedChannelInfosHandler | None = None,
        auth_service: "YouTubeAuthService | None" = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._handler = handler
        self._channel_handler = channel_handler
        self._channel_infos_handler = channel_infos_handler
        self._auth = auth_service
        self._feed: list[FeedVideoDTO] = []
        self._channel_infos: list[ChannelInfoDTO] = []
        self._workers: list[_FeedWorker] = []

    @property
    def feed(self) -> list[FeedVideoDTO]:
        return self._feed

    @property
    def channel_infos(self) -> list[ChannelInfoDTO]:
        return self._channel_infos

    def _cookie_opts(self) -> dict:
        return self._auth.get_ytdlp_opts() if self._auth else {}

    def _start(self, fetch: Callable[[], list], on_ok) -> None:
        if self._workers:
            return
        self.loading_changed.emit(True)
        worker = _FeedWorker(fetch, self)
        worker.finished_ok.connect(on_ok)
        worker.finished_err.connect(self._on_err)
        worker.finished.connect(lambda: self._workers.remove(worker))
        self._workers.append(worker)
        worker.start()

    def refresh(self, limit: int = 100) -> None:
        """전체 구독 피드를 가져온다."""
        cookie_opts = self._cookie_opts()
        self._start(
            lambda: self._handler.handle(
                GetSubscriptionFeedQuery(limit=limit, cookie_opts=cookie_opts)
            ),
            self._on_ok,
        )

    def load_channel(self, channel_url: str, limit: int = 30) -> None:
        """특정 채널의 최신 영상을 가져온다."""
        if self._channel_handler is None:
            self.error_occurred.emit("채널 영상 조회 기능을 사용할 수 없습니다.")
            return
        cookie_opts = self._cookie_opts()
        self._start(
            lambda: self._channel_handler.handle(
                GetChannelVideosQuery(
                    channel_url=channel_url, limit=limit, cookie_opts=cookie_opts
                )
            ),
            self._on_ok,
        )

    def load_channel_infos(self, channels: list[tuple[str, str, str]]) -> None:
        """구독 채널 카드 정보(아바타·구독자수·영상수)를 가져온다.

        channels: (channel_id, channel_name, channel_url) 튜플 목록.
        """
        if self._channel_infos_handler is None:
            self.error_occurred.emit("채널 정보 조회 기능을 사용할 수 없습니다.")
            return
        self._start(
            lambda: self._channel_infos_handler.handle(
                GetSubscribedChannelInfosQuery(channels=channels)
            ),
            self._on_infos_ok,
        )

    def _on_ok(self, items: list[FeedVideoDTO]) -> None:
        self._feed = items
        self.loading_changed.emit(False)
        self.feed_changed.emit()

    def _on_infos_ok(self, items: list[ChannelInfoDTO]) -> None:
        self._channel_infos = items
        self.loading_changed.emit(False)
        self.channel_infos_changed.emit()

    def _on_err(self, err: str) -> None:
        self.loading_changed.emit(False)
        self.error_occurred.emit(err)

    def shutdown(self) -> None:
        """종료 시 진행 중인 워커를 정리한다 (MainWindow.closeEvent에서 호출)."""
        for worker in list(self._workers):
            worker.wait(3000)
