from __future__ import annotations

import threading
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
        # 다운로드 워커 스레드 여럿이 같은 큐에서 `_raise`/`pull_events`를 부른다.
        # 예전의 `list(...)` 복사 + `clear()`는 그 사이에 끼어든 이벤트를 복사본에도
        # 없이 지워 **영원히 유실**시켰고, 두 스레드가 같은 이벤트를 둘 다 가져가기도
        # 했다. 표준 라이브러리 잠금 하나로 '넣기'와 '비우며 가져가기'를 직렬화한다 —
        # 외부 의존이 없어 도메인 순수성은 유지된다(잠금 구간은 리스트 연산뿐이다).
        self._events_lock = threading.Lock()

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
        with self._events_lock:
            self._events.append(event)

    def pull_events(self) -> list:
        # 비우지 않고 **통째로 교체**한다 — 가져간 목록과 남는 목록이 겹치지 않는다.
        with self._events_lock:
            events, self._events = self._events, []
        return events
