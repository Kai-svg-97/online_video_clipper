"""토스트 알림 — 화면 오른쪽 아래에 잠깐 떠올랐다 사라지는 짧은 알림.

지금까지 완료 알림은 상태바 한 줄이 전부였다. 상태바는 시선이 가지 않는 곳이라
"등록 완료", "요약 생성 실패" 같은 결과를 그냥 놓치기 쉽다. 진행 중 상태는 상태바가
계속 맡고(계속 보여야 하니까), **끝났다는 소식만** 토스트로 띄운다.

규칙
* 여러 개가 겹치면 위로 쌓는다(최근 것이 아래).
* 클릭하면 즉시 닫힌다 — 읽었으면 치울 수 있어야 한다.
* 부모 창 크기가 바뀌면 따라 움직인다.
* 색은 의미(성공·실패·정보)로만 구분하고 나머지는 테마 토큰을 쓴다.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, Qt, QTimer
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QLabel, QWidget

from gui.themes.colors import sem
from gui.themes.manager import ThemeManager

logger = logging.getLogger(__name__)

KIND_INFO = "info"
KIND_SUCCESS = "success"
KIND_ERROR = "error"

_MARGIN = 18          # 창 가장자리에서 띄우는 여백
_GAP = 8              # 토스트 사이 간격
_FADE_MS = 160
_DEFAULT_MSEC = 3200
# 동시에 띄우는 최대 개수 — 그 이상은 화면을 가린다.
_MAX_VISIBLE = 4


class Toast(QLabel):
    """알림 하나. `show_toast()`로 만들고 스스로 사라진다."""

    def __init__(self, parent: QWidget, text: str, kind: str, msec: int) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setWordWrap(True)
        self.setMaximumWidth(420)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._kind = kind
        self._apply_theme(ThemeManager.instance().current())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(0.0)
        self.setGraphicsEffect(self._effect)
        self.adjustSize()
        self.show()

        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(_FADE_MS)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(max(600, msec))
        self._timer.timeout.connect(self.dismiss)
        self._timer.start()

    def _apply_theme(self, tokens) -> None:
        accent = {
            KIND_SUCCESS: sem("success"),
            KIND_ERROR: sem("danger"),
        }.get(self._kind, tokens.accent)
        self.setStyleSheet(
            f"background: {tokens.bg_elevated}; color: {tokens.text_primary};"
            f" border: 1px solid {tokens.border}; border-left: 3px solid {accent};"
            " border-radius: 8px; padding: 10px 14px; font-size: 10pt;"
        )

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self.dismiss()

    def dismiss(self) -> None:
        """사라지며 스스로 정리한다(사라지는 중 다시 불려도 안전)."""
        if getattr(self, "_dismissing", False):
            return
        self._dismissing = True
        self._timer.stop()
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self._finish)
        self._fade.start()

    def _finish(self) -> None:
        manager = _manager_for(self.parentWidget(), create=False)
        if manager is not None:
            manager.remove(self)
        self.hide()
        self.deleteLater()


class _ToastManager(QObject):
    """한 창에 뜬 토스트들의 위치를 관리한다(부모 리사이즈도 따라간다)."""

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self._host = host
        self._toasts: list[Toast] = []
        host.installEventFilter(self)

    def add(self, toast: Toast) -> None:
        self._toasts.append(toast)
        # 상한을 넘으면 오래된 것부터 **즉시 목록에서 빼고**(자리 계산에서 제외) 사라지게
        # 한다. 사라짐은 애니메이션이라, 목록에 남겨 두면 상한을 잠깐 넘겨 화면을 가린다.
        while len(self._toasts) > _MAX_VISIBLE:
            oldest = self._toasts.pop(0)
            oldest.dismiss()
        self.reposition()

    def remove(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        self.reposition()

    def reposition(self) -> None:
        """오른쪽 아래부터 위로 쌓는다."""
        y = self._host.height() - _MARGIN
        for toast in reversed(self._toasts):
            try:
                size = toast.sizeHint()
            except RuntimeError:
                continue
            y -= size.height()
            toast.setGeometry(
                self._host.width() - size.width() - _MARGIN, y,
                size.width(), size.height(),
            )
            toast.raise_()
            y -= _GAP

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.Resize:
            self.reposition()
        return False

    def visible_toasts(self) -> list[Toast]:
        return list(self._toasts)


def _manager_for(host: QWidget | None, create: bool = True) -> _ToastManager | None:
    if host is None:
        return None
    manager = getattr(host, "_toast_manager", None)
    if manager is None and create:
        manager = _ToastManager(host)
        host._toast_manager = manager
    return manager


def show_toast(
    parent: QWidget,
    text: str,
    kind: str = KIND_INFO,
    msec: int = _DEFAULT_MSEC,
) -> Toast | None:
    """부모 창 오른쪽 아래에 알림을 띄운다(부모가 없으면 아무 일도 하지 않는다)."""
    if parent is None or not text:
        return None
    host = parent.window()
    manager = _manager_for(host)
    toast = Toast(host, text, kind, msec)
    manager.add(toast)
    return toast
