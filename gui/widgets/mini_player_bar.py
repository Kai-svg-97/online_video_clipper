"""지금 재생 중 미니바 — 상세 화면을 떠나도 재생을 이어 가는 하단 띠.

배경: 상세 화면을 벗어나면 `stop_player()`가 재생을 끊었다. 노래를 듣다가 다른
카테고리를 둘러보려면 재생이 멈췄고, 돌아와도 처음부터였다. 이제 **재생 중일 때만**
플레이어를 살려 둔 채 화면만 목록으로 돌아가고, 무엇이 재생 중인지·어디쯤인지를
이 띠가 보여 준다.

미니바는 메인 창 맨 아래(상태바 위)에 살아서 **다른 페이지(다운로드·설정)로 가도
보인다** — 플레이어 자체는 라이브러리 상세 위젯 안에 그대로 있고, 이 띠는 그 상태를
비추고 조작만 되돌려 보낸다(재생 주체를 옮기지 않는다).

띠를 클릭하면 보던 상세 화면으로 그대로 돌아간다 — 위젯을 언로드하지 않았으므로
다시 불러오지 않고 화면만 바꾸면 되며, 그래서 재생이 끊기지 않는다.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from gui.themes.manager import ThemeManager

logger = logging.getLogger(__name__)

_BAR_H = 52
_THUMB_W, _THUMB_H = 64, 36


def _fmt_ms(ms: int) -> str:
    """0:31 / 1:02:03 — 시간이 0이면 시 단위를 붙이지 않는다."""
    total = max(0, int(ms)) // 1000
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class _ClickableArea(QWidget):
    """썸네일·제목 묶음 — 클릭하면 그 영상 상세로 돌아간다."""

    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class MiniPlayerBar(QWidget):
    """지금 재생 중인 영상을 보여 주는 하단 띠.

    상태는 바깥(라이브러리 패널)이 밀어 넣고, 조작은 신호로 되돌려 보낸다 —
    이 위젯은 플레이어를 직접 알지 못한다(그래야 어느 화면에 있든 같은 띠를 쓴다).
    """

    play_toggled    = pyqtSignal()
    next_requested  = pyqtSignal()
    seek_requested  = pyqtSignal(int)    # ms
    open_requested  = pyqtSignal()       # 상세 화면으로 복귀
    close_requested = pyqtSignal()       # 재생 정지 + 띠 닫기

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._duration_ms = 0
        self._seeking = False
        self.setFixedHeight(_BAR_H)
        self._build_ui()
        self._apply_theme(ThemeManager.instance().current())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)
        self.hide()

    # ── 구성 ────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(10, 6, 10, 6)
        root.setSpacing(10)

        # 썸네일 + 제목(클릭 → 상세 복귀)
        self._click_area = _ClickableArea()
        click_row = QHBoxLayout(self._click_area)
        click_row.setContentsMargins(0, 0, 0, 0)
        click_row.setSpacing(8)

        self._thumb = QLabel()
        self._thumb.setFixedSize(_THUMB_W, _THUMB_H)
        self._thumb.setScaledContents(True)
        click_row.addWidget(self._thumb)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)
        self._title_lbl = QLabel()
        tf = QFont()
        tf.setPointSize(9)
        tf.setWeight(QFont.Weight.DemiBold)
        self._title_lbl.setFont(tf)
        self._sub_lbl = QLabel()
        sf = QFont()
        sf.setPointSize(8)
        self._sub_lbl.setFont(sf)
        text_col.addWidget(self._title_lbl)
        text_col.addWidget(self._sub_lbl)
        click_row.addLayout(text_col, 1)

        self._click_area.clicked.connect(self.open_requested)
        self._click_area.setSizePolicy(QSizePolicy.Policy.Preferred,
                                       QSizePolicy.Policy.Preferred)
        self._click_area.setMinimumWidth(180)
        self._click_area.setToolTip("클릭하면 보던 화면으로 돌아갑니다")
        root.addWidget(self._click_area)

        self._btn_play = self._tool_button("⏸", "재생/일시정지", self.play_toggled.emit)
        root.addWidget(self._btn_play)
        self._btn_next = self._tool_button("⏭", "다음 곡", self.next_requested.emit)
        root.addWidget(self._btn_next)

        self._pos_lbl = QLabel("0:00")
        self._pos_lbl.setFont(sf)
        root.addWidget(self._pos_lbl)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, 0)
        self._slider.sliderPressed.connect(self._on_slider_pressed)
        self._slider.sliderReleased.connect(self._on_slider_released)
        root.addWidget(self._slider, 1)

        self._dur_lbl = QLabel("0:00")
        self._dur_lbl.setFont(sf)
        root.addWidget(self._dur_lbl)

        self._btn_close = self._tool_button("✕", "재생을 멈추고 닫기",
                                            self.close_requested.emit)
        root.addWidget(self._btn_close)

    def _tool_button(self, text: str, tip: str, slot) -> QToolButton:
        btn = QToolButton()
        btn.setText(text)
        btn.setToolTip(tip)
        btn.setFixedSize(28, 28)
        btn.setAutoRaise(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(slot)
        return btn

    def _apply_theme(self, tokens) -> None:
        self.setStyleSheet(
            f"MiniPlayerBar {{ background: {tokens.bg_surface};"
            f" border-top: 1px solid {tokens.border}; }}"
        )
        self._title_lbl.setStyleSheet(f"color: {tokens.text_primary}; border: none;")
        self._sub_lbl.setStyleSheet(f"color: {tokens.text_muted}; border: none;")
        for lbl in (self._pos_lbl, self._dur_lbl):
            lbl.setStyleSheet(f"color: {tokens.text_secondary}; border: none;")
        for btn in (self._btn_play, self._btn_next, self._btn_close):
            btn.setStyleSheet(
                f"QToolButton {{ color: {tokens.text_primary}; border: none;"
                " font-size: 13px; }"
                f"QToolButton:hover {{ background: {tokens.bg_elevated};"
                " border-radius: 6px; }"
                f"QToolButton:disabled {{ color: {tokens.text_muted}; }}"
            )
        self._thumb.setStyleSheet(
            f"background: {tokens.bg_base}; border: 1px solid {tokens.border};"
            " border-radius: 4px;"
        )
        self._slider.setStyleSheet(
            "QSlider::groove:horizontal { height: 4px; border-radius: 2px;"
            f" background: {tokens.border}; }}"
            "QSlider::sub-page:horizontal { height: 4px; border-radius: 2px;"
            f" background: {tokens.accent}; }}"
            "QSlider::handle:horizontal { width: 10px; margin: -4px 0;"
            f" border-radius: 5px; background: {tokens.accent}; }}"
        )

    # ── 상태 주입 ────────────────────────────────────────────────────────
    def set_track(
        self,
        title: str,
        subtitle: str = "",
        poster: QPixmap | None = None,
        has_next: bool = False,
    ) -> None:
        self._title_lbl.setText(title or "재생 중")
        self._sub_lbl.setText(subtitle)
        if poster is not None and not poster.isNull():
            self._thumb.setPixmap(poster)
        else:
            self._thumb.clear()
        self._btn_next.setEnabled(has_next)
        self._btn_next.setVisible(has_next)

    def set_playing(self, playing: bool) -> None:
        self._btn_play.setText("⏸" if playing else "▶")

    def set_duration(self, ms: int) -> None:
        self._duration_ms = max(0, int(ms))
        self._slider.setRange(0, self._duration_ms)
        self._dur_lbl.setText(_fmt_ms(self._duration_ms))

    def set_position(self, ms: int) -> None:
        # 사용자가 손잡이를 잡고 있는 동안은 건드리지 않는다(끌던 위치가 튄다).
        if self._seeking:
            return
        self._slider.setValue(max(0, int(ms)))
        self._pos_lbl.setText(_fmt_ms(ms))

    # ── 조작 ────────────────────────────────────────────────────────────
    def _on_slider_pressed(self) -> None:
        self._seeking = True

    def _on_slider_released(self) -> None:
        self._seeking = False
        self.seek_requested.emit(int(self._slider.value()))
