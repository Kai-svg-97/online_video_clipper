"""좌측 패널을 접었다 펴는 스플리터 핸들."""

from __future__ import annotations

import logging

from PyQt6.QtWidgets import (
    QPushButton,
    QSplitter,
    QSplitterHandle,
)


from gui.panels.library.formatting import _t

logger = logging.getLogger(__name__)


class _CollapseHandle(QSplitterHandle):
    def __init__(self, orientation, parent: QSplitter) -> None:
        super().__init__(orientation, parent)
        self._btn = QPushButton("◀", self)
        self._btn.setFixedSize(14, 40)
        self._btn.setStyleSheet(
            f"QPushButton{{background:{_t().bg_overlay};color:{_t().text_secondary};"
            "border:none;border-radius:3px;font-size:9px;}"
            f"QPushButton:hover{{background:{_t().accent};color:{_t().text_on_accent};}}"
        )
        self._btn.clicked.connect(self._toggle)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        sp = self.splitter()
        # 미리보기 패널 제거 후에는 접기 버튼이 본문(nav_stack)을 접게 되므로,
        # 패널이 3개 이상일 때(마지막 핸들)만 노출한다 — 현재 2패널 구성에선 숨김.
        if sp and sp.count() > 2 and sp.handle(sp.count() - 1) is self:
            self._btn.show()
            self._btn.move(0, (self.height() - self._btn.height()) // 2)
        else:
            self._btn.hide()

    def _toggle(self) -> None:
        sp = self.splitter()
        if sp is None:
            return
        sizes = sp.sizes()
        last = sizes[-1]
        if last > 0:
            sp._saved_preview_size = last
            sizes[-1] = 0
            self._btn.setText("▶")
        else:
            sizes[-1] = getattr(sp, "_saved_preview_size", 400)
            self._btn.setText("◀")
        sp.setSizes(sizes)


class _PreviewSplitter(QSplitter):
    def __init__(self, orientation, parent=None) -> None:
        super().__init__(orientation, parent)
        self._saved_preview_size: int = 400

    def createHandle(self) -> QSplitterHandle:
        return _CollapseHandle(self.orientation(), self)
