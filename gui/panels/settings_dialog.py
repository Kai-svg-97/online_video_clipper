from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from config import settings as _s


class SettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._db_edit = self._path_row(str(_s.DATABASE_PATH))
        self._dl_edit = self._path_row(str(_s.DOWNLOAD_DIR))
        self._th_edit = self._path_row(str(_s.THUMBNAIL_DIR))
        self._log_edit = self._path_row(str(_s.LOG_DIR))

        form.addRow("Database file:", self._db_edit)
        form.addRow("Downloads folder:", self._dl_edit)
        form.addRow("Thumbnails folder:", self._th_edit)
        form.addRow("Logs folder:", self._log_edit)

        note = QLabel(
            "Edit <b>data/config.yaml</b> to set custom paths permanently.<br>"
            "Changes here are shown for reference only."
        )
        note.setWordWrap(True)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)

    @staticmethod
    def _path_row(path: str) -> QLineEdit:
        edit = QLineEdit(path)
        edit.setReadOnly(True)
        return edit
