"""메인 윈도우 — 아이콘 사이드바 + 콘텐츠 스택 레이아웃."""
from __future__ import annotations

import logging

from PyQt6.QtCore import QSize, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QColor, QIcon, QPainter, QPixmap, QPixmapCache
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from config.settings import PIXMAP_CACHE_LIMIT_KB, THEME
# YouTubeAuthDialog는 단독 다이얼로그 대신 Settings 패널로 통합됨
from gui.panels.download_panel import DownloadPanel
from gui.panels.library_panel import LibraryPanel
from gui.panels.monitoring_panel import MonitoringPanel
from gui.panels.settings_panel import SettingsPanel  # noqa: F401 (used in isinstance check)
from gui.panels.stats_panel import StatsPanel
from gui.themes.manager import ThemeManager
from gui.themes.tokens import ThemeTokens
from gui.view_models.clip_vm import ClipViewModel
from gui.view_models.download_vm import DownloadViewModel
from gui.view_models.feed_vm import FeedViewModel
from gui.view_models.library_vm import LibraryViewModel
from gui.view_models.monitoring_vm import MonitoringViewModel
from gui.view_models.playlist_vm import PlaylistViewModel
from infrastructure.auth.youtube_auth import YouTubeAuthService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SVG 아이콘 정의 (인라인)
# ---------------------------------------------------------------------------

_SVG_LIBRARY = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
  fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
  <rect x="3" y="3" width="7" height="7" rx="1"/>
  <rect x="14" y="3" width="7" height="7" rx="1"/>
  <rect x="3" y="14" width="7" height="7" rx="1"/>
  <rect x="14" y="14" width="7" height="7" rx="1"/>
</svg>"""

_SVG_DOWNLOAD = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
  fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
  <path d="M12 3v12M6 12l6 6 6-6"/><line x1="3" y1="20" x2="21" y2="20"/>
</svg>"""

_SVG_MONITOR = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
  fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
  <path d="M15 10l4.553-2.069A1 1 0 0121 8.87v6.26a1 1 0 01-1.447.9L15 14"/>
  <rect x="3" y="6" width="12" height="12" rx="2"/>
</svg>"""

_SVG_STATS = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
  fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
  <rect x="3" y="12" width="4" height="9"/><rect x="10" y="7" width="4" height="14"/>
  <rect x="17" y="3" width="4" height="18"/>
</svg>"""

_SVG_FEED = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
  fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
  <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/>
  <polyline points="9 22 9 12 15 12 15 22"/>
</svg>"""

_SVG_ACCOUNT = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
  fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
  <circle cx="12" cy="8" r="4"/>
  <path d="M4 20c0-4 3.6-7 8-7s8 3 8 7"/>
</svg>"""

_SVG_SETTINGS = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"
  fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
  <circle cx="12" cy="12" r="3"/>
  <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83
    2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33
    1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09
    A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06
    a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15
    a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09
    A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06
    a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68
    a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09
    a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06
    a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9
    a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09
    a1.65 1.65 0 00-1.51 1z"/>
</svg>"""


def _make_svg_icon(svg_bytes: bytes, color: str, size: int = 16) -> QIcon:
    """SVG 바이트에서 지정 색상의 QIcon을 생성한다."""
    colored = svg_bytes.replace(b'stroke="currentColor"',
                                f'stroke="{color}"'.encode())
    renderer = QSvgRenderer(colored)
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


# ---------------------------------------------------------------------------
# 사이드바 내비게이션 버튼
# ---------------------------------------------------------------------------

_PAGE_LIBRARY  = 0
_PAGE_DOWNLOAD = 1
_PAGE_MONITOR  = 2
_PAGE_STATS    = 3
_PAGE_SETTINGS = 4


class _NavButton(QPushButton):
    """사이드바 아이콘 내비게이션 버튼."""

    def __init__(
        self,
        svg: bytes,
        tooltip: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._svg = svg
        self.setToolTip(tooltip)
        self.setFixedSize(32, 32)
        self.setCheckable(True)
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_theme(ThemeManager.instance().current())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)
        self._show_badge = False

    def set_badge(self, visible: bool) -> None:
        self._show_badge = visible
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        if self._show_badge:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(210, 55, 55))
            r = 5
            p.drawEllipse(self.width() - r * 2 - 2, 2, r * 2, r * 2)
            p.end()

    def _apply_theme(self, tokens: ThemeTokens) -> None:
        icon_color = tokens.text_secondary
        active_color = tokens.text_primary
        bg_overlay = tokens.bg_overlay
        self._update_icons(icon_color, active_color)
        self.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background: {bg_overlay};
            }}
            QPushButton:checked {{
                background: {bg_overlay};
                border-left: 2px solid {tokens.accent};
                border-radius: 0px 6px 6px 0px;
            }}
        """)

    def _update_icons(self, normal: str, active: str) -> None:
        self.setIcon(_make_svg_icon(self._svg, normal, 16))
        self.setIconSize(QSize(16, 16))


# ---------------------------------------------------------------------------
# 사이드바
# ---------------------------------------------------------------------------

class _SideBar(QWidget):
    """48px 고정 너비 아이콘 사이드바."""

    settings_navigated_with_badge = pyqtSignal()

    def __init__(self, stack: QStackedWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._stack = stack
        self._buttons: list[_NavButton] = []
        self.setFixedWidth(48)
        self._build_ui()
        self._apply_theme(ThemeManager.instance().current())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 12)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # 로고
        logo = QLabel("▶")
        logo.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        logo.setStyleSheet("font-size: 14px; font-weight: 700; margin-bottom: 10px;")
        layout.addWidget(logo)

        # 주 내비게이션 버튼
        nav_defs = [
            (_SVG_LIBRARY,  "라이브러리",        _PAGE_LIBRARY),
            (_SVG_DOWNLOAD, "다운로드",          _PAGE_DOWNLOAD),
            (_SVG_MONITOR,  "채널 모니터링",      _PAGE_MONITOR),
            (_SVG_STATS,    "통계",              _PAGE_STATS),
        ]
        for svg, tip, page in nav_defs:
            btn = _NavButton(svg, tip)
            btn.clicked.connect(lambda checked, p=page: self._navigate(p))
            layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignHCenter)
            self._buttons.append(btn)

        layout.addStretch()

        # 계정 버튼 → 설정 페이지의 YouTube 연동 섹션으로 이동
        self._account_btn = _NavButton(_SVG_ACCOUNT, "YouTube 연동 설정")
        self._account_btn.setCheckable(False)
        self._account_btn.clicked.connect(lambda: self._navigate(_PAGE_SETTINGS))
        layout.addWidget(self._account_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        # 설정 버튼 (하단)
        self._settings_btn = _NavButton(_SVG_SETTINGS, "설정")
        self._settings_btn.clicked.connect(lambda: self._navigate(_PAGE_SETTINGS))
        layout.addWidget(self._settings_btn, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._buttons.append(self._settings_btn)

        # 첫 번째(라이브러리) 선택
        self._buttons[0].setChecked(True)

    def update_account_status(self, is_connected: bool) -> None:
        """YouTube 연동 상태에 따라 계정 버튼 tooltip을 갱신한다."""
        tip = "YouTube 연결됨 — 설정에서 관리" if is_connected else "YouTube 미연결 — 설정에서 연동"
        self._account_btn.setToolTip(tip)

    def show_update_badge(self, visible: bool) -> None:
        self._settings_btn.set_badge(visible)

    def _navigate(self, page: int) -> None:
        if page == _PAGE_SETTINGS \
                and getattr(self, "_settings_btn", None) \
                and self._settings_btn._show_badge:
            self._settings_btn.set_badge(False)
            self.settings_navigated_with_badge.emit()
        self._stack.setCurrentIndex(page)
        page_to_btn = {
            _PAGE_LIBRARY:  0,
            _PAGE_DOWNLOAD: 1,
            _PAGE_MONITOR:  2,
            _PAGE_STATS:    3,
            _PAGE_SETTINGS: 4,
        }
        for i, btn in enumerate(self._buttons):
            btn.setChecked(i == page_to_btn.get(page, 0))

    def _apply_theme(self, tokens: ThemeTokens) -> None:
        self.setStyleSheet(f"""
            _SideBar, QWidget#sidebar {{
                background-color: {tokens.bg_surface};
                border-right: 1px solid {tokens.border};
            }}
        """)
        self.setObjectName("sidebar")
        self.setAutoFillBackground(True)


# ---------------------------------------------------------------------------
# 경로 표시 바 (브레드크럼)
# ---------------------------------------------------------------------------

class _PathBar(QWidget):
    """영상 목록 상단 현재 위치 경로 표시 바."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(32)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(6)

        self._path_lbl = QLabel("라이브러리")
        self._path_lbl.setStyleSheet("font-size: 11px;")
        layout.addWidget(self._path_lbl)
        layout.addStretch()

        self._apply_theme(ThemeManager.instance().current())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)

    def set_path(self, path: str) -> None:
        self._path_lbl.setText(path)

    def _apply_theme(self, tokens: ThemeTokens) -> None:
        self.setObjectName("pathbar")
        self.setAutoFillBackground(True)
        self.setStyleSheet(f"""
            #pathbar {{
                background-color: {tokens.bg_surface};
                border-bottom: 1px solid {tokens.border};
            }}
        """)
        self._path_lbl.setStyleSheet(f"font-size:11px; color:{tokens.text_secondary};")


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

        self._msg = QLabel("다운로드 없음")
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
        )
        layout.addWidget(self._library_panel, 1)

        self._dl_bar = _DownloadBar(stack, download_vm)
        layout.addWidget(self._dl_bar)

    def library_panel(self) -> LibraryPanel:
        return self._library_panel


# ---------------------------------------------------------------------------
# 메인 윈도우
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(
        self,
        library_vm: LibraryViewModel,
        download_vm: DownloadViewModel,
        clip_vm: ClipViewModel,
        monitoring_vm: MonitoringViewModel,
        stats_handler=None,
        playlist_vm: PlaylistViewModel | None = None,
        feed_vm: FeedViewModel | None = None,
        auth_service: YouTubeAuthService | None = None,
        yt_oauth=None,   # YouTubeOAuthAdapter | None
    ) -> None:
        super().__init__()
        QPixmapCache.setCacheLimit(PIXMAP_CACHE_LIMIT_KB)
        self._library_vm = library_vm
        self._download_vm = download_vm
        self._clip_vm = clip_vm
        self._monitoring_vm = monitoring_vm
        self._stats_handler = stats_handler
        self._playlist_vm = playlist_vm
        self._feed_vm = feed_vm
        self._yt_oauth = yt_oauth
        self._auth_service = auth_service or YouTubeAuthService()
        self._update_controller = None

        self.setWindowTitle("YouTube Content Manager")
        self.setMinimumSize(1024, 680)

        # 테마 초기화 (저장된 테마 로드)
        ThemeManager.instance().initialize(THEME)

        self._setup_ui()
        self._setup_signals()
        self._setup_clipboard_monitoring()

    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 콘텐츠 스택
        self._stack = QStackedWidget()

        # 페이지 0: 라이브러리 (구독 채널 트리·피드 그리드 포함 — feed_vm 주입)
        self._library_page = _LibraryPage(
            self._library_vm,
            self._download_vm,
            self._clip_vm,
            self._stack,
            playlist_vm=self._playlist_vm,
            feed_vm=self._feed_vm,
            monitoring_vm=self._monitoring_vm,
        )
        self._stack.addWidget(self._library_page)                  # 0

        # 페이지 1: 다운로드
        self._download_panel = DownloadPanel(
            self._download_vm,
            thumb_provider=self._library_vm.find_thumbnail_by_url,
            title_provider=self._library_vm.find_title_by_url,
        )
        self._download_panel.video_open_requested.connect(self._on_download_video_open)
        self._download_panel.retry_requested.connect(self._on_retry_download)
        self._stack.addWidget(self._download_panel)                # 1

        # 페이지 2: 채널 모니터링
        self._stack.addWidget(MonitoringPanel(self._monitoring_vm))  # 2

        # 페이지 3: 통계 대시보드
        if self._stats_handler is not None:
            self._stack.addWidget(StatsPanel(self._stats_handler))   # 3
        else:
            from PyQt6.QtWidgets import QLabel  # noqa: PLC0415
            stub = QWidget()
            QVBoxLayout(stub).addWidget(QLabel("통계 기능 준비 중"))
            self._stack.addWidget(stub)                              # 3

        # (구독 피드는 별도 페이지를 두지 않고 라이브러리 좌측 트리의
        #  "구독" 노드로 통합됨 — _LibraryPage에 feed_vm을 주입한다.)

        # 페이지 4: 설정 (library_vm.tags 를 lazy 하게 공급)
        self._settings_panel = SettingsPanel(
            get_tags_fn=lambda: self._library_vm.tags,
            yt_oauth=self._yt_oauth,
        )
        self._stack.addWidget(self._settings_panel)                  # 4

        # 사이드바 (스택 생성 후)
        self._sidebar = _SideBar(self._stack)

        root.addWidget(self._sidebar)
        root.addWidget(self._stack, 1)

        # 상태 표시줄
        self.setStatusBar(QStatusBar())

        # 영상 등록 중 마퀴 진행 바 (상태바 우측 고정)
        self._add_progress = QProgressBar()
        self._add_progress.setRange(0, 0)  # 마퀴(indeterminate) 모드
        self._add_progress.setTextVisible(False)  # 얇은 바라 퍼센트 텍스트 숨김
        self._add_progress.setFixedWidth(120)
        self._add_progress.setFixedHeight(14)
        self._add_progress.hide()
        self.statusBar().addPermanentWidget(self._add_progress)

    def _setup_signals(self) -> None:
        lp = self._library_page.library_panel()

        self._pending_url: str = ""

        # 라이브러리 VM 이벤트
        self._library_vm.error_occurred.connect(self._show_library_error)
        self._library_vm.video_add_started.connect(self._on_add_started)
        self._library_vm.video_add_finished.connect(self._on_add_finished)

        # 다운로드
        lp.download_requested.connect(
            lambda url, title, s: self._download_vm.start_download(url, title, s)
        )
        self._download_vm.error_occurred.connect(self._show_error)
        self._clip_vm.error_occurred.connect(self._show_error)
        self._monitoring_vm.error_occurred.connect(self._show_error)

        # 숨김 태그 변경 → 라이브러리 패널 즉시 갱신
        self._settings_panel.hidden_tags_changed.connect(
            lp._on_hidden_tags_changed
        )

        # 노드 동시 로딩 수 변경 → 피드·로컬 양쪽 ViewModel에 즉시 반영
        if self._feed_vm is not None:
            self._settings_panel.feed_workers_changed.connect(
                self._feed_vm.set_max_workers
            )
        if self._library_vm is not None:
            self._settings_panel.feed_workers_changed.connect(
                self._library_vm.set_max_workers
            )

        # 구독 피드는 라이브러리 패널 좌측 트리의 "구독" 노드로 통합됨.
        # 피드 카드 신호(카테고리/재생목록 추가·다운로드)는 LibraryPanel 내부에서
        # 기존 핸들러에 연결되므로 여기서 별도 배선하지 않는다.

    def _setup_clipboard_monitoring(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.dataChanged.connect(self._on_clipboard_changed)

    # ------------------------------------------------------------------
    def _on_add_started(self, url: str) -> None:
        self._pending_url = url
        short = url.split("/")[2] if url.count("/") >= 2 else url[:40]
        self.statusBar().showMessage(f"등록 중: {short}", 0)
        self._add_progress.show()

    def _on_add_finished(self, url: str) -> None:
        self._pending_url = ""
        self._add_progress.hide()
        short = url.split("/")[2] if url.count("/") >= 2 else url[:40]
        self.statusBar().showMessage(f"등록 완료: {short}", 5000)

    # ------------------------------------------------------------------
    def _on_clipboard_changed(self) -> None:
        pass  # URL 바 제거 후 클립보드 자동 감지 비활성화

    def _show_error(self, msg: str) -> None:
        self.statusBar().showMessage(f"오류: {msg}", 6000)

    def _show_library_error(self, msg: str) -> None:
        self._add_progress.hide()
        url = self._pending_url
        self._pending_url = ""
        short = url.split("/")[2] if url.count("/") >= 2 else url[:40]
        detail = f"{short} 등록 실패: {msg}" if url else msg
        self.statusBar().showMessage(f"오류: {detail}", 6000)

        dlg = QMessageBox(QMessageBox.Icon.Warning, "영상 등록 오류", detail, parent=self)
        dlg.addButton(QMessageBox.StandardButton.Ok)
        if url:
            copy_btn = dlg.addButton("URL 복사", QMessageBox.ButtonRole.ActionRole)
            copy_btn.clicked.connect(
                lambda: QApplication.clipboard().setText(url)
            )
        dlg.exec()

    # ------------------------------------------------------------------
    def set_update_controller(self, controller) -> None:
        """composition root에서 창 생성 후 주입. 시작 시 업데이트 체크를 예약한다."""
        self._update_controller = controller
        QTimer.singleShot(2000, controller.check_silently)
        if hasattr(self._settings_panel, "check_update_requested"):
            self._settings_panel.check_update_requested.connect(
                controller.check_interactively
            )
        if hasattr(self._settings_panel, "install_update_requested"):
            self._settings_panel.install_update_requested.connect(
                controller._show_update_dialog
            )
        controller.update_notification.connect(self._on_update_notification)
        self._sidebar.settings_navigated_with_badge.connect(
            self._settings_panel.scroll_and_flash_update_section
        )

    def _on_update_notification(self, dto) -> None:
        self._sidebar.show_update_badge(True)
        self._settings_panel.set_pending_update(dto)

    def _on_download_video_open(self, url: str) -> None:
        """다운로드 카드 클릭 → 라이브러리 영상 상세화면 오픈."""
        video_id = self._library_vm.find_video_id_by_url(url)
        if video_id is None:
            return
        self._sidebar._navigate(_PAGE_LIBRARY)
        self._library_page.library_panel()._open_detail(video_id)

    def _on_retry_download(self, job: object) -> None:
        """실패 카드 클릭 → 동일 URL 재다운로드."""
        try:
            self._download_vm.start_download(job.url, job.title)
        except Exception:
            logger.exception("재다운로드 실패: %s", getattr(job, "url", "?"))

    def closeEvent(self, event: QCloseEvent) -> None:
        # 백그라운드 QThread 워커를 정리한 뒤 종료한다.
        for vm in (self._download_vm, self._library_vm, self._feed_vm,
                   self._update_controller):
            if vm is None:
                continue
            shutdown = getattr(vm, "shutdown", None)
            if callable(shutdown):
                try:
                    shutdown()
                except Exception:
                    logger.exception("뷰모델 shutdown 실패")
        event.accept()
