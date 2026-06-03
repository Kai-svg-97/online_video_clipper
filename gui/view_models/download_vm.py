from __future__ import annotations

from uuid import UUID

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from application.download.commands import CancelDownloadCommand, CancelDownloadHandler, StartDownloadCommand, StartDownloadHandler
from application.download.dtos import DownloadJobDTO
from domain.download.value_objects import DownloadSettings
from application.download.event_bridge import DownloadEventBridge
from application.download.queries import GetDownloadHistoryHandler, GetDownloadHistoryQuery, GetDownloadQueueHandler, GetDownloadQueueQuery


class _DownloadWorker(QThread):
    def __init__(
        self,
        handler: StartDownloadHandler,
        job_id: UUID,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._handler = handler
        self._job_id = job_id

    def run(self) -> None:
        self._handler.execute_job(self._job_id)


class DownloadViewModel(QObject):
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
        try:
            job = self._start.handle(StartDownloadCommand(url=url, title=title, settings=settings))
            worker = _DownloadWorker(self._start, job.id, self)
            worker.finished.connect(lambda: self._cleanup_worker(job.id))
            self._workers[job.id] = worker
            worker.start()
            self.queue_changed.emit()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def cancel_download(self, job_id: UUID) -> None:
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

    def shutdown(self) -> None:
        """앱 종료 시 호출 — 실행 중인 다운로드 워커를 정리한다.

        진행 중인 다운로드는 협조적 취소가 없어 terminate로 중단하고
        wait()로 스레드 종료를 보장한다. 죽은 객체로 시그널이 가는 것을 막는다.
        """
        for worker in list(self._workers.values()):
            if worker.isRunning():
                worker.terminate()
                worker.wait(3000)
        self._workers.clear()
