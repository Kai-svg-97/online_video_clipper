"""Library panel — 3-pane browser: left sidebar | video list | preview pane.

Centre pane uses a navigation QStackedWidget (_nav_stack) so that double-clicking
a video replaces the list area with VideoDetailWidget inline (no modal dialog).
"""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from uuid import UUID

from PyQt6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QEvent,
    QMimeData,
    QModelIndex,
    QPoint,
    QRect,
    QSize,
    QTimer,
    QUrl,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction, QBrush, QColor, QDesktopServices, QDrag, QFont, QPainter, QPainterPath, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSplitter,
    QSplitterHandle,
    QStackedWidget,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from application.library.dtos import CategoryDTO, VideoDTO
from config.settings import LRU_THUMBNAIL_MAX, THUMBNAIL_DIR, THUMBNAIL_HEIGHT, THUMBNAIL_WIDTH
from gui.dialogs.batch_download_dialog import BatchDownloadDialog
from gui.panels.video_detail_panel import VideoDetailWidget, _TagFlow, _clear_layout
from gui.themes.manager import ThemeManager
from gui.themes.tokens import ThemeTokens
from gui.view_models.library_vm import LibraryViewModel
from gui.widgets.video_player import InlinePlayer


def _t() -> ThemeTokens:
    """현재 테마 토큰을 반환하는 단축 함수."""
    return ThemeManager.instance().current()

# ------------------------------------------------------------------
# Thumbnail size constants (per view type)
# ------------------------------------------------------------------
_TW_ICON = THUMBNAIL_WIDTH     # 320
_TH_ICON = THUMBNAIL_HEIGHT    # 180
_TW_LIST = 213                 # 16:9 at list row size
_TH_LIST = 120
_TW_PREV = 300
_TH_PREV = 169

# Icon-grid card metrics
_ICON_TEXT_H = 90  # px below thumbnail: title(2) + channel + views/time
_ICON_PAD    = 8   # horizontal padding inside card

_MIME_VIDEO_ID   = "application/x-video-id"
_MIME_CAT_ID     = "application/x-category-id"
_CAT_PARENT_ROLE = Qt.ItemDataRole.UserRole + 100  # parent_id on category tree items
_VIEW_ICON   = 0
_VIEW_LIST   = 1
_VIEW_DETAIL = 2
_TAG_COUNT_W = 28   # width reserved for the count badge in tag chips (also the delete hit area)

# 32 visually distinct, dark-background-friendly colors for active tag chips.
# Assigned deterministically by hash(tag_name) % 32 so each tag always gets the same color.
_TAG_PALETTE: tuple[str, ...] = (
    "#1a6b8a", "#8b2252", "#2a7a3b", "#6b3d9a",
    "#b5451b", "#1a5276", "#0d7377", "#7a4430",
    "#5d3a9b", "#1e7a44", "#7d2e68", "#2e6b8a",
    "#6b2d2d", "#2a6b4a", "#3a4d8a", "#7a4e2d",
    "#1a7860", "#6b4a8a", "#4a6b2a", "#8a3a5d",
    "#2a5c8a", "#5c3a8a", "#8a5c1a", "#1a6b55",
    "#6b1a3a", "#3a6b1a", "#8a4a1a", "#1a4a6b",
    "#6b6b1a", "#4a8a4a", "#8a1a6b", "#1a8a8a",
)


# ------------------------------------------------------------------
# Multi-size LRU thumbnail cache
# ------------------------------------------------------------------

class _ThumbnailCache:
    def __init__(self, maxsize: int = LRU_THUMBNAIL_MAX) -> None:
        self._cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._maxsize = maxsize

    def get(self, key: str) -> QPixmap | None:
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put(self, key: str, pixmap: QPixmap) -> None:
        self._cache[key] = pixmap
        self._cache.move_to_end(key)
        if len(self._cache) > self._maxsize:
            self._cache.popitem(last=False)


_thumb_cache = _ThumbnailCache(LRU_THUMBNAIL_MAX * 3)


def _load_thumb(thumbnail_path: str, w: int, h: int) -> QPixmap:
    """Load thumbnail scaled to (w, h); cached by path+size."""
    key = f"{thumbnail_path}@{w}x{h}" if thumbnail_path else f"__ph__{w}x{h}"
    cached = _thumb_cache.get(key)
    if cached is not None:
        return cached

    if thumbnail_path:
        full = Path(THUMBNAIL_DIR) / thumbnail_path
        if full.exists():
            src = QPixmap(str(full))
            if not src.isNull():
                scaled = src.scaled(
                    w, h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                _thumb_cache.put(key, scaled)
                return scaled

    pm = QPixmap(w, h)
    pm.fill(QColor(_t().bg_overlay))
    _thumb_cache.put(key, pm)
    return pm


def _url_from_mime(mime: QMimeData) -> str:
    """Extract an http/https URL from MIME data, or return empty string."""
    text = mime.text().strip()
    if text.startswith(("http://", "https://")):
        return text
    if mime.hasUrls():
        for qu in mime.urls():
            s = qu.toString().strip()
            if s.startswith(("http://", "https://")):
                return s
    return ""


def _relative_time(date_str: str | None) -> str:
    """Return a Korean relative time string like '3년 전' from an ISO date string."""
    if not date_str:
        return ""
    from datetime import date, datetime
    try:
        if "T" in date_str or " " in date_str:
            pub = datetime.fromisoformat(date_str).date()
        else:
            pub = date.fromisoformat(date_str)
        today = date.today()
        days = (today - pub).days
        if days < 0:
            return ""
        if days < 7:
            return f"{days}일 전" if days > 0 else "오늘"
        if days < 30:
            return f"{days // 7}주 전"
        if days < 365:
            return f"{days // 30}개월 전"
        return f"{days // 365}년 전"
    except (ValueError, TypeError):
        return ""


def _fmt_views(view_count: int | None) -> str:
    """Return a short Korean view count string like '1.2만 회'."""
    if view_count is None:
        return ""
    if view_count < 1_000:
        return f"조회수 {view_count}회"
    if view_count < 10_000:
        return f"조회수 {view_count / 1000:.1f}천 회"
    if view_count < 100_000_000:
        return f"조회수 {view_count / 10000:.1f}만 회"
    return f"조회수 {view_count / 100_000_000:.1f}억 회"


# ------------------------------------------------------------------
# QListView subclass: emits empty_clicked on click on empty space
# ------------------------------------------------------------------

class _VideoListView(QListView):
    empty_clicked = pyqtSignal()
    url_dropped   = pyqtSignal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._ext_url_drag = False

    def mousePressEvent(self, event) -> None:
        if not self.indexAt(event.pos()).isValid():
            self.empty_clicked.emit()
            self.clearSelection()
        super().mousePressEvent(event)

    def dragEnterEvent(self, event) -> None:
        self._ext_url_drag = bool(_url_from_mime(event.mimeData()))
        if self._ext_url_drag:
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self._ext_url_drag:
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:
        self._ext_url_drag = False
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self._ext_url_drag = False
        url = _url_from_mime(event.mimeData())
        if url:
            self.url_dropped.emit(url)
            event.acceptProposedAction()
        else:
            event.ignore()


# ------------------------------------------------------------------
# Collapsible splitter handle (triangle toggle on rightmost handle)
# ------------------------------------------------------------------

class _CollapseHandle(QSplitterHandle):
    def __init__(self, orientation, parent: QSplitter) -> None:
        super().__init__(orientation, parent)
        self._btn = QPushButton("◀", self)
        self._btn.setFixedSize(14, 40)
        self._btn.setStyleSheet(
            "QPushButton{background:#444;color:#ccc;border:none;border-radius:3px;font-size:9px;}"
            "QPushButton:hover{background:#666;}"
        )
        self._btn.clicked.connect(self._toggle)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        sp = self.splitter()
        # Only show the collapse button on the last handle
        if sp and sp.handle(sp.count() - 1) is self:
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


# ------------------------------------------------------------------
# Shared helper: paint a duration badge over an already-drawn thumbnail
# ------------------------------------------------------------------

def _paint_duration_badge(painter: QPainter, dur: str, tx: int, ty: int, tw: int, th: int) -> None:
    if not dur:
        return
    painter.save()
    painter.setFont(QFont("", 8))
    fm = painter.fontMetrics()
    bw = fm.horizontalAdvance(dur) + 8
    bh = fm.height() + 4
    bx = tx + tw - bw - 4
    by = ty + th - bh - 4
    painter.setBrush(QBrush(QColor(0, 0, 0, 200)))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(bx, by, bw, bh, 3, 3)
    painter.setPen(QColor("#fff"))
    painter.drawText(QRect(bx, by, bw, bh), Qt.AlignmentFlag.AlignCenter, dur)
    painter.restore()


# ------------------------------------------------------------------
# Icon-grid delegate: YouTube-style card
# ------------------------------------------------------------------

class _IconDelegate(QStyledItemDelegate):
    _TW    = _TW_ICON
    _TH    = _TH_ICON
    _PAD   = _ICON_PAD
    _ITEM_W = _TW_ICON + _ICON_PAD * 2
    _ITEM_H = _TH_ICON + _ICON_TEXT_H

    def __init__(self, parent=None, filter_cat_id: UUID | None = None) -> None:
        super().__init__(parent)
        self.filter_cat_id: UUID | None = filter_cat_id
        self.active_tag_names: list[str] = []

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(self._ITEM_W, self._ITEM_H)

    def paint(self, painter, option, index) -> None:
        from PyQt6.QtWidgets import QApplication, QStyle  # noqa: PLC0415
        QApplication.style().drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, option.widget
        )

        rect: QRect  = option.rect
        path: str    = index.data(VideoListModel.ThumbPathRole) or ""
        title: str   = index.data(Qt.ItemDataRole.DisplayRole) or ""
        channel: str = index.data(VideoListModel.ChannelRole) or ""
        duration: str= index.data(VideoListModel.DurationRole) or ""
        fav: bool    = bool(index.data(VideoListModel.FavoriteRole))
        watched: bool= bool(index.data(VideoListModel.WatchedRole))
        pub_at: str  = index.data(VideoListModel.PublishedAtRole) or ""
        views: int | None = index.data(VideoListModel.ViewCountRole)
        cat_id: UUID | None = index.data(VideoListModel.CategoryIdRole)
        cat_name: str = index.data(VideoListModel.CategoryRole) or ""

        # ── Thumbnail (둥근 모서리) ──────────────────────────────────
        thumb = _load_thumb(path, self._TW, self._TH)
        tx = rect.left() + self._PAD
        ty = rect.top()
        thumb_clip = QPainterPath()
        thumb_clip.addRoundedRect(float(tx), float(ty), float(self._TW), float(self._TH), 6.0, 6.0)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipPath(thumb_clip)
        painter.drawPixmap(tx, ty, thumb)
        if watched:
            painter.setOpacity(0.4)
            painter.fillRect(QRect(tx, ty, self._TW, self._TH), QColor(0, 0, 0))
            painter.setOpacity(1.0)
        painter.restore()

        _paint_duration_badge(painter, duration, tx, ty, self._TW, self._TH)

        if fav:
            painter.save()
            painter.setFont(QFont("", 11))
            painter.setPen(QColor(_t().star_color))
            painter.drawText(
                QRect(tx + self._TW - 22, ty + 4, 20, 20),
                Qt.AlignmentFlag.AlignCenter, "★",
            )
            painter.restore()

        # ── Text area below thumbnail ──────────────────────────────
        text_x = rect.left() + self._PAD
        text_w = self._TW
        title_top = ty + self._TH + 6

        tok = _t()

        # Title (2 lines, 10pt, elided)
        painter.save()
        painter.setFont(QFont("", 10))
        painter.setPen(QColor(tok.text_primary))
        title_rect = QRect(text_x, title_top, text_w, 40)
        painter.drawText(title_rect, Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignTop, title)
        painter.restore()

        # Channel (8pt, secondary)
        painter.save()
        painter.setFont(QFont("", 8))
        painter.setPen(QColor(tok.text_secondary))
        ch_rect = QRect(text_x, title_top + 42, text_w, 16)
        painter.drawText(ch_rect, Qt.TextFlag.TextSingleLine, channel)
        painter.restore()

        # Views + relative time (3rd row, 8pt, muted)
        views_str = _fmt_views(views)
        time_str = _relative_time(pub_at)
        meta_parts = [p for p in (views_str, time_str) if p]
        meta_left = "  •  ".join(meta_parts) if meta_parts else ""

        # Category name right-aligned (only for subcategory items)
        show_cat = (
            cat_name
            and self.filter_cat_id is not None
            and cat_id != self.filter_cat_id
        )

        video_tag_names: tuple = index.data(VideoListModel.TagNamesRole) or ()
        active_set = set(self.active_tag_names)
        matching_tags = [n for n in video_tag_names if n in active_set] if active_set else []

        painter.save()
        painter.setFont(QFont("", 8))
        row3_rect = QRect(text_x, title_top + 60, text_w, 16)
        if matching_tags:
            tags_text = "  ".join(f"#{n}" for n in matching_tags[:3])
            painter.setPen(QColor(tok.accent))
            painter.drawText(row3_rect, Qt.TextFlag.TextSingleLine | Qt.AlignmentFlag.AlignLeft, tags_text)
        else:
            painter.setPen(QColor(tok.text_muted))
            if meta_left:
                painter.drawText(row3_rect, Qt.TextFlag.TextSingleLine | Qt.AlignmentFlag.AlignLeft, meta_left)
            if show_cat:
                painter.setPen(QColor(tok.accent))
                painter.drawText(row3_rect, Qt.TextFlag.TextSingleLine | Qt.AlignmentFlag.AlignRight, cat_name)
        painter.restore()

        # Selection border (drawn last, on top of everything)
        from PyQt6.QtWidgets import QStyle  # noqa: PLC0415
        if option.state & QStyle.StateFlag.State_Selected:
            painter.save()
            pen = QPen(QColor(tok.selected_border))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -1, -1))
            painter.restore()


# ------------------------------------------------------------------
# List-view delegate: YouTube list style
# ------------------------------------------------------------------

class _ListDelegate(QStyledItemDelegate):
    _TW    = _TW_LIST   # 213
    _TH    = _TH_LIST   # 120
    _ROW_H = _TH_LIST + 40  # 160 px per row (room for 3 text lines)

    def __init__(self, parent=None, filter_cat_id: UUID | None = None) -> None:
        super().__init__(parent)
        self.filter_cat_id: UUID | None = filter_cat_id
        self.active_tag_names: list[str] = []

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(option.rect.width(), self._ROW_H)

    def paint(self, painter, option, index) -> None:
        from PyQt6.QtWidgets import QApplication, QStyle  # noqa: PLC0415
        QApplication.style().drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, option.widget
        )

        rect: QRect  = option.rect
        path: str    = index.data(VideoListModel.ThumbPathRole) or ""
        title: str   = index.data(Qt.ItemDataRole.DisplayRole) or ""
        channel: str = index.data(VideoListModel.ChannelRole) or ""
        duration: str= index.data(VideoListModel.DurationRole) or ""
        fav: bool    = bool(index.data(VideoListModel.FavoriteRole))
        watched: bool= bool(index.data(VideoListModel.WatchedRole))
        pub_at: str  = index.data(VideoListModel.PublishedAtRole) or ""
        views: int | None = index.data(VideoListModel.ViewCountRole)
        cat_id: UUID | None = index.data(VideoListModel.CategoryIdRole)
        cat_name: str = index.data(VideoListModel.CategoryRole) or ""

        # ── Thumbnail (둥근 모서리) ──────────────────────────────────
        thumb = _load_thumb(path, self._TW, self._TH)
        tx = rect.left() + 6
        ty = rect.top() + (rect.height() - self._TH) // 2
        thumb_clip = QPainterPath()
        thumb_clip.addRoundedRect(float(tx), float(ty), float(self._TW), float(self._TH), 6.0, 6.0)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipPath(thumb_clip)
        painter.drawPixmap(tx, ty, thumb)
        if watched:
            painter.setOpacity(0.4)
            painter.fillRect(QRect(tx, ty, self._TW, self._TH), QColor(0, 0, 0))
            painter.setOpacity(1.0)
        painter.restore()

        _paint_duration_badge(painter, duration, tx, ty, self._TW, self._TH)

        # ── Text area ──────────────────────────────────────────────
        text_x = tx + self._TW + 12
        text_w = rect.right() - text_x - (24 if fav else 8)
        text_top = rect.top() + 8

        # Title (2 lines, 10pt, word-wrap + elide)
        painter.save()
        painter.setFont(QFont("", 10))
        fg = option.palette.color(
            option.palette.ColorGroup.Normal, option.palette.ColorRole.Text
        )
        painter.setPen(fg)
        title_rect = QRect(text_x, text_top, text_w, 40)
        painter.drawText(title_rect, Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignTop, title)
        painter.restore()

        tok = _t()

        # Channel (2nd row, 8pt, secondary)
        painter.save()
        painter.setFont(QFont("", 8))
        painter.setPen(QColor(tok.text_secondary))
        ch_rect = QRect(text_x, text_top + 44, text_w, 16)
        painter.drawText(ch_rect, Qt.TextFlag.TextSingleLine, channel)
        painter.restore()

        # Views + time (3rd row) + optional category right-aligned
        views_str = _fmt_views(views)
        time_str = _relative_time(pub_at)
        meta_parts = [p for p in (views_str, time_str) if p]
        meta_left = "  •  ".join(meta_parts) if meta_parts else ""

        show_cat = (
            cat_name
            and self.filter_cat_id is not None
            and cat_id != self.filter_cat_id
        )

        painter.save()
        painter.setFont(QFont("", 8))
        row3_rect = QRect(text_x, text_top + 62, text_w, 16)
        painter.setPen(QColor(tok.text_muted))
        if meta_left:
            painter.drawText(row3_rect, Qt.TextFlag.TextSingleLine | Qt.AlignmentFlag.AlignLeft, meta_left)
        if show_cat:
            painter.setPen(QColor(tok.accent))
            painter.drawText(row3_rect, Qt.TextFlag.TextSingleLine | Qt.AlignmentFlag.AlignRight, cat_name)
        painter.restore()

        # 태그 필터 활성 시: 해당 영상이 가진 태그 중 선택된 것만 표시
        video_tag_names: tuple = index.data(VideoListModel.TagNamesRole) or ()
        active_set = set(self.active_tag_names)
        matching_tags = [n for n in video_tag_names if n in active_set] if active_set else []
        if matching_tags:
            tags_text = "  ".join(f"#{n}" for n in matching_tags)
            painter.save()
            painter.setFont(QFont("", 8))
            painter.setPen(QColor(tok.accent))
            tag_rect = QRect(text_x, text_top + 82, text_w, 16)
            painter.drawText(tag_rect, Qt.TextFlag.TextSingleLine | Qt.AlignmentFlag.AlignLeft, tags_text)
            painter.restore()

        # Favourite star
        if fav:
            painter.save()
            painter.setFont(QFont("", 11))
            painter.setPen(QColor(tok.star_color))
            painter.drawText(
                QRect(rect.right() - 22, rect.top() + 6, 20, 20),
                Qt.AlignmentFlag.AlignCenter, "★",
            )
            painter.restore()

        # Selection border (drawn last, on top of everything)
        from PyQt6.QtWidgets import QStyle  # noqa: PLC0415
        if option.state & QStyle.StateFlag.State_Selected:
            painter.save()
            pen = QPen(QColor(tok.selected_border))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -2, -1))
            painter.restore()


# ------------------------------------------------------------------
# VideoListModel
# ------------------------------------------------------------------

class VideoListModel(QAbstractListModel):
    ThumbnailRole   = Qt.ItemDataRole.UserRole + 1
    VideoIdRole     = Qt.ItemDataRole.UserRole + 2
    DtoRole         = Qt.ItemDataRole.UserRole + 3
    ThumbPathRole   = Qt.ItemDataRole.UserRole + 4
    ChannelRole     = Qt.ItemDataRole.UserRole + 5
    DurationRole    = Qt.ItemDataRole.UserRole + 6
    FavoriteRole    = Qt.ItemDataRole.UserRole + 7
    CategoryRole    = Qt.ItemDataRole.UserRole + 8
    WatchedRole     = Qt.ItemDataRole.UserRole + 9
    PublishedAtRole = Qt.ItemDataRole.UserRole + 10
    ViewCountRole   = Qt.ItemDataRole.UserRole + 11
    CategoryIdRole  = Qt.ItemDataRole.UserRole + 12
    TagNamesRole    = Qt.ItemDataRole.UserRole + 13

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: list[VideoDTO] = []

    def set_videos(self, videos: list[VideoDTO]) -> None:
        self.beginResetModel()
        self._items = videos
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._items)

    @staticmethod
    def _fmt_dur(sec: int | None) -> str:
        if sec is None:
            return ""
        m, s = divmod(sec, 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._items):
            return None
        dto = self._items[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return dto.title
        if role == Qt.ItemDataRole.DecorationRole:
            return _load_thumb(dto.thumbnail_path, _TW_ICON, _TH_ICON)
        if role == self.ThumbnailRole:
            return _load_thumb(dto.thumbnail_path, _TW_ICON, _TH_ICON)
        if role == self.VideoIdRole:
            return dto.id
        if role == self.DtoRole:
            return dto
        if role == self.ThumbPathRole:
            return dto.thumbnail_path
        if role == self.ChannelRole:
            return dto.channel_name
        if role == self.DurationRole:
            return self._fmt_dur(dto.duration_sec)
        if role == self.FavoriteRole:
            return dto.favorite
        if role == self.CategoryRole:
            return dto.category_name
        if role == self.WatchedRole:
            return dto.watched
        if role == self.PublishedAtRole:
            return dto.published_at
        if role == self.ViewCountRole:
            return dto.view_count
        if role == self.CategoryIdRole:
            return dto.category_id
        if role == self.TagNamesRole:
            return dto.tag_names
        if role == Qt.ItemDataRole.SizeHintRole:
            return QSize(_TW_ICON + _ICON_PAD * 2, _TH_ICON + _ICON_TEXT_H)
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        return super().flags(index) | Qt.ItemFlag.ItemIsDragEnabled

    def mimeTypes(self) -> list[str]:
        return [_MIME_VIDEO_ID]

    def mimeData(self, indexes: list[QModelIndex]) -> QMimeData:
        data = QMimeData()
        ids = [str(self._items[i.row()].id) for i in indexes if i.isValid()]
        data.setData(_MIME_VIDEO_ID, QByteArray(",".join(ids).encode()))
        return data

    def supportedDragActions(self) -> Qt.DropAction:
        return Qt.DropAction.MoveAction


# ------------------------------------------------------------------
# Tag chip delegate + list widget
# ------------------------------------------------------------------

class _TagChipDelegate(QStyledItemDelegate):
    """Renders each tag as a rounded chip; right side shows count badge (click = delete)."""

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width() if option.rect.width() > 0 else 180, 28)

    def paint(self, painter, option, index) -> None:
        from PyQt6.QtWidgets import QStyle  # noqa: PLC0415
        text  = index.data(Qt.ItemDataRole.DisplayRole) or ""
        count = index.data(Qt.ItemDataRole.UserRole + 1) or 0
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        chip = option.rect.adjusted(3, 3, -3, -3)

        # Chip background
        bg = QColor("#1a4f82") if selected else QColor("#2a3a4a")
        painter.setBrush(QBrush(bg))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(chip, 10, 10)

        # Count badge (right side) — also acts as the delete hit area
        badge_w = max(20, len(str(count)) * 7 + 10)
        badge_h = chip.height() - 6
        badge_x = chip.right() - badge_w - 4
        badge_y = chip.center().y() - badge_h // 2
        badge_rect = QRect(badge_x, badge_y, badge_w, badge_h)
        badge_bg = QColor("#1a6fa0") if selected else QColor("#204060")
        painter.setBrush(QBrush(badge_bg))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(badge_rect, badge_h // 2, badge_h // 2)

        painter.setFont(QFont("", 7))
        painter.setPen(QColor("#ddeeff"))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, str(count))

        # Tag text
        painter.setFont(QFont("", 8))
        painter.setPen(QColor("#fff") if selected else QColor("#ccc"))
        painter.drawText(
            QRect(chip.left() + 8, chip.top(), badge_x - chip.left() - 10, chip.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine,
            text,
        )

        painter.restore()


class _TagListWidget(QListWidget):
    """Tag list with multi-toggle selection; count badge acts as delete button."""

    delete_requested = pyqtSignal(object)  # tag UUID (click on count badge)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setItemDelegate(_TagChipDelegate(self))
        self.setSpacing(1)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)

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


# ------------------------------------------------------------------
# Active tag filter bar (chips shown between category tree and tag list)
# ------------------------------------------------------------------

class _ActiveTagsBar(QWidget):
    """Panel directly below the category tree showing active tag-filter chips.

    Each chip shows ``#tagname ✕``; click removes that tag from the filter.
    Chips wrap onto new lines so the panel auto-sizes to its content.
    Tag colors are assigned deterministically from _TAG_PALETTE.
    """

    tag_removed = pyqtSignal(object)  # UUID

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            "background:#182430; border-radius:4px;"
        )

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 6, 0, 6)
        self._root.setSpacing(5)

        # Panel title row
        title_row = QHBoxLayout()
        title_row.setContentsMargins(8, 0, 8, 0)
        title_row.setSpacing(5)
        dot = QLabel("◆")
        dot.setStyleSheet("color:#5a9ad4; font-size:7pt; background:transparent;")
        dot.setFixedWidth(10)
        title_row.addWidget(dot)
        lbl = QLabel("활성 태그 필터")
        lbl.setStyleSheet(
            "font-size:8pt; color:#aac; font-weight:600; background:transparent;"
        )
        title_row.addWidget(lbl)
        title_row.addStretch()
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
            color     = _TAG_PALETTE[hash(name) % len(_TAG_PALETTE)]

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
            chip.setStyleSheet(
                f"QPushButton{{border:none;border-radius:10px;"
                f"background:{color};color:#fff;"
                f"padding:1px 9px;font-size:7pt;}}"
                f"QPushButton:hover{{background:#b03030;border-radius:10px;}}"
            )
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _, i=tid: self.tag_removed.emit(i))
            row.addWidget(chip)
            row_used += chip_w + 4

        if row is not None:
            row.addStretch()

        self._root.addWidget(holder)
        self._holder = holder


# ------------------------------------------------------------------
# Category tree
# ------------------------------------------------------------------

class _CategoryTree(QTreeWidget):
    url_dropped          = pyqtSignal(str, object)
    video_moved          = pyqtSignal(object, object)
    category_reparented  = pyqtSignal(object, object)   # (cat_id, new_parent_id)
    add_category_req     = pyqtSignal(object)
    rename_category_req  = pyqtSignal(object, str)
    delete_category_req  = pyqtSignal(object, str)
    refresh_metadata_req = pyqtSignal(object)   # cat_id UUID or None (=all)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDropIndicatorShown(True)
        self.setIndentation(10)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self._ext_url_drag = False
        self._vid_drag     = False
        self._cat_drag     = False
        self._drag_hover_item: QTreeWidgetItem | None = None

        # Inline rename state — store UUID, never a raw C++ item pointer
        self._is_editing            = False
        self._editing_item: QTreeWidgetItem | None = None
        self._pending_edit_cat_id: object = None   # UUID or None
        self._edit_timer = QTimer(self)
        self._edit_timer.setSingleShot(True)
        self._edit_timer.setInterval(900)
        self._edit_timer.timeout.connect(self._on_edit_timer)
        self.itemChanged.connect(self._on_item_changed)
        # Reset _is_editing if editor closes without commit (Escape)
        self.itemDelegate().closeEditor.connect(self._on_editor_closed)

    def _show_context_menu(self, pos: QPoint) -> None:
        # Cancel any pending edit: QMenu.exec() spins its own event loop, so the
        # timer would fire while the menu is open and try to edit a stale item.
        self._edit_timer.stop()
        self._pending_edit_cat_id = None

        item = self.itemAt(pos)
        cat_id = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        menu = QMenu(self)

        add_act = QAction("카테고리 추가", self)
        add_act.triggered.connect(lambda: self.add_category_req.emit(None))
        menu.addAction(add_act)

        if cat_id is not None:
            name = item.text(0)
            sub_act = QAction("하위 카테고리 추가", self)
            sub_act.triggered.connect(lambda: self.add_category_req.emit(cat_id))
            menu.addAction(sub_act)
            menu.addSeparator()
            ren_act = QAction("이름 변경 (F2)", self)
            # Capture cat_id (UUID), never the item pointer — item may be deleted
            # if any event processed during menu.exec() rebuilds the tree.
            ren_act.triggered.connect(lambda checked=False, cid=cat_id: self._start_edit_by_cat_id(cid))
            menu.addAction(ren_act)
            del_act = QAction("삭제", self)
            del_act.triggered.connect(lambda: self.delete_category_req.emit(cat_id, name))
            menu.addAction(del_act)

        if item is not None:
            menu.addSeparator()
            ref_act = QAction("메타데이터 일괄 갱신", self)
            ref_act.triggered.connect(
                lambda checked=False, cid=cat_id: self.refresh_metadata_req.emit(cid)
            )
            menu.addAction(ref_act)

        menu.exec(self.viewport().mapToGlobal(pos))

    # ── Inline rename ──────────────────────────────────────────────

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_F2:
            item = self.currentItem()
            if item is not None and item.data(0, Qt.ItemDataRole.UserRole) is not None:
                self._edit_timer.stop()
                self._pending_edit_cat_id = None
                self._start_edit(item)
                return
        if self._is_editing and event.key() == Qt.Key.Key_Escape:
            self._is_editing = False
            self._editing_item = None
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        # Capture selection state BEFORE super() changes it — edit timer only fires
        # when clicking an item that is already the current (selected) item.
        already_current = False
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.pos())
            already_current = item is not None and item is self.currentItem()

        super().mousePressEvent(event)

        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.pos())
            cid = item.data(0, Qt.ItemDataRole.UserRole) if item else None
            if cid is not None and already_current:
                self._pending_edit_cat_id = cid
                self._edit_timer.start()
            else:
                self._edit_timer.stop()
                self._pending_edit_cat_id = None

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        if self._pending_edit_cat_id is not None:
            item = self.itemAt(event.pos())
            cur_cid = item.data(0, Qt.ItemDataRole.UserRole) if item else None
            if cur_cid != self._pending_edit_cat_id:
                self._edit_timer.stop()
                self._pending_edit_cat_id = None

    def _find_item(self, cat_id) -> QTreeWidgetItem | None:
        """Find the live tree item for cat_id, or None if it no longer exists."""
        def _recurse(parent: QTreeWidgetItem) -> QTreeWidgetItem | None:
            for i in range(parent.childCount()):
                child = parent.child(i)
                if child.data(0, Qt.ItemDataRole.UserRole) == cat_id:
                    return child
                found = _recurse(child)
                if found:
                    return found
            return None

        for i in range(self.topLevelItemCount()):
            top = self.topLevelItem(i)
            if top.data(0, Qt.ItemDataRole.UserRole) == cat_id:
                return top
            found = _recurse(top)
            if found:
                return found
        return None

    def _on_edit_timer(self) -> None:
        cid = self._pending_edit_cat_id
        self._pending_edit_cat_id = None
        if cid is None:
            return
        # Look up the live item; it may have been deleted if the tree was rebuilt
        item = self._find_item(cid)
        if item is not None:
            self._start_edit(item)

    def _start_edit_by_cat_id(self, cat_id) -> None:
        item = self._find_item(cat_id)
        if item is not None:
            self._start_edit(item)

    def _start_edit(self, item: QTreeWidgetItem) -> None:
        cat_id = item.data(0, Qt.ItemDataRole.UserRole)
        if cat_id is None:
            return
        self._editing_item = item
        self._is_editing = True
        # blockSignals prevents setFlags from emitting itemChanged, which would
        # otherwise fire _on_item_changed → rename_category_req → _refresh_categories
        # → categories_changed → tree.clear() → item deleted → editItem crash.
        self.blockSignals(True)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.blockSignals(False)
        try:
            self.editItem(item, 0)
        except RuntimeError:
            self._is_editing = False
            self._editing_item = None

    def _on_item_changed(self, item: QTreeWidgetItem, _column: int) -> None:
        if not self._is_editing or item is not self._editing_item:
            return
        self._is_editing = False
        self.blockSignals(True)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.blockSignals(False)
        new_name = item.text(0).strip()
        cat_id = item.data(0, Qt.ItemDataRole.UserRole)
        self._editing_item = None
        if new_name and cat_id is not None:
            self.rename_category_req.emit(cat_id, new_name)

    def _on_editor_closed(self, _editor, _hint) -> None:
        # Fires for both commit and cancel; reset flag on cancel (commit already reset it)
        if self._is_editing:
            self._is_editing = False
            if self._editing_item is not None:
                try:
                    self.blockSignals(True)
                    self._editing_item.setFlags(
                        self._editing_item.flags() & ~Qt.ItemFlag.ItemIsEditable
                    )
                    self.blockSignals(False)
                except RuntimeError:
                    self.blockSignals(False)
            self._editing_item = None

    # ── Drag-and-drop ──────────────────────────────────────────────

    def startDrag(self, supported_actions) -> None:
        # Cancel any pending edit — startDrag() blocks in its own event loop
        self._edit_timer.stop()
        self._pending_edit_cat_id = None
        item = self.currentItem()
        if item is None:
            return
        cat_id = item.data(0, Qt.ItemDataRole.UserRole)
        if cat_id is None:
            return  # "전체 영상" is not draggable
        mime = QMimeData()
        mime.setData(_MIME_CAT_ID, QByteArray(str(cat_id).encode()))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event) -> None:
        mime = event.mimeData()
        self._cat_drag     = mime.hasFormat(_MIME_CAT_ID)
        self._vid_drag     = mime.hasFormat(_MIME_VIDEO_ID)
        self._ext_url_drag = bool(_url_from_mime(mime))
        if self._cat_drag or self._vid_drag or self._ext_url_drag:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if not (self._cat_drag or self._vid_drag or self._ext_url_drag):
            event.ignore()
            return
        item = self.itemAt(event.position().toPoint())
        if item:
            self.setCurrentItem(item)
            self._drag_hover_item = item
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._drag_hover_item = None
        self._ext_url_drag = False
        self._vid_drag     = False
        self._cat_drag     = False
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        mime = event.mimeData()
        pos  = event.position().toPoint()
        # itemAt() misses the item when the cursor lands in padding between items;
        # fall back to the last item tracked in dragMoveEvent.
        item = self.itemAt(pos) or self._drag_hover_item

        self._ext_url_drag    = False
        self._vid_drag        = False
        self._cat_drag        = False
        self._drag_hover_item = None

        if mime.hasFormat(_MIME_CAT_ID):
            cat_id = UUID(bytes(mime.data(_MIME_CAT_ID)).decode())
            if item is None:
                new_parent_id = None
            else:
                target_cat_id = item.data(0, Qt.ItemDataRole.UserRole)
                ind = self.dropIndicatorPosition()
                if target_cat_id is None:
                    # Dropped on "전체 영상" → root
                    new_parent_id = None
                elif ind == QAbstractItemView.DropIndicatorPosition.OnItem:
                    # Dropped onto item → become its child
                    new_parent_id = target_cat_id
                else:
                    # Dropped above/below → become sibling (same parent as target)
                    new_parent_id = item.data(0, _CAT_PARENT_ROLE)
            self.category_reparented.emit(cat_id, new_parent_id)
            event.acceptProposedAction()
            return

        cat_id = item.data(0, Qt.ItemDataRole.UserRole) if item else None

        if mime.hasFormat(_MIME_VIDEO_ID):
            raw = bytes(mime.data(_MIME_VIDEO_ID)).decode()
            for vid in raw.split(","):
                vid = vid.strip()
                if vid:
                    self.video_moved.emit(UUID(vid), cat_id)
            event.acceptProposedAction()
        else:
            url = _url_from_mime(mime)
            if url:
                self.url_dropped.emit(url, cat_id)
                event.acceptProposedAction()
            else:
                event.ignore()


# ------------------------------------------------------------------
# Preview pane (right side)
# ------------------------------------------------------------------

class _PreviewPane(QWidget):
    """Right-side preview: inline player + video info + clickable tags."""

    detail_requested     = pyqtSignal(object)
    tag_filter_requested = pyqtSignal(object, str)
    download_requested   = pyqtSignal(str, str, object)

    def __init__(self, vm: LibraryViewModel, parent=None) -> None:
        super().__init__(parent)
        self._vm = vm
        self._current_dto: VideoDTO | None = None
        self._setup()

    def _setup(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        self._player = InlinePlayer(self)
        self._player.playback_failed.connect(self._on_play_failed)
        self._player.download_requested.connect(self.download_requested.emit)
        layout.addWidget(self._player)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        info_widget = QWidget()
        self._info_layout = QVBoxLayout(info_widget)
        self._info_layout.setContentsMargins(0, 0, 0, 0)
        self._info_layout.setSpacing(4)

        self._title_lbl = QLabel()
        self._title_lbl.setWordWrap(True)
        title_font = QFont()
        title_font.setPointSize(10)
        title_font.setBold(True)
        self._title_lbl.setFont(title_font)
        self._info_layout.addWidget(self._title_lbl)

        self._meta_lbl = QLabel()
        self._meta_lbl.setWordWrap(True)
        tok = _t()
        self._meta_lbl.setStyleSheet(
            f"color:{tok.text_secondary};font-size:8pt;"
        )
        self._info_layout.addWidget(self._meta_lbl)

        self._tags_container = QWidget()
        self._tags_container_layout = QVBoxLayout(self._tags_container)
        self._tags_container_layout.setContentsMargins(0, 0, 0, 0)
        self._tags_container_layout.setSpacing(0)
        self._info_layout.addWidget(self._tags_container)

        self._info_layout.addStretch()
        scroll.setWidget(info_widget)
        layout.addWidget(scroll, stretch=1)

        # 아이콘 전용 액션 버튼 (텍스트 레이블 없음)
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 4, 0, 0)
        btn_row.setSpacing(6)

        def _icon_btn(tooltip: str) -> QPushButton:
            b = QPushButton()
            b.setToolTip(tooltip)
            b.setFixedSize(28, 28)
            b.setEnabled(False)
            return b

        self._btn_download = _icon_btn("다운로드")
        self._btn_download.setText("⬇")
        self._btn_browser  = _icon_btn("브라우저에서 열기")
        self._btn_browser.setText("🌐")
        self._btn_fav      = _icon_btn("즐겨찾기 토글")
        self._btn_fav.setText("☆")
        self._btn_detail   = _icon_btn("상세보기 (더블클릭)")
        self._btn_detail.setText("⊕")

        self._btn_browser.clicked.connect(self._on_browser)
        self._btn_detail.clicked.connect(self._on_detail)
        self._btn_fav.clicked.connect(self._on_fav_toggle)
        self._btn_download.clicked.connect(self._on_download)

        for b in (self._btn_download, self._btn_browser, self._btn_fav, self._btn_detail):
            btn_row.addWidget(b)
        btn_row.addStretch()

        layout.addLayout(btn_row)
        self._show_empty()

    def show_video(self, dto: VideoDTO) -> None:
        self._current_dto = dto
        detail = self._vm.get_video_detail(dto.id)

        pw = max(self._player.width(), _TW_PREV)
        ph = pw * 9 // 16
        thumb = _load_thumb(dto.thumbnail_path, pw, ph)
        downloads = detail.downloads if detail else []
        self._player.load(dto.url, downloads, thumbnail_pixmap=thumb, title=dto.title)

        self._title_lbl.setText(dto.title)

        meta_parts = []
        if dto.channel_name:
            meta_parts.append(f"채널: {dto.channel_name}")
        if dto.duration_sec is not None:
            m, s = divmod(dto.duration_sec, 60)
            h, m = divmod(m, 60)
            dur = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
            meta_parts.append(f"재생시간: {dur}")
        if detail and detail.published_at:
            meta_parts.append(f"업로드: {detail.published_at}")
        if detail and detail.view_count is not None:
            meta_parts.append(f"조회수: {detail.view_count:,}회")
        if dto.category_name:
            meta_parts.append(f"카테고리: {dto.category_name}")
        self._meta_lbl.setText("\n".join(meta_parts))

        _clear_layout(self._tags_container_layout)
        if detail and detail.tags:
            tag_ids_map = {t.name: t.id for t in self._vm.tags}
            flow = _TagFlow(detail.tags, tag_ids_map, self._tags_container)
            flow.tag_clicked.connect(self.tag_filter_requested.emit)
            self._tags_container_layout.addWidget(flow)

        self._btn_browser.setEnabled(True)
        self._btn_detail.setEnabled(True)
        self._btn_fav.setEnabled(True)
        self._btn_download.setEnabled(True)
        self._btn_fav.setText("★" if dto.favorite else "☆")

    def clear(self) -> None:
        self._show_empty()

    def stop_player(self) -> None:
        self._player.stop()

    def get_playback_state(self) -> tuple[bool, int]:
        """(재생 중 여부, 현재 위치 ms) 반환."""
        return self._player.is_playing(), self._player.position_ms

    @property
    def has_video(self) -> bool:
        """선택된 영상이 있으면 True."""
        return self._current_dto is not None

    def _show_empty(self) -> None:
        self._current_dto = None
        self._player.load("", [], None)
        self._title_lbl.setText("영상을 선택하세요")
        self._meta_lbl.clear()
        _clear_layout(self._tags_container_layout)
        for b in (self._btn_browser, self._btn_detail, self._btn_fav, self._btn_download):
            b.setEnabled(False)

    def _on_browser(self) -> None:
        if self._current_dto:
            QDesktopServices.openUrl(QUrl(self._current_dto.url))

    def _on_detail(self) -> None:
        if self._current_dto:
            self.detail_requested.emit(self._current_dto)

    def _on_fav_toggle(self) -> None:
        if self._current_dto:
            self._vm.toggle_favorite(self._current_dto.id)

    def _on_download(self) -> None:
        if self._current_dto:
            self.download_requested.emit(
                self._current_dto.url, self._current_dto.title, None
            )

    def _on_play_failed(self, _err: str) -> None:
        if self._current_dto:
            QDesktopServices.openUrl(QUrl(self._current_dto.url))


# ------------------------------------------------------------------
# Library panel (3-pane: categories+tags | video list | preview)
# ------------------------------------------------------------------

class LibraryPanel(QWidget):
    video_selected     = pyqtSignal(object)
    download_requested = pyqtSignal(str, str, object)

    def __init__(self, vm: LibraryViewModel, clip_vm=None, download_vm=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vm = vm
        self._clip_vm = clip_vm
        self._download_vm = download_vm
        self._all_tags: list = []
        self._active_tag_ids: set[UUID] = set()
        self._icon_delegate = _IconDelegate()
        self._list_delegate = _ListDelegate()
        self._refresh_dlg: QProgressDialog | None = None
        # 내비게이션 히스토리 (최대 50개 상태 보존)
        self._nav_history: list[dict] = []
        self._is_restoring: bool = False
        self._setup_ui()
        self._connect_signals()
        vm.load()

    # ── Layout ─────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        outer_splitter = _PreviewSplitter(Qt.Orientation.Horizontal, self)

        # ── 1. Left: categories + tag list ──
        left = QWidget()
        left.setMaximumWidth(220)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(2)

        # 카테고리 추가는 트리 우클릭 메뉴로 이동 (버튼 제거)
        left_layout.addSpacing(4)

        left_splitter = QSplitter(Qt.Orientation.Vertical)

        # 카테고리 컨테이너: 트리 + 선택된 태그 바 (태그 리스트 위치 고정)
        cat_container = QWidget()
        cat_layout = QVBoxLayout(cat_container)
        cat_layout.setContentsMargins(0, 0, 0, 0)
        cat_layout.setSpacing(2)
        self._cat_tree = _CategoryTree()
        self._cat_tree.setHeaderHidden(True)
        self._apply_cat_tree_style()
        cat_layout.addWidget(self._cat_tree, stretch=1)
        self._active_tags_bar = _ActiveTagsBar()
        cat_layout.addWidget(self._active_tags_bar)
        left_splitter.addWidget(cat_container)

        tag_section = QWidget()
        tag_section_layout = QVBoxLayout(tag_section)
        tag_section_layout.setContentsMargins(0, 0, 0, 0)
        tag_section_layout.setSpacing(4)

        popular_hdr = QLabel("인기 태그")
        popular_hdr.setStyleSheet(
            f"font-size:8pt;color:{_t().text_muted};font-weight:600;padding:2px 4px;"
        )
        tag_section_layout.addWidget(popular_hdr)

        self._popular_tags_widget = QWidget()
        self._popular_tags_layout = QVBoxLayout(self._popular_tags_widget)
        self._popular_tags_layout.setContentsMargins(4, 0, 4, 4)
        self._popular_tags_layout.setSpacing(2)
        tag_section_layout.addWidget(self._popular_tags_widget)

        tag_hdr = QLabel("전체 태그")
        tag_hdr.setStyleSheet(f"font-size:8pt;color:{_t().text_muted};padding:2px 4px;")
        tag_section_layout.addWidget(tag_hdr)

        self._tag_filter_input = QLineEdit()
        self._tag_filter_input.setPlaceholderText("태그 검색...")
        self._tag_filter_input.setClearButtonEnabled(True)
        self._tag_filter_input.setStyleSheet("font-size:8pt;")
        tag_section_layout.addWidget(self._tag_filter_input)

        self._tag_list = _TagListWidget()
        tag_section_layout.addWidget(self._tag_list)

        left_splitter.addWidget(tag_section)
        left_splitter.setStretchFactor(0, 2)
        left_splitter.setStretchFactor(1, 1)

        left_layout.addWidget(left_splitter)

        # ── 스마트 폴더 섹션 ──
        sf_header_row = QHBoxLayout()
        sf_header_row.setContentsMargins(4, 4, 4, 2)
        sf_hdr_lbl = QLabel("스마트 폴더")
        sf_hdr_lbl.setStyleSheet(f"font-size:8pt;color:{_t().text_muted};")
        sf_header_row.addWidget(sf_hdr_lbl)
        sf_header_row.addStretch()
        sf_add_btn = QPushButton("+")
        sf_add_btn.setFixedSize(18, 18)
        sf_add_btn.setToolTip("현재 필터를 스마트 폴더로 저장")
        sf_add_btn.setFlat(True)
        sf_add_btn.clicked.connect(self._on_save_smart_folder)
        sf_header_row.addWidget(sf_add_btn)
        left_layout.addLayout(sf_header_row)

        self._sf_list = QListWidget()
        self._sf_list.setMaximumHeight(120)
        self._sf_list.setStyleSheet("font-size:8pt;")
        self._sf_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._sf_list.itemClicked.connect(self._on_smart_folder_clicked)
        self._sf_list.customContextMenuRequested.connect(self._on_sf_context_menu)
        left_layout.addWidget(self._sf_list)

        self._smart_folders: list = []
        self._load_smart_folders_ui()

        outer_splitter.addWidget(left)

        # ── 2. Centre: nav stack ──
        self._nav_stack = QStackedWidget()

        centre_content = QWidget()
        centre_layout = QVBoxLayout(centre_content)
        centre_layout.setContentsMargins(0, 0, 0, 0)
        centre_layout.setSpacing(0)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(4, 4, 4, 4)
        toolbar.setSpacing(4)

        self._btn_icon  = QToolButton()
        self._btn_icon.setText("⊞")
        self._btn_list  = QToolButton()
        self._btn_list.setText("☰")
        self._btn_table = QToolButton()
        self._btn_table.setText("⊟")
        for btn in (self._btn_icon, self._btn_list, self._btn_table):
            btn.setCheckable(True)
            btn.setFixedSize(28, 28)
        self._btn_icon.setChecked(True)
        self._view_group = QButtonGroup(self)
        self._view_group.addButton(self._btn_icon,  _VIEW_ICON)
        self._view_group.addButton(self._btn_list,  _VIEW_LIST)
        self._view_group.addButton(self._btn_table, _VIEW_DETAIL)
        toolbar.addWidget(self._btn_icon)
        toolbar.addWidget(self._btn_list)
        toolbar.addWidget(self._btn_table)
        toolbar.addSpacing(12)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("검색...")
        self._search_box.setClearButtonEnabled(True)
        toolbar.addWidget(self._search_box, stretch=1)

        # 정렬 옵션
        toolbar.addSpacing(8)
        self._sort_combo = QComboBox()
        self._sort_combo.addItem("최신순", ("created_at", False))
        self._sort_combo.addItem("오래된순", ("created_at", True))
        self._sort_combo.addItem("제목순 ↑", ("title", True))
        self._sort_combo.addItem("제목순 ↓", ("title", False))
        self._sort_combo.addItem("채널순 ↑", ("channel_name", True))
        self._sort_combo.addItem("채널순 ↓", ("channel_name", False))
        self._sort_combo.addItem("길이 길순", ("duration_sec", False))
        self._sort_combo.addItem("길이 짧순", ("duration_sec", True))
        self._sort_combo.setFixedWidth(90)
        toolbar.addWidget(self._sort_combo)

        toolbar.addSpacing(8)
        self._btn_preview = QToolButton()
        self._btn_preview.setText("⊡")
        self._btn_preview.setToolTip("미리보기 패널 열기/닫기")
        self._btn_preview.setCheckable(True)
        self._btn_preview.setChecked(False)
        self._btn_preview.setFixedSize(28, 28)
        toolbar.addWidget(self._btn_preview)

        centre_layout.addLayout(toolbar)

        self._view_stack = QStackedWidget()
        self._model = VideoListModel()

        # Icon grid
        self._icon_view = _VideoListView()
        self._icon_view.setModel(self._model)
        self._icon_view.setViewMode(QListView.ViewMode.IconMode)
        self._icon_view.setResizeMode(QListView.ResizeMode.Adjust)
        self._icon_view.setUniformItemSizes(True)
        self._icon_view.setSpacing(14)
        self._icon_view.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self._icon_view.setIconSize(QSize(_TW_ICON, _TH_ICON))
        self._icon_view.setItemDelegate(self._icon_delegate)
        self._icon_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._icon_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._view_stack.addWidget(self._icon_view)

        # List view
        self._list_view = _VideoListView()
        self._list_view.setModel(self._model)
        self._list_view.setItemDelegate(self._list_delegate)
        self._list_view.setViewMode(QListView.ViewMode.ListMode)
        self._list_view.setUniformItemSizes(True)
        self._list_view.setSpacing(2)
        self._list_view.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self._list_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._view_stack.addWidget(self._list_view)

        # Detail table
        self._table = QTableWidget()
        self._table.setColumnCount(9)
        self._table.setHorizontalHeaderLabels(
            ["제목", "채널", "재생시간", "카테고리", "★", "✓", "등록 일시", "영상", "음원"]
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._view_stack.addWidget(self._table)

        centre_layout.addWidget(self._view_stack, stretch=1)
        self._nav_stack.addWidget(centre_content)

        self._detail_widget = VideoDetailWidget(clip_vm=self._clip_vm)
        self._nav_stack.addWidget(self._detail_widget)

        outer_splitter.addWidget(self._nav_stack)

        # ── 3. Right: preview pane ──
        self._preview = _PreviewPane(self._vm)
        self._preview.setMinimumWidth(320)
        outer_splitter.addWidget(self._preview)

        outer_splitter.setStretchFactor(0, 0)
        outer_splitter.setStretchFactor(1, 1)
        outer_splitter.setStretchFactor(2, 0)
        outer_splitter.setSizes([200, 700, 0])
        self._preview.hide()

        self._outer_splitter = outer_splitter

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(outer_splitter)

    # ── Signal wiring ──────────────────────────────────────────────

    def _connect_signals(self) -> None:
        self._vm.videos_changed.connect(self._on_videos_changed)
        self._vm.categories_changed.connect(self._on_categories_changed)
        self._vm.tags_changed.connect(self._on_tags_changed)
        ThemeManager.instance().theme_changed.connect(lambda _: self._apply_cat_tree_style())

        self._view_group.idClicked.connect(self._switch_view)
        self._search_box.textChanged.connect(self._vm.set_search_text)
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        self._btn_preview.clicked.connect(self._toggle_preview)

        self._cat_tree.currentItemChanged.connect(self._on_cat_selection_changed)
        self._cat_tree.url_dropped.connect(self._on_url_dropped)
        self._cat_tree.video_moved.connect(self._on_video_moved)
        self._cat_tree.category_reparented.connect(self._on_category_reparented)
        self._cat_tree.add_category_req.connect(self._on_add_category)
        self._cat_tree.rename_category_req.connect(self._on_rename_category)
        self._cat_tree.delete_category_req.connect(self._on_delete_category)
        self._cat_tree.refresh_metadata_req.connect(self._on_refresh_metadata)
        self._vm.metadata_refresh_progress.connect(self._on_refresh_progress)
        self._vm.metadata_refresh_finished.connect(self._on_refresh_finished)
        self._tag_list.itemClicked.connect(self._on_tag_clicked)
        self._tag_list.delete_requested.connect(self._on_tag_delete_requested)
        self._tag_filter_input.textChanged.connect(self._on_tag_filter_text_changed)
        self._active_tags_bar.tag_removed.connect(self._on_active_tag_removed)

        self._icon_view.clicked.connect(
            lambda idx: self._on_item_clicked(idx, self._icon_view)
        )
        self._list_view.clicked.connect(
            lambda idx: self._on_item_clicked(idx, self._list_view)
        )
        self._icon_view.doubleClicked.connect(self._on_double_click)
        self._list_view.doubleClicked.connect(self._on_double_click)
        self._icon_view.empty_clicked.connect(self._on_empty_clicked)
        self._list_view.empty_clicked.connect(self._on_empty_clicked)
        self._icon_view.url_dropped.connect(self._on_list_url_dropped)
        self._list_view.url_dropped.connect(self._on_list_url_dropped)
        self._icon_view.customContextMenuRequested.connect(
            lambda pos: self._show_video_menu(pos, self._icon_view)
        )
        self._list_view.customContextMenuRequested.connect(
            lambda pos: self._show_video_menu(pos, self._list_view)
        )

        self._table.clicked.connect(self._on_table_clicked)
        self._table.doubleClicked.connect(self._on_table_double_click)
        self._table.customContextMenuRequested.connect(self._show_table_menu)

        self._preview.detail_requested.connect(self._on_preview_detail_requested)
        self._preview.tag_filter_requested.connect(self._on_tag_filter_requested)
        self._preview.download_requested.connect(self.download_requested.emit)

        self._detail_widget.back_requested.connect(self._on_back_from_detail)
        self._detail_widget.tag_filter_requested.connect(self._on_tag_filter_requested)
        self._detail_widget.tags_updated.connect(self._on_detail_tags_updated)
        self._detail_widget.download_requested.connect(self.download_requested.emit)

        # Ctrl+휠 뷰 전환 & 마우스 BackButton 히스토리 이벤트 필터
        for w in (self._icon_view, self._list_view, self._table):
            viewport = getattr(w, "viewport", None)
            if viewport:
                viewport().installEventFilter(self)
            w.installEventFilter(self)

    # ── VM → UI ────────────────────────────────────────────────────

    def _on_videos_changed(self) -> None:
        self._model.set_videos(self._vm.videos)
        self._refresh_table()

    def _on_categories_changed(self) -> None:
        self._cat_tree.clear()
        all_item = QTreeWidgetItem(["전체 영상"])
        all_item.setData(0, Qt.ItemDataRole.UserRole, None)
        self._cat_tree.addTopLevelItem(all_item)

        cats = self._vm.categories
        id_to_item: dict[UUID, QTreeWidgetItem] = {}
        for cat in cats:
            item = QTreeWidgetItem([cat.name])
            item.setData(0, Qt.ItemDataRole.UserRole, cat.id)
            item.setData(0, _CAT_PARENT_ROLE, cat.parent_id)
            id_to_item[cat.id] = item

        for cat in cats:
            item = id_to_item[cat.id]
            if cat.parent_id and cat.parent_id in id_to_item:
                id_to_item[cat.parent_id].addChild(item)
            else:
                self._cat_tree.addTopLevelItem(item)

        self._cat_tree.expandAll()

    def _on_tags_changed(self) -> None:
        self._all_tags = sorted(self._vm.tags, key=lambda t: t.name)
        # Drop active IDs that no longer exist (tag was deleted)
        existing = {t.id for t in self._all_tags}
        self._active_tag_ids &= existing
        self._refresh_tag_display()

    def _refresh_tag_display(self) -> None:
        from config.settings import load_hidden_tag_names  # noqa: PLC0415
        hidden_names = load_hidden_tag_names()
        filter_text = self._tag_filter_input.text().strip().lower()
        self._tag_list.blockSignals(True)
        self._tag_list.clear()
        for tag in self._all_tags:
            if tag.name in hidden_names:
                continue
            if filter_text and filter_text not in tag.name.lower():
                continue
            item = QListWidgetItem(f"#{tag.name}")
            item.setData(Qt.ItemDataRole.UserRole, tag.id)
            item.setData(Qt.ItemDataRole.UserRole + 1, tag.count)
            self._tag_list.addItem(item)
            if tag.id in self._active_tag_ids:
                item.setSelected(True)
        self._tag_list.blockSignals(False)
        self._refresh_active_tags_bar()

    def _on_tag_filter_text_changed(self) -> None:
        self._refresh_tag_display()

    def _apply_cat_tree_style(self) -> None:
        tok = _t()
        self._cat_tree.setStyleSheet(f"""
            QTreeWidget {{
                background: transparent;
                border: none;
                outline: none;
            }}
            QTreeWidget::item {{
                padding: 4px 6px;
                border-radius: 4px;
            }}
            QTreeWidget::item:selected {{
                background: {tok.accent};
                color: {tok.text_on_accent};
                font-weight: 700;
                border-radius: 4px;
                border: 1px solid {tok.accent_hover};
                padding-left: 8px;
            }}
            QTreeWidget::item:hover:!selected {{
                background: {tok.bg_overlay};
            }}
        """)

    def _refresh_active_tags_bar(self) -> None:
        tags = [(t.id, t.name) for t in self._all_tags if t.id in self._active_tag_ids]
        self._active_tags_bar.refresh(tags)
        self._refresh_popular_tags()

    def _refresh_popular_tags(self) -> None:
        from config.settings import load_hidden_tag_names  # noqa: PLC0415
        hidden_names = load_hidden_tag_names()
        while self._popular_tags_layout.count():
            item = self._popular_tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        top_tags = sorted(
            (t for t in self._all_tags if t.name not in hidden_names),
            key=lambda t: -t.count,
        )[:5]
        for tag in top_tags:
            selected = tag.id in self._active_tag_ids
            color = _TAG_PALETTE[hash(tag.name) % len(_TAG_PALETTE)]
            bg = color if selected else "#2a3a4a"
            fg = "#fff" if selected else "#ccc"
            btn = QPushButton(f"#{tag.name}  {tag.count}")
            btn.setFixedHeight(26)
            btn.setStyleSheet(
                f"QPushButton{{border:none;border-radius:10px;"
                f"background:{bg};color:{fg};"
                f"padding:2px 10px;font-size:9pt;text-align:left;}}"
                f"QPushButton:hover{{background:{color};color:#fff;}}"
            )
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, tid=tag.id: self._on_popular_tag_clicked(tid))
            self._popular_tags_layout.addWidget(btn)

    def _on_popular_tag_clicked(self, tag_id: UUID) -> None:
        if not self._is_restoring:
            self._push_nav_state()
        if tag_id in self._active_tag_ids:
            self._active_tag_ids.discard(tag_id)
        else:
            self._active_tag_ids.add(tag_id)
        self._tag_list.blockSignals(True)
        for i in range(self._tag_list.count()):
            item = self._tag_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == tag_id:
                item.setSelected(tag_id in self._active_tag_ids)
                break
        self._tag_list.blockSignals(False)
        self._vm.set_tag_filter(list(self._active_tag_ids))
        self._refresh_active_tags_bar()
        self._update_delegate_tags()
        if self._active_tag_ids:
            self._cat_tree.clearSelection()

    def _update_delegate_tags(self) -> None:
        names = [t.name for t in self._all_tags if t.id in self._active_tag_ids]
        self._icon_delegate.active_tag_names = names
        self._list_delegate.active_tag_names = names
        self._icon_view.viewport().update()
        self._list_view.viewport().update()

    def _on_tag_delete_requested(self, tag_id: UUID) -> None:
        tag = next((t for t in self._vm.tags if t.id == tag_id), None)
        if tag is None:
            return
        reply = QMessageBox.question(
            self, "태그 삭제",
            f"태그 '#{tag.name}'을(를) 삭제하시겠습니까?\n모든 영상에서 이 태그가 제거됩니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._vm.delete_tag(tag_id)

    # ── Table ──────────────────────────────────────────────────────

    def _cat_path(self, cat_id: UUID | None) -> str:
        if cat_id is None:
            return ""
        cats_by_id = {c.id: c for c in self._vm.categories}
        parts: list[str] = []
        current = cats_by_id.get(cat_id)
        while current:
            parts.insert(0, current.name)
            current = cats_by_id.get(current.parent_id) if current.parent_id else None
        return " > ".join(parts)

    def _refresh_table(self) -> None:
        _AUDIO_FMTS = frozenset(("mp3", "m4a", "aac", "flac", "opus", "wav", "ogg"))

        def _fmt(s):
            if s is None:
                return "—"
            m, sec = divmod(s, 60)
            h, m = divmod(m, 60)
            return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"

        videos = self._vm.videos
        self._table.setRowCount(len(videos))
        for row, dto in enumerate(videos):
            t = QTableWidgetItem(dto.title)
            t.setData(Qt.ItemDataRole.UserRole, dto.id)
            self._table.setItem(row, 0, t)
            self._table.setItem(row, 1, QTableWidgetItem(dto.channel_name))
            self._table.setItem(row, 2, QTableWidgetItem(_fmt(dto.duration_sec)))
            self._table.setItem(row, 3, QTableWidgetItem(self._cat_path(dto.category_id)))
            fav = QTableWidgetItem("★" if dto.favorite else "")
            fav.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 4, fav)
            wtc = QTableWidgetItem("✓" if dto.watched else "")
            wtc.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 5, wtc)
            # 등록 일시
            self._table.setItem(row, 6, QTableWidgetItem(dto.created_at or "—"))
            # 영상/음원 다운로드 여부 (lazy: 개별 detail 조회)
            detail = self._vm.get_video_detail(dto.id)
            has_video = has_audio = False
            if detail:
                for dl in detail.downloads:
                    fmt_lower = (dl.fmt or "").lower()
                    if fmt_lower in _AUDIO_FMTS:
                        has_audio = True
                    elif fmt_lower:
                        has_video = True
            v_item = QTableWidgetItem("✓" if has_video else "—")
            v_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 7, v_item)
            a_item = QTableWidgetItem("✓" if has_audio else "—")
            a_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 8, a_item)
        self._table.resizeColumnsToContents()

    # ── View mode ──────────────────────────────────────────────────

    def _switch_view(self, view_id: int) -> None:
        self._view_stack.setCurrentIndex(view_id)
        btn = self._view_group.button(view_id)
        if btn is not None and not btn.isChecked():
            btn.setChecked(True)

    # ── Category / tag selection ───────────────────────────────────

    def current_category_id(self) -> UUID | None:
        item = self._cat_tree.currentItem()
        if item is None:
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)

    def _on_cat_selection_changed(self, current, _previous) -> None:
        if current is None:
            return
        if not self._is_restoring:
            self._push_nav_state()
        cat_id = current.data(0, Qt.ItemDataRole.UserRole)
        self._active_tag_ids.clear()
        self._tag_list.blockSignals(True)
        self._tag_list.clearSelection()
        self._tag_list.blockSignals(False)
        self._refresh_active_tags_bar()
        self._update_delegate_tags()
        self._vm.set_category_filter(cat_id)  # also clears tag filter internally
        # Update delegates so they know which category is selected (for subcategory label)
        self._icon_delegate.filter_cat_id = cat_id
        self._list_delegate.filter_cat_id = cat_id
        self._icon_view.viewport().update()
        self._list_view.viewport().update()

    def _on_tag_clicked(self, item: QListWidgetItem) -> None:
        if not self._is_restoring:
            self._push_nav_state()
        tag_id: UUID = item.data(Qt.ItemDataRole.UserRole)
        # With MultiSelection, isSelected() already reflects post-click state
        if item.isSelected():
            self._active_tag_ids.add(tag_id)
        else:
            self._active_tag_ids.discard(tag_id)
        self._vm.set_tag_filter(list(self._active_tag_ids))
        self._refresh_active_tags_bar()
        self._update_delegate_tags()
        if self._active_tag_ids:
            self._cat_tree.clearSelection()

    def _on_active_tag_removed(self, tag_id: UUID) -> None:
        """Called when ✕ is clicked on a chip in the active tags bar."""
        if not self._is_restoring:
            self._push_nav_state()
        self._active_tag_ids.discard(tag_id)
        self._vm.set_tag_filter(list(self._active_tag_ids))
        self._tag_list.blockSignals(True)
        for i in range(self._tag_list.count()):
            item = self._tag_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == tag_id:
                item.setSelected(False)
                break
        self._tag_list.blockSignals(False)
        self._refresh_active_tags_bar()
        self._update_delegate_tags()

    def _on_tag_filter_requested(self, tag_id: UUID, _tag_name: str) -> None:
        """Called when a tag chip is clicked in the preview pane or detail view."""
        if not self._is_restoring:
            self._push_nav_state()
        self._active_tag_ids = {tag_id}
        self._vm.set_tag_filter([tag_id])
        self._tag_list.blockSignals(True)
        self._tag_list.clearSelection()
        for i in range(self._tag_list.count()):
            item = self._tag_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == tag_id:
                item.setSelected(True)
                break
        self._tag_list.blockSignals(False)
        self._refresh_active_tags_bar()
        self._update_delegate_tags()
        self._cat_tree.clearSelection()
        if self._nav_stack.currentIndex() == 1:
            self._on_back_from_detail()

    # ── In-place navigation ────────────────────────────────────────

    def _open_detail(self, video_id: UUID) -> None:
        detail = self._vm.get_video_detail(video_id)
        if detail is None:
            return
        if not self._is_restoring:
            self._push_nav_state()
        tag_ids = {t.name: t.id for t in self._vm.tags}
        # Bug A: 미리보기 재생 상태를 캡처한 뒤 중지하고, 상세보기에서 이어서 재생
        was_playing, pos_ms = self._preview.get_playback_state()
        self._preview.stop_player()
        resume = pos_ms if was_playing else 0
        self._detail_widget.load(detail, tag_ids, resume_ms=resume)
        self._preview.hide()
        self._nav_stack.setCurrentIndex(1)

    def _on_back_from_detail(self) -> None:
        self._detail_widget.stop_player()
        self._nav_stack.setCurrentIndex(0)
        if self._preview.has_video and self._btn_preview.isChecked():
            sizes = self._outer_splitter.sizes()
            if sizes[-1] == 0:
                saved = getattr(self._outer_splitter, "_saved_preview_size", 400)
                sizes[1] = max(100, sizes[1] - saved)
                sizes[-1] = saved
                self._outer_splitter.setSizes(sizes)
            self._preview.show()

    def _on_detail_tags_updated(self, video_id: UUID, tags: list) -> None:
        """Called when user manually adds a tag in the detail view."""
        self._vm.update_video_tags(video_id, tags)
        if self._nav_stack.currentIndex() == 1:
            detail = self._vm.get_video_detail(video_id)
            if detail:
                tag_ids = {t.name: t.id for t in self._vm.tags}
                self._detail_widget.load(detail, tag_ids)

    def _on_sort_changed(self, index: int) -> None:
        sort_by, sort_asc = self._sort_combo.itemData(index)
        self._vm.set_sort(sort_by, sort_asc)

    # ── Smart Folders ──────────────────────────────────────────────

    def _load_smart_folders_ui(self) -> None:
        from application.library.smart_folders import load_smart_folders  # noqa: PLC0415
        self._smart_folders = load_smart_folders()
        self._sf_list.clear()
        for sf in self._smart_folders:
            item = QListWidgetItem(sf.name)
            item.setData(Qt.ItemDataRole.UserRole, sf.id)
            self._sf_list.addItem(item)

    def _on_save_smart_folder(self) -> None:
        from application.library.smart_folders import SmartFolder, load_smart_folders, save_smart_folders  # noqa: PLC0415
        name, ok = QInputDialog.getText(self, "스마트 폴더 저장", "폴더 이름:")
        if not ok or not name.strip():
            return
        sf = SmartFolder(
            name=name.strip(),
            tag_ids=[str(tid) for tid in self._active_tag_ids],
            min_duration_sec=getattr(self._vm, "_min_duration_sec", None),
            max_duration_sec=getattr(self._vm, "_max_duration_sec", None),
        )
        folders = load_smart_folders()
        folders.append(sf)
        save_smart_folders(folders)
        self._load_smart_folders_ui()

    def _on_smart_folder_clicked(self, item: QListWidgetItem) -> None:
        sf_id = item.data(Qt.ItemDataRole.UserRole)
        sf = next((f for f in self._smart_folders if f.id == sf_id), None)
        if sf is None:
            return
        if not self._is_restoring:
            self._push_nav_state()
        self._active_tag_ids.clear()
        self._tag_list.clearSelection()
        if sf.tag_ids:
            for tid_str in sf.tag_ids:
                try:
                    from uuid import UUID  # noqa: PLC0415
                    tid = UUID(tid_str)
                    self._active_tag_ids.add(tid)
                    for i in range(self._tag_list.count()):
                        tw_item = self._tag_list.item(i)
                        if tw_item.data(Qt.ItemDataRole.UserRole) == tid:
                            tw_item.setSelected(True)
                            break
                except Exception:
                    pass
        self._vm.set_tag_filter(list(self._active_tag_ids))
        self._vm.set_duration_filter(sf.min_duration_sec, sf.max_duration_sec)
        self._vm.set_favorite_filter(sf.favorite_only)
        self._refresh_active_tags_bar()

    def _on_sf_context_menu(self, pos) -> None:
        from application.library.smart_folders import load_smart_folders, save_smart_folders  # noqa: PLC0415
        item = self._sf_list.itemAt(pos)
        if item is None:
            return
        sf_id = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        rename_act = QAction("이름 변경", self)
        rename_act.triggered.connect(lambda: self._rename_smart_folder(sf_id))
        delete_act = QAction("삭제", self)
        delete_act.triggered.connect(lambda: self._delete_smart_folder(sf_id))
        menu.addAction(rename_act)
        menu.addAction(delete_act)
        menu.exec(self._sf_list.viewport().mapToGlobal(pos))

    def _rename_smart_folder(self, sf_id: str) -> None:
        from application.library.smart_folders import load_smart_folders, save_smart_folders  # noqa: PLC0415
        sf = next((f for f in self._smart_folders if f.id == sf_id), None)
        if sf is None:
            return
        name, ok = QInputDialog.getText(self, "이름 변경", "새 폴더 이름:", text=sf.name)
        if not ok or not name.strip():
            return
        sf.name = name.strip()
        folders = load_smart_folders()
        for i, f in enumerate(folders):
            if f.id == sf_id:
                folders[i] = sf
                break
        save_smart_folders(folders)
        self._load_smart_folders_ui()

    def _delete_smart_folder(self, sf_id: str) -> None:
        from application.library.smart_folders import load_smart_folders, save_smart_folders  # noqa: PLC0415
        folders = [f for f in load_smart_folders() if f.id != sf_id]
        save_smart_folders(folders)
        self._load_smart_folders_ui()

    def _on_preview_detail_requested(self, dto: VideoDTO) -> None:
        self._open_detail(dto.id)

    # ── Empty space click ────────────────────────────────────────────

    def _on_empty_clicked(self) -> None:
        pass  # 빈 공간 클릭 시 미리보기 패널 상태 유지

    # ── 이벤트 필터: Ctrl+휠 뷰 전환 & 마우스 BackButton 히스토리 ────────

    def eventFilter(self, obj, event) -> bool:
        etype = event.type()
        if etype == QEvent.Type.Wheel:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                delta = event.angleDelta().y()
                self._cycle_view(1 if delta > 0 else -1)
                return True
        elif etype == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.BackButton:
                self._go_back()
                return True
        return super().eventFilter(obj, event)

    def _cycle_view(self, direction: int) -> None:
        """Ctrl+휠로 뷰 타입을 순환 전환한다. direction=1: 이전, -1: 다음."""
        views = [_VIEW_ICON, _VIEW_LIST, _VIEW_DETAIL]
        current = self._view_stack.currentIndex()
        idx = views.index(current) if current in views else 0
        new_id = views[(idx - direction) % len(views)]
        self._switch_view(new_id)

    # ── 내비게이션 히스토리 ────────────────────────────────────────────

    def _push_nav_state(self) -> None:
        """현재 카테고리·태그·화면 상태를 히스토리 스택에 저장한다."""
        state = {
            "cat_id": self.current_category_id(),
            "tag_ids": frozenset(self._active_tag_ids),
            "nav_idx": self._nav_stack.currentIndex(),
        }
        self._nav_history.append(state)
        if len(self._nav_history) > 50:
            self._nav_history.pop(0)

    def _go_back(self) -> None:
        """히스토리에서 직전 상태를 꺼내 복원한다."""
        if not self._nav_history:
            return
        state = self._nav_history.pop()
        self._is_restoring = True
        try:
            # 상세 화면이면 목록으로 먼저 복귀
            if self._nav_stack.currentIndex() == 1:
                self._on_back_from_detail()

            # 태그 필터 복원
            saved_tags: frozenset = state.get("tag_ids", frozenset())
            self._active_tag_ids = set(saved_tags)
            self._vm.set_tag_filter(list(self._active_tag_ids))
            self._tag_list.blockSignals(True)
            self._tag_list.clearSelection()
            for i in range(self._tag_list.count()):
                item = self._tag_list.item(i)
                if item.data(Qt.ItemDataRole.UserRole) in self._active_tag_ids:
                    item.setSelected(True)
            self._tag_list.blockSignals(False)
            self._refresh_active_tags_bar()
            self._update_delegate_tags()

            # 카테고리 복원
            cat_id = state.get("cat_id")
            self._vm.set_category_filter(cat_id)
            self._icon_delegate.filter_cat_id = cat_id
            self._list_delegate.filter_cat_id = cat_id
            self._cat_tree.blockSignals(True)
            if cat_id is None:
                top = self._cat_tree.topLevelItem(0)
                if top:
                    self._cat_tree.setCurrentItem(top)
            else:
                item = self._cat_tree._find_item(cat_id)
                if item:
                    self._cat_tree.setCurrentItem(item)
            self._cat_tree.blockSignals(False)
            self._icon_view.viewport().update()
            self._list_view.viewport().update()
        finally:
            self._is_restoring = False

    def _on_hidden_tags_changed(self) -> None:
        """설정에서 숨김 태그가 변경되면 태그 표시 목록을 즉시 갱신한다."""
        self._refresh_tag_display()
        self._refresh_popular_tags()

    # ── URL dropped onto video list ────────────────────────────────

    def _on_list_url_dropped(self, url: str) -> None:
        cat_id = None
        current = self._cat_tree.currentItem()
        if current:
            cat_id = current.data(0, Qt.ItemDataRole.UserRole)
        self._vm.add_video(url, cat_id)

    # ── Category management ────────────────────────────────────────

    def _on_refresh_metadata(self, category_id) -> None:
        if self._refresh_dlg is not None:
            return  # already running
        self._refresh_dlg = QProgressDialog(
            "메타데이터 갱신 중...", None, 0, 100, self
        )
        self._refresh_dlg.setWindowTitle("메타데이터 일괄 갱신")
        self._refresh_dlg.setWindowModality(Qt.WindowModality.WindowModal)
        self._refresh_dlg.setMinimumDuration(0)
        self._refresh_dlg.setValue(0)
        self._refresh_dlg.show()
        self._vm.refresh_category_metadata(category_id)

    def _on_refresh_progress(self, current: int, total: int) -> None:
        if self._refresh_dlg is not None and total > 0:
            self._refresh_dlg.setValue(int(current / total * 100))

    def _on_refresh_finished(self, count: int) -> None:
        if self._refresh_dlg is not None:
            self._refresh_dlg.close()
            self._refresh_dlg = None

    def _on_add_category(self, parent_id) -> None:
        name, ok = QInputDialog.getText(self, "카테고리 추가", "카테고리 이름:")
        if ok and name.strip():
            self._vm.create_category(name.strip(), parent_id=parent_id)

    def _on_rename_category(self, category_id, new_name: str) -> None:
        # Receives the already-edited name from the inline tree editor
        if new_name.strip():
            self._vm.rename_category(category_id, new_name.strip())

    def _on_category_reparented(self, cat_id: UUID, new_parent_id) -> None:
        self._vm.reparent_category(cat_id, new_parent_id)

    def _on_delete_category(self, category_id, name: str) -> None:
        reply = QMessageBox.question(
            self, "카테고리 삭제",
            f"'{name}' 카테고리를 삭제하시겠습니까?\n영상은 '미분류'로 이동됩니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._vm.delete_category(category_id)

    # ── Item click / double-click ──────────────────────────────────

    def _toggle_preview(self, checked: bool) -> None:
        sizes = self._outer_splitter.sizes()
        if checked:
            saved = getattr(self._outer_splitter, "_saved_preview_size", 400)
            if sizes[-1] == 0:
                sizes[1] = max(100, sizes[1] - saved)
                sizes[-1] = saved
                self._outer_splitter.setSizes(sizes)
            self._preview.show()
        else:
            if sizes[-1] > 0:
                self._outer_splitter._saved_preview_size = sizes[-1]
            sizes[-1] = 0
            self._outer_splitter.setSizes(sizes)
            self._preview.hide()

    def _on_item_clicked(self, index: QModelIndex, view: QListView) -> None:
        # Only update preview when exactly one item is selected
        if len(view.selectedIndexes()) != 1:
            return
        dto: VideoDTO | None = self._model.data(index, VideoListModel.DtoRole)
        if dto:
            if self._preview.isVisible():
                self._preview.show_video(dto)
            self.video_selected.emit(dto)

    def _on_double_click(self, index: QModelIndex) -> None:
        dto: VideoDTO | None = self._model.data(index, VideoListModel.DtoRole)
        if dto:
            self._open_detail(dto.id)

    def _on_table_clicked(self, index: QModelIndex) -> None:
        item = self._table.item(index.row(), 0)
        if item:
            vid_id = item.data(Qt.ItemDataRole.UserRole)
            if vid_id and index.row() < len(self._vm.videos):
                if self._preview.isVisible():
                    self._preview.show_video(self._vm.videos[index.row()])

    def _on_table_double_click(self, index: QModelIndex) -> None:
        item = self._table.item(index.row(), 0)
        if item:
            vid_id = item.data(Qt.ItemDataRole.UserRole)
            if vid_id:
                self._open_detail(vid_id)

    # ── URL/video drop ─────────────────────────────────────────────

    def _on_url_dropped(self, url: str, category_id) -> None:
        self._vm.add_video(url, category_id)

    def _on_video_moved(self, video_id: UUID, category_id) -> None:
        self._vm.assign_category(video_id, category_id)

    # ── Context menus ──────────────────────────────────────────────

    def _show_video_menu(self, pos: QPoint, view: QListView) -> None:
        indexes = view.selectedIndexes()
        if not indexes:
            return
        global_pos = view.viewport().mapToGlobal(pos)
        if len(indexes) > 1:
            self._build_bulk_menu(indexes, global_pos)
        else:
            dto: VideoDTO = self._model.data(indexes[0], VideoListModel.DtoRole)
            if dto:
                self._build_video_menu(dto, global_pos)

    def _show_table_menu(self, pos: QPoint) -> None:
        row = self._table.rowAt(pos.y())
        if row < 0 or row >= len(self._vm.videos):
            return
        self._build_video_menu(self._vm.videos[row], self._table.viewport().mapToGlobal(pos))

    def _build_bulk_menu(self, indexes: list[QModelIndex], global_pos: QPoint) -> None:
        dtos = [
            self._model.data(idx, VideoListModel.DtoRole)
            for idx in indexes
            if self._model.data(idx, VideoListModel.DtoRole) is not None
        ]
        video_ids = [d.id for d in dtos]
        menu = QMenu(self)
        menu.addSection(f"{len(video_ids)}개 영상 선택됨")

        dl_act = QAction("일괄 다운로드", self)
        dl_act.triggered.connect(lambda: self._on_batch_download(dtos))
        menu.addAction(dl_act)

        tag_act = QAction("태그 추가", self)
        tag_act.triggered.connect(lambda: self._on_bulk_add_tags(video_ids))
        menu.addAction(tag_act)

        menu.addSeparator()

        cat_menu = menu.addMenu("카테고리 일괄 변경")
        uncat_act = QAction("미분류", self)
        uncat_act.triggered.connect(lambda: self._vm.assign_category_bulk(video_ids, None))
        cat_menu.addAction(uncat_act)
        cat_menu.addSeparator()
        self._add_bulk_cat_actions(cat_menu, self._vm.categories, None, video_ids)

        menu.exec(global_pos)

    def _on_batch_download(self, dtos: list[VideoDTO]) -> None:
        dlg = BatchDownloadDialog(len(dtos), self)
        if dlg.exec() != BatchDownloadDialog.DialogCode.Accepted:
            return
        settings = dlg.build_settings()
        skip = dlg.skip_existing
        skipped_urls: set[str] = set()
        if skip:
            try:
                from gui.view_models.download_vm import DownloadViewModel  # noqa: PLC0415
                history = getattr(self, "_download_vm", None)
                if history is not None and hasattr(history, "load_history"):
                    skipped_urls = {j.url for j in history.load_history(200) if j.status == "COMPLETED"}
            except Exception:
                pass
        for dto in dtos:
            if skip and dto.url in skipped_urls:
                continue
            self.download_requested.emit(dto.url, dto.title, settings)

    def _on_bulk_add_tags(self, video_ids: list[UUID]) -> None:
        tag_str, ok = QInputDialog.getText(
            self, "태그 추가",
            f"{len(video_ids)}개 영상에 추가할 태그를 입력하세요 (쉼표로 구분):",
        )
        if ok and tag_str.strip():
            tag_names = [
                t.strip().lstrip("#")
                for t in tag_str.split(",")
                if t.strip().lstrip("#")
            ]
            if tag_names:
                self._vm.add_tags_bulk(video_ids, tag_names)

    def _add_bulk_cat_actions(
        self, menu: QMenu, cats: list[CategoryDTO], parent_id, video_ids: list[UUID]
    ) -> None:
        for cat in cats:
            if cat.parent_id != parent_id:
                continue
            children = [c for c in cats if c.parent_id == cat.id]
            if children:
                sub = menu.addMenu(cat.name)
                mv = QAction(f"→ {cat.name}", self)
                cid = cat.id
                mv.triggered.connect(lambda _, c=cid: self._vm.assign_category_bulk(video_ids, c))
                sub.addAction(mv)
                sub.addSeparator()
                self._add_bulk_cat_actions(sub, cats, cat.id, video_ids)
            else:
                act = QAction(cat.name, self)
                cid = cat.id
                act.triggered.connect(lambda _, c=cid: self._vm.assign_category_bulk(video_ids, c))
                menu.addAction(act)

    def _build_video_menu(self, dto: VideoDTO, global_pos: QPoint) -> None:
        menu = QMenu(self)

        detail_act = QAction("상세 정보", self)
        detail_act.triggered.connect(lambda: self._open_detail(dto.id))
        menu.addAction(detail_act)

        menu.addSeparator()

        cat_menu = menu.addMenu("카테고리 이동")
        uncat_act = QAction("미분류", self)
        uncat_act.triggered.connect(lambda: self._on_video_moved(dto.id, None))
        cat_menu.addAction(uncat_act)
        cat_menu.addSeparator()
        self._add_cat_actions(cat_menu, self._vm.categories, None, dto.id)

        menu.addSeparator()

        fav_act = QAction("즐겨찾기 해제" if dto.favorite else "즐겨찾기 추가", self)
        fav_act.triggered.connect(lambda: self._toggle_favorite(dto))
        menu.addAction(fav_act)

        watch_act = QAction("시청 완료 표시", self)
        watch_act.setEnabled(not dto.watched)
        watch_act.triggered.connect(lambda: self._vm.mark_watched(dto.id))
        menu.addAction(watch_act)

        menu.addSeparator()

        del_act = QAction("삭제", self)
        del_act.triggered.connect(lambda: self._confirm_delete(dto))
        menu.addAction(del_act)

        menu.exec(global_pos)

    def _add_cat_actions(
        self, menu: QMenu, cats: list[CategoryDTO], parent_id, video_id: UUID
    ) -> None:
        for cat in cats:
            if cat.parent_id != parent_id:
                continue
            children = [c for c in cats if c.parent_id == cat.id]
            if children:
                sub = menu.addMenu(cat.name)
                mv = QAction(f"→ {cat.name}", self)
                cid = cat.id
                mv.triggered.connect(lambda _, c=cid: self._on_video_moved(video_id, c))
                sub.addAction(mv)
                sub.addSeparator()
                self._add_cat_actions(sub, cats, cat.id, video_id)
            else:
                act = QAction(cat.name, self)
                cid = cat.id
                act.triggered.connect(lambda _, c=cid: self._on_video_moved(video_id, c))
                menu.addAction(act)

    def _toggle_favorite(self, dto: VideoDTO) -> None:
        from application.library.commands import UpdateVideoCommand
        try:
            self._vm._update_video.handle(
                UpdateVideoCommand(video_id=dto.id, favorite=not dto.favorite)
            )
            self._vm._refresh_videos()
        except Exception as exc:
            self._vm.error_occurred.emit(str(exc))

    def _confirm_delete(self, dto: VideoDTO) -> None:
        reply = QMessageBox.question(
            self, "영상 삭제",
            f"'{dto.title}'\n이 영상을 목록에서 삭제하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._vm.delete_video(dto.id)
