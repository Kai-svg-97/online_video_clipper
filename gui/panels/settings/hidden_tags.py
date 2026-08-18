"""숨김 태그 관리 — 표시/숨김 두 목록을 드래그로 옮긴다.
"""

from __future__ import annotations

import logging
from typing import Callable

from PyQt6.QtCore import QByteArray, QMimeData, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)


from gui.panels.settings.helpers import _t

_MOVE_MIME = "application/x-settings-tag-name"

logger = logging.getLogger(__name__)


class _TagMoveDelegate(QStyledItemDelegate):
    """태그 이름(왼쪽)과 영상 수(오른쪽)를 나란히 그리는 델리게이트."""

    def sizeHint(self, option, index) -> QSize:
        return QSize(max(option.rect.width(), 160), 26)

    def paint(self, painter, option, index) -> None:
        from PyQt6.QtWidgets import QApplication, QStyle  # noqa: PLC0415
        QApplication.style().drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, option.widget
        )
        name  = index.data(Qt.ItemDataRole.UserRole + 2) or ""
        count = index.data(Qt.ItemDataRole.UserRole + 1) or 0
        tok   = _t()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 태그명
        painter.setFont(QFont("", 9))
        painter.setPen(QColor(tok.text_on_accent if selected else tok.text_primary))
        name_rect = option.rect.adjusted(8, 0, -44, 0)
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine,
            f"#{name}",
        )

        # 영상 수 뱃지
        painter.setFont(QFont("", 8))
        painter.setPen(QColor(tok.text_on_accent if selected else tok.text_muted))
        count_rect = option.rect.adjusted(0, 0, -6, 0)
        painter.drawText(
            count_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight | Qt.TextFlag.TextSingleLine,
            str(count),
        )

        painter.restore()

class _TagMoveList(QListWidget):
    """다른 _TagMoveList로부터의 드래그 드롭을 수락하는 태그 목록."""

    drop_received = pyqtSignal(list)  # list[str] — tag names

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setItemDelegate(_TagMoveDelegate(self))
        self.setSpacing(1)

    def mimeTypes(self) -> list[str]:
        return [_MOVE_MIME]

    def mimeData(self, items) -> QMimeData:
        mime = QMimeData()
        names = [i.data(Qt.ItemDataRole.UserRole + 2) for i in items
                 if i.data(Qt.ItemDataRole.UserRole + 2)]
        mime.setData(_MOVE_MIME, QByteArray("|".join(names).encode()))
        return mime

    def dragEnterEvent(self, event) -> None:
        if event.source() is not self and event.mimeData().hasFormat(_MOVE_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.source() is not self and event.mimeData().hasFormat(_MOVE_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        if event.source() is not self and event.mimeData().hasFormat(_MOVE_MIME):
            raw   = bytes(event.mimeData().data(_MOVE_MIME)).decode()
            names = [n for n in raw.split("|") if n]
            if names:
                self.drop_received.emit(names)
            event.acceptProposedAction()
        else:
            event.ignore()

class _HiddenTagsSection(QWidget):
    """태그 숨김 관리 섹션 — 표시 태그 ↔ 숨긴 태그 두 목록."""

    changed = pyqtSignal()

    def __init__(
        self,
        get_tags_fn: Callable,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._get_tags = get_tags_fn
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        # 안내 문구
        hint = QLabel(
            "표시 태그를 더블클릭하거나 오른쪽으로 드래그하면 태그 목록에서 숨겨집니다."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size: 10px; color: {_t().text_secondary}; margin-bottom: 4px;")
        root.addWidget(hint)

        lists_row = QHBoxLayout()
        lists_row.setSpacing(12)

        # ── 표시 태그 ──────────────────────────────────
        vis_col = QVBoxLayout()
        vis_col.setSpacing(4)
        vis_lbl = QLabel("표시 태그  (더블클릭 → 숨기기)")
        vis_lbl.setStyleSheet("font-size: 10px; font-weight: 600;")
        self._vis_list = _TagMoveList()
        self._vis_list.setMinimumHeight(200)
        self._vis_list.itemDoubleClicked.connect(
            lambda item: self._move_to_hidden([item.data(Qt.ItemDataRole.UserRole + 2)])
        )
        self._vis_list.drop_received.connect(self._move_to_visible)
        vis_col.addWidget(vis_lbl)
        vis_col.addWidget(self._vis_list)
        lists_row.addLayout(vis_col)

        # ── 화살표 힌트 ───────────────────────────────
        arrow_col = QVBoxLayout()
        arrow_col.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        lbl_r = QLabel("→")
        lbl_l = QLabel("←")
        for lbl in (lbl_r, lbl_l):
            lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            lbl.setStyleSheet(f"font-size: 14px; color: {_t().text_secondary};")
        arrow_col.addStretch()
        arrow_col.addWidget(lbl_r)
        arrow_col.addSpacing(8)
        arrow_col.addWidget(lbl_l)
        arrow_col.addStretch()
        lists_row.addLayout(arrow_col)

        # ── 숨긴 태그 ──────────────────────────────────
        hid_col = QVBoxLayout()
        hid_col.setSpacing(4)
        hid_lbl = QLabel("숨긴 태그  (더블클릭 → 표시)")
        hid_lbl.setStyleSheet("font-size: 10px; font-weight: 600;")
        self._hid_list = _TagMoveList()
        self._hid_list.setMinimumHeight(200)
        self._hid_list.itemDoubleClicked.connect(
            lambda item: self._move_to_visible([item.data(Qt.ItemDataRole.UserRole + 2)])
        )
        self._hid_list.drop_received.connect(self._move_to_hidden)
        hid_col.addWidget(hid_lbl)
        hid_col.addWidget(self._hid_list)
        lists_row.addLayout(hid_col)

        root.addLayout(lists_row)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """태그 목록을 새로 불러와 두 목록을 재구성한다."""
        from config.settings import load_hidden_tag_names  # noqa: PLC0415
        hidden_names = load_hidden_tag_names()
        all_tags = sorted(self._get_tags(), key=lambda t: t.name)

        self._vis_list.clear()
        self._hid_list.clear()

        for tag in all_tags:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole,     tag.id)
            item.setData(Qt.ItemDataRole.UserRole + 1, tag.count)
            item.setData(Qt.ItemDataRole.UserRole + 2, tag.name)
            if tag.name in hidden_names:
                self._hid_list.addItem(item)
            else:
                self._vis_list.addItem(item)

    # ------------------------------------------------------------------
    def _move_to_hidden(self, names: list[str]) -> None:
        from config.settings import load_hidden_tag_names, save_hidden_tag_names  # noqa: PLC0415
        hidden = load_hidden_tag_names()
        for n in names:
            hidden.add(n)
        save_hidden_tag_names(hidden)
        self.refresh()
        self.changed.emit()

    def _move_to_visible(self, names: list[str]) -> None:
        from config.settings import load_hidden_tag_names, save_hidden_tag_names  # noqa: PLC0415
        hidden = load_hidden_tag_names()
        for n in names:
            hidden.discard(n)
        save_hidden_tag_names(hidden)
        self.refresh()
        self.changed.emit()
