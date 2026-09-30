"""48px 아이콘 사이드바와 그 내비게이션 버튼."""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QPushButton, QStackedWidget, QVBoxLayout, QWidget

from gui.shell.pages import (
    _PAGE_DOWNLOAD,
    _PAGE_LIBRARY,
    _PAGE_MONITOR,
    _PAGE_SETTINGS,
    _PAGE_STATS,
)
from gui.text import tr
from gui.themes.colors import sem
from gui.themes.manager import ThemeManager
from gui.themes.tokens import ThemeTokens

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
            # 주의를 끄는 알림 점 — 의미 색(danger)이 테마 밝기에 맞는 톤을 준다.
            p.setBrush(QColor(sem("danger")))
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
        # paintEvent가 _apply_theme보다 먼저 불릴 수 있어 기본값을 먼저 잡는다.
        _tok = ThemeManager.instance().current()
        self._bg = QColor(_tok.bg_surface)
        self._border = QColor(_tok.border)
        self.setFixedWidth(48)
        self._build_ui()
        self._apply_theme(ThemeManager.instance().current())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 12)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # 주 내비게이션 버튼
        nav_defs = [
            (_SVG_LIBRARY,  tr("라이브러리"),        _PAGE_LIBRARY),
            (_SVG_DOWNLOAD, tr("다운로드"),          _PAGE_DOWNLOAD),
            (_SVG_MONITOR,  tr("채널 모니터링"),      _PAGE_MONITOR),
            (_SVG_STATS,    tr("통계"),              _PAGE_STATS),
        ]
        for svg, tip, page in nav_defs:
            btn = _NavButton(svg, tip)
            btn.clicked.connect(lambda checked, p=page: self._navigate(p))
            layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignHCenter)
            self._buttons.append(btn)

        layout.addStretch()

        # 설정 버튼 (하단)
        self._settings_btn = _NavButton(_SVG_SETTINGS, tr("설정"))
        self._settings_btn.clicked.connect(lambda: self._navigate(_PAGE_SETTINGS))
        layout.addWidget(self._settings_btn, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._buttons.append(self._settings_btn)

        # 첫 번째(라이브러리) 선택
        self._buttons[0].setChecked(True)

    def show_update_badge(self, visible: bool) -> None:
        self._settings_btn.set_badge(visible)

    def set_settings_tooltip(self, text: str) -> None:
        self._settings_btn.setToolTip(text)

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
        # 배경은 paintEvent에서 직접 칠한다. 앱 레벨 QSS의 `QWidget { background-color }`가
        # 위젯 레벨 스타일시트(ID 선택자 포함)를 덮어써서 bg_surface가 적용되지 않았다
        # (slate에서는 base/surface 차이가 3단위라 눈에 안 띄어 방치돼 있었음).
        self._bg = QColor(tokens.bg_surface)
        self._border = QColor(tokens.border)
        self.setObjectName("sidebar")
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._bg)
        painter.setPen(QPen(self._border, 1))
        x = self.width() - 1
        painter.drawLine(x, 0, x, self.height())
        painter.end()
        super().paintEvent(event)
