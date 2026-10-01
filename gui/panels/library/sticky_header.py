"""라이브러리 트리의 고정 헤더(sticky scroll).

펼쳐진 폴더의 자식을 스크롤해 내려가는 동안 그 조상 폴더들을 맨 위에 한 줄씩 쌓아
둔다. 폴더의 마지막 자손 행이 그 고정 줄 아래까지 올라오면 고정 줄이 함께 밀려 올라가며
사라진다 — 편집기의 sticky scroll과 같은 연출이다. 긴 카테고리 안에서 "지금 어느 폴더
안을 보고 있는지"를 잃지 않게 한다.

## 왜 이렇게 만들었나

- **계산은 순수 함수**(`compute_sticky_rows`)로 뺀다. 행 높이가 모두 같으므로(트리가
  `setUniformRowHeights`) 깊이만큼만 훑으면 되고, 시험이 픽셀 단위로 검증할 수 있다.
- **그림은 트리 자신의 것을 빌린다.** 가이드선·셰브론은 `tree.drawBranches`, 행 내용은
  트리의 델리게이트가 그린다 — 따로 그리면 행 모양을 바꿀 때마다 두 곳을 고쳐야 한다.
- **휠은 가로채지 않는다.** 뷰포트로 그대로 넘겨, 거기 걸린 부드러운 스크롤 필터가 받게
  한다. 수정키가 붙은 휠도 건드리지 않는다(CLAUDE.md 입력 규칙).
- **드래그하는 동안 숨는다.** 가려진 행으로 떨어져 엉뚱한 폴더에 들어가면 안 된다.
- **깊은 줄을 먼저, 얕은 줄을 위에 그린다.** 밀려 올라가는 자식 폴더 줄이 부모 줄 밑으로
  미끄러져 들어가게 보인다. 누르기 판정은 그 반대 순서(보이는 쪽이 먼저)다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PyQt6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen, QWheelEvent
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QStyle,
    QStyleOptionViewItem,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)

from gui.themes.manager import ThemeManager

logger = logging.getLogger(__name__)

MAX_ROWS = 3
# 고정 줄 아래로 최소한 이만큼의 행은 보이게 둔다 — 낮은 트리에서 목록을 가리지 않게.
_MIN_FREE_ROWS = 2


@dataclass(frozen=True, slots=True)
class StickyRow:
    """고정 줄 하나 — 그릴 항목과 뷰포트 기준 위쪽 y(밀려 올라가면 음수)."""

    item: QTreeWidgetItem
    top: int


def _row_height(tree: QTreeWidget) -> int:
    first = tree.topLevelItem(0)
    if first is None:
        return 0
    height = tree.visualItemRect(first).height()
    return height if height > 0 else tree.sizeHintForRow(0)


def _ancestors(item: QTreeWidgetItem) -> list[QTreeWidgetItem]:
    """위에서부터의 조상 목록(자기 자신은 빼고)."""
    chain: list[QTreeWidgetItem] = []
    parent = item.parent()
    while parent is not None:
        chain.append(parent)
        parent = parent.parent()
    chain.reverse()
    return chain


def _last_visible_descendant(item: QTreeWidgetItem) -> QTreeWidgetItem:
    """펼쳐진 가지를 따라 내려간 마지막 행 — 이 폴더가 화면에서 끝나는 곳."""
    node = item
    while node.isExpanded():
        child = None
        for i in range(node.childCount() - 1, -1, -1):
            candidate = node.child(i)
            if not candidate.isHidden():
                child = candidate
                break
        if child is None:
            break
        node = child
    return node


def compute_sticky_rows(tree: QTreeWidget, max_rows: int = MAX_ROWS) -> list[StickyRow]:
    """지금 스크롤 위치에서 맨 위에 고정할 조상 폴더들.

    k번째 줄 바로 아래(y = k × 행 높이)에 걸친 항목의 k번째 조상이 펼쳐져 있으면 그것을
    쌓는다. 각 줄의 위치는 "원래 자리(k × 행 높이)"와 "그 폴더의 마지막 자손 행 아래끝 −
    행 높이" 중 위쪽이다 — 뒤쪽이 이기면 밀려 올라가는 것이다.
    """
    height = _row_height(tree)
    if height <= 0:
        return []
    viewport = tree.viewport()
    limit = min(max_rows, max(0, viewport.height() // height - _MIN_FREE_ROWS))
    probe_x = max(1, viewport.width() // 2)

    stack: list[QTreeWidgetItem] = []
    while len(stack) < limit:
        depth = len(stack)
        item = tree.itemAt(QPoint(probe_x, depth * height))
        if item is None:
            break
        chain = _ancestors(item)
        if depth >= len(chain):
            break
        if any(a is not b for a, b in zip(chain[:depth], stack)):
            break
        candidate = chain[depth]
        if not candidate.isExpanded():
            break
        stack.append(candidate)

    rows: list[StickyRow] = []
    for depth, node in enumerate(stack):
        bottom = tree.visualItemRect(_last_visible_descendant(node)).bottom() + 1
        top = min(depth * height, bottom - height)
        if top + height <= 0:
            break          # 다 밀려 나갔다 — 더 깊은 줄은 그보다 먼저 끝났다
        rows.append(StickyRow(node, top))
    return rows


class StickyHeader(QWidget):
    """트리 뷰포트 위에 얹는 고정 헤더. `_PlaylistTree`가 만들어 붙인다."""

    def __init__(self, tree: QTreeWidget) -> None:
        super().__init__(tree.viewport())
        self._tree = tree
        self._rows: list[StickyRow] = []
        self._suspended = False
        self.hide()

        # 펼치기·목록 변경은 한 번에 여러 번 올 수 있어 다음 루프로 모아 계산한다.
        self._pending = QTimer(self)
        self._pending.setSingleShot(True)
        self._pending.setInterval(0)
        self._pending.timeout.connect(self.refresh)

        # 스크롤은 즉시 — 한 프레임만 늦어도 고정 줄이 행과 어긋나 떨린다.
        tree.verticalScrollBar().valueChanged.connect(self._on_scrolled)
        tree.itemExpanded.connect(self._on_structure_changed)
        tree.itemCollapsed.connect(self._on_structure_changed)
        model = tree.model()
        model.rowsInserted.connect(self._on_structure_changed)
        model.rowsRemoved.connect(self._on_structure_changed)
        model.modelReset.connect(self._on_structure_changed)
        model.layoutChanged.connect(self._on_structure_changed)
        model.dataChanged.connect(self._on_data_changed)
        tree.viewport().installEventFilter(self)
        # 싱글턴 신호에는 바운드 메서드만 — 위젯이 사라지면 Qt가 연결을 끊는다(CLAUDE.md).
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)

    # ── 상태 ───────────────────────────────────────────────────────────
    def rows(self) -> list[StickyRow]:
        return list(self._rows)

    def refresh(self) -> None:
        if self._suspended:
            self.hide()
            return
        try:
            rows = compute_sticky_rows(self._tree)
        except Exception:
            logger.exception("고정 헤더 계산 실패 — 이번 갱신은 숨긴다")
            rows = []
        self._rows = rows
        if not rows:
            self.hide()
            return
        height = self._row_height()
        bottom = max(r.top + height for r in rows)
        self.setGeometry(0, 0, self._tree.viewport().width(), max(0, bottom))
        self.show()
        self.raise_()
        self.update()

    def _row_height(self) -> int:
        return _row_height(self._tree)

    # ── 신호 ───────────────────────────────────────────────────────────
    def _on_scrolled(self, _value: int) -> None:
        self.refresh()

    def _on_structure_changed(self, *_args) -> None:
        self._pending.start()

    def _on_data_changed(self, *_args) -> None:
        if self._rows:
            self.update()   # 이름·개수·스피너가 바뀌었을 수 있다

    def _on_theme_changed(self, _tokens) -> None:
        self.update()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if obj is self._tree.viewport():
            kind = event.type()
            if kind == QEvent.Type.Resize:
                self._pending.start()
            elif kind == QEvent.Type.DragEnter:
                self._suspended = True
                self.hide()
            elif kind in (QEvent.Type.DragLeave, QEvent.Type.Drop):
                self._suspended = False
                self.refresh()
        return False

    # ── 입력 ───────────────────────────────────────────────────────────
    def _row_at(self, y: int) -> int | None:
        """보이는 쪽(얕은 줄)이 먼저다 — 그리는 순서의 반대."""
        height = self._row_height()
        for i, row in enumerate(self._rows):
            if row.top <= y < row.top + height:
                return i
        return None

    def mousePressEvent(self, event) -> None:  # noqa: N802
        try:
            index = self._row_at(int(event.position().y()))
            if index is None:
                event.ignore()
                return
            self._jump_to(index)
            event.accept()
        except Exception:
            logger.exception("고정 헤더 클릭 처리 실패")
            event.ignore()

    def _jump_to(self, index: int) -> None:
        """그 폴더를 고르고, 자기 조상 고정 줄 바로 아래로 스크롤한다(가려지지 않게)."""
        item = self._rows[index].item
        tree = self._tree
        tree.setCurrentItem(item)
        if tree.verticalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerPixel:
            bar = tree.verticalScrollBar()
            offset = tree.visualItemRect(item).top() - index * self._row_height()
            bar.setValue(bar.value() + offset)
        else:
            tree.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtTop)

    def wheelEvent(self, event) -> None:  # noqa: N802
        """뷰포트로 그대로 넘긴다 — 부드러운 스크롤 필터가 거기 걸려 있다.

        무시(`ignore`)만 해서는 부모로 넘어가지 않는다(실측: 고정 줄 위에서 휠을 굴려도
        스크롤 값이 그대로였다). 위치만 뷰포트 좌표로 옮기고 휠 양·수정키·단계는 그대로
        둔다 — 수정키가 붙은 휠(Ctrl+휠 등)도 원래 받던 곳이 받게.
        """
        # 이벤트 처리기에서 새어 나간 파이썬 예외는 PyQt가 프로세스 종료로 다룰 수 있다 — 감싼다.
        try:
            viewport = self._tree.viewport()
            pos = self.mapTo(viewport, event.position().toPoint())
            forwarded = QWheelEvent(
                QPointF(pos), event.globalPosition(), event.pixelDelta(), event.angleDelta(),
                event.buttons(), event.modifiers(), event.phase(), event.inverted(),
            )
            QApplication.sendEvent(viewport, forwarded)
            event.setAccepted(forwarded.isAccepted())
        except Exception:
            logger.exception("고정 헤더 휠 전달 실패")
            event.ignore()

    # ── 그리기 ─────────────────────────────────────────────────────────
    def paintEvent(self, _event) -> None:  # noqa: N802
        # paint 안의 예외는 로그 없이 프로세스를 죽인다(CLAUDE.md) — 전부 감싼다.
        painter = QPainter(self)
        try:
            self._paint(painter)
        except Exception:
            logger.exception("고정 헤더 그리기 실패")
        finally:
            painter.end()

    def _paint(self, painter: QPainter) -> None:
        if not self._rows:
            return
        tokens = ThemeManager.instance().current()
        height = self._row_height()
        width = self.width()
        # 뒤의 트리가 비치지 않게 불투명하게 — 트리는 배경이 투명이라 사이드바의 bg_base가 보인다.
        painter.fillRect(QRect(0, 0, width, self.height()), QColor(tokens.bg_base))
        for row in reversed(self._rows):
            rect = QRect(0, row.top, width, height)
            painter.fillRect(rect, QColor(tokens.bg_base))
            self._paint_row(painter, row, rect)
        painter.setPen(QPen(QColor(tokens.border_muted), 1))
        painter.drawLine(0, self.height() - 1, width, self.height() - 1)

    def _paint_row(self, painter: QPainter, row: StickyRow, rect: QRect) -> None:
        tree = self._tree
        index = tree.indexFromItem(row.item, 0)
        content = tree.visualItemRect(row.item)
        left = content.left()
        tree.drawBranches(painter, QRect(0, rect.top(), left, rect.height()), index)
        option = QStyleOptionViewItem()
        tree.initViewItemOption(option)
        option.rect = QRect(left, rect.top(), content.width(), rect.height())
        option.state |= QStyle.StateFlag.State_Enabled
        if row.item.isSelected():
            option.state |= QStyle.StateFlag.State_Selected
        tree.itemDelegate().paint(painter, option, index)
