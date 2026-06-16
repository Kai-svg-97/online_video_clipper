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
    partial_ready = pyqtSignal(list)  # 부분 결과 배치 — Qt 큐드 시그널로 main thread 전달

    def __init__(
        self,
        fetch: Callable[[], list[FeedVideoDTO]],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._fetch = fetch

    def run(self) -> None:
        try:
            def on_progress(batch: list) -> None:
                self.partial_ready.emit(list(batch))  # thread-safe: Qt queued connection
            result = self._fetch(on_progress=on_progress)
            self.finished_ok.emit(result)
        except Exception as exc:
            self.finished_err.emit(str(exc))


class FeedViewModel(QObject):
    feed_changed = pyqtSignal()
    feed_batch_appended = pyqtSignal(list)  # list[FeedVideoDTO] — 부분 결과 배치
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
        self._gen: int = 0   # 요청 세대 — 최신 요청 결과만 반영(이전 요청 무시)
        self._pending: tuple | None = None   # 진행 중일 때 보류된 최신 요청

    @property
    def feed(self) -> list[FeedVideoDTO]:
        return self._feed

    @property
    def channel_infos(self) -> list[ChannelInfoDTO]:
        return self._channel_infos

    def _cookie_opts(self) -> dict:
        return self._auth.get_ytdlp_opts() if self._auth else {}

    def _start(self, fetch: Callable[[], list], on_ok) -> None:
        # 한 번에 워커 하나만 실행한다(공유 세션 동시 과부하·hang 방지). 진행 중이면
        # 새 요청을 버리지 않고 '최신 보류'로 저장해 두었다가, 현재 워커가 끝나면 실행한다.
        # 세대 토큰으로 오래된 결과는 무시(최신 요청만 반영).
        self._gen += 1
        gen = self._gen
        if self._workers:
            self._pending = (fetch, on_ok, gen)   # 이전 보류는 덮어씀(최신만 유지)
            return
        self._run(fetch, on_ok, gen)

    def _run(self, fetch: Callable[[], list], on_ok, gen: int) -> None:
        self.loading_changed.emit(True)
        worker = _FeedWorker(fetch, self)
        worker.finished_ok.connect(lambda items, _g=gen, _ok=on_ok: self._finish_ok(items, _ok, _g))
        worker.finished_err.connect(lambda msg, _g=gen: self._finish_err(msg, _g))
        worker.finished.connect(lambda w=worker: self._drain(w))
        worker.partial_ready.connect(lambda batch, _g=gen: self._on_partial(batch, _g))
        self._workers.append(worker)
        worker.start()

    def _finish_ok(self, items, on_ok, gen: int) -> None:
        if gen == self._gen:
            on_ok(items)   # 데이터 세팅 + feed_changed/channel_infos_changed 방출

    def _finish_err(self, msg: str, gen: int) -> None:
        if gen == self._gen:
            self.error_occurred.emit(msg)

    def _drain(self, worker) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        if self._pending is not None and not self._workers:
            fetch, on_ok, gen = self._pending
            self._pending = None
            self._run(fetch, on_ok, gen)
        elif not self._workers:
            self.loading_changed.emit(False)   # 모든 워커 종료 → 로딩 상태 1회만 해제

    def refresh(self, limit: int = 100) -> None:
        """전체 구독 피드를 가져온다."""
        cookie_opts = self._cookie_opts()
        self._start(
            lambda on_progress=None: self._handler.handle(
                GetSubscriptionFeedQuery(limit=limit, cookie_opts=cookie_opts),
                on_progress=on_progress,
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
            lambda on_progress=None: self._channel_handler.handle(
                GetChannelVideosQuery(
                    channel_url=channel_url, limit=limit, cookie_opts=cookie_opts
                ),
                on_progress=on_progress,
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
            lambda on_progress=None: self._channel_infos_handler.handle(
                GetSubscribedChannelInfosQuery(channels=channels)
            ),
            self._on_infos_ok,
        )

    def _on_partial(self, batch: list, gen: int) -> None:
        """부분 결과 배치 수신 — gen 일치 시만 UI에 방출."""
        if gen != self._gen:
            return
        self.feed_batch_appended.emit(batch)

    def _on_ok(self, items: list[FeedVideoDTO]) -> None:
        # loading_changed(False)는 _drain이 (보류 포함) 모든 워커 종료 시 1회 방출한다.
        self._feed = items
        self.feed_changed.emit()

    def _on_infos_ok(self, items: list[ChannelInfoDTO]) -> None:
        self._channel_infos = items
        self.channel_infos_changed.emit()

    def shutdown(self) -> None:
        """종료 시 진행 중인 워커를 정리한다 (MainWindow.closeEvent에서 호출)."""
        self._pending = None
        for worker in list(self._workers):
            worker.wait(3000)
