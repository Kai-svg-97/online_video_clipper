"""라이브러리 페이지(LibraryPanel + 하단 다운로드 상태바)."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout, QWidget

from gui.media_services import MediaServices
from gui.panels.library_panel import LibraryPanel
from gui.shell.pages import _PAGE_DOWNLOAD
from gui.text import tr
from gui.themes.manager import ThemeManager
from gui.themes.tokens import ThemeTokens
from gui.view_models.clip_vm import ClipViewModel
from gui.view_models.download_vm import DownloadViewModel
from gui.view_models.feed_vm import FeedViewModel
from gui.view_models.library_vm import LibraryViewModel
from gui.view_models.monitoring_vm import MonitoringViewModel
from gui.view_models.playlist_vm import PlaylistViewModel


# ---------------------------------------------------------------------------
# 다운로드 상태바
# ---------------------------------------------------------------------------

class _DownloadBar(QWidget):
    """하단 슬림 다운로드 상태 표시바.

    활성 다운로드가 없으면 숨긴다.
    클릭 시 다운로드 페이지로 이동한다.
    """

    def __init__(
        self,
        stack: QStackedWidget,
        download_vm: DownloadViewModel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._stack = stack
        self._vm = download_vm
        self.setFixedHeight(28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)

        self._dot = QLabel("●")
        self._dot.setStyleSheet("font-size: 8px;")
        layout.addWidget(self._dot)

        self._msg = QLabel(tr("다운로드 없음"))
        self._msg.setStyleSheet("font-size: 10px;")
        layout.addWidget(self._msg)
        layout.addStretch()

        self._apply_theme(ThemeManager.instance().current())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)

        # DownloadViewModel 연결
        self._vm.queue_changed.connect(self._refresh)
        self._refresh()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        self._stack.setCurrentIndex(_PAGE_DOWNLOAD)

    def _refresh(self) -> None:
        jobs = self._vm.queue
        active = [j for j in jobs if j.status in ("pending", "running", "downloading")]
        if active:
            first = active[0]
            pct = first.progress.percent if hasattr(first, "progress") else 0
            self._msg.setText(f"{first.title} — {pct:.0f}%")
            self.show()
        else:
            self.hide()

    def _apply_theme(self, tokens: ThemeTokens) -> None:
        self.setStyleSheet(f"""
            _DownloadBar {{
                background-color: {tokens.bg_surface};
                border-top: 1px solid {tokens.border};
            }}
        """)
        self.setObjectName("dlbar")
        self.setAutoFillBackground(True)
        self._dot.setStyleSheet(f"font-size: 8px; color: {tokens.text_muted};")
        self._msg.setStyleSheet(f"font-size: 10px; color: {tokens.text_muted};")


# ---------------------------------------------------------------------------
# 라이브러리 페이지 (URL 바 + LibraryPanel + DownloadBar)
# ---------------------------------------------------------------------------

class _LibraryPage(QWidget):
    def __init__(
        self,
        library_vm: LibraryViewModel,
        download_vm: DownloadViewModel,
        clip_vm: ClipViewModel,
        stack: QStackedWidget,
        playlist_vm: PlaylistViewModel | None = None,
        feed_vm: FeedViewModel | None = None,
        monitoring_vm: MonitoringViewModel | None = None,
        song_vm=None,
        recommend_vm=None,
        album_vm=None,
        subtitle_vm=None,
        media: MediaServices | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._library_panel = LibraryPanel(
            library_vm,
            clip_vm=clip_vm,
            download_vm=download_vm,
            playlist_vm=playlist_vm,
            feed_vm=feed_vm,
            monitoring_vm=monitoring_vm,
            song_vm=song_vm,
            recommend_vm=recommend_vm,
            album_vm=album_vm,
            subtitle_vm=subtitle_vm,
            media=media,
        )
        layout.addWidget(self._library_panel, 1)

        self._dl_bar = _DownloadBar(stack, download_vm)
        layout.addWidget(self._dl_bar)

    def library_panel(self) -> LibraryPanel:
        return self._library_panel
