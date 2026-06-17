from __future__ import annotations

from collections import deque
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

FEED_ALL_KEY = "__all__"   # 전체 구독 피드 식별 키


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
        self._key: str = ""   # _run()에서 설정

    def run(self) -> None:
        try:
            def on_progress(batch: list) -> None:
                self.partial_ready.emit(list(batch))  # thread-safe: Qt queued connection
            result = self._fetch(on_progress=on_progress)
            self.finished_ok.emit(result)
        except Exception as exc:
            self.finished_err.emit(str(exc))


class FeedViewModel(QObject):
    # ── 하위 호환 시그널 ──────────────────────────────────────────────────────
    feed_changed = pyqtSignal()
    feed_batch_appended = pyqtSignal(list)   # list[FeedVideoDTO] — 부분 결과 배치
    channel_infos_changed = pyqtSignal()
    loading_changed = pyqtSignal(bool)
    error_occurred = pyqtSignal(str)
    # ── 키별 시그널 (멀티워커·채널별 캐시 지원) ───────────────────────────────
    loading_key_changed = pyqtSignal(str, bool)   # (key, loading)
    feed_key_changed    = pyqtSignal(str, list)   # (key, items)
    feed_batch_ready    = pyqtSignal(str, list)   # (key, batch)

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
        # ── 멀티워커 ─────────────────────────────────────────────────────────
        self._workers: list[_FeedWorker] = []
        self._pending_queue: deque[tuple] = deque()   # (fetch, on_ok, gen, key)
        # ── 채널별 캐시 ──────────────────────────────────────────────────────
        self._cache: dict[str, list[FeedVideoDTO]] = {}
        # ── 설정에서 max_workers 읽기 ─────────────────────────────────────────
        try:
            import config.settings as _s  # noqa: PLC0415
            self._max_workers: int = getattr(_s, "MAX_CONCURRENT_FEED_WORKERS", 4)
        except Exception:
            self._max_workers = 4
        self._gen: int = 0

    @property
    def feed(self) -> list[FeedVideoDTO]:
        return self._feed

    @property
    def channel_infos(self) -> list[ChannelInfoDTO]:
        return self._channel_infos

    def get_cached(self, key: str) -> list[FeedVideoDTO] | None:
        """캐시에 해당 키의 데이터가 있으면 반환, 없으면 None."""
        return self._cache.get(key)

    def set_max_workers(self, n: int) -> None:
        """최대 동시 워커 수를 변경한다 (메인 스레드에서만 호출)."""
        self._max_workers = max(1, min(n, 8))

    def _cookie_opts(self) -> dict:
        return self._auth.get_ytdlp_opts() if self._auth else {}

    def _start(self, fetch: Callable[[], list], on_ok, key: str, silent: bool = False) -> None:
        self._gen += 1
        gen = self._gen
        if len(self._workers) < self._max_workers:
            self._run(fetch, on_ok, gen, key, silent)
        else:
            if len(self._pending_queue) >= 32:   # 메모리 안전 상한
                self._pending_queue.popleft()
            self._pending_queue.append((fetch, on_ok, gen, key, silent))

    def _run(self, fetch: Callable[[], list], on_ok, gen: int, key: str, silent: bool = False) -> None:
        # silent=True: 캐시를 이미 표시 중인 재방문 — 스피너·상태텍스트 없이 조용히 갱신
        if not silent:
            self.loading_changed.emit(True)
            self.loading_key_changed.emit(key, True)
        worker = _FeedWorker(fetch, self)
        worker._key = key
        worker.finished_ok.connect(
            lambda items, _g=gen, _ok=on_ok, _k=key: self._finish_ok(items, _ok, _g, _k)
        )
        worker.finished_err.connect(lambda msg, _g=gen: self._finish_err(msg, _g))
        worker.finished.connect(lambda w=worker, _k=key, _s=silent: self._drain(w, _k, _s))
        worker.partial_ready.connect(
            lambda batch, _g=gen, _k=key, _s=silent: self._on_partial(batch, _g, _k, _s)
        )
        self._workers.append(worker)
        worker.start()

    def _finish_ok(self, items, on_ok, gen: int, key: str) -> None:
        if gen == self._gen:
            self._cache[key] = items
            on_ok(items, key)

    def _finish_err(self, msg: str, gen: int) -> None:
        if gen == self._gen:
            self.error_occurred.emit(msg)

    def _drain(self, worker, key: str, silent: bool = False) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        if not silent:
            self.loading_key_changed.emit(key, False)
        while len(self._workers) < self._max_workers and self._pending_queue:
            fetch, on_ok, gen, next_key, next_silent = self._pending_queue.popleft()
            self._run(fetch, on_ok, gen, next_key, next_silent)
        if not self._workers:
            self.loading_changed.emit(False)

    def refresh(self, limit: int = 100, silent: bool = False) -> None:
        """전체 구독 피드를 가져온다. silent=True면 스피너 없이 조용히 갱신한다."""
        cookie_opts = self._cookie_opts()
        self._start(
            lambda on_progress=None: self._handler.handle(
                GetSubscriptionFeedQuery(limit=limit, cookie_opts=cookie_opts),
                on_progress=on_progress,
            ),
            self._on_ok,
            key=FEED_ALL_KEY,
            silent=silent,
        )

    def load_channel(self, channel_url: str, limit: int = 30, silent: bool = False) -> None:
        """특정 채널의 최신 영상을 가져온다. silent=True면 스피너 없이 조용히 갱신한다."""
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
            key=channel_url,
            silent=silent,
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
            key="__channel_infos__",
        )

    def _on_partial(self, batch: list, gen: int, key: str, silent: bool = False) -> None:
        """부분 결과 배치 수신 — gen 일치 시만 UI에 방출.
        silent(재방문 갱신)일 땐 이미 캐시를 표시 중이므로 부분 배치를 흘리지 않는다."""
        if gen != self._gen or silent:
            return
        self.feed_batch_appended.emit(batch)   # 하위 호환
        self.feed_batch_ready.emit(key, batch)

    def _on_ok(self, items: list[FeedVideoDTO], key: str) -> None:
        self._feed = items
        self.feed_key_changed.emit(key, items)
        self.feed_changed.emit()   # 하위 호환

    def _on_infos_ok(self, items: list[ChannelInfoDTO], key: str) -> None:
        self._channel_infos = items
        self.channel_infos_changed.emit()

    def shutdown(self) -> None:
        """종료 시 진행 중인 워커를 정리한다 (MainWindow.closeEvent에서 호출)."""
        self._pending_queue.clear()
        for worker in list(self._workers):
            worker.wait(3000)
