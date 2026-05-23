from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from domain.download.aggregates import DownloadQueueAggregate
from domain.download.entities import DownloadJob
from domain.download.repositories import IDownloadRepository
from domain.download.value_objects import DownloadSettings
from infrastructure.event_bus import EventBus
from infrastructure.downloader.ytdlp_adapter import YtDlpAdapter


@dataclass
class StartDownloadCommand:
    url: str
    title: str
    settings: DownloadSettings | None = None
    output_dir: Path | None = None


@dataclass
class CancelDownloadCommand:
    job_id: UUID


@dataclass
class RetryDownloadCommand:
    job_id: UUID


# ------------------------------------------------------------------
# Handlers
# ------------------------------------------------------------------

class StartDownloadHandler:
    def __init__(
        self,
        queue: DownloadQueueAggregate,
        repo: IDownloadRepository,
        ytdlp: YtDlpAdapter,
        event_bus: EventBus,
    ) -> None:
        self._queue = queue
        self._repo = repo
        self._ytdlp = ytdlp
        self._bus = event_bus

    def handle(self, cmd: StartDownloadCommand) -> DownloadJob:
        job = DownloadJob.create(
            url=cmd.url,
            title=cmd.title,
            settings=cmd.settings,
        )
        self._queue.enqueue(job)
        self._repo.save(job)
        return job

    def execute_job(self, job_id: UUID, output_dir: Path | None = None) -> None:
        """Run the actual download. Call from a background QThread."""
        self._queue.start(job_id)
        self._bus.publish_all(self._queue.pull_events())

        job = next((j for j in self._queue.running_jobs() if j.id == job_id), None)
        if job is None:
            return

        def on_progress(progress):
            self._queue.update_progress(job_id, progress)
            self._bus.publish_all(self._queue.pull_events())

        adapter = YtDlpAdapter(on_progress=on_progress)
        try:
            file_path = adapter.download(job.url, job.settings, output_dir)
            self._queue.complete(job_id, str(file_path))
            job.file_path = str(file_path)
            self._repo.save(job)
        except Exception as exc:
            self._queue.fail(job_id, str(exc))
            job_for_save = DownloadJob.create(job.url, job.title, job.settings)
            job_for_save.id = job_id
            self._repo.save(job_for_save)
        finally:
            self._bus.publish_all(self._queue.pull_events())


class CancelDownloadHandler:
    def __init__(self, queue: DownloadQueueAggregate, event_bus: EventBus) -> None:
        self._queue = queue
        self._bus = event_bus

    def handle(self, cmd: CancelDownloadCommand) -> None:
        self._queue.cancel(cmd.job_id)
        self._bus.publish_all(self._queue.pull_events())
