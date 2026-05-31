from __future__ import annotations

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from application.library.dtos import FeedVideoDTO
from application.library.playlist_queries import GetSubscriptionFeedHandler, GetSubscriptionFeedQuery

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from infrastructure.auth.youtube_auth import YouTubeAuthService


class _FeedWorker(QThread):
    finished_ok = pyqtSignal(list)
    finished_err = pyqtSignal(str)

    def __init__(
        self,
        handler: GetSubscriptionFeedHandler,
        limit: int,
        cookie_opts: dict,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._handler = handler
        self._limit = limit
        self._cookie_opts = cookie_opts

    def run(self) -> None:
        try:
            result = self._handler.handle(
                GetSubscriptionFeedQuery(
                    limit=self._limit,
                    cookie_opts=self._cookie_opts,
                )
            )
            self.finished_ok.emit(result)
        except Exception as exc:
            self.finished_err.emit(str(exc))


class FeedViewModel(QObject):
    feed_changed = pyqtSignal()
    loading_changed = pyqtSignal(bool)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        handler: GetSubscriptionFeedHandler,
        auth_service: "YouTubeAuthService | None" = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._handler = handler
        self._auth = auth_service
        self._feed: list[FeedVideoDTO] = []
        self._workers: list[_FeedWorker] = []

    @property
    def feed(self) -> list[FeedVideoDTO]:
        return self._feed

    def refresh(self, limit: int = 100) -> None:
        if self._workers:
            return
        self.loading_changed.emit(True)
        cookie_opts = self._auth.get_ytdlp_opts() if self._auth else {}
        worker = _FeedWorker(self._handler, limit, cookie_opts, self)
        worker.finished_ok.connect(self._on_ok)
        worker.finished_err.connect(self._on_err)
        worker.finished.connect(lambda: self._workers.remove(worker))
        self._workers.append(worker)
        worker.start()

    def _on_ok(self, items: list[FeedVideoDTO]) -> None:
        self._feed = items
        self.loading_changed.emit(False)
        self.feed_changed.emit()

    def _on_err(self, err: str) -> None:
        self.loading_changed.emit(False)
        self.error_occurred.emit(err)
