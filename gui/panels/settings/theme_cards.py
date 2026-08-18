"""테마 프리셋 카드와 미리보기 — 색 토큰을 실제로 칠해 보여 준다.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.themes.manager import ThemeManager
from gui.themes.tokens import ThemeTokens

from gui.panels.settings.helpers import _t

logger = logging.getLogger(__name__)


class _ThemeCard(QWidget):
    """테마 프리셋 선택 카드 — 미니 창 목업 + 이름."""

    _CARD_W = 80
    _CARD_H = 56

    def __init__(self, tokens: ThemeTokens, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._selected = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedWidth(self._CARD_W + 16)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 미리보기 캔버스
        self._preview = _ThemePreview(tokens)
        self._preview.setFixedSize(self._CARD_W, self._CARD_H)
        layout.addWidget(self._preview, alignment=Qt.AlignmentFlag.AlignHCenter)

        # 이름 레이블 — 카드가 놓인 배경은 "현재" 테마이므로 미리보기 테마 색이 아니라
        # 현재 테마 색으로 칠해야 한다(어두운 프리셋 이름이 밝은 배경에서 흐려지지 않게).
        self._name_lbl = QLabel(tokens.display_name)
        self._name_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.set_selected(False)
        layout.addWidget(self._name_lbl)

    # ------------------------------------------------------------------
    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._preview.set_selected(selected)
        cur = _t()
        color = cur.accent if selected else cur.text_secondary
        weight = "600" if selected else "500"
        self._name_lbl.setStyleSheet(
            f"font-size: 11px; font-weight: {weight}; color: {color};"
        )

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        ThemeManager.instance().apply(self._tokens.name)

class _ThemePreview(QWidget):
    """테마 미리보기 — QPainter로 미니 창을 그린다."""

    def __init__(self, tokens: ThemeTokens, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._selected = False

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        tok = self._tokens
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = 5  # corner radius

        # 외곽 테두리 (선택 시 액센트 색상)
        border_color = tok.selected_border if self._selected else tok.border_muted
        border_w = 2 if self._selected else 1

        # 배경
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, r, r)
        p.fillPath(path, QColor(tok.bg_base))

        # 테두리
        pen = p.pen()
        pen.setColor(QColor(border_color))
        pen.setWidth(border_w)
        p.setPen(pen)
        p.drawRoundedRect(border_w // 2, border_w // 2,
                          w - border_w, h - border_w, r, r)

        # 사이드바 (좌측 10px)
        sb_w = 10
        p.fillRect(border_w, border_w, sb_w, h - border_w * 2,
                   QColor(tok.bg_surface))

        # 사이드바 아이콘 점
        dot_x = border_w + sb_w // 2 - 2
        p.fillRect(dot_x, 8, 4, 4, QColor(tok.accent))
        p.fillRect(dot_x, 16, 4, 4, QColor(tok.bg_overlay))
        p.fillRect(dot_x, 24, 4, 4, QColor(tok.bg_overlay))

        # 콘텐츠 영역 카드들
        cx = border_w + sb_w + 4
        cw = (w - cx - border_w - 4) // 3 - 2
        ch = (h - border_w * 2 - 12) // 2 - 1
        for col in range(3):
            card_x = cx + col * (cw + 2)
            p.fillRect(card_x, border_w + 8, cw, ch, QColor(tok.bg_elevated))

        # 상단 바 (URL 바)
        p.fillRect(border_w + sb_w, border_w, w - border_w - sb_w - border_w,
                   7, QColor(tok.bg_surface))

        p.end()
