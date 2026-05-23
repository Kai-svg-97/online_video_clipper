from __future__ import annotations

from uuid import UUID

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from application.download.commands import CancelDownloadCommand, CancelDownloadHandler, StartDownloadCommand, StartDownloadHandler
from application.download.queries import GetDownloadHistoryHandler, GetDownloadHistoryQuery, GetDownloadQueueHandler, GetDownloadQueueQuery
from domain.download.entities import DownloadJob
from domain.download.events import DownloadCompleted, DownloadFailed, DownloadProgressUpdated
from domain.download.value_objects import DownloadSettings
from infrastructure.event_bus import EventBus


class _DownloadWorker(QThread):
    """Runs a single download job on a background thread."""

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
        event_bus: EventBus,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._start = start_handler
        self._cancel = cancel_handler
        self._queue_q = queue_handler
        self._history_q = history_handler
        self._bus = event_bus
        self._workers: dict[UUID, _DownloadWorker] = {}

        # Subscribe to domain events for UI refresh
        event_bus.subscribe(DownloadProgressUpdated, self._on_progress)
        event_bus.subscribe(DownloadCompleted, self._on_completed)
        event_bus.subscribe(DownloadFailed, self._on_failed)

    @property
    def queue(self) -> list[DownloadJob]:
        return self._queue_q.handle(GetDownloadQueueQuery())

    def load_history(self, limit: int = 50) -> list[DownloadJob]:
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
        if job_id in self._workers:
            self._workers[job_id].terminate()
        try:
            self._cancel.handle(CancelDownloadCommand(job_id))
            self.queue_changed.emit()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def _on_progress(self, event: DownloadProgressUpdated) -> None:
        self.queue_changed.emit()

    def _on_completed(self, event: DownloadCompleted) -> None:
        self.queue_changed.emit()
        self.history_changed.emit()

    def _on_failed(self, event: DownloadFailed) -> None:
        self.queue_changed.emit()
        self.error_occurred.emit(f"Download failed: {event.error}")

    def _cleanup_worker(self, job_id: UUID) -> None:
        self._workers.pop(job_id, None)
