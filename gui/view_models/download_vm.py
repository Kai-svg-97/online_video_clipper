from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from gui.view_models.base import WorkerOwnerMixin

from application.download.commands import CancelDownloadCommand, CancelDownloadHandler, StartDownloadCommand, StartDownloadHandler
from application.download.dtos import DownloadJobDTO
from domain.download.live import MAX_CONCURRENT_RECORDINGS, is_recordable
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


class _LiveProbeWorker(QThread):
    """이 주소가 지금 방송 중인지 확인한다(메타데이터 1회 조회)."""

    done = pyqtSignal(object, str)   # job_id, 라이브 상태

    def __init__(self, probe, job_id: UUID, url: str) -> None:
        # 부모를 주지 않는다 — gui/workers.py 의 규칙과 같다.
        super().__init__(None)
        self._probe = probe
        self._job_id = job_id
        self._url = url

    def run(self) -> None:
        from domain.download.live import NOT_LIVE  # noqa: PLC0415

        try:
            status = self._probe(self._url)
        except Exception:
            logger.exception("라이브 상태 조회 실패 (무시): %s", self._url)
            status = NOT_LIVE
        self.done.emit(self._job_id, status)


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
        live_status_fn=None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._start = start_handler
        self._cancel = cancel_handler
        self._queue_q = queue_handler
        self._history_q = history_handler
        # 주소 → 라이브 상태. 없으면 라이브 판정을 하지 않는다(기능만 비활성).
        self._live_status_fn = live_status_fn
        # 이미 라이브인지 확인한 작업 — 두 번 묻지 않는다.
        self._probed: set[UUID] = set()
        self._workers: dict[UUID, _DownloadWorker] = {}
        # 아직 시작하지 않은 작업(FIFO). 동시 실행 수와 예약 시간대 **둘 다** 여기서
        # 지킨다 — 예전에는 요청이 올 때마다 워커를 바로 띄워, 설정 화면의
        # "동시 다운로드 수"가 화면에만 있고 아무 효과가 없었다.
        self._pending: list[UUID] = []
        # 녹화 중인 작업 id — 예약·동시한도 게이트를 **우회한** 것들이라
        # 일반 대기줄과 따로 센다.
        self._recordings: set[UUID] = set()
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
        # **대기하게 된 작업만** 라이브인지 확인한다. 곧바로 시작했다면 라이브든
        # 아니든 이미 받고 있으므로 물어볼 이유가 없다 — 모든 다운로드에 메타데이터
        # 조회를 끼워 넣으면 흔한 경우가 1초씩 느려진다.
        if job.id in self._pending:
            self._probe_live(job.id, url)

    def start_live_recording(
        self, url: str, title: str, settings: DownloadSettings | None = None
    ) -> bool:
        """라이브 방송 녹화를 **즉시** 시작한다(예약 시간대·동시 다운로드 한도 우회).

        방송은 지금 아니면 받을 수 없다 — 게이트에 걸려 대기하면 그동안 방송이 끝난다.
        대신 녹화 자체의 상한(`MAX_CONCURRENT_RECORDINGS`)을 지킨다: 녹화는 몇 시간씩
        이어져 쌓아 두면 디스크가 먼저 찬다.

        상한에 걸리면 False 를 돌려준다(호출부가 사용자에게 알린다).
        """
        if len(self._recordings) >= MAX_CONCURRENT_RECORDINGS:
            return False
        try:
            job = self._start.handle(
                StartDownloadCommand(url=url, title=title, settings=settings)
            )
        except Exception as exc:
            self.error_occurred.emit(str(exc))
            return False
        self._recordings.add(job.id)
        self._launch(job.id)
        return True

    def _probe_live(self, job_id: UUID, url: str) -> None:
        if self._live_status_fn is None or job_id in self._probed:
            return
        self._probed.add(job_id)
        worker = _LiveProbeWorker(self._live_status_fn, job_id, url)
        worker.done.connect(self._on_live_probed)
        self._start_worker(worker)

    def _on_live_probed(self, job_id: object, status: str) -> None:
        """방송 중이면 대기줄에서 빼내 즉시 녹화로 돌린다.

        그 사이 시작됐거나 취소됐을 수 있으므로 **아직 대기 중인지 다시 본다**.
        """
        if job_id not in self._pending or not is_recordable(status):
            return
        if len(self._recordings) >= MAX_CONCURRENT_RECORDINGS:
            self.error_occurred.emit(
                "방송 중이지만 동시 녹화 수가 꽉 차 대기합니다."
            )
            return
        self._pending.remove(job_id)
        self._recordings.add(job_id)
        self._launch(job_id)

    @property
    def recording_count(self) -> int:
        return len(self._recordings)

    def is_recording(self, job_id: UUID) -> bool:
        """이 작업이 녹화인가 — 화면이 진행률 대신 경과·용량을 보여줄지 판단한다."""
        return job_id in self._recordings

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

        # 녹화는 게이트를 우회해 시작했으므로 **한도 계산에서 뺀다** — 넣으면
        # 장시간 녹화 하나가 일반 다운로드 자리를 통째로 막는다.
        running_normal = len(self._workers) - len(self._recordings & set(self._workers))
        for _ in range(slots_available(running_normal, self._concurrent_limit())):
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
        self._recordings.discard(job_id)
        # 한 자리가 비었으니 다음 대기 작업을 올린다.
        self._pump()

    def shutdown(self) -> None:
        """앱 종료 시 호출 — 실행 중인 다운로드 워커를 정리한다.

        진행 중인 다운로드는 협조적 취소가 없어 terminate로 중단하고
        wait()로 스레드 종료를 보장한다. 죽은 객체로 시그널이 가는 것을 막는다.
        """
        self._window_timer.stop()
        self._pending.clear()
        self._recordings.clear()
        self._probed.clear()
        for worker in list(self._workers.values()):
            if worker.isRunning():
                worker.terminate()
                worker.wait(3000)
        self._workers.clear()
        super().shutdown()   # 공용 추적 목록 정리
