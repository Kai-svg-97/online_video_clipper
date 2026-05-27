import pytest
from domain.download.aggregates import DownloadQueueAggregate
from domain.download.entities import DownloadJob, JobStatus
from domain.download.events import DownloadCancelled, DownloadCompleted, DownloadStarted
from domain.download.value_objects import DownloadSettings, Quality, MediaFormat


class TestDownloadSettings:
    def test_defaults(self):
        s = DownloadSettings()
        assert s.quality == Quality.P1080
        assert s.format == MediaFormat.MP4

    def test_equality(self):
        a = DownloadSettings(quality=Quality.P720)
        b = DownloadSettings(quality=Quality.P720)
        assert a == b


class TestDownloadQueueAggregate:
    def _job(self, url="https://youtu.be/abc"):
        return DownloadJob.create(url, "Test Video")

    def test_enqueue_and_start(self):
        q = DownloadQueueAggregate()
        job = self._job()
        q.enqueue(job)
        q.start(job.id)
        events = q.pull_events()
        assert any(isinstance(e, DownloadStarted) for e in events)
        assert job.status == JobStatus.RUNNING

    def test_complete_removes_from_queue(self):
        q = DownloadQueueAggregate()
        job = self._job()
        q.enqueue(job)
        q.start(job.id)
        q.pull_events()
        q.complete(job.id, "/path/to/file.mp4")
        assert len(q.all_jobs()) == 0
        events = q.pull_events()
        assert any(isinstance(e, DownloadCompleted) for e in events)

    def test_fail_increments_retry(self):
        q = DownloadQueueAggregate()
        job = self._job()
        q.enqueue(job)
        q.start(job.id)
        q.pull_events()
        q.fail(job.id, "network error")
        assert job.retry_count == 1
        assert job.status == JobStatus.FAILED

    def test_cancel_removes_from_queue(self):
        q = DownloadQueueAggregate()
        job = self._job()
        q.enqueue(job)
        q.cancel(job.id)
        assert len(q.all_jobs()) == 0
        events = q.pull_events()
        assert any(isinstance(e, DownloadCancelled) for e in events)

    def test_start_unknown_job_raises(self):
        from uuid import uuid4
        q = DownloadQueueAggregate()
        with pytest.raises(KeyError):
            q.start(uuid4())
