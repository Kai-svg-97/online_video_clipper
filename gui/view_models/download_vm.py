from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from gui.view_models.base import WorkerOwnerMixin

from application.download.commands import CancelDownloadCommand, CancelDownloadHandler, StartDownloadCommand, StartDownloadHandler
from application.download.dtos import DownloadJobDTO
from domain.download.schedule import DownloadWindow, clamp_concurrent, slots_available
from domain.download.value_objects import DownloadSettings
from application.download.event_bridge import DownloadEventBridge
from application.download.queries import GetDownloadHistoryHandler, GetDownloadHistoryQuery, GetDownloadQueueHandler, GetDownloadQueueQuery

logger = logging.getLogger(__name__)

# 예약 시간대가 열렸는지 확인하는 주기. 창 경계는 '시' 단위라 1분이면 충분하고,
# 더 촘촘히 깨우면 유휴 상태에서 쓸데없이 돈다.
_WINDOW_POLL_MS = 60_000


class _DownloadWorker(QThread):
    def __init__(
        self,
        handler: StartDownloadHandler,
        job_id: UUID,
    ) -> None:
        # 부모를 주지 않는다 — 붙드는 일은 track_thread가 한다(gui/workers.py).
        super().__init__(None)
        self._handler = handler
        self._job_id = job_id

    def run(self) -> None:
        self._handler.execute_job(self._job_id)


class DownloadViewModel(WorkerOwnerMixin, QObject):
    queue_changed = pyqtSignal()
    history_changed = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        start_handler: StartDownloadHandler,
        cancel_handler: CancelDownloadHandler,
        queue_handler: GetDownloadQueueHandler,
        history_handler: GetDownloadHistoryHandler,
        event_bridge: DownloadEventBridge,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._start = start_handler
        self._cancel = cancel_handler
        self._queue_q = queue_handler
        self._history_q = history_handler
        self._workers: dict[UUID, _DownloadWorker] = {}
        # 아직 시작하지 않은 작업(FIFO). 동시 실행 수와 예약 시간대 **둘 다** 여기서
        # 지킨다 — 예전에는 요청이 올 때마다 워커를 바로 띄워, 설정 화면의
        # "동시 다운로드 수"가 화면에만 있고 아무 효과가 없었다.
        self._pending: list[UUID] = []
        # 예약 시간대가 열리기를 기다리는 타이머. 대기 중일 때만 돈다.
        self._window_timer = QTimer(self)
        self._window_timer.setInterval(_WINDOW_POLL_MS)
        self._window_timer.timeout.connect(self._pump)

        event_bridge.add_progress_listener(self._on_progress)
        event_bridge.add_completed_listener(self._on_completed)
        event_bridge.add_failed_listener(self._on_failed)

    @property
    def queue(self) -> list[DownloadJobDTO]:
        return self._queue_q.handle(GetDownloadQueueQuery())

    def load_history(self, limit: int = 50) -> list[DownloadJobDTO]:
        return self._history_q.handle(GetDownloadHistoryQuery(limit=limit))

    def start_download(
        self, url: str, title: str, settings: DownloadSettings | None = None
    ) -> None:
        """작업을 큐에 넣는다. 실제 시작은 자리와 시간대가 허락할 때다."""
        try:
            job = self._start.handle(StartDownloadCommand(url=url, title=title, settings=settings))
        except Exception as exc:
            self.error_occurred.emit(str(exc))
            return
        self._pending.append(job.id)
        self.queue_changed.emit()
        self._pump()

    # ── 큐 게이트 ─────────────────────────────────────────────────

    @staticmethod
    def current_window() -> DownloadWindow:
        """지금 설정된 예약 시간대(런타임 값이라 매번 읽는다)."""
        from config import settings as cfg  # noqa: PLC0415

        return DownloadWindow(
            enabled=bool(cfg.DOWNLOAD_WINDOW_ENABLED),
            start_hour=int(cfg.DOWNLOAD_WINDOW_START),
            end_hour=int(cfg.DOWNLOAD_WINDOW_END),
        )

    @staticmethod
    def _concurrent_limit() -> int:
        from config import settings as cfg  # noqa: PLC0415

        return clamp_concurrent(cfg.MAX_CONCURRENT_DOWNLOADS)

    @property
    def waiting_count(self) -> int:
        """아직 시작하지 않고 기다리는 작업 수 — 화면 표시용."""
        return len(self._pending)

    def _pump(self) -> None:
        """자리와 시간대가 허락하는 만큼 대기 작업을 시작한다.

        시간대가 닫혀 있으면 아무것도 시작하지 않고 타이머를 켜 둔다 — 창이 열리는
        순간을 놓치지 않기 위해서다. 대기가 없으면 타이머를 멈춘다(유휴 시 낭비 방지).
        """
        if not self._pending:
            self._window_timer.stop()
            return
        if not self.current_window().allows(datetime.now().time()):
            if not self._window_timer.isActive():
                self._window_timer.start()
            return
        self._window_timer.stop()

        for _ in range(slots_available(len(self._workers), self._concurrent_limit())):
            if not self._pending:
                break
            self._launch(self._pending.pop(0))

    def _launch(self, job_id: UUID) -> None:
        worker = _DownloadWorker(self._start, job_id)
        # 바운드 메서드가 아니라 람다인 이유는 job_id를 실어야 하기 때문이다.
        # 신호원(worker)이 수신자(self)보다 먼저 죽으므로 죽은 객체 접근 위험은 없다.
        worker.finished.connect(lambda jid=job_id: self._cleanup_worker(jid))
        self._workers[job_id] = worker
        self._start_worker(worker)
        self.queue_changed.emit()

    def cancel_download(self, job_id: UUID) -> None:
        # 아직 시작하지 않았다면 대기줄에서 빼는 것으로 끝난다(죽일 워커가 없다).
        if job_id in self._pending:
            self._pending.remove(job_id)
        worker = self._workers.get(job_id)
        if worker is not None:
            # yt-dlp 다운로드에 협조적 취소 훅이 없어 terminate가 불가피하다.
            # terminate 후 반드시 wait()로 스레드 종료를 보장해, 죽은 객체로의
            # 시그널 방출이나 리소스 정리 누락을 막는다.
            worker.terminate()
            worker.wait(3000)
        try:
            self._cancel.handle(CancelDownloadCommand(job_id))
            self.queue_changed.emit()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def _on_progress(self) -> None:
        self.queue_changed.emit()

    def _on_completed(self) -> None:
        self.queue_changed.emit()
        self.history_changed.emit()

    def _on_failed(self, error: str) -> None:
        self.queue_changed.emit()
        self.error_occurred.emit(f"Download failed: {error}")

    def _cleanup_worker(self, job_id: UUID) -> None:
        self._workers.pop(job_id, None)
        # 한 자리가 비었으니 다음 대기 작업을 올린다.
        self._pump()

    def shutdown(self) -> None:
        """앱 종료 시 호출 — 실행 중인 다운로드 워커를 정리한다.

        진행 중인 다운로드는 협조적 취소가 없어 terminate로 중단하고
        wait()로 스레드 종료를 보장한다. 죽은 객체로 시그널이 가는 것을 막는다.
        """
        self._window_timer.stop()
        self._pending.clear()
        for worker in list(self._workers.values()):
            if worker.isRunning():
                worker.terminate()
                worker.wait(3000)
        self._workers.clear()
        super().shutdown()   # 공용 추적 목록 정리
