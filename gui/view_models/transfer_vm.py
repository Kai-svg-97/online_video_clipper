"""설정 패널 '라이브러리 가져오기/내보내기' 상태 관리.

네 핸들러(내보내기/미리보기/충돌감지/가져오기)는 모두 `handle(cmd) -> DTO` 한
메서드짜리라 워커 클래스 하나(`_CommandWorker`)를 공유한다. 네트워크는 관여하지
않지만 zip 압축·다수 파일 I/O·SQLite 쓰기가 있어 QThread에서 실행한다.
"""
from __future__ import annotations

import logging
from uuid import UUID

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from application.transfer.commands import (
    DetectImportConflictsCommand,
    DetectImportConflictsHandler,
    ExportLibraryCommand,
    ExportLibraryHandler,
    ImportLibraryCommand,
    ImportLibraryHandler,
    PreviewImportCommand,
    PreviewImportHandler,
)

logger = logging.getLogger(__name__)


class _CommandWorker(QThread):
    """단일 `handler.handle(cmd)` 호출을 백그라운드로 실행한다."""

    done = pyqtSignal(object)    # 핸들러가 반환한 DTO
    failed = pyqtSignal(str)

    def __init__(self, handler, cmd, parent=None) -> None:
        super().__init__(parent)
        self._handler = handler
        self._cmd = cmd

    def run(self) -> None:
        try:
            result = self._handler.handle(self._cmd)
            self.done.emit(result)
        except Exception as exc:
            logger.exception("라이브러리 가져오기/내보내기 작업 실패")
            self.failed.emit(str(exc))


class LibraryTransferViewModel(QObject):
    """설정 패널의 내보내기/가져오기 버튼·다이얼로그가 호출하는 뷰모델."""

    export_finished   = pyqtSignal(object)   # ExportResultDTO
    preview_ready     = pyqtSignal(object)   # ImportPreviewDTO
    conflicts_ready   = pyqtSignal(object)   # ImportConflictsDTO
    import_finished   = pyqtSignal(object)   # ImportResultDTO
    busy_changed      = pyqtSignal(bool)
    error_occurred    = pyqtSignal(str)

    def __init__(
        self,
        export_handler: ExportLibraryHandler,
        preview_handler: PreviewImportHandler,
        conflicts_handler: DetectImportConflictsHandler,
        import_handler: ImportLibraryHandler,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._export = export_handler
        self._preview = preview_handler
        self._conflicts = conflicts_handler
        self._import = import_handler
        self._workers: list[QThread] = []

    def export_library(self, category_ids: list[UUID], dest_path: str) -> None:
        cmd = ExportLibraryCommand(category_ids=category_ids, dest_path=dest_path)
        self._run(self._export, cmd, self.export_finished)

    def preview_import(self, archive_path: str) -> None:
        cmd = PreviewImportCommand(archive_path=archive_path)
        self._run(self._preview, cmd, self.preview_ready)

    def detect_conflicts(self, archive_path: str, category_ids: list[str]) -> None:
        cmd = DetectImportConflictsCommand(archive_path=archive_path, category_ids=category_ids)
        self._run(self._conflicts, cmd, self.conflicts_ready)

    def import_library(
        self, archive_path: str, category_ids: list[str], resolutions: dict[str, dict[str, str]],
    ) -> None:
        cmd = ImportLibraryCommand(
            archive_path=archive_path, category_ids=category_ids, resolutions=resolutions,
        )
        self._run(self._import, cmd, self.import_finished)

    # ── 내부 ────────────────────────────────────────────────────────────

    def _run(self, handler, cmd, done_signal: pyqtSignal) -> None:
        worker = _CommandWorker(handler, cmd, self)

        def _on_done(result) -> None:
            self.busy_changed.emit(False)
            done_signal.emit(result)
            self._cleanup(worker)

        def _on_failed(msg: str) -> None:
            self.busy_changed.emit(False)
            self.error_occurred.emit(msg)
            self._cleanup(worker)

        worker.done.connect(_on_done)
        worker.failed.connect(_on_failed)
        self._workers.append(worker)
        self.busy_changed.emit(True)
        worker.start()

    def _cleanup(self, worker: QThread) -> None:
        if worker in self._workers:
            self._workers.remove(worker)

    def shutdown(self) -> None:
        """종료 시 실행 중인 워커를 정리한다(MainWindow.closeEvent에서 호출)."""
        for worker in list(self._workers):
            worker.wait(3000)
