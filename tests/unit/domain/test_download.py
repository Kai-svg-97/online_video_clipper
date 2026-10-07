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


class TestQueueEventsThreadSafety:
    """C4 — 이벤트 유실. `pull_events` 의 `list()` 복사와 `clear()` 사이에 끼어든
    `_raise` 는 복사본에 없는데 `clear()` 로 지워져 **영원히 사라진다**.

    시험 1 은 그 틈을 결정적으로 만든다. 시험 2 는 8 스레드 스트레스로 보강한다.
    ("complete/cancel 이 다른 스레드의 update_progress 와 겹치는 경우"는 이번 범위
    밖이다 — 현행 `_get` 의 KeyError 동작을 유지한다.)
    """

    @staticmethod
    def _updated(events, job_id):
        from domain.download.events import DownloadProgressUpdated

        return [
            e for e in events
            if isinstance(e, DownloadProgressUpdated) and e.job_id == job_id
        ]

    def test_복사와_clear_사이에_끼어든_이벤트도_사라지지_않는다(self):
        import threading

        from domain.download.value_objects import DownloadProgress

        agg = DownloadQueueAggregate()
        job_a = DownloadJob.create("https://youtu.be/aaaaaaaaaaa", "A")
        job_b = DownloadJob.create("https://youtu.be/bbbbbbbbbbb", "B")
        agg.enqueue(job_a)
        agg.enqueue(job_b)
        agg.update_progress(job_a.id, DownloadProgress(percent=10.0))

        published = {"b": 0}
        threads: list[threading.Thread] = []
        fired = {"done": False}

        def other_thread():
            agg.update_progress(job_b.id, DownloadProgress(percent=50.0))

        def hook():
            if fired["done"]:          # 재진입 방지 — 한 번만 끼어든다
                return
            fired["done"] = True
            published["b"] += 1        # 이 스레드가 곧 발행하려 한다
            t = threading.Thread(target=other_thread)
            threads.append(t)
            t.start()
            # 잠금으로 고친 구현이면 t 는 잠금에서 막혀 timeout 으로 돌아온다(교착 아님).
            t.join(timeout=0.5)

        class _HookList(list):
            def clear(self):
                hook()
                super().clear()

        agg._events = _HookList(agg._events)

        first = agg.pull_events()
        for t in threads:
            t.join(timeout=5)
        second = agg.pull_events()

        got_b = self._updated(first + second, job_b.id)
        # clear() 를 부르지 않는 구현(교체 방식)이면 hook 이 안 불려 둘 다 0 이다 — 그것도 정상.
        # 어느 구현이든 '발행한 수 == 회수한 수' 여야 한다. 현행은 1 대 0.
        assert len(got_b) == published["b"], (
            f"job_b 이벤트 발행 {published['b']}건, 회수 {len(got_b)}건 — 유실됐다"
        )
        # job_a 의 이벤트는 정확히 한 번 회수됐다(중복·유실 없음).
        assert len(self._updated(first + second, job_a.id)) == 1

    def test_여덟_스레드가_섞어_불러도_이벤트가_하나도_사라지지_않고_중복도_없다(self):
        import sys
        import threading
        import time

        from domain.download.events import DownloadProgressUpdated
        from domain.download.value_objects import DownloadProgress

        threads_n, per_thread = 8, 2000
        agg = DownloadQueueAggregate()
        jobs = [
            DownloadJob.create(f"https://youtu.be/{i:011d}", f"J{i}")
            for i in range(threads_n)
        ]
        for j in jobs:
            agg.enqueue(j)

        collected: list[list] = [[] for _ in range(threads_n)]
        errors: list[BaseException] = []
        barrier = threading.Barrier(threads_n)

        def worker(idx: int):
            try:
                barrier.wait(timeout=5)
                for i in range(per_thread):
                    agg.update_progress(jobs[idx].id, DownloadProgress(percent=i * 0.05))
                    collected[idx].extend(agg.pull_events())
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        old = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)
        started = time.monotonic()
        try:
            ts = [threading.Thread(target=worker, args=(i,)) for i in range(threads_n)]
            for t in ts:
                t.start()
            for t in ts:
                t.join(timeout=30)
        finally:
            sys.setswitchinterval(old)

        assert not errors, errors
        assert not any(t.is_alive() for t in ts)
        assert time.monotonic() - started < 10     # 교착·과도한 직렬화 방지(여유 있게)

        tail = agg.pull_events()
        updates = [
            e for e in [*(e for c in collected for e in c), *tail]
            if isinstance(e, DownloadProgressUpdated)
        ]
        keys = [(e.job_id, e.percent) for e in updates]
        assert len(keys) == threads_n * per_thread, (
            f"회수 {len(keys)}건 / 발행 {threads_n * per_thread}건 — 유실 또는 중복"
        )
        assert len(set(keys)) == len(keys), "같은 이벤트가 두 번 회수됐다"

