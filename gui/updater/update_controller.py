"""업데이트 체크 워커 수명 및 다이얼로그 표시를 관리하는 컨트롤러."""
from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox

from application.updater.commands import DownloadUpdateHandler
from application.updater.dtos import UpdateDTO
from application.updater.queries import CheckForUpdateHandler
from domain.shared.ports import UpdateInfo
from gui.updater.pending import pending_marker_path, write_pending_update
from gui.updater.update_checker_worker import UpdateCheckWorker, UpdateDownloadWorker
from gui.updater.update_dialog import UpdateDialog

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SEC = 3_600  # 1시간


class UpdateController(QObject):
    """업데이트 확인·자동 다운로드·설치 트리거를 담당. MainWindow가 소유하며 shutdown()으로 정리."""

    update_notification = pyqtSignal(object)   # UpdateDTO — 발견했지만 자동 설치 준비 실패
    update_ready = pyqtSignal(object)          # UpdateDTO — 자동 다운로드 완료(종료 시 설치 준비됨)
    check_started = pyqtSignal()               # 확인 시작 — 설정 화면 상태 표시용
    check_finished = pyqtSignal()              # 확인/다운로드 종료(성공·실패 무관)

    def __init__(
        self,
        check_handler: CheckForUpdateHandler,
        download_handler: DownloadUpdateHandler,
        parent_window,
    ) -> None:
        super().__init__(parent_window)
        self._check_handler = check_handler
        self._download_handler = download_handler
        self._parent_window = parent_window
        self._worker: UpdateCheckWorker | None = None
        self._dl_worker: UpdateDownloadWorker | None = None
        self._downloaded_version: str | None = None   # 세션 중 중복 다운로드 방지
        self._last_dto: UpdateDTO | None = None
        self._last_info: UpdateInfo | None = None
        # "나중에"는 현재 세션만 억제 — 시작 시 스누즈를 초기화한다
        try:
            from config import settings as s  # noqa: PLC0415
            if getattr(s, "SNOOZED_UPDATE_VERSION", ""):
                s.save_setting("snoozed_update_version", "")
        except Exception:
            logger.exception("snoozed_update_version 초기화 실패")

    # ------------------------------------------------------------------
    def check_silently(self) -> None:
        """시작 시 조용히 확인. 새 버전 있을 때만 다이얼로그 표시."""
        if not self._should_check():
            return
        self._run_check(interactive=False)

    def check_interactively(self) -> None:
        """설정 버튼에서 호출 — '최신 버전입니다'도 표시."""
        self._run_check(interactive=True)

    def shutdown(self) -> None:
        for w in (self._worker, self._dl_worker):
            if w and w.isRunning():
                w.terminate()
                w.wait(3000)

    # ------------------------------------------------------------------
    def _should_check(self) -> bool:
        """AUTO_UPDATE_CHECK 설정이 켜져 있고, 마지막 확인 후 1시간이 지났는지 확인."""
        try:
            from config import settings as s  # noqa: PLC0415
            if not getattr(s, "AUTO_UPDATE_CHECK", True):
                return False
            last = getattr(s, "LAST_UPDATE_CHECK", 0) or 0
            return (time.time() - float(last)) >= _CHECK_INTERVAL_SEC
        except Exception:
            logger.exception("업데이트 체크 조건 확인 실패")
            return True

    @staticmethod
    def _mark_checked() -> None:
        """자동 확인 인터벌(1시간)을 소진 처리한다.

        **성공적으로 끝난 경우에만** 호출한다. 예전에는 확인을 시작하자마자 기록해,
        다운로드가 실패해도 다음 1시간 동안 재시도가 막혔다 — 앱을 다시 켜도 배지조차
        뜨지 않아 사용자가 업데이트할 방법이 없었다.
        """
        try:
            from config import settings as s  # noqa: PLC0415
            s.save_setting("last_update_check", time.time())
        except Exception:
            logger.exception("last_update_check 저장 실패")

    def _run_check(self, *, interactive: bool) -> None:
        if self._worker and self._worker.isRunning():
            return

        self.check_started.emit()
        self._worker = UpdateCheckWorker(self._check_handler, self)
        self._worker.found.connect(
            lambda dto: self._on_found(dto, interactive=interactive)
        )
        self._worker.none_found.connect(
            lambda: self._on_none_found(interactive=interactive)
        )
        self._worker.failed.connect(
            lambda msg: self._on_failed(msg, interactive=interactive)
        )
        self._worker.start()

    def _on_found(self, dto: UpdateDTO, *, interactive: bool) -> None:
        if not interactive:
            try:
                from config import settings as s  # noqa: PLC0415
                if dto.version == getattr(s, "SNOOZED_UPDATE_VERSION", ""):
                    self._mark_checked()
                    self.check_finished.emit()
                    return
            except Exception:
                logger.exception("snoozed_update_version 확인 실패")

        self._last_dto = dto
        self._last_info = UpdateInfo(
            version=dto.version,
            asset_name=dto.asset_name,
            download_url=dto.download_url,
            size_bytes=dto.size_bytes,
            sha256=dto.sha256,
            release_notes=dto.release_notes,
        )

        if interactive:
            self.check_finished.emit()
            self._show_update_dialog(dto)
        else:
            # 자동: 백그라운드 다운로드 → 완료 시 종료 설치 준비(배지/헤더).
            self._start_download(dto)

    # ------------------------------------------------------------------
    def _start_download(self, dto: UpdateDTO) -> None:
        if self._downloaded_version == dto.version:
            self.update_ready.emit(dto)   # 이미 이 버전 준비됨
            return
        if self._dl_worker and self._dl_worker.isRunning():
            return
        if self._last_info is None:
            return
        dest_dir = Path(tempfile.mkdtemp(prefix="ovc_update_"))
        self._dl_worker = UpdateDownloadWorker(
            self._download_handler, self._last_info, dest_dir, self
        )
        self._dl_worker.done.connect(lambda p, d=dto: self._on_download_done(p, d))
        self._dl_worker.failed.connect(lambda msg, d=dto: self._on_download_failed(msg, d))
        self._dl_worker.start()

    def _on_download_done(self, installer_path: str, dto: UpdateDTO) -> None:
        self._downloaded_version = dto.version
        self._mark_checked()
        self.check_finished.emit()
        if write_pending_update(installer_path):
            # 앱 종료 시 main.py tail이 설치. 지금은 준비 완료만 알림.
            self.update_ready.emit(dto)
        else:
            # 비win32 등 마커 미기록 — 수동 알림으로 폴백.
            self.update_notification.emit(dto)

    def _on_download_failed(self, msg: str, dto: UpdateDTO) -> None:
        # 인터벌을 소진하지 않는다 — 다음 실행에서 곧바로 다시 시도할 수 있어야 한다.
        logger.warning("업데이트 자동 다운로드 실패: %s", msg)
        self.check_finished.emit()
        self.update_notification.emit(dto)   # 배지 + 설정 헤더에 수동 설치 버튼

    def install_now(self, *_args) -> None:
        """헤더 '지금 설치' — pending 마커가 있으면 앱을 종료해 tail이 설치하도록 한다."""
        if pending_marker_path().exists():
            QApplication.instance().quit()
        elif self._last_dto is not None:
            # 마커 없음(다운로드 실패 등) — 수동 다운로드 다이얼로그로 폴백.
            self._show_update_dialog(self._last_dto)

    def _show_update_dialog(self, dto: UpdateDTO) -> None:
        dlg = UpdateDialog(
            dto=dto,
            info=self._last_info,
            download_handler=self._download_handler,
            parent=self._parent_window,
        )
        dlg.exec()

    def _on_none_found(self, *, interactive: bool) -> None:
        self._mark_checked()
        self.check_finished.emit()
        if interactive:
            QMessageBox.information(
                self._parent_window,
                "업데이트 확인",
                "현재 최신 버전을 사용 중입니다.",
            )

    def _on_failed(self, msg: str, *, interactive: bool) -> None:
        # 확인 자체가 실패했으면 인터벌을 소진하지 않는다(다음 실행에서 재시도).
        logger.warning("업데이트 확인 실패: %s", msg)
        self.check_finished.emit()
        if interactive:
            QMessageBox.warning(
                self._parent_window,
                "업데이트 확인 실패",
                f"업데이트를 확인하지 못했습니다.\n\n{msg}",
            )
