"""업데이트 체크 워커 수명 및 다이얼로그 표시를 관리하는 컨트롤러."""
from __future__ import annotations

import logging
import time

from PyQt6.QtCore import QObject
from PyQt6.QtWidgets import QMessageBox

from application.updater.commands import DownloadUpdateHandler
from application.updater.dtos import UpdateDTO
from application.updater.queries import CheckForUpdateHandler
from domain.shared.ports import UpdateInfo
from gui.updater.update_checker_worker import UpdateCheckWorker
from gui.updater.update_dialog import UpdateDialog

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SEC = 86_400  # 24시간


class UpdateController(QObject):
    """업데이트 확인·다이얼로그 표시를 담당. MainWindow가 소유하며 shutdown()으로 정리."""

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
        self._last_dto: UpdateDTO | None = None
        self._last_info: UpdateInfo | None = None

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
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait(3000)

    # ------------------------------------------------------------------
    def _should_check(self) -> bool:
        """AUTO_UPDATE_CHECK 설정이 켜져 있고, 24시간이 지났는지 확인."""
        try:
            from config import settings as s  # noqa: PLC0415
            if not getattr(s, "AUTO_UPDATE_CHECK", True):
                return False
            last = getattr(s, "LAST_UPDATE_CHECK", 0) or 0
            return (time.time() - float(last)) >= _CHECK_INTERVAL_SEC
        except Exception:
            logger.exception("업데이트 체크 조건 확인 실패")
            return True

    def _run_check(self, *, interactive: bool) -> None:
        if self._worker and self._worker.isRunning():
            return

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

        # 체크 시각 갱신
        try:
            from config import settings as s  # noqa: PLC0415
            s.save_setting("last_update_check", time.time())
        except Exception:
            logger.exception("last_update_check 저장 실패")

    def _on_found(self, dto: UpdateDTO, *, interactive: bool) -> None:  # noqa: ARG002
        # domain UpdateInfo 를 재구성 (DTO에서 복원)
        self._last_dto = dto
        self._last_info = UpdateInfo(
            version=dto.version,
            asset_name=dto.asset_name,
            download_url=dto.download_url,
            size_bytes=dto.size_bytes,
            sha256=dto.sha256,
            release_notes=dto.release_notes,
        )
        dlg = UpdateDialog(
            dto=dto,
            info=self._last_info,
            download_handler=self._download_handler,
            parent=self._parent_window,
        )
        dlg.exec()

    def _on_none_found(self, *, interactive: bool) -> None:
        if interactive:
            QMessageBox.information(
                self._parent_window,
                "업데이트 확인",
                "현재 최신 버전을 사용 중입니다.",
            )

    def _on_failed(self, msg: str, *, interactive: bool) -> None:
        logger.warning("업데이트 확인 실패: %s", msg)
        if interactive:
            QMessageBox.warning(
                self._parent_window,
                "업데이트 확인 실패",
                f"업데이트를 확인하지 못했습니다.\n\n{msg}",
            )
