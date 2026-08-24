"""영상 목록(그리드·리스트·표) 로딩 스켈레톤 오버레이.

조회 중에는 화면이 비어 있거나 이전 목록을 그대로 들고 있지 않고, 실제 카드/행이
놓일 자리를 셰이머 블록으로 먼저 보여준다. 목록 위에 겹쳐 그리므로(`ListOverlay`와
같은 방식) 레이아웃에 자리를 차지하지 않고, 클릭도 통과시킨다.

칸마다 위젯을 새로 만들지 않고 `gui.widgets.skeleton.SkeletonRow`(칸 여러 개를
한 번의 paintEvent로 그리는 행 primitive)를 재사용해 카드/행 하나당 위젯 2~4개로
제한한다. 그리는 개수는 **뷰포트를 채울 만큼만** 계산한다 — 고정 개수를 만들면
창이 작을 때 낭비고 크면 모자란다.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget

from gui.panels.library.constants import (
    _TH_ICON,
    _TH_LIST,
    _TW_ICON,
    _TW_LIST,
    _VIEW_DETAIL,
    _VIEW_ICON,
    _VIEW_LIST,
)
from gui.panels.library.overlay import _OverlayResizer
from gui.widgets.skeleton import SkeletonRow

# 카드/행 사이 간격 — 실제 델리게이트 배치와 비슷한 정도면 충분하다(픽셀 일치 불필요).
_CARD_GAP = 12
_ROW_GAP = 8
_TABLE_ROW_H = 28
_TABLE_ROW_GAP = 6


class ListSkeleton(QWidget):
    """목록 위에 겹쳐 그리는 로딩 자리표시자.

    `set_view(view_id)`로 그리드/리스트/표 배치를 고르고, `set_loading(bool)`로
    표시/숨김을 전환한다. 로딩이 아닐 때는 자식 위젯을 전부 비워 둔다(숨은 채
    타이머가 도는 위젯이 없어야 한다).
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._view_id = _VIEW_ICON
        self._loading = False
        self._blocks: list[SkeletonRow] = []
        parent.installEventFilter(_OverlayResizer(self, parent))
        self.setGeometry(parent.rect())
        self.hide()

    def set_view(self, view_id: int) -> None:
        """현재 목록 뷰(아이콘/리스트/표)에 맞는 배치로 바꾼다."""
        if view_id == self._view_id:
            return
        self._view_id = view_id
        if self._loading:
            self._rebuild()

    def set_loading(self, loading: bool) -> None:
        """표시/숨김 전환. 같은 값이면 아무 일도 하지 않는다."""
        loading = bool(loading)
        if loading == self._loading:
            return
        self._loading = loading
        if loading:
            self._rebuild()
            self.raise_()
            self.show()
        else:
            self.hide()
            self._clear()

    @property
    def is_loading(self) -> bool:
        return self._loading

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt 시그니처)
        super().resizeEvent(event)
        if self._loading:
            self._rebuild()

    def _clear(self) -> None:
        for block in self._blocks:
            block.setParent(None)
            block.deleteLater()
        self._blocks.clear()

    def _add_block(
        self, x: float, y: float, w: float, h: int, *, cell_count: int = 1,
        cell_ratios: list[float] | None = None,
    ) -> None:
        block = SkeletonRow(
            cell_count=cell_count, height=h, parent=self, cell_ratios=cell_ratios
        )
        block.setGeometry(int(x), int(y), max(1, int(w)), h)
        block.set_loading(True)
        block.show()
        self._blocks.append(block)

    def _rebuild(self) -> None:
        self._clear()
        if self.width() <= 0 or self.height() <= 0:
            return
        if self._view_id == _VIEW_LIST:
            self._build_list_rows()
        elif self._view_id == _VIEW_DETAIL:
            self._build_table_stripes()
        else:
            self._build_grid()

    def _build_grid(self) -> None:
        """아이콘(카드) 그리드 — 썸네일 블록 + 제목 1줄 + 채널/메타 1줄."""
        card_w, thumb_h = _TW_ICON, _TH_ICON
        card_h = thumb_h + 60
        cols = max(1, (self.width() + _CARD_GAP) // (card_w + _CARD_GAP))
        rows = self.height() // (card_h + _CARD_GAP) + 2
        total_w = cols * card_w + (cols - 1) * _CARD_GAP
        x0 = max(0, (self.width() - total_w) // 2)
        for r in range(rows):
            y = r * (card_h + _CARD_GAP)
            if y > self.height():
                break
            for c in range(cols):
                x = x0 + c * (card_w + _CARD_GAP)
                self._add_block(x, y, card_w, thumb_h)
                self._add_block(x, y + thumb_h + 10, card_w * 0.85, 14)
                self._add_block(x, y + thumb_h + 32, card_w * 0.55, 12, cell_count=2,
                                 cell_ratios=[1.0, 1.0])

    def _build_list_rows(self) -> None:
        """리스트 행 — 좌측 썸네일 블록 + 우측 텍스트 줄 3개."""
        thumb_w, thumb_h = _TW_LIST, _TH_LIST
        text_x = 16 + thumb_w + 16
        text_w = max(60, self.width() - text_x - 16)
        count = self.height() // (thumb_h + _ROW_GAP) + 2
        for i in range(count):
            y = i * (thumb_h + _ROW_GAP)
            if y > self.height():
                break
            self._add_block(16, y, thumb_w, thumb_h)
            self._add_block(text_x, y + 8, text_w * 0.75, 14)
            self._add_block(text_x, y + 34, text_w * 0.5, 12)
            self._add_block(text_x, y + 56, text_w * 0.32, 12)

    def _build_table_stripes(self) -> None:
        """표 뷰 — 행 스트라이프만(칼럼 구분은 흉내만 낸다)."""
        count = self.height() // (_TABLE_ROW_H + _TABLE_ROW_GAP) + 2
        row_w = max(60, self.width() - 16)
        for i in range(count):
            y = i * (_TABLE_ROW_H + _TABLE_ROW_GAP)
            if y > self.height():
                break
            self._add_block(
                8, y, row_w, _TABLE_ROW_H - 8, cell_count=5, cell_ratios=[3, 2, 1, 1, 1]
            )
