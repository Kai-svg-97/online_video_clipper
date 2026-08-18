"""목록 위에 겹쳐 상태를 알리는 안내판 — 조회 중·결과 없음.

지금까지 목록 화면은 **아무 말도 하지 않았다**. 카테고리를 누르면 조회가 끝날 때까지
이전 목록이 그대로 남아 있다가 툭 바뀌었고, 결과가 0건이면 그냥 빈 화면이었다
(비어 있는 건지 못 불러온 건지 알 수 없었다).

안내판은 **레이아웃에 자리를 차지하지 않는다** — 목록 위에 덮어 그리므로 나타났다
사라져도 카드 배치가 흔들리지 않는다. 클릭은 통과시켜(`WA_TransparentForMouseEvents`)
안내가 떠 있는 동안에도 아래 목록을 조작할 수 있다.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from gui.themes.manager import ThemeManager

logger = logging.getLogger(__name__)


class ListOverlay(QWidget):
    """목록 위 안내판. `show_message()`로 띄우고 `hide()`로 걷는다."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        self._label = QLabel("")
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label)
        self._apply_theme(ThemeManager.instance().current())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)
        self.hide()
        # 부모 크기를 따라다닌다(레이아웃에 들어가지 않으므로 직접 맞춘다).
        parent.installEventFilter(_OverlayResizer(self, parent))
        self.setGeometry(parent.rect())

    def _apply_theme(self, tokens) -> None:
        self._label.setStyleSheet(
            f"color: {tokens.text_secondary}; font-size: 11pt;"
            f" background: {tokens.bg_overlay}; border-radius: 10px; padding: 14px 20px;"
        )

    def show_message(self, text: str) -> None:
        self._label.setText(text)
        self.raise_()
        self.show()

    def text(self) -> str:
        return self._label.text()


class _OverlayResizer(QObject):
    """부모가 리사이즈될 때 안내판을 같은 크기로 맞춘다."""

    def __init__(self, overlay: ListOverlay, parent: QWidget) -> None:
        super().__init__(parent)
        self._overlay = overlay

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            try:
                self._overlay.setGeometry(obj.rect())
            except RuntimeError:
                logger.debug("안내판이 이미 정리됨 — 무시")
        return False
