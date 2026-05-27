"""설정 패널 — 인라인 QWidget (다이얼로그 아님).

사이드바 ⚙ 아이콘 클릭 시 메인 콘텐츠 스택에 표시된다.
테마 프리셋 선택 + 저장 경로 표시.
"""
from __future__ import annotations

import dataclasses

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.themes.manager import ThemeManager
from gui.themes.tokens import PRESETS, ThemeTokens


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

        # 이름 레이블
        self._name_lbl = QLabel(tokens.display_name)
        self._name_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._name_lbl.setStyleSheet(
            f"font-size: 11px; font-weight: 500; color: {tokens.text_secondary};"
        )
        layout.addWidget(self._name_lbl)

    # ------------------------------------------------------------------
    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._preview.set_selected(selected)
        tok = self._tokens
        color = tok.text_primary if selected else tok.text_secondary
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


class SettingsPanel(QWidget):
    """설정 패널 (인라인, QDialog 아님)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme_cards: dict[str, _ThemeCard] = {}
        self._build_ui()
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)
        # 현재 테마 반영
        self._on_theme_changed(ThemeManager.instance().current())

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(0)

        # 헤더
        header = QLabel("설정")
        header.setStyleSheet("font-size: 16px; font-weight: 600; margin-bottom: 24px;")
        layout.addWidget(header)
        layout.addSpacing(20)

        # ── 테마 섹션 ──
        theme_label = QLabel("테마")
        theme_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            "text-transform: uppercase; color: #555; margin-bottom: 12px;"
        )
        layout.addWidget(theme_label)
        layout.addSpacing(10)

        cards_row = QHBoxLayout()
        cards_row.setContentsMargins(0, 0, 0, 0)
        cards_row.setSpacing(16)

        for name, tokens in PRESETS.items():
            card = _ThemeCard(tokens)
            self._theme_cards[name] = card
            cards_row.addWidget(card)
        cards_row.addStretch()

        layout.addLayout(cards_row)
        layout.addSpacing(8)

        hint = QLabel("클릭하면 즉시 적용됩니다. 재시작 후에도 유지됩니다.")
        hint.setStyleSheet("font-size: 10px; color: #555; margin-top: 4px;")
        layout.addWidget(hint)
        layout.addSpacing(28)

        # ── 구분선 ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #1a1a1a;")
        layout.addWidget(sep)
        layout.addSpacing(24)

        # ── 저장 경로 섹션 ──
        path_label = QLabel("저장 경로")
        path_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            "text-transform: uppercase; color: #555; margin-bottom: 12px;"
        )
        layout.addWidget(path_label)
        layout.addSpacing(10)

        try:
            from config import settings as s
            paths = {
                "데이터베이스": str(s.DATABASE_PATH),
                "다운로드 폴더": str(s.DOWNLOAD_DIR),
                "썸네일 폴더": str(s.THUMBNAIL_DIR),
                "로그 폴더": str(s.LOG_DIR),
            }
        except Exception:
            paths = {}

        for label_text, path_text in paths.items():
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(12)
            lbl = QLabel(label_text)
            lbl.setFixedWidth(90)
            lbl.setStyleSheet("font-size: 11px; color: #555;")
            val = QLabel(path_text)
            val.setStyleSheet(
                "font-size: 10px; color: #444; font-family: monospace;"
            )
            val.setWordWrap(False)
            val.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            row.addWidget(lbl)
            row.addWidget(val, 1)
            layout.addLayout(row)
            layout.addSpacing(6)

        note = QLabel("경로를 변경하려면 data/config.yaml 을 편집하세요.")
        note.setStyleSheet("font-size: 10px; color: #444; margin-top: 8px;")
        layout.addWidget(note)

        layout.addStretch()

    # ------------------------------------------------------------------
    def _on_theme_changed(self, tokens: ThemeTokens) -> None:
        """테마 변경 시 선택 상태를 업데이트한다."""
        for name, card in self._theme_cards.items():
            card.set_selected(name == tokens.name)
