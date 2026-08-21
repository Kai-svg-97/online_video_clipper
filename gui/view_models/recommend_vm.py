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

# 미리 받기 한 묶음 크기와 검색 깊이의 기본값. 페이지마다 검색을 깊게 파고
# (per_query = _BASE_PER_QUERY × (page+1)) 이미 본 URL을 걸러 새 것만 남긴다.
_MORE_LIMIT = 12
_BASE_PER_QUERY = 12


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
    # ── 미리 받기(무한 스크롤) ──
    more_ready           = pyqtSignal(list)   # list[FeedVideoDTO] — 뒤에 덧붙일 묶음
    more_loading_changed = pyqtSignal(bool)
    more_exhausted       = pyqtSignal()       # 더 나오지 않음(요청 중단 신호)

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
        # 미리 받기 상태 — 같은 씨앗으로 '더 깊이' 검색해 뒤에 덧붙인다.
        self._more_worker: _RecommendWorker | None = None
        self._seeds: tuple = ((), (), ())
        self._search_text: str = ""   # 검색창 낱말(있으면 씨앗 대신 이것으로 검색)
        self._page: int = 0
        self._more_exhausted: bool = False

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
        search_text: str = "",
    ) -> None:
        """추천을 조회한다.

        ``force``가 False면 씨앗이 직전 조회와 같을 때 재조회하지 않는다 —
        목록 화면을 오갈 때마다 같은 검색을 반복하지 않기 위한 가드다.

        ``search_text``가 있으면 씨앗 대신 그 낱말로 YouTube를 검색한다. 이때는
        **씨앗이 비어 있어도 조회한다** — 검색 결과가 0건이라 목록이 텅 비었을 때가
        오히려 "YouTube에는 뭐가 있나"를 가장 보고 싶은 순간이다.
        """
        search_text = (search_text or "").strip()
        if not search_text and not seed_titles and not seed_channels and not seed_tags:
            self._items = []
            self._last_key = ""
            self.items_changed.emit([])
            return
        key = repr((search_text, seed_titles, seed_channels, seed_tags, limit))
        if not force and key == self._last_key and self._items:
            self.items_changed.emit(self._items)   # 캐시 재표시
            return
        self._last_key = key
        # 새 씨앗이면 미리 받기도 처음부터 — 이전 목록의 페이지 깊이를 물려받으면
        # 첫 '더 받기'가 엉뚱하게 깊은 결과부터 가져온다.
        self._seeds = (seed_titles, seed_channels, seed_tags)
        self._search_text = search_text
        self._page = 0
        self._more_exhausted = False

        cookie_opts = self._cookie_opts()
        query = GetRecommendationsQuery(
            seed_titles=seed_titles,
            seed_channels=seed_channels,
            seed_tags=seed_tags,
            search_text=search_text,
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

    def load_more(self, exclude_urls: frozenset[str] = frozenset()) -> None:
        """지금 목록 뒤에 덧붙일 추가분을 백그라운드로 받는다.

        **씨앗을 새로 뽑지 않는다.** `derive_seed_queries`는 목록당 최대 3개(제목
        키워드·최다 태그·최다 채널)뿐이라 더 뽑을 검색어가 없다. 대신 같은 검색어로
        **더 깊이**(`per_query`를 페이지마다 늘려) 검색하고, 이미 보여 준 URL을
        `exclude_urls`로 걸러 새로 나온 것만 남긴다.

        결과가 하나도 없으면 그 씨앗은 바닥난 것으로 보고 더 요청하지 않는다
        (스크롤할 때마다 같은 검색을 반복하면 조용히 네트워크만 축낸다).
        """
        if self._more_exhausted or self._more_worker is not None:
            return
        seed_titles, seed_channels, seed_tags = self._seeds
        if not self._search_text and not seed_titles and not seed_channels and not seed_tags:
            return
        self._page += 1
        query = GetRecommendationsQuery(
            seed_titles=seed_titles,
            seed_channels=seed_channels,
            seed_tags=seed_tags,
            search_text=self._search_text,
            limit=_MORE_LIMIT,
            per_query=_BASE_PER_QUERY * (self._page + 1),
            exclude_urls=exclude_urls,
            cookie_opts=self._cookie_opts(),
        )
        gen = self._gen
        self.more_loading_changed.emit(True)
        worker = _RecommendWorker(
            lambda on_progress=None: self._handler.handle(query), self
        )
        worker.finished_ok.connect(lambda items, g=gen: self._on_more_ok(items, g))
        worker.finished_err.connect(lambda msg, g=gen: self._on_more_err(msg, g))
        worker.finished.connect(lambda w=worker: self._on_more_done(w))
        self._more_worker = worker
        worker.start()

    def _on_more_ok(self, items: list, gen: int) -> None:
        # 결과가 도착한 시점에 자리를 비운다 — 스레드가 완전히 끝나기(finished)를
        # 기다리면 그 사이 들어온 다음 요청이 '조회 중'으로 오인돼 조용히 버려진다.
        self._more_worker = None
        if gen != self._gen:
            return   # 그 사이 씨앗이 바뀌었다 — 늦게 온 추가분은 버린다
        if not items:
            self._more_exhausted = True
            self.more_exhausted.emit()
            return
        self._items = [*self._items, *items]
        self.more_ready.emit(items)

    def _on_more_err(self, msg: str, gen: int) -> None:
        # 추가분 실패는 화면을 어지럽히지 않는다 — 이미 보고 있는 목록은 멀쩡하다.
        self._more_worker = None
        logger.warning("추천 추가분 조회 실패: %s", msg)
        if gen == self._gen:
            self._more_exhausted = True
            self.more_exhausted.emit()

    def _on_more_done(self, worker: _RecommendWorker) -> None:
        if worker is self._more_worker:
            self._more_worker = None
        if self._more_worker is None:
            # 이미 다음 요청이 시작됐다면 '조회 중'을 유지한다 — 여기서 False를 쏘면
            # 진행 중인데도 스트립이 다시 요청을 받아 중복 조회가 된다.
            self.more_loading_changed.emit(False)

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
        for attr in ("_worker", "_more_worker"):
            worker = getattr(self, attr)
            setattr(self, attr, None)
            if worker is not None and worker.isRunning():
                worker.wait(3000)
