from __future__ import annotations

from uuid import UUID

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from application.download.dtos import DownloadJobDTO
from gui.view_models.download_vm import DownloadViewModel


class _JobRow(QWidget):
    def __init__(self, job: DownloadJobDTO, on_cancel, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        self._title = QLabel(job.title)
        self._title.setMaximumWidth(300)
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
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


class DownloadPanel(QWidget):
    def __init__(self, vm: DownloadViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vm = vm
        self._rows: dict[UUID, _JobRow] = {}
        self._setup_ui()
        vm.queue_changed.connect(self._refresh)

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        header = QLabel("Downloads")
        header.setAlignment(Qt.AlignmentFlag.AlignLeft)
        outer.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.addStretch()
        scroll.setWidget(self._container)
        outer.addWidget(scroll)

    def _refresh(self) -> None:
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
