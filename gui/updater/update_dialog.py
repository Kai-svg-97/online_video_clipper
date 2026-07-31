"""업데이트 다운로드·적용 다이얼로그 — 클린 미니멀 레이아웃."""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from application.updater.commands import DownloadUpdateHandler
from application.updater.dtos import UpdateDTO
from domain.shared.ports import UpdateInfo
from gui.updater.update_checker_worker import UpdateDownloadWorker
from gui.themes.colors import tok

logger = logging.getLogger(__name__)


class UpdateDialog(QDialog):
    """새 버전 다운로드·설치 다이얼로그 — 클린 미니멀 레이아웃."""

    def __init__(
        self,
        dto: UpdateDTO,
        info: UpdateInfo,
        download_handler: DownloadUpdateHandler,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._dto = dto
        self._info = info
        self._download_handler = download_handler
        self._worker: UpdateDownloadWorker | None = None

        self.setWindowTitle("업데이트")
        self.setFixedWidth(360)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(24, 24, 24, 20)

        ver_lbl = QLabel(f"v{self._dto.version}")
        ver_lbl.setStyleSheet("font-size: 22px; font-weight: 700; margin-bottom: 2px;")
        layout.addWidget(ver_lbl)

        sub_lbl = QLabel("새 버전이 출시되었습니다")
        sub_lbl.setStyleSheet(f"font-size: 11px; color: {tok().text_secondary}; margin-bottom: 16px;")
        layout.addWidget(sub_lbl)
        layout.addSpacing(16)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #2a2a2a;")
        layout.addWidget(sep)
        layout.addSpacing(14)

        size_mb = self._dto.size_bytes / (1024 * 1024)
        size_lbl = QLabel(f"다운로드 크기  {size_mb:.1f} MB")
        size_lbl.setStyleSheet("font-size: 11px; color: #aaa;")
        layout.addWidget(size_lbl)
        layout.addSpacing(16)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(4)
        self._progress.setStyleSheet(
            f"QProgressBar {{ background: {tok().bg_overlay}; border-radius: 2px; }}"
            f"QProgressBar::chunk {{ background: {tok().accent}; border-radius: 2px; }}"
        )
        self._progress.hide()
        layout.addWidget(self._progress)

        self._status_lbl = QLabel()
        self._status_lbl.setStyleSheet(f"font-size: 9px; color: {tok().text_secondary}; margin-top: 4px;")
        self._status_lbl.hide()
        layout.addWidget(self._status_lbl)

        layout.addSpacing(20)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()

        self._later_btn = QPushButton("나중에")
        self._later_btn.setFixedWidth(72)
        self._later_btn.setFlat(True)
        self._later_btn.setStyleSheet(f"color: {tok().text_secondary};")
        self._later_btn.clicked.connect(self._on_later)
        btn_row.addWidget(self._later_btn)

        self._install_btn = QPushButton("지금 업데이트")
        self._install_btn.setFixedWidth(110)
        self._install_btn.setDefault(True)
        self._install_btn.clicked.connect(self._start_download)
        btn_row.addWidget(self._install_btn)

        layout.addLayout(btn_row)

    def _on_later(self) -> None:
        try:
            from config.settings import save_setting  # noqa: PLC0415
            save_setting("snoozed_update_version", self._dto.version)
        except Exception:
            logger.exception("snoozed_update_version 저장 실패")
        self.reject()

    def _start_download(self) -> None:
        self._install_btn.setEnabled(False)
        self._later_btn.setEnabled(False)
        self._progress.show()
        self._status_lbl.show()
        self._status_lbl.setText("다운로드 준비 중…")

        dest_dir = Path(tempfile.mkdtemp(prefix="ovc_update_"))
        self._worker = UpdateDownloadWorker(
            self._download_handler, self._info, dest_dir, self
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, downloaded: int, total: int) -> None:
        mb_d = downloaded / (1024 * 1024)
        if total > 0:
            pct = int(downloaded * 100 / total)
            self._progress.setRange(0, 100)
            self._progress.setValue(pct)
            mb_t = total / (1024 * 1024)
            self._status_lbl.setText(f"{mb_d:.1f} / {mb_t:.1f} MB")
        else:
            self._progress.setRange(0, 0)
            self._status_lbl.setText(f"{mb_d:.1f} MB 다운로드 중…")

    def _on_done(self, installer_path: str) -> None:
        self._status_lbl.setText("완료. 설치를 시작합니다…")
        self._apply_update(installer_path)

    def _on_failed(self, msg: str) -> None:
        self._progress.hide()
        self._status_lbl.hide()
        self._install_btn.setEnabled(True)
        self._later_btn.setEnabled(True)
        QMessageBox.warning(
            self, "다운로드 실패",
            f"업데이트 파일을 다운로드하지 못했습니다.\n\n{msg}",
        )

    def _apply_update(self, installer_path: str) -> None:
        from gui.updater.pending import write_pending_update  # noqa: PLC0415

        if write_pending_update(installer_path):
            self._status_lbl.setText("앱 종료 후 설치가 자동으로 시작됩니다…")
            QApplication.instance().quit()
        else:
            QMessageBox.information(
                self, "다운로드 완료",
                f"업데이트 파일:\n{installer_path}\n\n앱을 종료하고 새 버전으로 교체하세요.",
            )
            self.accept()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait(3000)
        super().closeEvent(event)
