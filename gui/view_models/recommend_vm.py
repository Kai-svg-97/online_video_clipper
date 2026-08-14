"""추천 영상 스트립의 UI 상태.

``FeedViewModel``을 재사용하지 않고 별도 뷰모델을 두는 이유: FeedViewModel의
세대 카운터(``_gen``)는 키별 캐시가 있어도 **전역 하나**라, 추천 조회가 세대를
올리면 같은 시점에 진행 중이던 구독 피드/채널 조회 결과가 버려진다. 추천은
목록이 바뀔 때마다 자동으로 돌기 때문에 그 충돌이 상시 발생한다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from application.library.dtos import FeedVideoDTO
from application.library.playlist_queries import (
    GetRecommendationsHandler,
    GetRecommendationsQuery,
)

if TYPE_CHECKING:
    from infrastructure.auth.youtube_auth import YouTubeAuthService

logger = logging.getLogger(__name__)


class _RecommendWorker(QThread):
    finished_ok   = pyqtSignal(list)
    finished_err  = pyqtSignal(str)
    partial_ready = pyqtSignal(list)

    def __init__(self, fetch: Callable, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fetch = fetch

    def run(self) -> None:
        try:
            result = self._fetch(on_progress=lambda batch: self.partial_ready.emit(list(batch)))
            self.finished_ok.emit(result)
        except Exception as exc:
            logger.exception("추천 영상 조회 실패")
            self.finished_err.emit(str(exc))


class RecommendViewModel(QObject):
    """현재 목록 기반 추천 후보를 백그라운드로 조회한다."""

    items_changed   = pyqtSignal(list)   # list[FeedVideoDTO] — 최종 결과
    partial_ready   = pyqtSignal(list)   # list[FeedVideoDTO] — 부분 결과(즉시 표시용)
    loading_changed = pyqtSignal(bool)
    error_occurred  = pyqtSignal(str)

    def __init__(
        self,
        handler: GetRecommendationsHandler,
        auth_service: "YouTubeAuthService | None" = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._handler = handler
        self._auth = auth_service
        self._items: list[FeedVideoDTO] = []
        self._worker: _RecommendWorker | None = None
        self._gen: int = 0
        self._last_key: str = ""

    @property
    def items(self) -> list[FeedVideoDTO]:
        return self._items

    def _cookie_opts(self) -> dict:
        # 쿠키가 있으면 개인화된 검색 결과를 받지만, 없어도 추천은 동작한다.
        try:
            return self._auth.get_ytdlp_opts() if self._auth else {}
        except Exception:
            logger.exception("추천 조회용 쿠키 옵션 획득 실패 — 익명 검색으로 진행")
            return {}

    def load(
        self,
        seed_titles: tuple[str, ...],
        seed_channels: tuple[str, ...] = (),
        seed_tags: tuple[str, ...] = (),
        limit: int = 24,
        exclude_urls: frozenset[str] = frozenset(),
        force: bool = False,
    ) -> None:
        """추천을 조회한다.

        ``force``가 False면 씨앗이 직전 조회와 같을 때 재조회하지 않는다 —
        목록 화면을 오갈 때마다 같은 검색을 반복하지 않기 위한 가드다.
        """
        if not seed_titles and not seed_channels and not seed_tags:
            self._items = []
            self._last_key = ""
            self.items_changed.emit([])
            return
        key = repr((seed_titles, seed_channels, seed_tags, limit))
        if not force and key == self._last_key and self._items:
            self.items_changed.emit(self._items)   # 캐시 재표시
            return
        self._last_key = key

        cookie_opts = self._cookie_opts()
        query = GetRecommendationsQuery(
            seed_titles=seed_titles,
            seed_channels=seed_channels,
            seed_tags=seed_tags,
            limit=limit,
            exclude_urls=exclude_urls,
            cookie_opts=cookie_opts,
        )
        self._gen += 1
        gen = self._gen
        # 앞선 조회는 결과를 버린다(세대 비교) — 스레드는 자연 종료되게 둔다.
        self.loading_changed.emit(True)
        worker = _RecommendWorker(
            lambda on_progress=None: self._handler.handle(query, on_progress=on_progress),
            self,
        )
        worker.finished_ok.connect(lambda items, g=gen: self._on_ok(items, g))
        worker.finished_err.connect(lambda msg, g=gen: self._on_err(msg, g))
        worker.partial_ready.connect(lambda batch, g=gen: self._on_partial(batch, g))
        worker.finished.connect(lambda w=worker, g=gen: self._on_worker_done(w, g))
        self._worker = worker
        worker.start()

    def invalidate(self) -> None:
        """씨앗 캐시를 비워 다음 load()가 반드시 재조회하게 한다."""
        self._last_key = ""

    def _on_partial(self, batch: list, gen: int) -> None:
        if gen == self._gen:
            self.partial_ready.emit(batch)

    def _on_ok(self, items: list, gen: int) -> None:
        if gen != self._gen:
            return
        self._items = items
        self.items_changed.emit(items)

    def _on_err(self, msg: str, gen: int) -> None:
        if gen == self._gen:
            # 실패한 조회의 씨앗은 캐시하지 않는다(⟳ 없이도 다음 기회에 재시도).
            self._last_key = ""
            self.error_occurred.emit(msg)

    def _on_worker_done(self, worker: _RecommendWorker, gen: int) -> None:
        if worker is self._worker:
            self._worker = None
        if gen == self._gen:
            self.loading_changed.emit(False)

    def shutdown(self) -> None:
        """종료 시 진행 중인 워커를 정리한다 (MainWindow.closeEvent에서 호출)."""
        worker = self._worker
        self._worker = None
        if worker is not None and worker.isRunning():
            worker.wait(3000)
