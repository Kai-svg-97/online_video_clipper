"""업데이트 확인 및 다운로드 QThread 워커."""
from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from application.updater.commands import DownloadUpdateCommand, DownloadUpdateHandler
from application.updater.dtos import UpdateDTO
from application.updater.queries import CheckForUpdateHandler, CheckForUpdateQuery
from domain.shared.ports import UpdateInfo

logger = logging.getLogger(__name__)


class UpdateCheckWorker(QThread):
    """백그라운드에서 최신 버전을 확인하는 워커."""

    found = pyqtSignal(object)    # UpdateDTO
    none_found = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(
        self,
        check_handler: CheckForUpdateHandler,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._handler = check_handler

    def run(self) -> None:
        try:
            dto: UpdateDTO | None = self._handler.handle(CheckForUpdateQuery())
            if dto is not None:
                self.found.emit(dto)
            else:
                self.none_found.emit()
        except Exception as exc:
            logger.exception("업데이트 확인 워커 오류")
            self.failed.emit(str(exc))


class UpdateDownloadWorker(QThread):
    """백그라운드에서 업데이트 파일을 다운로드하는 워커."""

    progress = pyqtSignal(int, int)   # (downloaded_bytes, total_bytes)
    done = pyqtSignal(str)            # 다운로드된 파일 경로
    failed = pyqtSignal(str)

    def __init__(
        self,
        download_handler: DownloadUpdateHandler,
        info: UpdateInfo,
        dest_dir: Path,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._handler = download_handler
        self._info = info
        self._dest_dir = dest_dir

    def run(self) -> None:
        try:
            path = self._handler.handle(
                DownloadUpdateCommand(self._info, self._dest_dir),
                on_progress=lambda d, t: self.progress.emit(d, t),
            )
            self.done.emit(str(path))
        except Exception as exc:
            logger.exception("업데이트 다운로드 워커 오류")
            self.failed.emit(str(exc))
