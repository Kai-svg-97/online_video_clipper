"""자막 색인 뷰모델 — 색인 수집(네트워크)과 조회(로컬)를 나눠 다룬다.

조회는 SQLite 읽기라 동기로 충분하고, 수집은 영상마다 네트워크 왕복이 있어 반드시
배경 스레드다. 이 둘을 한 화면이 쓰므로 뷰모델 하나로 묶는다.
"""

from __future__ import annotations

import logging
from uuid import UUID

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from application.library.subtitle_commands import (
    BulkIndexSubtitlesHandler,
    TranscribeVideoCommand,
    TranscribeVideoHandler,
    FetchAndIndexSubtitlesCommand,
    FetchAndIndexSubtitlesHandler,
    IndexSubtitleCuesCommand,
    IndexSubtitleCuesHandler,
)
from application.library.subtitle_queries import (
    GetSubtitleCoverageHandler,
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


class _BulkIndexWorker(QThread):
    """라이브러리 전체 자막 색인 — 영상당 1초 안팎이라 수백 건이면 10분을 넘긴다."""

    progress = pyqtSignal(int, int, str)   # 현재, 전체, 제목
    done = pyqtSignal(object)              # BulkIndexResult

    def __init__(self, handler: BulkIndexSubtitlesHandler) -> None:
        # 부모를 주지 않는다 — 소유 뷰모델이 사라질 때 실행 중 스레드가 파괴되면
        # Qt가 프로세스를 죽인다(gui/workers.py).
        super().__init__(None)
        self._handler = handler
        self._stop = False

    def stop(self) -> None:
        """협조적 중단 — 다음 영상으로 넘어가기 전에 멈춘다."""
        self._stop = True

    def run(self) -> None:
        try:
            result = self._handler.handle(
                on_progress=self.progress.emit, should_stop=lambda: self._stop
            )
        except Exception:
            logger.exception("자막 일괄 색인 실패")
            result = None
        self.done.emit(result)


class _TranscribeWorker(QThread):
    """음성 인식 — 영상 길이의 6~35%가 걸린다(모델에 따라). 반드시 배경."""

    progress = pyqtSignal(float)          # 0.0 ~ 1.0
    done = pyqtSignal(object, int)        # video_id, 색인한 줄 수
    model_downloading = pyqtSignal(str)   # 모델 키 — 처음 한 번 받는 중

    def __init__(self, handler, cmd, transcriber, model_key: str) -> None:
        # 부모를 주지 않는다 — gui/workers.py 의 규칙과 같다.
        super().__init__(None)
        self._handler = handler
        self._cmd = cmd
        self._transcriber = transcriber
        self._model_key = model_key
        self._stop = False

    def stop(self) -> None:
        """협조적 중단 — 다음 세그먼트로 넘어가기 전에 멈춘다."""
        self._stop = True

    def run(self) -> None:
        # 모델이 없으면 먼저 받는다. 수십~수백 MB라 시간이 걸리므로 화면에 알린다.
        try:
            if self._transcriber is not None and not self._transcriber.is_model_ready(
                self._model_key
            ):
                self.model_downloading.emit(self._model_key)
                self._transcriber.download_model(self._model_key)
        except Exception:
            logger.exception("전사 모델 준비 실패: %s", self._model_key)

        count = self._handler.handle(
            self._cmd,
            on_progress=self.progress.emit,
            should_stop=lambda: self._stop,
        )
        self.done.emit(self._cmd.video_id, count)


class SubtitleViewModel(WorkerOwnerMixin, QObject):
    lines_loaded = pyqtSignal(object, object)   # video_id, list[SubtitleLineDTO]
    index_started = pyqtSignal(object)          # video_id
    index_finished = pyqtSignal(object, int)    # video_id, 줄 수(0이면 자막 없음)
    bulk_progress = pyqtSignal(int, int, str)
    bulk_finished = pyqtSignal(object)          # BulkIndexResult (실패 시 None)
    transcribe_started = pyqtSignal(object)     # video_id
    transcribe_model_downloading = pyqtSignal(str)
    transcribe_progress = pyqtSignal(object, float)   # video_id, 0.0~1.0
    transcribe_finished = pyqtSignal(object, int)     # video_id, 줄 수

    def __init__(
        self,
        index_cues_handler: IndexSubtitleCuesHandler,
        fetch_handler: FetchAndIndexSubtitlesHandler,
        get_lines_handler: GetSubtitleLinesHandler,
        get_indexes_handler: GetSubtitleIndexesHandler,
        bulk_handler: BulkIndexSubtitlesHandler | None = None,
        coverage_handler: GetSubtitleCoverageHandler | None = None,
        transcribe_handler: TranscribeVideoHandler | None = None,
        transcriber=None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._index_cues = index_cues_handler
        self._fetch = fetch_handler
        self._get_lines = get_lines_handler
        self._get_indexes = get_indexes_handler
        self._bulk = bulk_handler
        self._coverage = coverage_handler
        self._bulk_worker: _BulkIndexWorker | None = None
        self._transcribe = transcribe_handler
        self._transcriber = transcriber
        self._transcribe_workers: dict = {}
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

    def coverage(self):
        """라이브러리 자막 색인 현황(없으면 None)."""
        if self._coverage is None:
            return None
        try:
            return self._coverage.handle()
        except Exception:
            logger.exception("자막 색인 현황 조회 실패")
            return None

    # ── 일괄 색인 ─────────────────────────────────────────────────

    @property
    def is_bulk_running(self) -> bool:
        return self._bulk_worker is not None

    def start_bulk_index(self) -> bool:
        """라이브러리 전체 색인을 시작한다. 이미 돌고 있으면 False."""
        if self._bulk is None or self._bulk_worker is not None:
            return False
        worker = _BulkIndexWorker(self._bulk)
        worker.progress.connect(self.bulk_progress)
        worker.done.connect(self._on_bulk_done)
        self._bulk_worker = worker
        self._start_worker(worker)
        return True

    def stop_bulk_index(self) -> None:
        if self._bulk_worker is not None:
            self._bulk_worker.stop()

    def _on_bulk_done(self, result: object) -> None:
        self._bulk_worker = None
        self.bulk_finished.emit(result)

    def shutdown(self) -> None:
        """종료 시 긴 작업을 먼저 멈춘다 — 협조적 중단이라 곧 끝난다."""
        self.stop_bulk_index()
        for worker in list(self._transcribe_workers.values()):
            worker.stop()
        self._transcribe_workers.clear()
        super().shutdown()

    # ── 음성 인식 ─────────────────────────────────────────────────

    @property
    def can_transcribe(self) -> bool:
        return self._transcribe is not None

    def transcribe(self, video_id: UUID, media_path: str, language: str = "") -> bool:
        """음성 인식으로 자막을 만든다(배경). 이미 이 영상을 돌고 있으면 False."""
        if self._transcribe is None or not media_path:
            return False
        if video_id in self._transcribe_workers:
            return False
        model_key = self.transcribe_model_key
        cmd = TranscribeVideoCommand(
            video_id=video_id, media_path=media_path,
            model_key=model_key, language=language,
        )
        worker = _TranscribeWorker(self._transcribe, cmd, self._transcriber, model_key)
        worker.model_downloading.connect(self.transcribe_model_downloading)
        worker.progress.connect(self._on_transcribe_progress)
        worker.done.connect(self._on_transcribe_done)
        self._transcribe_workers[video_id] = worker
        self.transcribe_started.emit(video_id)
        self._start_worker(worker)
        return True

    def stop_transcribe(self, video_id: UUID) -> None:
        worker = self._transcribe_workers.get(video_id)
        if worker is not None:
            worker.stop()

    # ── 전사 모델 관리(설정 화면) ─────────────────────────────────
    #
    # 모델 파일을 다루는 일은 전부 어댑터에 맡기고 여기서는 **예외를 흡수**한다 —
    # 설정 화면은 모델이 없어도 열려야 하고, 디스크 오류로 화면이 죽으면 안 된다.

    @property
    def transcribe_model_key(self) -> str:
        from config import settings as cfg  # noqa: PLC0415 (런타임 설정)

        return cfg.TRANSCRIBE_MODEL

    def set_transcribe_model(self, model_key: str) -> None:
        from config import settings as cfg  # noqa: PLC0415

        cfg.save_setting("transcribe_model", model_key)

    def installed_models(self) -> set[str]:
        """받아 둔 모델 키. 어댑터가 없으면 빈 집합."""
        if self._transcriber is None:
            return set()
        try:
            return set(self._transcriber.installed_models())
        except Exception:
            logger.exception("받아 둔 전사 모델 조회 실패")
            return set()

    def model_disk_mb(self, model_key: str) -> int:
        if self._transcriber is None:
            return 0
        try:
            return int(self._transcriber.model_disk_mb(model_key))
        except Exception:
            logger.exception("전사 모델 용량 조회 실패: %s", model_key)
            return 0

    def delete_model(self, model_key: str) -> bool:
        if self._transcriber is None:
            return False
        try:
            return bool(self._transcriber.delete_model(model_key))
        except Exception:
            logger.exception("전사 모델 삭제 실패: %s", model_key)
            return False

    def _on_transcribe_progress(self, ratio: float) -> None:
        # 어느 영상의 진행인지는 워커가 알지만 신호는 비율만 준다 — 한 번에 하나가
        # 보통이라, 지금 돌고 있는 것 중 하나를 골라 실어 보낸다.
        for video_id in list(self._transcribe_workers):
            self.transcribe_progress.emit(video_id, ratio)
            break

    def _on_transcribe_done(self, video_id: object, count: int) -> None:
        self._transcribe_workers.pop(video_id, None)
        self.transcribe_finished.emit(video_id, count)

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
