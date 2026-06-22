"""업데이트 다운로드·적용 다이얼로그."""
from __future__ import annotations

import logging
import sys
import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
)

from application.updater.commands import DownloadUpdateHandler
from application.updater.dtos import UpdateDTO
from domain.shared.ports import UpdateInfo
from gui.updater.update_checker_worker import UpdateDownloadWorker

logger = logging.getLogger(__name__)


class UpdateDialog(QDialog):
    """새 버전 안내 및 다운로드·설치 다이얼로그."""

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

        self.setWindowTitle("업데이트 사용 가능")
        self.setMinimumWidth(480)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # 버전 안내
        title = QLabel(f"<b>버전 {self._dto.version}</b> 업데이트가 있습니다")
        title.setStyleSheet("font-size: 13px;")
        layout.addWidget(title)

        size_mb = self._dto.size_bytes / (1024 * 1024)
        meta = QLabel(f"다운로드 크기: {size_mb:.1f} MB")
        meta.setStyleSheet("font-size: 10px; color: #888;")
        layout.addWidget(meta)

        # 릴리스 노트 (외부 링크 차단 — XSS 유사 공격 방지)
        if self._dto.release_notes:
            notes = QTextBrowser()
            notes.setPlainText(self._dto.release_notes)
            notes.setOpenExternalLinks(False)
            notes.setOpenLinks(False)
            notes.setFixedHeight(120)
            notes.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            layout.addWidget(notes)

        # 진행 바 (숨김 → 다운로드 시작 시 표시)
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setTextVisible(True)
        self._progress.hide()
        layout.addWidget(self._progress)

        self._status_lbl = QLabel()
        self._status_lbl.setStyleSheet("font-size: 10px; color: #888;")
        self._status_lbl.hide()
        layout.addWidget(self._status_lbl)

        # 버튼 행
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._later_btn = QPushButton("나중에")
        self._later_btn.setFixedWidth(80)
        self._later_btn.clicked.connect(self._on_later)
        btn_row.addWidget(self._later_btn)

        self._install_btn = QPushButton("다운로드 및 설치")
        self._install_btn.setFixedWidth(140)
        self._install_btn.setDefault(True)
        self._install_btn.clicked.connect(self._start_download)
        btn_row.addWidget(self._install_btn)

        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    def _on_later(self) -> None:
        """나중에 클릭 — 이 버전을 스누즈로 저장하고 다이얼로그를 닫는다."""
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
        self._status_lbl.setText("다운로드 중…")

        # 예측 불가능한 1회용 디렉터리 — 경로 planting 공격 방지
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
            # content-length 헤더 없음 — 부정형 진행 바
            self._progress.setRange(0, 0)
            self._status_lbl.setText(f"{mb_d:.1f} MB 다운로드 중…")

    def _on_done(self, installer_path: str) -> None:
        self._status_lbl.setText("다운로드 완료. 설치 프로그램을 시작합니다…")
        self._apply_update(installer_path)

    def _on_failed(self, msg: str) -> None:
        self._progress.hide()
        self._status_lbl.hide()
        self._install_btn.setEnabled(True)
        self._later_btn.setEnabled(True)
        QMessageBox.warning(
            self,
            "다운로드 실패",
            f"업데이트 파일을 다운로드하지 못했습니다.\n\n{msg}",
        )

    def _apply_update(self, installer_path: str) -> None:
        if sys.platform == "win32":
            # 앱이 완전히 종료된 뒤 설치 프로그램을 실행해야 파일 잠금(재시도 창)을 피할 수 있다.
            # installer 경로를 pending 파일에 기록해두고, main.py의 app.exec() 반환 후에 실행한다.
            pending = Path(tempfile.gettempdir()) / "ovc_pending_update.txt"
            try:
                pending.write_text(installer_path, encoding="utf-8")
            except OSError:
                logger.exception("pending update 파일 작성 실패")
                QMessageBox.warning(
                    self,
                    "설치 실패",
                    f"업데이트 파일을 준비하지 못했습니다.\n파일 위치: {installer_path}",
                )
                return
            self._status_lbl.setText("앱 종료 후 설치가 자동으로 시작됩니다…")
            QApplication.instance().quit()
        else:
            # Linux: AppImage 교체 안내 (v1 범위 외 — 파일 위치 표시)
            QMessageBox.information(
                self,
                "다운로드 완료",
                f"업데이트 파일이 다운로드되었습니다.\n"
                f"파일 위치: {installer_path}\n\n"
                f"앱을 종료하고 새 버전으로 교체하세요.",
            )
            self.accept()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait(3000)
        super().closeEvent(event)
