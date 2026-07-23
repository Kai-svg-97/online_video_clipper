"""SyncViewModel — 클라우드 동기화 UI 상태(설정 패널).

SyncService(infrastructure)를 QThread로 감싼다: push/pull·미디어 동기화·연결(OAuth)은
백그라운드에서 돌리고 결과를 Qt 시그널로 방출한다. 연결돼 있으면 QTimer로 주기 자동
동기화한다(사용자 결정: 자동/주기).
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

logger = logging.getLogger(__name__)

_AUTO_INTERVAL_MS = 5 * 60 * 1000  # 5분


class _SyncWorker(QThread):
    """push→pull→미디어 동기화를 백그라운드로 실행."""

    done = pyqtSignal(int, int)   # (pushed, pulled)
    failed = pyqtSignal(str)

    def __init__(self, service, parent=None) -> None:
        super().__init__(parent)
        self._service = service

    def run(self) -> None:
        try:
            pushed, pulled = self._service.sync_now()
            try:
                self._service.sync_media()
            except Exception:
                logger.exception("미디어 파일 동기화 실패(메타데이터는 반영됨)")
            self.done.emit(pushed, pulled)
        except Exception as exc:
            logger.exception("동기화 실패")
            self.failed.emit(str(exc))


class _ConnectWorker(QThread):
    """provider 연결(대화형 OAuth)을 백그라운드로 실행."""

    done = pyqtSignal(bool)
    failed = pyqtSignal(str)

    def __init__(self, service, provider_key: str, creds: dict, parent=None) -> None:
        super().__init__(parent)
        self._service = service
        self._provider_key = provider_key
        self._creds = creds

    def run(self) -> None:
        try:
            if self._provider_key == "folder":
                ok = self._service.connect_folder(self._creds["folder_path"])
            elif self._provider_key == "gdrive":
                ok = self._service.connect_gdrive(
                    self._creds["client_id"], self._creds["client_secret"]
                )
            else:
                ok = self._service.connect_onedrive(self._creds["client_id"])
            self.done.emit(bool(ok))
        except Exception as exc:
            logger.exception("provider 연결 실패")
            self.failed.emit(str(exc))


class SyncViewModel(QObject):
    status_changed = pyqtSignal(object)   # SyncStatusDTO
    busy_changed = pyqtSignal(bool)
    sync_finished = pyqtSignal(int, int)  # (pushed, pulled)
    connection_changed = pyqtSignal(bool)
    error_occurred = pyqtSignal(str)

    def __init__(self, service, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._workers: list[QThread] = []
        self._busy = False
        self._timer = QTimer(self)
        self._timer.setInterval(_AUTO_INTERVAL_MS)
        self._timer.timeout.connect(self._auto_tick)

    # -- 상태 -----------------------------------------------------------
    def refresh_status(self) -> None:
        try:
            self.status_changed.emit(self._service.status())
        except Exception as exc:
            logger.exception("동기화 상태 조회 실패")
            self.error_occurred.emit(str(exc))

    def is_connected(self) -> bool:
        return self._service.is_connected()

    def start_auto_sync(self) -> None:
        """연결돼 있으면 즉시 1회 동기화하고 주기 타이머를 켠다."""
        if self._service.is_connected():
            self.sync_now()
            self._timer.start()

    def _auto_tick(self) -> None:
        if self._service.is_connected() and not self._busy:
            self.sync_now()

    # -- 동기화 ---------------------------------------------------------
    def sync_now(self) -> None:
        if self._busy or not self._service.is_connected():
            return
        self._set_busy(True)
        worker = _SyncWorker(self._service, self)
        worker.done.connect(self._on_sync_done)
        worker.failed.connect(self._on_sync_failed)
        self._track(worker)
        worker.start()

    def _on_sync_done(self, pushed: int, pulled: int) -> None:
        self._set_busy(False)
        self.sync_finished.emit(pushed, pulled)
        self.refresh_status()

    def _on_sync_failed(self, err: str) -> None:
        self._set_busy(False)
        self.error_occurred.emit(err)

    # -- 연결/해제 -------------------------------------------------------
    def connect(self, provider_key: str, **creds) -> None:
        if self._busy:
            return
        self._set_busy(True)
        worker = _ConnectWorker(self._service, provider_key, creds, self)
        worker.done.connect(self._on_connect_done)
        worker.failed.connect(self._on_sync_failed)
        self._track(worker)
        worker.start()

    def _on_connect_done(self, ok: bool) -> None:
        self._set_busy(False)
        self.connection_changed.emit(ok)
        self.refresh_status()
        if ok:
            self._timer.start()

    def disconnect(self) -> None:
        self._timer.stop()
        try:
            self._service.disconnect()
        except Exception as exc:
            logger.exception("연결 해제 실패")
            self.error_occurred.emit(str(exc))
        self.connection_changed.emit(False)
        self.refresh_status()

    # -- 내부 -----------------------------------------------------------
    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.busy_changed.emit(busy)

    def _track(self, worker: QThread) -> None:
        worker.finished.connect(
            lambda: self._workers.remove(worker) if worker in self._workers else None
        )
        self._workers.append(worker)

    def shutdown(self) -> None:
        self._timer.stop()
        for worker in list(self._workers):
            try:
                if worker.isRunning():
                    worker.quit()
                    if not worker.wait(3000):
                        worker.terminate()
                        worker.wait()
            except RuntimeError:
                pass
        self._workers.clear()
