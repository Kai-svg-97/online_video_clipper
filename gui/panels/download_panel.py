from __future__ import annotations

from pathlib import Path
from uuid import UUID

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from application.download.dtos import DownloadJobDTO
from gui.view_models.download_vm import DownloadViewModel


class _JobRow(QWidget):
    """진행 중인 다운로드 행."""

    def __init__(self, job: DownloadJobDTO, on_cancel, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        self._title = QLabel(job.title)
        self._title.setMaximumWidth(300)
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setTextVisible(False)  # 얇은 바라 퍼센트 텍스트 숨김
        self._bar.setValue(int(job.progress.percent))
        self._speed = QLabel(job.progress.speed_formatted())
        cancel_btn = QPushButton("✕")
        cancel_btn.setFixedWidth(28)
        cancel_btn.clicked.connect(lambda: on_cancel(job.id))

        layout.addWidget(self._title)
        layout.addWidget(self._bar, 1)
        layout.addWidget(self._speed)
        layout.addWidget(cancel_btn)

    def update_job(self, job: DownloadJobDTO) -> None:
        self._bar.setValue(int(job.progress.percent))
        self._speed.setText(job.progress.speed_formatted())


_VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".m4a", ".mp3", ".opus"}


def _is_listable_history(job: DownloadJobDTO) -> bool:
    """완료 이력에 보여줄 행인지 판정.

    file_path가 있으면 영상 확장자만 표시(썸네일 .jpg/.webp·중단 파일 .part 등 제외).
    file_path가 없는 실패 작업은 '실패' 행으로 그대로 보여준다.
    """
    if not job.file_path:
        return bool(job.error_msg)
    suffix = Path(job.file_path).suffix.lower()
    if suffix == ".part":
        return False
    return suffix in _VIDEO_EXTS


def _fmt_size(b: int | None) -> str:
    if b is None:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


class _HistoryRow(QWidget):
    """완료/실패 이력 행."""

    def __init__(self, job: DownloadJobDTO, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        completed = job.status == "COMPLETED"
        badge_text = "완료" if completed else "실패"
        badge_color = "#4caf50" if completed else "#f44336"
        badge_lbl = QLabel(badge_text)
        badge_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge_lbl.setFixedWidth(44)
        badge_lbl.setStyleSheet(
            f"color: white; background: {badge_color}; border-radius: 6px;"
            " font-size: 8pt; font-weight: bold; padding: 1px 0;"
        )
        layout.addWidget(badge_lbl)

        title_lbl = QLabel(job.title or job.url)
        title_lbl.setMaximumWidth(300)
        title_lbl.setToolTip(job.url)
        layout.addWidget(title_lbl, 1)

        if job.file_path:
            fp = Path(job.file_path)
            size = fp.stat().st_size if fp.exists() else None
            size_lbl = QLabel(_fmt_size(size))
            size_lbl.setFixedWidth(70)
            layout.addWidget(size_lbl)

            open_btn = QPushButton("📂")
            open_btn.setFixedWidth(28)
            open_btn.setToolTip("폴더 열기")
            folder = str(fp.parent)
            open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(folder)))
            layout.addWidget(open_btn)
        elif job.error_msg:
            err_lbl = QLabel(job.error_msg)
            err_lbl.setStyleSheet("color: #f44336; font-size: 8pt;")
            err_lbl.setToolTip(job.error_msg)
            layout.addWidget(err_lbl, 1)


class _QueueTab(QWidget):
    """진행 중인 다운로드 탭."""

    def __init__(self, vm: DownloadViewModel, parent=None) -> None:
        super().__init__(parent)
        self._vm = vm
        self._rows: dict[UUID, _JobRow] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.addStretch()
        scroll.setWidget(self._container)
        outer.addWidget(scroll)

        vm.queue_changed.connect(self.refresh)

    def refresh(self) -> None:
        jobs = self._vm.queue
        current_ids = {j.id for j in jobs}

        for job_id in list(self._rows):
            if job_id not in current_ids:
                row = self._rows.pop(job_id)
                self._container_layout.removeWidget(row)
                row.deleteLater()

        for job in jobs:
            if job.id in self._rows:
                self._rows[job.id].update_job(job)
            else:
                row = _JobRow(job, self._vm.cancel_download, self._container)
                self._rows[job.id] = row
                self._container_layout.insertWidget(
                    self._container_layout.count() - 1, row
                )


class _HistoryTab(QWidget):
    """완료/실패 이력 탭."""

    def __init__(self, vm: DownloadViewModel, parent=None) -> None:
        super().__init__(parent)
        self._vm = vm

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        header_row = QHBoxLayout()
        refresh_btn = QPushButton("새로고침")
        refresh_btn.setFixedHeight(24)
        refresh_btn.clicked.connect(self.refresh)
        header_row.addStretch()
        header_row.addWidget(refresh_btn)
        outer.addLayout(header_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.addStretch()
        scroll.setWidget(self._container)
        outer.addWidget(scroll)

        vm.history_changed.connect(self.refresh)

    def refresh(self) -> None:
        # 기존 행 전부 제거
        while self._container_layout.count() > 1:
            item = self._container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for job in self._vm.load_history():
            if not _is_listable_history(job):
                continue
            row = _HistoryRow(job, self._container)
            self._container_layout.insertWidget(
                self._container_layout.count() - 1, row
            )


class DownloadPanel(QWidget):
    def __init__(self, vm: DownloadViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vm = vm
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        header = QLabel("다운로드")
        header.setAlignment(Qt.AlignmentFlag.AlignLeft)
        outer.addWidget(header)

        tabs = QTabWidget()
        self._queue_tab = _QueueTab(self._vm)
        self._history_tab = _HistoryTab(self._vm)
        tabs.addTab(self._queue_tab, "진행 중")
        tabs.addTab(self._history_tab, "완료 이력")
        tabs.currentChanged.connect(self._on_tab_changed)
        outer.addWidget(tabs)

    def _on_tab_changed(self, index: int) -> None:
        if index == 1:
            self._history_tab.refresh()
