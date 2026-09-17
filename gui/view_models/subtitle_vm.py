"""자막 색인 뷰모델 — 색인 수집(네트워크)과 조회(로컬)를 나눠 다룬다.

조회는 SQLite 읽기라 동기로 충분하고, 수집은 영상마다 네트워크 왕복이 있어 반드시
배경 스레드다. 이 둘을 한 화면이 쓰므로 뷰모델 하나로 묶는다.
"""

from __future__ import annotations

import logging
from uuid import UUID

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from application.library.subtitle_commands import (
    FetchAndIndexSubtitlesCommand,
    FetchAndIndexSubtitlesHandler,
    IndexSubtitleCuesCommand,
    IndexSubtitleCuesHandler,
)
from application.library.subtitle_queries import (
    GetSubtitleIndexesHandler,
    GetSubtitleIndexesQuery,
    GetSubtitleLinesHandler,
    GetSubtitleLinesQuery,
)
from gui.view_models.base import WorkerOwnerMixin

logger = logging.getLogger(__name__)


class _IndexWorker(QThread):
    """자막을 받아 색인한다 — 네트워크라 배경에서."""

    done = pyqtSignal(object, int)   # video_id, 색인한 줄 수

    def __init__(
        self,
        handler: FetchAndIndexSubtitlesHandler,
        cmd: FetchAndIndexSubtitlesCommand,
    ) -> None:
        # 부모를 주지 않는다 — 소유 뷰모델이 사라질 때 실행 중 스레드가 파괴되면
        # Qt가 프로세스를 죽인다(gui/workers.py).
        super().__init__(None)
        self._handler = handler
        self._cmd = cmd

    def run(self) -> None:
        # 핸들러가 이미 예외를 삼키고 0을 돌려주지만, 여기서도 한 겹 막는다 —
        # 배경 스레드에서 새어 나간 예외는 프로세스를 죽인다.
        try:
            count = self._handler.handle(self._cmd)
        except Exception:
            logger.exception("자막 색인 실패 (무시): %s", self._cmd.url)
            count = 0
        self.done.emit(self._cmd.video_id, count)


class SubtitleViewModel(WorkerOwnerMixin, QObject):
    lines_loaded = pyqtSignal(object, object)   # video_id, list[SubtitleLineDTO]
    index_started = pyqtSignal(object)          # video_id
    index_finished = pyqtSignal(object, int)    # video_id, 줄 수(0이면 자막 없음)

    def __init__(
        self,
        index_cues_handler: IndexSubtitleCuesHandler,
        fetch_handler: FetchAndIndexSubtitlesHandler,
        get_lines_handler: GetSubtitleLinesHandler,
        get_indexes_handler: GetSubtitleIndexesHandler,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._index_cues = index_cues_handler
        self._fetch = fetch_handler
        self._get_lines = get_lines_handler
        self._get_indexes = get_indexes_handler
        # 같은 영상을 두 번 색인하지 않게 — 자막을 껐다 켜면 큐가 다시 들어온다.
        self._indexing: set[UUID] = set()

    # ── 조회 ──────────────────────────────────────────────────────

    def has_index(self, video_id: UUID) -> bool:
        try:
            return bool(self._get_indexes.handle(GetSubtitleIndexesQuery(video_id)))
        except Exception:
            logger.exception("자막 색인 조회 실패: %s", video_id)
            return False

    def load_lines(self, video_id: UUID, text: str = "") -> None:
        """자막 줄을 읽어 `lines_loaded`로 알린다(검색어를 주면 그 줄만)."""
        try:
            lines = self._get_lines.handle(
                GetSubtitleLinesQuery(video_id=video_id, text=text)
            )
        except Exception:
            logger.exception("자막 줄 조회 실패: %s", video_id)
            lines = []
        self.lines_loaded.emit(video_id, lines)

    # ── 수집 ──────────────────────────────────────────────────────

    def index_cues(self, video_id: UUID, lang: str, label: str, cues) -> None:
        """이미 받아 둔 큐를 색인한다 — **공짜 경로**(네트워크 왕복 없음).

        재생 중 자막을 켜면 큐가 이미 손에 있다. 그걸 흘려보내지 않고 남긴다.
        """
        if not cues:
            return
        try:
            count = self._index_cues.handle(
                IndexSubtitleCuesCommand(
                    video_id=video_id, lang=lang, label=label, cues=cues
                )
            )
        except Exception:
            logger.exception("자막 큐 색인 실패 (무시): %s", video_id)
            return
        if count:
            self.index_finished.emit(video_id, count)

    def fetch_and_index(
        self, video_id: UUID, url: str, preferred_langs: tuple[str, ...] = ("ko", "en")
    ) -> None:
        """자막을 받아 색인한다(배경). 같은 영상이 진행 중이면 무시한다."""
        if not url or video_id in self._indexing:
            return
        self._indexing.add(video_id)
        self.index_started.emit(video_id)
        cmd = FetchAndIndexSubtitlesCommand(
            video_id=video_id, url=url, preferred_langs=preferred_langs
        )
        worker = _IndexWorker(self._fetch, cmd)
        worker.done.connect(self._on_index_done)
        self._start_worker(worker)

    def _on_index_done(self, video_id: object, count: int) -> None:
        self._indexing.discard(video_id)
        self.index_finished.emit(video_id, count)
