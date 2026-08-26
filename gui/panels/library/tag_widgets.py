"""태그·즐겨찾기 관련 작은 위젯들(인기 태그 버튼, 태그 목록, 활성 태그 바)."""

from __future__ import annotations

import logging

from PyQt6.QtCore import (
    QRect,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction, QBrush, QColor, QFont, QPainter, QPen,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.themes.colors import sem
from gui.themes.manager import ThemeManager
from gui.themes.tokens import ThemeTokens

from gui.panels.library.constants import _FAV_BADGE_W, _TAG_COUNT_W
from gui.panels.library.delegates import _FavChipDelegate, _TagChipDelegate
from gui.panels.library.formatting import chip_colors, tag_color

logger = logging.getLogger(__name__)


class _PopularTagButton(QPushButton):
    """인기 태그 한 줄 버튼 — 태그명 왼쪽, 카운트 배지 오른쪽 정렬."""

    def __init__(self, name: str, count: int, color: str, selected: bool, parent=None) -> None:
        super().__init__(parent)
        self._tag_name = f"#{name}"
        self._count = count
        self._color = color
        self._selected = selected
        self.setFixedHeight(26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)

    def paintEvent(self, _event) -> None:
        tokens = ThemeManager.instance().current()
        c = chip_colors(tokens, selected=self._selected, data_color=self._color)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)

        painter.setBrush(QBrush(QColor(c["bg"])))
        painter.setPen(QPen(QColor(c["border"]), 1))
        painter.drawRoundedRect(rect, 10, 10)

        badge_text = str(self._count)
        painter.setFont(QFont("", 7))
        fm = painter.fontMetrics()
        badge_w = fm.horizontalAdvance(badge_text) + 12
        badge_h = rect.height() - 8
        badge_x = rect.right() - badge_w - 4
        badge_y = rect.center().y() - badge_h // 2
        badge_rect = QRect(badge_x, badge_y, badge_w, badge_h)

        painter.setBrush(QBrush(QColor(c["badge_bg"])))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(badge_rect, badge_h // 2, badge_h // 2)

        painter.setPen(QColor(c["badge_text"]))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)

        painter.setFont(QFont("", 9))
        painter.setPen(QColor(c["text"]))
        name_rect = QRect(rect.left() + 8, rect.top(), badge_x - rect.left() - 12, rect.height())
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine,
            self._tag_name,
        )
        painter.end()


class _FavListWidget(QListWidget):
    """즐겨찾기 바 내부 리스트 위젯 — 오른쪽 배지 클릭 시 unfav_requested 발행."""

    unfav_requested = pyqtSignal(str, str, str)   # (type, id, name)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.indexAt(event.pos())
            if index.isValid():
                item = self.item(index.row())
                vis = self.visualItemRect(item)
                if event.pos().x() >= vis.right() - _FAV_BADGE_W:
                    data = item.data(Qt.ItemDataRole.UserRole)
                    if data:
                        self.unfav_requested.emit(data[0], data[1], data[2])
                    return
        super().mousePressEvent(event)


class _FavoritesBar(QWidget):
    """즐겨찾기 항목을 가로로 나열한 바. 클릭 시 필터 적용, DnD로 순서 변경."""

    item_clicked    = pyqtSignal(str, str)         # (type, id)
    unfav_requested = pyqtSignal(str, str, str)    # (type, id, name) — 배지 클릭

    _ICON = {"category": "🏷", "playlist": "▶", "tag": "#"}

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)

        self._list = _FavListWidget()
        self._list.setFlow(QListWidget.Flow.LeftToRight)
        self._list.setWrapping(False)
        self._list.setMaximumHeight(32)
        self._list.setFrameShape(QFrame.Shape.NoFrame)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._list.setItemDelegate(_FavChipDelegate(self._list))
        self._list.setStyleSheet(
            "QListWidget{background:transparent;border:none;}"
            "QListWidget::item{border-radius:10px;margin:1px;}"
        )
        self._list.itemClicked.connect(self._on_clicked)
        self._list.model().rowsMoved.connect(self._on_reordered)
        self._list.unfav_requested.connect(self.unfav_requested)
        layout.addWidget(self._list)
        self.hide()

    def refresh(self, counts: dict[str, int] | None = None) -> None:
        from application.library.favorites import load_favorites  # noqa: PLC0415
        items = load_favorites()
        self._list.clear()
        cnt = counts or {}
        for fav in items:
            icon = self._ICON.get(fav.type, "★")
            wi = QListWidgetItem(f"{icon} {fav.name}")
            wi.setData(Qt.ItemDataRole.UserRole, (fav.type, fav.id, fav.name))
            wi.setData(Qt.ItemDataRole.UserRole + 1, cnt.get(f"{fav.type}:{fav.id}", 0))
            wi.setToolTip(f"{fav.name} — 클릭: 필터 적용 / 숫자 클릭: 즐겨찾기 해제")
            self._list.addItem(wi)
        self.setVisible(self._list.count() > 0)

    def _on_clicked(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if data:
            self.item_clicked.emit(data[0], data[1])

    def _on_reordered(self) -> None:
        from application.library.favorites import FavoriteItem, save_favorites  # noqa: PLC0415
        items = []
        for i in range(self._list.count()):
            wi = self._list.item(i)
            data = wi.data(Qt.ItemDataRole.UserRole)
            if data:
                items.append(FavoriteItem(type=data[0], id=data[1], name=data[2], order=i))
        save_favorites(items)


class _TagListWidget(QListWidget):
    """Tag list with multi-toggle selection; count badge acts as delete button."""

    delete_requested  = pyqtSignal(object)        # tag UUID (click on count badge)
    favorite_toggled  = pyqtSignal(str, str, str) # (type="tag", id, name)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setItemDelegate(_TagChipDelegate(self))
        self.setSpacing(1)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_tag_context_menu)

    def _show_tag_context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if item is None:
            return
        tag_id = str(item.data(Qt.ItemDataRole.UserRole))
        tag_name = item.text().lstrip("#")
        from application.library.favorites import is_favorite  # noqa: PLC0415
        menu = QMenu(self)
        fav_label = "★ 즐겨찾기 제거" if is_favorite(tag_id, "tag") else "☆ 즐겨찾기 추가"
        fav_act = QAction(fav_label, self)
        fav_act.triggered.connect(lambda: self.favorite_toggled.emit("tag", tag_id, tag_name))
        menu.addAction(fav_act)
        menu.exec(self.viewport().mapToGlobal(pos))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.indexAt(event.pos())
            if index.isValid():
                item = self.item(index.row())
                vis = self.visualItemRect(item)
                # Count badge occupies the rightmost _TAG_COUNT_W px of the chip area
                # chip right = vis.right() - 3  (delegate adjusts by 3)
                if event.pos().x() >= vis.right() - 3 - _TAG_COUNT_W:
                    tag_id = item.data(Qt.ItemDataRole.UserRole)
                    self.delete_requested.emit(tag_id)
                    return
        super().mousePressEvent(event)


class _ActiveTagsBar(QWidget):
    """Panel directly below the category tree showing active tag-filter chips.

    Each chip shows ``#tagname ✕``; click removes that tag from the filter.
    Chips wrap onto new lines so the panel auto-sizes to its content.
    Tag colors are assigned deterministically from _TAG_PALETTE.
    """

    tag_removed = pyqtSignal(object)  # UUID

    def _apply_theme(self, tokens: ThemeTokens) -> None:
        """배경·제목 색을 테마 토큰으로 갱신한다."""
        self.setStyleSheet(
            f"background:{tokens.bg_surface}; border-radius:4px;"
        )
        self._dot.setStyleSheet(
            f"color:{tokens.accent}; font-size:7pt; background:transparent;"
        )
        self._title_lbl.setStyleSheet(
            f"font-size:8pt; color:{tokens.text_secondary}; "
            "font-weight:600; background:transparent;"
        )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 6, 0, 6)
        self._root.setSpacing(5)

        # Panel title row
        title_row = QHBoxLayout()
        title_row.setContentsMargins(8, 0, 8, 0)
        title_row.setSpacing(5)
        self._dot = QLabel("◆")
        self._dot.setFixedWidth(10)
        title_row.addWidget(self._dot)
        self._title_lbl = QLabel("활성 태그 필터")
        title_row.addWidget(self._title_lbl)
        title_row.addStretch()

        # 배경·점·라벨 색은 테마 토큰에서 가져온다 (과거 #182430·#5a9ad4·#aac 하드코딩)
        self._apply_theme(ThemeManager.instance().current())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)
        self._root.addLayout(title_row)

        # Chip container — replaced wholesale on each refresh()
        self._holder: QWidget | None = None
        self.hide()

    def refresh(self, tags: list[tuple]) -> None:
        """Rebuild from a list of (UUID, name) pairs; hide when empty."""
        if self._holder is not None:
            self._root.removeWidget(self._holder)
            self._holder.deleteLater()
            self._holder = None

        if not tags:
            self.hide()
            return

        self.show()

        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        v = QVBoxLayout(holder)
        v.setContentsMargins(6, 0, 6, 0)
        v.setSpacing(4)

        # Pack chips into rows; estimate chip width to decide when to wrap
        MAX_ROW_W = 192   # ~220px panel − margins
        row: QHBoxLayout | None = None
        row_used = 0

        for tid, name in tags:
            label     = f"#{name}  ✕"
            chip_w    = min(len(label) * 7 + 24, 186)
            color     = tag_color(name)

            if row is None or row_used + chip_w + 4 > MAX_ROW_W:
                if row is not None:
                    row.addStretch()
                row = QHBoxLayout()
                row.setContentsMargins(0, 0, 0, 0)
                row.setSpacing(4)
                v.addLayout(row)
                row_used = 0

            chip = QPushButton(label)
            chip.setFixedHeight(22)
            # 호버는 "이 태그를 제거한다"는 뜻이라 의미 색(danger)을 쓴다 — 예전엔
            # `#b03030`을 박아 두었고, 그 값은 '영상 없음' 경고 뱃지 상수와 같아
            # 서로 다른 의미가 같은 색을 공유하고 있었다.
            # 글자는 흰색 고정 — 배경이 테마 색이 아니라 `_TAG_PALETTE`의 식별용
            # 고정 팔레트이기 때문이다(전 32색이 흰 글자 대비 4.5:1 이상임을
            # tests/gui/test_theme_contrast.py 가 고정한다).
            chip.setStyleSheet(
                f"QPushButton{{border:none;border-radius:10px;"
                f"background:{color};color:#fff;"
                f"padding:1px 9px;font-size:7pt;}}"
                f"QPushButton:hover{{background:{sem('danger')};border-radius:10px;}}"
            )
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _, i=tid: self.tag_removed.emit(i))
            row.addWidget(chip)
            row_used += chip_w + 4

        if row is not None:
            row.addStretch()

        self._root.addWidget(holder)
        self._holder = holder
