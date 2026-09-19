"""업데이트 배지 — 타이틀바 좌측에 앉아 새 버전을 알리고, 누르면 받고 설치한다.

무엇을 보여 줄지는 **전부 `domain/updater/badge_state.py`가 정한다.** 여기는 그 결과를
그리기만 한다 — `paintEvent` 안에서 난 파이썬 예외는 PyQt가 프로세스 종료로 처리하므로
(Windows에서 0xC0000409, 로그도 남지 않는다) 이 안에서 계산을 하지 않는 것이 안전하다.

## 채움 연출

진행률만큼 배지 배경이 색으로 덮인다. `_TrackSlider`(`gui/widgets/player/controls.py`)와
같은 방식이다 — 둥근 사각형을 통째로 깔고, 그 위에 비율만큼을 다시 둥근 사각형으로
덮는다. 덮는 쪽을 같은 반지름으로 그리면 왼쪽 모서리가 자연스럽게 맞는다.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from domain.updater.badge_state import BadgeState, BadgeView, ClickAction, describe
from gui.themes.manager import ThemeManager
from gui.themes.tokens import ThemeTokens

logger = logging.getLogger(__name__)

_H = 24               # 타이틀바(36px) 안에 여백을 두고 들어가는 높이
_PAD_X = 9            # 글자 좌우 여백
_RADIUS = 5.0
_MIN_W, _MAX_W = 56, 220


class UpdateBadge(QWidget):
    """새 버전 배지. 상태는 밖(`UpdateController`)이 주고, 클릭만 밖으로 돌려준다."""

    clicked = pyqtSignal()

    def __init__(self, current_version: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_version = current_version
        self._state = BadgeState.HIDDEN
        self._new_version = ""
        self._downloaded = 0
        self._total = 0
        self._size_bytes = 0
        self._error = ""
        # 진행률은 **본 적 있는 최대값**만 반영한다 — 이어받기 재시도로 되돌아가면
        # 배지가 깜빡이고, 사용자에겐 그것이 고장으로 읽힌다.
        self._peak = 0
        self._hover = False

        self.setFixedHeight(_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        # paintEvent가 이 아래 어느 줄보다 먼저 불려도 살아남아야 한다 — 거기서
        # 속성 하나가 비면 예외가 아니라 **프로세스 종료**가 된다. 그래서 그릴 때
        # 읽는 것(_view·색·폰트)을 전부 먼저 채운다.
        self._view: BadgeView = describe(BadgeState.HIDDEN)
        tokens = ThemeManager.instance().current()
        self._apply_theme(tokens)
        ThemeManager.instance().theme_changed.connect(self._apply_theme)
        self._refresh()

    # ── 공개 API — 컨트롤러가 부른다 ──────────────────────────────
    def show_found(self, version: str, size_bytes: int = 0) -> None:
        self._new_version = version
        self._size_bytes = size_bytes
        self._error = ""
        self._downloaded = self._total = self._peak = 0
        self._set_state(BadgeState.FOUND)

    def show_progress(self, downloaded: int, total: int) -> None:
        self._peak = max(self._peak, downloaded)
        self._downloaded = self._peak
        self._total = total
        self._set_state(BadgeState.DOWNLOADING)

    def show_ready(self, version: str) -> None:
        self._new_version = version
        self._error = ""
        self._set_state(BadgeState.READY)

    def show_installing(self) -> None:
        self._set_state(BadgeState.INSTALLING)

    def show_failed(self, error: str) -> None:
        self._error = error
        self._downloaded = self._peak = 0
        self._set_state(BadgeState.FAILED)

    def hide_badge(self) -> None:
        self._set_state(BadgeState.HIDDEN)

    @property
    def state(self) -> BadgeState:
        return self._state

    @property
    def action(self) -> ClickAction:
        """지금 누르면 무엇이 일어나는가 — 배선하는 쪽이 이걸 보고 분기한다."""
        return self._view.action

    # ── 내부 ──────────────────────────────────────────────────────
    def _set_state(self, state: BadgeState) -> None:
        self._state = state
        self._refresh()

    def _refresh(self) -> None:
        self._view = describe(
            self._state,
            current_version=self._current_version,
            new_version=self._new_version,
            downloaded=self._downloaded,
            total=self._total,
            size_bytes=self._size_bytes,
            error=self._error,
        )
        self.setVisible(self._view.visible)
        self.setToolTip(self._view.tooltip)
        if self._view.visible:
            self.setFixedWidth(self._width_for(self._view.label))
        self.update()

    def _width_for(self, text: str) -> int:
        w = QFontMetrics(self._font).horizontalAdvance(text) + _PAD_X * 2
        return max(_MIN_W, min(_MAX_W, w))

    def _apply_theme(self, tokens: ThemeTokens) -> None:
        self._border = QColor(tokens.accent)
        self._bg = QColor(tokens.bg_elevated)
        self._fill = QColor(tokens.progress_fg)
        self._fg = QColor(tokens.text_primary)
        # 채워진 부분 위의 글자 — progress_fg 위에서 읽혀야 한다. 같은 토큰 쌍을
        # accent 배경 위 글자에 이미 쓰고 있어 대비가 검증돼 있다.
        self._fg_on_fill = QColor(tokens.text_on_accent)
        self._hover_bg = QColor(tokens.bg_overlay)
        self._font = QFont()
        self._font.setPointSize(9)
        self._font.setBold(True)
        self.update()

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
            if self._view.action is not ClickAction.NOTHING:
                self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        # 여기서 예외가 나면 로그 한 줄 없이 앱이 사라진다. 판정은 이미 도메인에서
        # 끝났고, 남은 것은 산술과 그리기뿐이다.
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

            # ① 바탕
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._hover_bg if self._hover else self._bg)
            p.drawRoundedRect(rect, _RADIUS, _RADIUS)

            # ② 진행률 채움 — 바탕과 같은 반지름으로 덮어 왼쪽 모서리를 맞춘다.
            frac = self._view.fill
            if frac > 0:
                clip = QPainterPath()
                clip.addRoundedRect(rect, _RADIUS, _RADIUS)
                p.save()
                p.setClipPath(clip)
                filled = QRectF(rect)
                filled.setWidth(rect.width() * frac)
                p.setBrush(self._fill)
                p.drawRoundedRect(filled, _RADIUS, _RADIUS)
                p.restore()

            # ③ 테두리 — 시인성의 핵심. 띠 배경과 배지를 갈라 준다.
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(self._border, 1))
            p.drawRoundedRect(rect, _RADIUS, _RADIUS)

            # ④ 글자 — **두 번 그린다.** 채움 경계가 글자 한가운데를 지나가므로
            #    펜 하나로는 어느 쪽이든 묻힌다. 실제로 11개 테마 전부에서
            #    text_primary가 progress_fg 위에서 AA 미달이었다(zinc 2.56:1).
            #    채워진 쪽은 채움 위 글자색으로, 나머지는 평소 글자색으로 칠하고
            #    각각 자기 영역으로 잘라 낸다.
            p.setFont(self._font)
            split = rect.left() + rect.width() * frac
            self._draw_label(p, QRectF(rect.left(), rect.top(),
                                       split - rect.left(), rect.height()),
                             self._fg_on_fill)
            self._draw_label(p, QRectF(split, rect.top(),
                                       rect.right() - split, rect.height()),
                             self._fg)
        finally:
            p.end()

    def _draw_label(self, p: QPainter, clip: QRectF, color: QColor) -> None:
        """글자를 `clip` 영역으로 잘라 그린다(위치는 배지 전체 기준 가운데 정렬).

        폭이 0 이하면 그릴 것이 없다 — `setClipRect`에 빈 사각형을 넘기면 아무것도
        안 그려지지만, 굳이 상태를 저장·복원할 이유도 없다.
        """
        if clip.width() <= 0:
            return
        p.save()
        p.setClipRect(clip)
        p.setPen(color)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._view.label)
        p.restore()
