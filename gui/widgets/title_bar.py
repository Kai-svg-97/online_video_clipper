"""커스텀 타이틀바 — 창 제목·캡션 버튼, 그리고 좌측 배지 슬롯.

OS가 그리는 제목 표시줄에는 위젯을 넣을 수 없다. 업데이트 배지를 "좌측 상단"에 두려면
제목 표시줄 자체를 우리가 그려야 하고, 그러면 최소화·최대화·닫기도 우리 몫이 된다.

이 파일은 **순수 Qt이고 플랫폼을 가리지 않는다.** 네이티브 프레임을 지우는 일
(`WM_NCCALCSIZE` 등)은 `gui/frameless/`가 맡는다 — 여기서 분리해 둔 덕분에 네이티브
코드 없이도 이 위젯만 먼저 띄워 볼 수 있고, 프레임리스가 걸리지 않는 환경에서는
그냥 숨기면 된다.

## 드래그를 직접 구현하지 않는다

창 이동·스냅·복원 추종은 `hit_test()`가 `HTCAPTION`을 돌려주면 OS가 알아서 한다.
그래서 **비대화형 자식(제목 라벨·구분선)에는 `WA_TransparentForMouseEvents`를 켠다** —
안 켜면 `childAt()`이 그 라벨을 돌려주어 `HTCLIENT`이 되고, 글자 위에서는 창을 끌 수
없게 된다(같은 기법이 `gui/widgets/player/surfaces.py`에 이미 쓰인다).
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from gui.themes.manager import ThemeManager
from gui.themes.tokens import ThemeTokens

logger = logging.getLogger(__name__)

# Win32 히트테스트 코드. 여기서 상수로 두는 이유는 `gui/frameless/`를 임포트하지
# 않기 위해서다 — 이 위젯은 플랫폼 코드에 의존하지 않는다.
HTCLIENT = 1
HTCAPTION = 2

TITLE_BAR_HEIGHT = 36
_BTN_W, _BTN_H = 46, 36

# 닫기 버튼 호버색만 테마 토큰을 쓰지 않는다 — Windows 표준 닫기 호버색이고,
# 흰 글리프 대비 5.9:1을 보장한다. `sem("danger")`는 어두운 테마에서 #f87171이라
# 흰 글리프가 2.3:1로 묻힌다(색상 규칙의 '의미·브랜드 색' 예외).
_CLOSE_HOVER_BG = "#C42B1C"
_CLOSE_HOVER_FG = "#ffffff"


class _CaptionButton(QWidget):
    """최소화/최대화/닫기 버튼 — 글리프를 QPainter로 직접 긋는다.

    SVG 아이콘을 16px로 래스터화하면 150% DPI에서 흐려진다. 선 3개짜리 도형이라
    직접 그리는 편이 코드도 짧고 배율에 자유롭다.
    """

    def __init__(self, glyph: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._glyph = glyph          # "min" | "max" | "restore" | "close"
        self._hover = False
        self._on_click = None
        self.setFixedSize(_BTN_W, _BTN_H)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        tokens = ThemeManager.instance().current()
        self._fg = QColor(tokens.text_secondary)
        self._fg_hover = QColor(tokens.text_primary)
        self._hover_bg = QColor(tokens.bg_overlay)
        self._apply_theme(tokens)
        ThemeManager.instance().theme_changed.connect(self._apply_theme)

    # ── 공개 API ──────────────────────────────────────────────────
    def set_glyph(self, glyph: str) -> None:
        self._glyph = glyph
        self.update()

    def set_click_handler(self, fn) -> None:
        """클릭 콜백. 시그널 대신 콜백을 쓰는 이유는 수신자가 모두 창 자신이라서다."""
        self._on_click = fn

    # ── 이벤트 ────────────────────────────────────────────────────
    def enterEvent(self, event) -> None:  # type: ignore[override]
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            if self._on_click is not None:
                self._on_click()
        super().mouseReleaseEvent(event)

    def _apply_theme(self, tokens: ThemeTokens) -> None:
        self._fg = QColor(tokens.text_secondary)
        self._fg_hover = QColor(tokens.text_primary)
        self._hover_bg = QColor(tokens.bg_overlay)
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        # 페인팅 중 예외는 PyQt가 프로세스 종료로 처리한다(0xC0000409) — 로그조차
        # 남지 않는다. 계산은 전부 여기 안에서 끝나는 산술이라 실패할 여지가 없다.
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            closing = self._glyph == "close"
            if self._hover:
                p.fillRect(
                    self.rect(),
                    QColor(_CLOSE_HOVER_BG) if closing else self._hover_bg,
                )
            if self._hover:
                fg = QColor(_CLOSE_HOVER_FG) if closing else self._fg_hover
            else:
                fg = self._fg
            p.setPen(QPen(fg, 1))
            self._draw_glyph(p)
        finally:
            p.end()

    def _draw_glyph(self, p: QPainter) -> None:
        cx, cy = self.width() // 2, self.height() // 2
        h = 5   # 글리프 반폭 — 10x10 상자에 들어간다
        if self._glyph == "min":
            p.drawLine(cx - h, cy, cx + h, cy)
        elif self._glyph == "max":
            p.drawRect(QRect(cx - h, cy - h, h * 2, h * 2))
        elif self._glyph == "restore":
            # 앞 사각형 + 뒤로 살짝 밀린 사각형(윈도우 표준 복원 글리프)
            p.drawRect(QRect(cx - h, cy - h + 2, h * 2 - 2, h * 2 - 2))
            p.drawLine(cx - h + 2, cy - h, cx + h, cy - h)
            p.drawLine(cx + h, cy - h, cx + h, cy + h - 2)
        elif self._glyph == "close":
            p.drawLine(cx - h, cy - h, cx + h, cy + h)
            p.drawLine(cx + h, cy - h, cx - h, cy + h)


class TitleBar(QWidget):
    """창 상단 띠 — [배지 슬롯] 제목 ......... ─ □ ×"""

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._window = window
        self.setFixedHeight(TITLE_BAR_HEIGHT)

        # paintEvent가 _apply_theme보다 먼저 불릴 수 있어 기본값을 먼저 잡는다
        # (_SideBar가 같은 이유로 같은 순서를 쓴다).
        tokens = ThemeManager.instance().current()
        self._bg = QColor(tokens.bg_surface)
        self._border = QColor(tokens.border)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 0, 0)
        layout.setSpacing(8)

        # ① 배지 슬롯 — 외부(업데이트 배지)가 위젯을 주입한다. 비어 있으면 폭 0.
        self._slot = QWidget(self)
        self._slot_layout = QHBoxLayout(self._slot)
        self._slot_layout.setContentsMargins(0, 0, 0, 0)
        self._slot_layout.setSpacing(4)
        layout.addWidget(self._slot)

        # ② 제목 — 마우스 투명이어야 글자 위에서도 창을 끌 수 있다.
        self._title = QLabel(window.windowTitle(), self)
        self._title.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        layout.addWidget(self._title)
        layout.addStretch(1)

        # ③ 캡션 버튼
        self._btn_min = _CaptionButton("min", self)
        self._btn_max = _CaptionButton("max", self)
        self._btn_close = _CaptionButton("close", self)
        self._btn_min.set_click_handler(self._on_minimize)
        self._btn_max.set_click_handler(self._on_toggle_max)
        self._btn_close.set_click_handler(self._on_close)
        for btn in (self._btn_min, self._btn_max, self._btn_close):
            layout.addWidget(btn)

        window.windowTitleChanged.connect(self._title.setText)
        self._apply_theme(tokens)
        ThemeManager.instance().theme_changed.connect(self._apply_theme)

    # ── 공개 API ──────────────────────────────────────────────────
    def set_leading_widget(self, widget: QWidget) -> None:
        """좌측 슬롯에 위젯을 넣는다(업데이트 배지 등).

        주입하는 위젯이 **클릭을 받지 않는다면** 호출 측에서
        `WA_TransparentForMouseEvents`를 켠다 — 안 켜면 그 위에서 창을 끌 수 없다.
        """
        self._slot_layout.addWidget(widget)

    def set_maximized(self, maximized: bool) -> None:
        """최대화 글리프를 맞춘다. Aero Snap·Win+↑로도 상태가 바뀌므로 창의
        `changeEvent`에서 불러 줘야 한다(버튼을 거치지 않는 경로가 있다)."""
        self._btn_max.set_glyph("restore" if maximized else "max")

    def hit_test(self, window_pos: QPoint) -> int:
        """이 좌표가 캡션(드래그 가능)인가 — `HTCAPTION` 또는 `HTCLIENT`.

        `window_pos`는 **창 기준 논리 좌표**다. 버튼·배지 위에서는 `HTCLIENT`을
        돌려줘야 Qt가 평소대로 클릭을 받는다.
        """
        local = self.mapFrom(self._window, window_pos)
        if not self.rect().contains(local):
            return HTCLIENT
        child = self.childAt(local)
        # 제목 라벨은 마우스 투명이라 childAt이 self(또는 슬롯 컨테이너)를 돌려준다.
        if child is None or child is self or child is self._slot:
            return HTCAPTION
        return HTCLIENT

    # ── 내부 ──────────────────────────────────────────────────────
    def _on_minimize(self) -> None:
        self._window.showMinimized()

    def _on_toggle_max(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def _on_close(self) -> None:
        self._window.close()

    def _apply_theme(self, tokens: ThemeTokens) -> None:
        self._bg = QColor(tokens.bg_surface)
        self._border = QColor(tokens.border)
        # `background: transparent`가 없으면 전역 QSS의 `QWidget { background-color:
        # bg_base }`가 라벨 뒤를 칠해, 띠(bg_surface) 위에 색이 다른 상자가 뜬다.
        self._title.setStyleSheet(
            f"background: transparent; font-size: 12px; color: {tokens.text_secondary};"
        )
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        # 배경은 QSS가 아니라 여기서 칠한다 — 앱 레벨 QSS의
        # `QWidget { background-color }`가 위젯 스타일시트를 덮어쓴다
        # (`gui/main_window.py`의 _SideBar._apply_theme 실측 주석과 같은 이유).
        p = QPainter(self)
        try:
            p.fillRect(self.rect(), self._bg)
            p.setPen(QPen(self._border, 1))
            y = self.height() - 1
            p.drawLine(0, y, self.width(), y)
        finally:
            p.end()
