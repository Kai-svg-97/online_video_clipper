from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from domain.download.entities import DownloadJob, JobStatus
from domain.download.events import (
    DownloadCancelled,
    DownloadCompleted,
    DownloadFailed,
    DownloadProgressUpdated,
    DownloadStarted,
)
from domain.download.value_objects import DownloadProgress


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DownloadQueueAggregate:
    """Manages the in-memory download queue.

    Completed jobs are removed immediately to avoid unbounded memory growth.
    """

    def __init__(self) -> None:
        self._jobs: dict[UUID, DownloadJob] = {}
        self._events: list = []

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def enqueue(self, job: DownloadJob) -> None:
        self._jobs[job.id] = job

    def start(self, job_id: UUID) -> None:
        job = self._get(job_id)
        job.status = JobStatus.RUNNING
        job.updated_at = _now()
        self._raise(DownloadStarted(job_id=job_id, url=job.url))

    def update_progress(self, job_id: UUID, progress: DownloadProgress) -> None:
        job = self._get(job_id)
        job.progress = progress
        job.updated_at = _now()
        self._raise(
            DownloadProgressUpdated(
                job_id=job_id,
                percent=progress.percent,
                speed_bps=progress.speed_bps,
                eta_sec=progress.eta_sec,
            )
        )

    def complete(self, job_id: UUID, file_path: str) -> None:
        job = self._get(job_id)
        url = job.url
        job.status = JobStatus.COMPLETED
        job.file_path = file_path
        job.updated_at = _now()
        self._raise(DownloadCompleted(job_id=job_id, url=url, file_path=file_path))
        # Remove from queue immediately — reduces in-memory footprint
        del self._jobs[job_id]

    def fail(self, job_id: UUID, error: str) -> None:
        job = self._get(job_id)
        job.status = JobStatus.FAILED
        job.error_msg = error
        job.retry_count += 1
        job.updated_at = _now()
        self._raise(DownloadFailed(job_id=job_id, url=job.url, error=error))

    def cancel(self, job_id: UUID) -> None:
        job = self._get(job_id)
        job.status = JobStatus.CANCELLED
        job.updated_at = _now()
        self._raise(DownloadCancelled(job_id=job_id))
        del self._jobs[job_id]

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def pending_jobs(self) -> list[DownloadJob]:
        return [j for j in self._jobs.values() if j.status == JobStatus.PENDING]

    def running_jobs(self) -> list[DownloadJob]:
        return [j for j in self._jobs.values() if j.status == JobStatus.RUNNING]

    def all_jobs(self) -> list[DownloadJob]:
        return list(self._jobs.values())

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get(self, job_id: UUID) -> DownloadJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(f"DownloadJob {job_id} not found in queue")
        return job

    def _raise(self, event: object) -> None:
        self._events.append(event)

    def pull_events(self) -> list:
        events = list(self._events)
        self._events.clear()
        return events
