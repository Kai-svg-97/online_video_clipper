from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCloseEvent, QPixmapCache
from PyQt6.QtWidgets import (
    QApplication,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from config.settings import PIXMAP_CACHE_LIMIT_KB
from gui.panels.download_panel import DownloadPanel
from gui.panels.library_panel import LibraryPanel
from gui.panels.settings_dialog import SettingsDialog
from gui.view_models.clip_vm import ClipViewModel
from gui.view_models.download_vm import DownloadViewModel
from gui.view_models.library_vm import LibraryViewModel
from gui.view_models.monitoring_vm import MonitoringViewModel


class MainWindow(QMainWindow):
    def __init__(
        self,
        library_vm: LibraryViewModel,
        download_vm: DownloadViewModel,
        clip_vm: ClipViewModel,
        monitoring_vm: MonitoringViewModel,
    ) -> None:
        super().__init__()
        QPixmapCache.setCacheLimit(PIXMAP_CACHE_LIMIT_KB)
        self._library_vm = library_vm
        self._download_vm = download_vm
        self._clip_vm = clip_vm
        self._monitoring_vm = monitoring_vm
        self.setWindowTitle("YouTube Content Manager")
        self.setMinimumSize(1024, 680)
        self._setup_ui()
        self._setup_clipboard_monitoring()

    def _setup_ui(self) -> None:
        toolbar = QToolBar("Main", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("Paste YouTube URL here…")
        self._url_input.setMinimumWidth(400)
        self._url_input.returnPressed.connect(self._on_url_submitted)

        paste_btn = QPushButton("Paste & Add")
        paste_btn.clicked.connect(self._on_paste_clicked)

        settings_btn = QPushButton("⚙ Settings")
        settings_btn.clicked.connect(self._on_settings_clicked)

        toolbar.addWidget(self._url_input)
        toolbar.addWidget(paste_btn)
        toolbar.addSeparator()
        toolbar.addWidget(settings_btn)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self._library_panel = LibraryPanel(self._library_vm)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._library_panel)
        splitter.addWidget(DownloadPanel(self._download_vm))
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        main_layout.addWidget(splitter)

        self.setStatusBar(QStatusBar())
        self._library_vm.error_occurred.connect(self._show_library_error)
        self._library_vm.video_add_started.connect(
            lambda url: self.statusBar().showMessage(f"영상 등록 중: {url}", 0)
        )
        self._library_vm.video_add_finished.connect(
            lambda url: self.statusBar().showMessage(f"등록 완료: {url}", 5000)
        )
        self._library_panel.download_requested.connect(
            lambda url, title, s: self._download_vm.start_download(url, title, s)
        )
        self._download_vm.error_occurred.connect(self._show_error)
        self._clip_vm.error_occurred.connect(self._show_error)
        self._monitoring_vm.error_occurred.connect(self._show_error)

    def _setup_clipboard_monitoring(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.dataChanged.connect(self._on_clipboard_changed)

    def _on_clipboard_changed(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is None:
            return
        text = clipboard.text().strip()
        if text.startswith(("https://www.youtube.com/", "https://youtu.be/")):
            self._url_input.setText(text)

    def _on_url_submitted(self) -> None:
        url = self._url_input.text().strip()
        if url:
            self._library_vm.add_video(url, self._library_panel.current_category_id())
            self._url_input.clear()

    def _on_paste_clicked(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard:
            self._url_input.setText(clipboard.text().strip())
        self._on_url_submitted()

    def _on_settings_clicked(self) -> None:
        dlg = SettingsDialog(self)
        dlg.exec()

    def _show_error(self, msg: str) -> None:
        self.statusBar().showMessage(f"오류: {msg}", 6000)

    def _show_library_error(self, msg: str) -> None:
        """Show library errors as a dialog so they can't be missed."""
        self.statusBar().showMessage(f"오류: {msg}", 6000)
        QMessageBox.warning(self, "영상 등록 오류", msg)

    def closeEvent(self, event: QCloseEvent) -> None:
        event.accept()
