from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from domain.download.aggregates import DownloadQueueAggregate
from domain.download.entities import DownloadJob
from domain.download.repositories import IDownloadRepository
from domain.download.value_objects import DownloadSettings
from domain.shared.ports import IEventBus, IMediaSource, MediaSourceFactory


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
        ytdlp: IMediaSource,
        event_bus: IEventBus,
        make_downloader: MediaSourceFactory | None = None,
    ) -> None:
        self._queue = queue
        self._repo = repo
        self._ytdlp = ytdlp
        self._bus = event_bus
        # 다운로드는 작업별 진행률 훅이 필요해 새 인스턴스를 만들어야 한다.
        # composition root가 팩토리를 주입하지 않으면 진행률 없이 주입된 소스를 쓴다.
        self._make_downloader = make_downloader

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

        adapter = (
            self._make_downloader(on_progress)
            if self._make_downloader is not None
            else self._ytdlp
        )
        try:
            file_path = adapter.download(job.url, job.settings, output_dir)
            self._queue.complete(job_id, str(file_path))
            job.file_path = str(file_path)
            # Same url+quality+format: keep only the newest file
            self._repo.delete_completed_duplicates(
                job.url,
                job.settings.quality.value,
                job.settings.format.value,
                job_id,
            )
            self._repo.save(job)
        except Exception as exc:
            self._queue.fail(job_id, str(exc))
            self._repo.save(job)  # job already has FAILED status + error_msg set by fail()
        finally:
            self._bus.publish_all(self._queue.pull_events())


class CancelDownloadHandler:
    def __init__(self, queue: DownloadQueueAggregate, event_bus: IEventBus) -> None:
        self._queue = queue
        self._bus = event_bus

    def handle(self, cmd: CancelDownloadCommand) -> None:
        self._queue.cancel(cmd.job_id)
        self._bus.publish_all(self._queue.pull_events())
