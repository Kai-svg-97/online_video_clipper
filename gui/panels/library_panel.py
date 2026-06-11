"""Library panel — 3-pane browser: left sidebar | video list | preview pane.

Centre pane uses a navigation QStackedWidget (_nav_stack) so that double-clicking
a video replaces the list area with VideoDetailWidget inline (no modal dialog).
"""
from __future__ import annotations

import logging
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
    QAction, QBrush, QColor, QDesktopServices, QDrag, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
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
from gui.panels.video_detail_panel import (
    RelatedItem,
    VideoDetailWidget,
    _TagFlow,
    _clear_layout,
)
from gui.themes.manager import ThemeManager
from gui.themes.tokens import ThemeTokens
from gui.view_models.library_vm import LibraryViewModel
from gui.widgets.video_player import InlinePlayer

logger = logging.getLogger(__name__)


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

_MIME_VIDEO_ID        = "application/x-video-id"
_MIME_CAT_ID          = "application/x-category-id"
_MIME_PLAYLIST_ID     = "application/x-playlist-id"
_MIME_PLAYLIST_SECTION = "application/x-playlist-section"
_MIME_YT_PLAYLIST_ID  = "application/x-yt-playlist-id"
_CAT_PARENT_ROLE = Qt.ItemDataRole.UserRole + 100  # parent_id on category tree items
_VIEW_ICON   = 0
_VIEW_LIST   = 1
_VIEW_DETAIL = 2
_VIEW_FOLDER = 3   # 폴더 내 재생목록 카드 그리드
_VIEW_FEED   = 4   # 구독 채널/전체 피드 카드 그리드
_VIEW_CHANNELS = 5 # 구독 채널 목록(아바타 카드) 그리드


def _fmt_elapsed(iso: str | None) -> str:
    """ISO 시간 문자열을 '3일 전' 형식으로 변환한다."""
    if not iso:
        return ""
    try:
        from datetime import datetime, timezone  # noqa: PLC0415
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        diff = datetime.now(timezone.utc) - dt
        s = diff.total_seconds()
        if s < 60:
            return "방금"
        if s < 3600:
            return f"{int(s // 60)}분 전"
        if s < 86400:
            return f"{int(s // 3600)}시간 전"
        if s < 86400 * 30:
            return f"{int(s // 86400)}일 전"
        if s < 86400 * 365:
            return f"{int(s // (86400 * 30))}개월 전"
        return f"{int(s // (86400 * 365))}년 전"
    except Exception:
        logger.exception("경과 시간 포맷 변환 실패")
        return ""
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


# 캐시 키에 렌더 크기(아이콘 그리드 / 리스트 / 상세뷰 3종)가 포함되므로,
# "썸네일 LRU 최대 100개" 규칙은 *렌더 크기당* 100개를 의미한다.
# 따라서 전체 상한은 LRU_THUMBNAIL_MAX × 렌더 크기 종류 수.
_THUMB_RENDER_SIZE_KINDS = 3
_thumb_cache = _ThumbnailCache(LRU_THUMBNAIL_MAX * _THUMB_RENDER_SIZE_KINDS)


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
    """MIME 데이터에서 http/https URL을 추출한다.

    Windows에서 브라우저 URL 드래그 시 dropEvent 시점에 데이터가 채워지므로
    dragEnterEvent에서는 데이터가 비어있을 수 있다.
    여러 MIME 포맷(text/plain, text/uri-list, text/x-moz-url)을 순서대로 확인한다.
    """
    # 1. text/plain
    text = mime.text().strip()
    if text.startswith(("http://", "https://")):
        return text
    # 2. Qt URL 목록 (text/uri-list 파싱 결과)
    if mime.hasUrls():
        for qu in mime.urls():
            s = qu.toString().strip()
            if s.startswith(("http://", "https://")):
                return s
    # 3. text/uri-list 직접 읽기 (hasUrls()가 False인 경우 대비)
    for fmt in ("text/uri-list", "text/x-moz-url"):
        if mime.hasFormat(fmt):
            try:
                raw = bytes(mime.data(fmt)).decode("utf-8", errors="ignore")
                for line in raw.splitlines():
                    line = line.strip()
                    if line.startswith(("http://", "https://")):
                        return line
            except Exception:
                logger.exception("MIME 데이터에서 URL 추출 실패")
    return ""


def _mime_may_contain_url(mime: QMimeData) -> bool:
    """dragEnterEvent 시점에 URL 드래그 여부를 판단한다.

    Windows에서 브라우저 드래그 시 dragEnter 단계에서 MIME 내용이 아직
    채워지지 않을 수 있다. 데이터 내용이 아닌 포맷 존재 여부만 확인한다.
    """
    if _url_from_mime(mime):
        return True
    # 포맷 존재만 확인 (내용은 dropEvent에서 검증)
    return mime.hasUrls() or any(
        mime.hasFormat(f) for f in ("text/uri-list", "text/x-moz-url")
    )


def _relative_time(date_str: str | None) -> str:
    """Return a Korean relative time string like '3년 전' from an ISO date string."""
    if not date_str:
        return ""
    from datetime import date, datetime
    try:
        if len(date_str) == 8 and date_str.isdigit():        # YYYYMMDD (yt-dlp)
            pub = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:]))
        elif "T" in date_str or " " in date_str:
            pub = datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
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
        self._current_playlist_id = None   # 현재 활성 재생목록 (DnD 소스용)

    def set_playlist_context(self, playlist_id) -> None:
        """현재 보여주는 재생목록 ID를 저장 — 재생목록 간 DnD 시 사용."""
        self._current_playlist_id = playlist_id

    def mousePressEvent(self, event) -> None:
        if not self.indexAt(event.pos()).isValid():
            self.empty_clicked.emit()
            self.clearSelection()
        super().mousePressEvent(event)

    def startDrag(self, actions) -> None:
        """재생목록 뷰 상태일 때 영상 ID를 MIME에 추가해 플레이리스트 트리로 DnD 가능하게 한다."""
        if self._current_playlist_id is None:
            super().startDrag(actions)
            return
        indexes = self.selectedIndexes()
        if not indexes:
            return
        video_ids = []
        for idx in indexes:
            vid_uuid = self.model().data(idx, VideoListModel.VideoIdRole)
            if vid_uuid:
                video_ids.append(str(vid_uuid))
        if not video_ids:
            super().startDrag(actions)
            return
        mime = QMimeData()
        mime.setData(
            _MIME_VIDEO_ID,
            QByteArray(",".join(video_ids).encode()),
        )
        mime.setData(
            "application/x-source-playlist-id",
            QByteArray(str(self._current_playlist_id).encode()),
        )
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(_MIME_VIDEO_ID):
            if event.source() is self:
                # 내부 재정렬(InternalMove) — super()에 위임
                super().dragEnterEvent(event)
            else:
                event.ignore()
            return
        # Windows에서 브라우저 드래그 시 dragEnter 단계에 MIME 내용이 없을 수 있어
        # 포맷 존재 여부로 판단한다 — 실제 URL 검증은 dropEvent에서 수행
        self._ext_url_drag = _mime_may_contain_url(event.mimeData())
        if self._ext_url_drag:
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(_MIME_VIDEO_ID):
            if event.source() is self:
                super().dragMoveEvent(event)
            else:
                event.ignore()
            return
        if self._ext_url_drag:
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:
        self._ext_url_drag = False
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self._ext_url_drag = False
        if event.mimeData().hasFormat(_MIME_VIDEO_ID):
            if event.source() is self:
                super().dropEvent(event)
            else:
                event.ignore()
            return
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

        show_cat = bool(cat_name)

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

        show_cat = bool(cat_name)

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

    reordered = pyqtSignal(list)   # list[UUID] — 새 순서

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: list[VideoDTO] = []
        self._reorder_mode: bool = False

    def set_reorder_mode(self, enabled: bool) -> None:
        self._reorder_mode = enabled

    @property
    def reorder_mode(self) -> bool:
        return self._reorder_mode

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
        base = super().flags(index) | Qt.ItemFlag.ItemIsDragEnabled
        if self._reorder_mode and index.isValid():
            base |= Qt.ItemFlag.ItemIsDropEnabled
        return base

    def mimeTypes(self) -> list[str]:
        return [_MIME_VIDEO_ID]

    def mimeData(self, indexes: list[QModelIndex]) -> QMimeData:
        data = QMimeData()
        ids = [str(self._items[i.row()].id) for i in indexes if i.isValid()]
        data.setData(_MIME_VIDEO_ID, QByteArray(",".join(ids).encode()))
        return data

    def supportedDragActions(self) -> Qt.DropAction:
        return Qt.DropAction.MoveAction

    def supportedDropActions(self) -> Qt.DropAction:
        if self._reorder_mode:
            return Qt.DropAction.MoveAction
        return Qt.DropAction.CopyAction

    def canDropMimeData(self, data: QMimeData, action, row, col, parent) -> bool:
        return self._reorder_mode and data.hasFormat(_MIME_VIDEO_ID)

    def dropMimeData(self, data: QMimeData, action, row, col, parent) -> bool:
        if not self._reorder_mode or not data.hasFormat(_MIME_VIDEO_ID):
            return False
        raw = data.data(_MIME_VIDEO_ID).data().decode()
        moved_id_strs = [s for s in raw.split(",") if s]
        if not moved_id_strs:
            return False
        moved_id_str = moved_id_strs[0]
        src_row = next(
            (i for i, dto in enumerate(self._items) if str(dto.id) == moved_id_str),
            -1,
        )
        if src_row < 0:
            return False
        # 아이콘(그리드) 모드: 드롭 위치가 아이템 위에 있으면 row=-1, parent=해당 아이템
        if row < 0:
            dst_row = parent.row() if parent.isValid() else len(self._items)
        else:
            dst_row = row
        if dst_row > src_row:
            dst_row -= 1
        if dst_row == src_row:
            return False
        self.beginMoveRows(QModelIndex(), src_row, src_row, QModelIndex(), dst_row if dst_row < src_row else dst_row + 1)
        item = self._items.pop(src_row)
        self._items.insert(dst_row, item)
        self.endMoveRows()
        self.reordered.emit([dto.id for dto in self._items])
        return True


# ------------------------------------------------------------------
# 인기 태그 버튼 (이름 왼쪽 + 둥근 카운트 배지 오른쪽)
# ------------------------------------------------------------------

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
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)

        bg = QColor(self._color) if self._selected else QColor("#2a3a4a")
        painter.setBrush(QBrush(bg))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 10, 10)

        badge_text = str(self._count)
        painter.setFont(QFont("", 7))
        fm = painter.fontMetrics()
        badge_w = fm.horizontalAdvance(badge_text) + 12
        badge_h = rect.height() - 8
        badge_x = rect.right() - badge_w - 4
        badge_y = rect.center().y() - badge_h // 2
        badge_rect = QRect(badge_x, badge_y, badge_w, badge_h)

        badge_bg = QColor("#1a6fa0") if self._selected else QColor("#204060")
        painter.setBrush(QBrush(badge_bg))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(badge_rect, badge_h // 2, badge_h // 2)

        painter.setPen(QColor("#ddeeff"))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)

        painter.setFont(QFont("", 9))
        painter.setPen(QColor("#fff") if self._selected else QColor("#ccc"))
        name_rect = QRect(rect.left() + 8, rect.top(), badge_x - rect.left() - 12, rect.height())
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine,
            self._tag_name,
        )
        painter.end()


# ------------------------------------------------------------------
# 즐겨찾기 바 — 검색 필드 위, 드래그로 순서 변경
# ------------------------------------------------------------------

_FAV_BADGE_W = 32   # count badge width in _FavoritesBar


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


class _FavChipDelegate(QStyledItemDelegate):
    """즐겨찾기 칩 — 아이콘+이름 왼쪽, 카운트 배지 오른쪽."""

    def sizeHint(self, option, index) -> QSize:
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        fm = QFontMetrics(QFont("", 8))
        text_w = fm.horizontalAdvance(text)
        # 좌우 패딩(14) + 텍스트 + 간격(6) + 배지
        return QSize(text_w + _FAV_BADGE_W + 20, 26)

    def paint(self, painter, option, index) -> None:
        from PyQt6.QtWidgets import QStyle  # noqa: PLC0415
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        count = index.data(Qt.ItemDataRole.UserRole + 1) or 0
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        chip = option.rect.adjusted(2, 2, -2, -2)

        bg = QColor("#1a6fa0") if selected else QColor("#253545")
        painter.setBrush(QBrush(bg))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(chip, 10, 10)

        # Count badge (right side)
        badge_text = str(count)
        painter.setFont(QFont("", 7))
        fm = painter.fontMetrics()
        badge_w = max(fm.horizontalAdvance(badge_text) + 10, _FAV_BADGE_W - 4)
        badge_h = chip.height() - 6
        badge_x = chip.right() - badge_w - 3
        badge_y = chip.center().y() - badge_h // 2
        badge_rect = QRect(badge_x, badge_y, badge_w, badge_h)
        badge_bg = QColor("#b03030") if count == 0 else (QColor("#2a6fa0") if selected else QColor("#1a4060"))
        painter.setBrush(QBrush(badge_bg))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(badge_rect, badge_h // 2, badge_h // 2)
        painter.setFont(QFont("", 7))
        painter.setPen(QColor("#ddeeff"))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)

        # Name text
        painter.setFont(QFont("", 8))
        painter.setPen(QColor("#fff") if selected else QColor("#ccc"))
        name_rect = QRect(chip.left() + 6, chip.top(), badge_x - chip.left() - 8, chip.height())
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine, text)

        painter.restore()


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
# Playlist panel (재생목록 탭)
# ------------------------------------------------------------------

_PLAYLIST_ID_ROLE = Qt.ItemDataRole.UserRole + 200
_FOLDER_ID_ROLE   = Qt.ItemDataRole.UserRole + 201
_ITEM_TYPE_ROLE   = Qt.ItemDataRole.UserRole + 202  # "root" | "folder" | "playlist" | "category" | "channel" | "feed_all"
_SECTION_ROLE     = Qt.ItemDataRole.UserRole + 203  # "local" | "youtube"
_CAT_ID_ROLE      = Qt.ItemDataRole.UserRole + 204  # category UUID
_CHANNEL_URL_ROLE = Qt.ItemDataRole.UserRole + 205  # 구독 채널 URL

_ITYPE_ROOT     = "root"
_ITYPE_FOLDER   = "folder"
_ITYPE_PLAYLIST = "playlist"
_ITYPE_CATEGORY = "category"
_ITYPE_CHANNEL  = "channel"    # 구독 채널 노드 (클릭 시 채널 영상 피드)
_ITYPE_FEED_ALL = "feed_all"   # 전체 구독 피드 노드


class _PlaylistTree(QTreeWidget):
    """재생목록 트리 위젯 — 로컬·YouTube 그룹 + 카테고리 + 폴더 + DnD."""

    playlist_selected             = pyqtSignal(object)         # UUID | None
    folder_selected               = pyqtSignal(object)         # folder UUID
    unfiled_selected              = pyqtSignal(object)         # source str ("local"|"youtube") — 미분류 디렉토리
    category_selected             = pyqtSignal(object)         # category UUID
    channel_selected              = pyqtSignal(str)            # 구독 채널 URL
    feed_all_selected             = pyqtSignal()               # 전체 구독 피드
    channels_root_selected        = pyqtSignal()               # "구독 채널" 노드 — 채널 목록 그리드
    playlist_delete_req           = pyqtSignal(object)         # playlist UUID
    playlist_rename_req           = pyqtSignal(object)         # playlist UUID
    playlist_move_req             = pyqtSignal(object, object) # (playlist_id, folder_id|None)
    folder_create_req             = pyqtSignal(str)            # source ("local"|"youtube")
    folder_rename_req             = pyqtSignal(object, str)    # (folder_id, old_name)
    folder_delete_req             = pyqtSignal(object)         # folder UUID
    copy_yt_to_local_req          = pyqtSignal(object)         # yt_playlist_id str
    sync_yt_req                   = pyqtSignal(object)         # yt_playlist_id str
    push_to_yt_req                = pyqtSignal(object, bool)   # (playlist_id, move: bool)
    import_yt_req                 = pyqtSignal()               # "↓ YouTube" button
    video_move_to_playlist_req    = pyqtSignal(object, object, object)  # (video_id_str, src_pl_id_str, tgt_pl_id UUID)
    add_category_req              = pyqtSignal(object)         # parent_id (UUID | None)
    rename_category_req           = pyqtSignal(object)         # category UUID
    delete_category_req           = pyqtSignal(object)         # category UUID
    category_reparented           = pyqtSignal(object, object) # (cat_id, new_parent_id | None)
    yt_playlist_to_category_req   = pyqtSignal(str, object)    # (yt_playlist_id, cat_id UUID)
    favorite_toggle_req           = pyqtSignal(str, str, str)  # (type, id, name)
    video_assign_category_req     = pyqtSignal(object, object) # (video_id UUID, cat_id UUID | None)
    local_playlist_to_category_req = pyqtSignal(object, object) # (playlist_id UUID, parent_cat_id UUID | None)

    def __init__(self, section: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._section = section   # "local" | "youtube" | None (둘 다)
        self._favs: set[tuple[str, str]] = set()   # {("category"|"playlist", id_str)}
        self.setHeaderHidden(True)
        self.setIndentation(20)
        # DragDrop: 내부 재생목록 폴더 이동 + 외부 영상 드롭 모두 지원
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.currentItemChanged.connect(self._on_selection_changed)
        self.itemExpanded.connect(self._on_item_expanded)
        self.itemCollapsed.connect(self._on_item_collapsed)

    # ── 로드 ─────────────────────────────────────────────────────────────────

    def load(self, playlists, folders, categories=None, subscriptions=None) -> None:
        """playlists: list[PlaylistDTO], folders: list[PlaylistFolderDTO], categories: list[CategoryDTO],
        subscriptions: list[SubscriptionDTO] (YouTube 섹션에서만 사용)"""
        from application.library.favorites import load_favorites  # noqa: PLC0415
        self._favs = {(f.type, f.id) for f in load_favorites()}
        self.blockSignals(True)
        prev_pl = None
        prev_cat = None
        cur = self.currentItem()
        if cur:
            prev_pl = cur.data(0, _PLAYLIST_ID_ROLE)
            prev_cat = cur.data(0, _CAT_ID_ROLE)

        self.clear()
        self._sub_group_item = None

        if self._section == "local":
            self._load_local_section(playlists, folders, categories)
        elif self._section == "youtube":
            self._load_youtube_section(playlists, folders, subscriptions or [])
        else:
            self._load_both_sections(playlists, folders, categories)

        if self._section == "youtube":
            self.expandAll()
            # 구독 채널 그룹은 항목이 많을 수 있으므로 기본 접힘 상태로 둔다.
            if self._sub_group_item is not None:
                self._sub_group_item.setExpanded(False)
        elif self._section == "local":
            # 카테고리는 기본 2단계까지만 펼친다 (최상위 + 직속 자식만 보이고 그 아래는 접음)
            self.expandToDepth(0)
        else:
            self.expandToDepth(1)   # 폴더/카테고리는 펼치되 하위 재귀 항목은 접음
        self.blockSignals(False)

        if prev_pl:
            self._restore_selection(prev_pl)
        elif prev_cat:
            # 카테고리 선택 유지 — 하위 카테고리 추가 등으로 트리가 재구성돼도
            # 작업 대상 카테고리가 선택된 채 보이도록 복원한다.
            self._restore_category_selection(prev_cat)

    def _load_local_section(self, playlists, folders, categories) -> None:
        if categories:
            child_parent_ids = {c.parent_id for c in categories if c.parent_id is not None}
            cat_by_id: dict = {}
            roots = [c for c in categories if c.parent_id is None]
            for c in roots:
                ci = self._make_category(c.name, c.id, getattr(c, "video_count", 0), has_children=c.id in child_parent_ids)
                self.addTopLevelItem(ci)
                cat_by_id[c.id] = ci
            queue = list(roots)
            while queue:
                parent_cat = queue.pop(0)
                for c in categories:
                    if c.parent_id == parent_cat.id:
                        ci = self._make_category(c.name, c.id, getattr(c, "video_count", 0), has_children=c.id in child_parent_ids)
                        cat_by_id[parent_cat.id].addChild(ci)
                        cat_by_id[c.id] = ci
                        queue.append(c)

        local_folders_by_id: dict = {}
        for f in folders:
            if f.source != "local":
                continue
            fi = self._make_folder(f.name, f.id, "local")
            self.addTopLevelItem(fi)
            local_folders_by_id[f.id] = fi

        local_unfiled = self._make_unfiled("local")
        self.addTopLevelItem(local_unfiled)

        for pl in playlists:
            if pl.source != "local":
                continue
            pi = self._make_playlist(pl.title, pl.item_count, pl.id, pl.yt_playlist_id)
            if pl.folder_id and pl.folder_id in local_folders_by_id:
                local_folders_by_id[pl.folder_id].addChild(pi)
            else:
                local_unfiled.addChild(pi)

    def _load_youtube_section(self, playlists, folders, subscriptions=None) -> None:
        # ── 구독 섹션 (피드 통합) ──
        # "전체 구독 피드" + 구독 채널 폴더 트리. 채널 클릭 시 해당 채널 영상을
        # 메인 영역에 카드로 표시한다.
        feed_all = QTreeWidgetItem(["📡  전체 구독 피드"])
        feed_all.setData(0, _ITEM_TYPE_ROLE, _ITYPE_FEED_ALL)
        feed_all.setData(0, _SECTION_ROLE, "youtube")
        feed_all.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self.addTopLevelItem(feed_all)

        sub_group = QTreeWidgetItem(["📡  구독 채널"])
        sub_group.setData(0, _ITEM_TYPE_ROLE, _ITYPE_ROOT)
        sub_group.setData(0, _SECTION_ROLE, "youtube")
        sub_group.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        gf = sub_group.font(0)
        gf.setWeight(QFont.Weight.Bold)
        sub_group.setFont(0, gf)
        self.addTopLevelItem(sub_group)
        self._sub_group_item = sub_group
        # 채널 목록은 이름 오름차순(대소문자 무시)으로 표시한다.
        for sub in sorted(subscriptions or [], key=lambda s: (s.channel_name or "").lower()):
            sub_group.addChild(self._make_channel(sub.channel_name, sub.channel_url))

        yt_folders_by_id: dict = {}
        for f in folders:
            if f.source != "youtube":
                continue
            fi = self._make_folder(f.name, f.id, "youtube")
            self.addTopLevelItem(fi)
            yt_folders_by_id[f.id] = fi

        yt_unfiled = self._make_unfiled("youtube")
        self.addTopLevelItem(yt_unfiled)

        for pl in playlists:
            if pl.source != "youtube":
                continue
            pi = self._make_playlist(pl.title, pl.item_count, pl.id, pl.yt_playlist_id)
            if pl.folder_id and pl.folder_id in yt_folders_by_id:
                yt_folders_by_id[pl.folder_id].addChild(pi)
            else:
                yt_unfiled.addChild(pi)

    def _load_both_sections(self, playlists, folders, categories) -> None:
        # ── 로컬 섹션 ──
        local_root = self._make_root("로컬", "local")
        self.addTopLevelItem(local_root)

        if categories:
            child_parent_ids = {c.parent_id for c in categories if c.parent_id is not None}
            cat_by_id: dict = {}
            roots = [c for c in categories if c.parent_id is None]
            for c in roots:
                ci = self._make_category(c.name, c.id, getattr(c, "video_count", 0), has_children=c.id in child_parent_ids)
                local_root.addChild(ci)
                cat_by_id[c.id] = ci
            queue = list(roots)
            while queue:
                parent_cat = queue.pop(0)
                for c in categories:
                    if c.parent_id == parent_cat.id:
                        ci = self._make_category(c.name, c.id, getattr(c, "video_count", 0), has_children=c.id in child_parent_ids)
                        cat_by_id[parent_cat.id].addChild(ci)
                        cat_by_id[c.id] = ci
                        queue.append(c)

        local_folders_by_id: dict = {}
        for f in folders:
            if f.source != "local":
                continue
            fi = self._make_folder(f.name, f.id, "local")
            local_root.addChild(fi)
            local_folders_by_id[f.id] = fi

        local_unfiled = self._make_unfiled("local")
        local_root.addChild(local_unfiled)

        for pl in playlists:
            if pl.source != "local":
                continue
            pi = self._make_playlist(pl.title, pl.item_count, pl.id, pl.yt_playlist_id)
            if pl.folder_id and pl.folder_id in local_folders_by_id:
                local_folders_by_id[pl.folder_id].addChild(pi)
            else:
                local_unfiled.addChild(pi)

        # ── YouTube 섹션 ──
        yt_root = self._make_root("YouTube", "youtube")
        self.addTopLevelItem(yt_root)

        yt_folders_by_id: dict = {}
        for f in folders:
            if f.source != "youtube":
                continue
            fi = self._make_folder(f.name, f.id, "youtube")
            yt_root.addChild(fi)
            yt_folders_by_id[f.id] = fi

        yt_unfiled = self._make_unfiled("youtube")
        yt_root.addChild(yt_unfiled)

        for pl in playlists:
            if pl.source != "youtube":
                continue
            pi = self._make_playlist(pl.title, pl.item_count, pl.id, pl.yt_playlist_id)
            if pl.folder_id and pl.folder_id in yt_folders_by_id:
                yt_folders_by_id[pl.folder_id].addChild(pi)
            else:
                yt_unfiled.addChild(pi)

    # ── 아이템 팩토리 ──────────────────────────────────────────────────────────

    @staticmethod
    def _no_drop_flags() -> Qt.ItemFlag:
        return (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
        )

    def _make_root(self, label: str, source: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([label])
        item.setData(0, _ITEM_TYPE_ROLE, _ITYPE_ROOT)
        item.setData(0, _SECTION_ROLE, source)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsDropEnabled)
        f = item.font(0)
        f.setWeight(QFont.Weight.Bold)
        f.setPointSize(9)
        item.setFont(0, f)
        return item

    def _make_folder(self, name: str, folder_id, source: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([f"📂  {name}"])
        item.setData(0, _ITEM_TYPE_ROLE, _ITYPE_FOLDER)
        item.setData(0, _FOLDER_ID_ROLE, folder_id)
        item.setData(0, _SECTION_ROLE, source)
        item.setToolTip(0, name)
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDropEnabled
        )
        return item

    def _make_unfiled(self, source: str) -> QTreeWidgetItem:
        # 미분류도 디렉토리로 기능하므로 폴더 아이콘을 앞에 표시한다.
        item = QTreeWidgetItem(["📂  미분류"])
        item.setData(0, _ITEM_TYPE_ROLE, _ITYPE_FOLDER)
        item.setData(0, _FOLDER_ID_ROLE, None)   # None = 미분류
        item.setData(0, _SECTION_ROLE, source)
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsDropEnabled
        )
        f = item.font(0)
        f.setItalic(True)
        item.setFont(0, f)
        return item

    def _make_category(self, name: str, cat_id, video_count: int = 0, has_children: bool = False) -> QTreeWidgetItem:
        # 펼침/접힘 세모는 트리 branch 컬럼(들여쓰기 영역)에 네이티브 인디케이터로 표시한다.
        # 라벨에는 더 이상 세모(▸)를 넣지 않는다. (has_children 인자는 호환을 위해 유지)
        starred = ("category", str(cat_id)) in self._favs
        label = f"🏷  {name}  ({video_count})" if video_count > 0 else f"🏷  {name}"
        item = QTreeWidgetItem([label])
        item.setData(0, _ITEM_TYPE_ROLE, _ITYPE_CATEGORY)
        item.setData(0, _CAT_ID_ROLE, cat_id)
        item.setData(0, _SECTION_ROLE, "local")
        item.setToolTip(0, name)
        if starred:
            from PyQt6.QtGui import QBrush, QColor  # noqa: PLC0415
            c = QColor(_t().star_color)
            c.setAlpha(50)
            item.setBackground(0, QBrush(c))
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsDropEnabled
        )
        return item

    def _make_playlist(self, title: str, count: int, pl_id, yt_id) -> QTreeWidgetItem:
        starred = ("playlist", str(pl_id)) in self._favs
        item = QTreeWidgetItem([f"{title}  ({count})"])
        item.setData(0, _ITEM_TYPE_ROLE, _ITYPE_PLAYLIST)
        item.setData(0, _PLAYLIST_ID_ROLE, pl_id)
        if starred:
            from PyQt6.QtGui import QBrush, QColor  # noqa: PLC0415
            c = QColor(_t().star_color)
            c.setAlpha(50)
            item.setBackground(0, QBrush(c))
        if yt_id:
            item.setToolTip(0, f"{title}\nYouTube: {yt_id}")
        else:
            item.setToolTip(0, title)
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsDropEnabled   # 영상 드롭 수신용
        )
        return item

    def _make_channel(self, name: str, channel_url: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([f"📺  {name}"])
        item.setData(0, _ITEM_TYPE_ROLE, _ITYPE_CHANNEL)
        item.setData(0, _CHANNEL_URL_ROLE, channel_url)
        item.setData(0, _SECTION_ROLE, "youtube")
        item.setToolTip(0, f"{name}\n{channel_url}")
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        return item

    # ── 선택 이벤트 ────────────────────────────────────────────────────────────

    def _on_selection_changed(self, current, _prev) -> None:
        if current is None:
            self.playlist_selected.emit(None)
            return
        itype = current.data(0, _ITEM_TYPE_ROLE)
        if itype == _ITYPE_PLAYLIST:
            self.playlist_selected.emit(current.data(0, _PLAYLIST_ID_ROLE))
        elif itype == _ITYPE_CHANNEL:
            self.channel_selected.emit(current.data(0, _CHANNEL_URL_ROLE) or "")
        elif itype == _ITYPE_FEED_ALL:
            self.feed_all_selected.emit()
        elif itype == _ITYPE_CATEGORY:
            self.category_selected.emit(current.data(0, _CAT_ID_ROLE))
        elif itype == _ITYPE_FOLDER:
            fid = current.data(0, _FOLDER_ID_ROLE)
            if fid:
                self.folder_selected.emit(fid)
            else:
                # 미분류 디렉토리 — 해당 섹션의 미분류 재생목록을 표시
                self.unfiled_selected.emit(current.data(0, _SECTION_ROLE))
        elif itype == _ITYPE_ROOT:
            if current.data(0, _SECTION_ROLE) == "local":
                self.category_selected.emit(None)  # 전체 영상
            elif current.data(0, _SECTION_ROLE) == "youtube":
                self.channels_root_selected.emit()  # 구독 채널 목록 그리드

    def _find_item(self, predicate):
        """술어를 만족하는 첫 노드를 깊이우선으로 찾는다 (없으면 None)."""
        def rec(item: QTreeWidgetItem):
            if predicate(item):
                return item
            for i in range(item.childCount()):
                found = rec(item.child(i))
                if found is not None:
                    return found
            return None
        for i in range(self.topLevelItemCount()):
            found = rec(self.topLevelItem(i))
            if found is not None:
                return found
        return None

    def select_for_snapshot(self, snap: dict) -> bool:
        """스냅샷(kind+id)에 해당하는 노드를 시그널 차단 상태로 선택. 찾으면 True."""
        kind = snap.get("kind", "category")

        def pred(item: QTreeWidgetItem) -> bool:
            it = item.data(0, _ITEM_TYPE_ROLE)
            if kind == "playlist":
                return it == _ITYPE_PLAYLIST and item.data(0, _PLAYLIST_ID_ROLE) == snap.get("playlist_id")
            if kind == "channel":
                return it == _ITYPE_CHANNEL and (item.data(0, _CHANNEL_URL_ROLE) or "") == (snap.get("channel_url") or "")
            if kind == "feed_all":
                return it == _ITYPE_FEED_ALL
            if kind == "channels_root":
                return it == _ITYPE_ROOT and item.data(0, _SECTION_ROLE) == "youtube"
            if kind == "folder":
                fid = snap.get("folder_id")
                if fid is None:   # 미분류
                    return it == _ITYPE_FOLDER and not item.data(0, _FOLDER_ID_ROLE)
                return it == _ITYPE_FOLDER and item.data(0, _FOLDER_ID_ROLE) == fid
            # category
            cat_id = snap.get("cat_id")
            if cat_id is None:
                return it == _ITYPE_ROOT and item.data(0, _SECTION_ROLE) == "local"
            return it == _ITYPE_CATEGORY and item.data(0, _CAT_ID_ROLE) == cat_id

        target = self._find_item(pred)
        if target is None:
            return False
        self.blockSignals(True)
        try:
            parent = target.parent()
            while parent is not None:
                parent.setExpanded(True)
                parent = parent.parent()
            self.setCurrentItem(target)
        finally:
            self.blockSignals(False)
        return True

    def _restore_selection(self, pl_id) -> None:
        def _find(item: QTreeWidgetItem) -> bool:
            if item.data(0, _PLAYLIST_ID_ROLE) == pl_id:
                self.setCurrentItem(item)
                return True
            for i in range(item.childCount()):
                if _find(item.child(i)):
                    return True
            return False
        for i in range(self.topLevelItemCount()):
            if _find(self.topLevelItem(i)):
                break

    def _restore_category_selection(self, cat_id) -> None:
        def _find(item: QTreeWidgetItem) -> QTreeWidgetItem | None:
            if item.data(0, _CAT_ID_ROLE) == cat_id:
                return item
            for i in range(item.childCount()):
                found = _find(item.child(i))
                if found is not None:
                    return found
            return None
        target = None
        for i in range(self.topLevelItemCount()):
            target = _find(self.topLevelItem(i))
            if target is not None:
                break
        if target is None:
            return
        # 선택 카테고리와 새로 추가된 하위 카테고리가 보이도록 자신·조상을 펼친다.
        target.setExpanded(True)
        parent = target.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        self.setCurrentItem(target)

    # ── 아이템 확장/축소 화살표 갱신 ────────────────────────────────────────────

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        if item.data(0, _ITEM_TYPE_ROLE) == _ITYPE_CATEGORY:
            text = item.text(0)
            if text.startswith("▸ "):
                item.setText(0, "▾ " + text[2:])

    def _on_item_collapsed(self, item: QTreeWidgetItem) -> None:
        if item.data(0, _ITEM_TYPE_ROLE) == _ITYPE_CATEGORY:
            text = item.text(0)
            if text.startswith("▾ "):
                item.setText(0, "▸ " + text[2:])

    # ── 드래그 앤 드롭 ────────────────────────────────────────────────────────

    def startDrag(self, supported_actions) -> None:
        item = self.currentItem()
        if item is None:
            return
        itype = item.data(0, _ITEM_TYPE_ROLE)
        if itype == _ITYPE_CATEGORY:
            # 카테고리는 기존 Qt DnD로 처리 (_MIME_CAT_ID는 _CategoryTree에서 사용)
            super().startDrag(supported_actions)
            return
        if itype != _ITYPE_PLAYLIST:
            return
        pl_id = item.data(0, _PLAYLIST_ID_ROLE)
        section = self._section_of(item)
        mime = QMimeData()
        mime.setData(_MIME_PLAYLIST_ID, QByteArray(str(pl_id).encode()))
        mime.setData(_MIME_PLAYLIST_SECTION, QByteArray(section.encode()))
        tip = item.toolTip(0) or ""
        if tip.startswith("YouTube: "):
            yt_id = tip[len("YouTube: "):]
            mime.setData(_MIME_YT_PLAYLIST_ID, QByteArray(yt_id.encode()))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event) -> None:
        mime = event.mimeData()
        if mime.hasFormat(_MIME_VIDEO_ID):
            event.acceptProposedAction()
        elif mime.hasFormat(_MIME_PLAYLIST_ID):
            event.acceptProposedAction()
        elif event.source() is self:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        target = self.itemAt(event.position().toPoint())
        mime = event.mimeData()

        if mime.hasFormat(_MIME_VIDEO_ID):
            # 영상 드롭: 재생목록 또는 카테고리 항목 위에서 허용
            if target and target.data(0, _ITEM_TYPE_ROLE) in (_ITYPE_PLAYLIST, _ITYPE_CATEGORY):
                event.acceptProposedAction()
            else:
                event.ignore()

        elif mime.hasFormat(_MIME_PLAYLIST_ID):
            # 재생목록 드래그 (내부 또는 크로스-트리)
            drag_section_bytes = mime.data(_MIME_PLAYLIST_SECTION)
            drag_section = drag_section_bytes.data().decode() if drag_section_bytes else ""
            if target is None:
                event.ignore()
                return
            target_type = target.data(0, _ITEM_TYPE_ROLE)
            target_section = target.data(0, _SECTION_ROLE) or self._section_of(target)

            if drag_section == "youtube" and target_type == _ITYPE_CATEGORY:
                # YouTube 재생목록 → 로컬 카테고리 (영상 임포트)
                event.acceptProposedAction()
            elif drag_section == "youtube" and target_type in (_ITYPE_FOLDER, _ITYPE_ROOT) and target_section == "local":
                # YouTube 재생목록 → 로컬 폴더/루트 (재생목록 복사)
                event.acceptProposedAction()
            elif drag_section == "local" and target_type in (_ITYPE_CATEGORY, _ITYPE_ROOT):
                # 로컬 재생목록 → 카테고리/루트 (영상 복사 + 새 카테고리 생성)
                event.acceptProposedAction()
            elif drag_section == target_section and target_type in (_ITYPE_FOLDER, _ITYPE_ROOT):
                # 같은 섹션 내 폴더 이동
                event.acceptProposedAction()
            else:
                event.ignore()

        elif event.source() is self:
            # 카테고리 reparent (내부 드래그)
            dragged = self.currentItem()
            if dragged is None or target is None:
                event.ignore()
                return
            drag_type = dragged.data(0, _ITEM_TYPE_ROLE)
            target_type = target.data(0, _ITEM_TYPE_ROLE)
            if drag_type == _ITYPE_CATEGORY and target_type in (_ITYPE_CATEGORY, _ITYPE_ROOT):
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        mime   = event.mimeData()
        target = self.itemAt(event.position().toPoint())

        # ── 영상 → 재생목록 / 카테고리 드롭 ────────────────────────────────
        if mime.hasFormat(_MIME_VIDEO_ID):
            if target is None:
                event.ignore()
                return
            target_type = target.data(0, _ITEM_TYPE_ROLE)
            raw_vids = mime.data(_MIME_VIDEO_ID).data()

            if target_type == _ITYPE_PLAYLIST:
                tgt_pl_id = target.data(0, _PLAYLIST_ID_ROLE)
                raw_src   = mime.data("application/x-source-playlist-id").data()
                src_pl_str = raw_src.decode() if raw_src else ""
                for vid_str in raw_vids.decode().split(","):
                    if vid_str:
                        self.video_move_to_playlist_req.emit(vid_str, src_pl_str, tgt_pl_id)
                event.accept()
                return

            if target_type == _ITYPE_CATEGORY:
                cat_id = target.data(0, _CAT_ID_ROLE)
                for vid_str in raw_vids.decode().split(","):
                    vid_str = vid_str.strip()
                    if vid_str:
                        try:
                            self.video_assign_category_req.emit(UUID(vid_str), cat_id)
                        except (ValueError, AttributeError):
                            pass
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
                return

            event.ignore()
            return

        # ── 재생목록 드래그 (커스텀 MIME) ─────────────────────────────────
        if mime.hasFormat(_MIME_PLAYLIST_ID):
            if target is None:
                event.ignore()
                return

            drag_section_bytes = mime.data(_MIME_PLAYLIST_SECTION)
            drag_section = drag_section_bytes.data().decode() if drag_section_bytes else ""
            yt_id_bytes = mime.data(_MIME_YT_PLAYLIST_ID)
            yt_playlist_id = yt_id_bytes.data().decode() if yt_id_bytes else ""
            pl_id_bytes = mime.data(_MIME_PLAYLIST_ID)
            pl_id_str = pl_id_bytes.data().decode() if pl_id_bytes else ""

            target_type = target.data(0, _ITEM_TYPE_ROLE)
            target_section = target.data(0, _SECTION_ROLE) or self._section_of(target)

            if drag_section == "youtube" and target_type == _ITYPE_CATEGORY:
                # YouTube 재생목록 → 로컬 카테고리 (영상 임포트)
                cat_id = target.data(0, _CAT_ID_ROLE)
                if yt_playlist_id:
                    self.yt_playlist_to_category_req.emit(yt_playlist_id, cat_id)
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
                return

            if drag_section == "youtube" and target_type in (_ITYPE_FOLDER, _ITYPE_ROOT) and target_section == "local":
                # YouTube 재생목록 → 로컬 폴더/루트 (재생목록 복사)
                if yt_playlist_id:
                    self.copy_yt_to_local_req.emit(yt_playlist_id)
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
                return

            if drag_section == "local" and target_type in (_ITYPE_CATEGORY, _ITYPE_ROOT):
                # 로컬 재생목록 → 카테고리/루트 (새 카테고리 생성 + 영상 복사)
                try:
                    pl_id = UUID(pl_id_str)
                except (ValueError, AttributeError):
                    event.ignore()
                    return
                parent_cat_id = target.data(0, _CAT_ID_ROLE) if target_type == _ITYPE_CATEGORY else None
                self.local_playlist_to_category_req.emit(pl_id, parent_cat_id)
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
                return

            if drag_section == target_section and target_type in (_ITYPE_FOLDER, _ITYPE_ROOT):
                # 같은 섹션 내 폴더/미분류로 이동
                try:
                    pl_id = UUID(pl_id_str)
                except (ValueError, AttributeError):
                    event.ignore()
                    return
                folder_id = target.data(0, _FOLDER_ID_ROLE)
                self.playlist_move_req.emit(pl_id, folder_id)
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
                return

            event.ignore()
            return

        # ── 내부 드래그: 카테고리 reparent ────────────────────────────────
        dragged = self.currentItem()
        if dragged is None or target is None:
            event.ignore()
            return

        drag_type    = dragged.data(0, _ITEM_TYPE_ROLE)
        target_type  = target.data(0, _ITEM_TYPE_ROLE)

        if drag_type == _ITYPE_CATEGORY and target_type in (_ITYPE_CATEGORY, _ITYPE_ROOT):
            cat_id = dragged.data(0, _CAT_ID_ROLE)
            if target_type == _ITYPE_ROOT:
                new_parent_id = None
            else:
                new_parent_id = target.data(0, _CAT_ID_ROLE)
                if new_parent_id == cat_id:
                    event.ignore()
                    return
            self.category_reparented.emit(cat_id, new_parent_id)
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return

        event.ignore()

    def _section_of(self, item: QTreeWidgetItem) -> str:
        """item 조상에서 섹션(source)을 찾는다. 없으면 트리의 section으로 폴백."""
        s = item.data(0, _SECTION_ROLE)
        if s:
            return s
        p = item.parent()
        while p is not None:
            s = p.data(0, _SECTION_ROLE)
            if s:
                return s
            p = p.parent()
        return self._section or ""

    # ── 컨텍스트 메뉴 ─────────────────────────────────────────────────────────

    def _show_context_menu(self, pos: QPoint) -> None:
        item = self.itemAt(pos)
        menu = QMenu(self)

        if item is None:
            # 빈 공간 우클릭 — 섹션 루트 메뉴 (section-specific 트리 전용)
            sec = self._section
            if sec:
                if sec == "local":
                    act_cat = QAction("새 카테고리 추가", self)
                    act_cat.triggered.connect(lambda: self.add_category_req.emit(None))
                    menu.addAction(act_cat)
                else:
                    act_folder = QAction("새 폴더 추가", self)
                    act_folder.triggered.connect(lambda: self.folder_create_req.emit(sec))
                    menu.addAction(act_folder)
                if sec == "youtube":
                    act_yt = QAction("↓ YouTube 재생목록 가져오기", self)
                    act_yt.triggered.connect(self.import_yt_req)
                    menu.addAction(act_yt)
            if menu.actions():
                menu.exec(self.viewport().mapToGlobal(pos))
            return

        itype   = item.data(0, _ITEM_TYPE_ROLE)
        section = item.data(0, _SECTION_ROLE) or self._section_of(item)

        if itype == _ITYPE_ROOT:
            if section == "local":
                act_cat = QAction("새 카테고리 추가", self)
                act_cat.triggered.connect(lambda: self.add_category_req.emit(None))
                menu.addAction(act_cat)
            else:
                act = QAction("새 폴더 추가", self)
                act.triggered.connect(lambda: self.folder_create_req.emit(section))
                menu.addAction(act)
            if section == "youtube":
                act_yt = QAction("↓ YouTube 재생목록 가져오기", self)
                act_yt.triggered.connect(self.import_yt_req)
                menu.addAction(act_yt)

        elif itype == _ITYPE_CATEGORY:
            cat_id = item.data(0, _CAT_ID_ROLE)
            cat_name = item.text(0).replace("🏷  ", "").split("  (")[0]
            from application.library.favorites import is_favorite  # noqa: PLC0415
            fav_label = "★ 즐겨찾기 제거" if is_favorite(str(cat_id), "category") else "☆ 즐겨찾기 추가"
            fav_act = QAction(fav_label, self)
            fav_act.triggered.connect(lambda: self.favorite_toggle_req.emit("category", str(cat_id), cat_name))
            menu.addAction(fav_act)
            menu.addSeparator()
            add_child_act = QAction("하위 카테고리 추가", self)
            add_child_act.triggered.connect(lambda: self.add_category_req.emit(cat_id))
            menu.addAction(add_child_act)
            rename_act = QAction("이름 변경", self)
            rename_act.triggered.connect(lambda: self.rename_category_req.emit(cat_id))
            menu.addAction(rename_act)
            menu.addSeparator()
            del_act = QAction("삭제", self)
            del_act.triggered.connect(lambda: self.delete_category_req.emit(cat_id))
            menu.addAction(del_act)

        elif itype == _ITYPE_FOLDER:
            folder_id = item.data(0, _FOLDER_ID_ROLE)
            if folder_id is not None:  # 미분류는 이름변경/삭제 불가
                rename_act = QAction("이름 변경", self)
                rename_act.triggered.connect(
                    lambda: self.folder_rename_req.emit(folder_id, item.text(0).replace("📂  ", ""))
                )
                menu.addAction(rename_act)
                del_act = QAction("폴더 삭제 (재생목록은 미분류로 이동)", self)
                del_act.triggered.connect(lambda: self.folder_delete_req.emit(folder_id))
                menu.addAction(del_act)

        elif itype == _ITYPE_PLAYLIST:
            pl_id = item.data(0, _PLAYLIST_ID_ROLE)
            pl_name = item.text(0).strip().rsplit("  (", 1)[0]
            from application.library.favorites import is_favorite  # noqa: PLC0415
            fav_label = "★ 즐겨찾기 제거" if is_favorite(str(pl_id), "playlist") else "☆ 즐겨찾기 추가"
            fav_act = QAction(fav_label, self)
            fav_act.triggered.connect(lambda: self.favorite_toggle_req.emit("playlist", str(pl_id), pl_name))
            menu.addAction(fav_act)
            menu.addSeparator()
            rename_act = QAction("이름 변경", self)
            rename_act.triggered.connect(lambda: self.playlist_rename_req.emit(pl_id))
            menu.addAction(rename_act)

            if section == "local":
                menu.addSeparator()
                copy_to_yt_act = QAction("YouTube로 복사 (YouTube에 새 재생목록 생성)", self)
                copy_to_yt_act.triggered.connect(
                    lambda: self.push_to_yt_req.emit(pl_id, False)
                )
                menu.addAction(copy_to_yt_act)
                move_to_yt_act = QAction("YouTube로 이동 (로컬 항목을 YouTube로 전환)", self)
                move_to_yt_act.triggered.connect(
                    lambda: self.push_to_yt_req.emit(pl_id, True)
                )
                menu.addAction(move_to_yt_act)

            if section == "youtube":
                yt_id = item.toolTip(0).replace("YouTube: ", "") if item.toolTip(0) else ""
                menu.addSeparator()
                copy_act = QAction("로컬로 복사", self)
                copy_act.triggered.connect(lambda: self.copy_yt_to_local_req.emit(yt_id))
                menu.addAction(copy_act)
                sync_act = QAction("YouTube에서 동기화", self)
                sync_act.triggered.connect(lambda: self.sync_yt_req.emit(yt_id))
                menu.addAction(sync_act)

            menu.addSeparator()
            del_act = QAction("삭제", self)
            del_act.triggered.connect(lambda: self.playlist_delete_req.emit(pl_id))
            menu.addAction(del_act)

        if menu.actions():
            menu.exec(self.viewport().mapToGlobal(pos))


# ------------------------------------------------------------------
# 폴더 카드 뷰 위젯들
# ------------------------------------------------------------------

class _PlaylistThumbLabel(QLabel):
    """재생목록 카드 썸네일 — 영상 개수 배지를 우하단에 오버레이."""

    _W, _H = 213, 120

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._thumb: QPixmap | None = None
        self._count: int = 0
        self.setFixedSize(self._W, self._H)

    def set_data(self, thumb_path: str, count: int) -> None:
        self._count = count
        self._thumb = None
        if thumb_path:
            p = Path(THUMBNAIL_DIR) / thumb_path
            if p.exists():
                pix = QPixmap(str(p))
                if not pix.isNull():
                    self._thumb = pix.scaled(
                        self._W, self._H,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        painter.fillRect(rect, QColor(30, 30, 30))
        if self._thumb:
            sw, sh = self._thumb.width(), self._thumb.height()
            sx = max(0, (sw - self._W) // 2)
            sy = max(0, (sh - self._H) // 2)
            painter.drawPixmap(rect, self._thumb, QRect(sx, sy, self._W, self._H))
        else:
            painter.setPen(QColor(90, 90, 90))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "No thumbnail")
        if self._count > 0:
            bw, bh = 46, 20
            bx = rect.right() - bw - 4
            by = rect.bottom() - bh - 4
            painter.fillRect(QRect(bx, by, bw, bh), QColor(0, 0, 0, 170))
            painter.setPen(QColor(255, 255, 255))
            f = QFont()
            f.setPointSize(8)
            f.setBold(True)
            painter.setFont(f)
            painter.drawText(QRect(bx, by, bw, bh), Qt.AlignmentFlag.AlignCenter, f"▶ {self._count}")
        painter.end()


class _FolderCard(QFrame):
    """섹션 루트 뷰의 폴더 디렉터리 카드."""

    clicked = pyqtSignal(object)   # folder UUID

    def __init__(self, folder, parent=None) -> None:
        super().__init__(parent)
        self._folder_id = folder.id
        self.setFixedWidth(221)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        icon_lbl = QLabel("📂")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("font-size:36pt;")
        layout.addWidget(icon_lbl)
        name_lbl = QLabel(folder.name)
        name_lbl.setWordWrap(True)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setStyleSheet("font-size:9pt; font-weight:600;")
        layout.addWidget(name_lbl)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._folder_id)
        super().mousePressEvent(event)


class _UnfiledCard(QFrame):
    """섹션 루트 뷰의 '미분류' 디렉터리 카드."""

    clicked = pyqtSignal()

    def __init__(self, count: int, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(221)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        icon_lbl = QLabel("📂")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("font-size:36pt;")
        layout.addWidget(icon_lbl)
        name_lbl = QLabel(f"미분류  ({count})" if count else "미분류")
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setStyleSheet("font-size:9pt; font-weight:600; color:#aaa;")
        layout.addWidget(name_lbl)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _PlaylistCard(QFrame):
    """폴더 뷰의 재생목록 카드 한 장."""

    clicked = pyqtSignal(object)   # playlist UUID

    def __init__(self, pl, get_first_item, parent=None) -> None:
        super().__init__(parent)
        self._pl_id = pl.id
        self.setFixedWidth(221)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._thumb = _PlaylistThumbLabel()
        layout.addWidget(self._thumb)

        title_lbl = QLabel(pl.title)
        title_lbl.setWordWrap(True)
        title_lbl.setMaximumHeight(38)
        title_lbl.setStyleSheet("font-size:9pt; font-weight:600;")
        layout.addWidget(title_lbl)

        time_lbl = QLabel(_fmt_elapsed(pl.updated_at))
        time_lbl.setStyleSheet("font-size:8pt; color:#888;")
        layout.addWidget(time_lbl)

        first = get_first_item(pl.id) if get_first_item else None
        self._thumb.set_data(first.thumbnail_path if first else "", pl.item_count)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._pl_id)
        super().mousePressEvent(event)


class _FolderContentsView(QScrollArea):
    """폴더/섹션 루트 선택 시 하위 폴더·미분류·재생목록을 카드 그리드로 표시한다."""

    playlist_selected = pyqtSignal(object)   # playlist UUID
    folder_selected   = pyqtSignal(object)   # folder UUID

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self._container = QWidget()
        self._grid = None   # QGridLayout — 카드 로드 시 생성
        self.setWidget(self._container)

    def load(
        self,
        playlists: list,
        get_first_item,
        folders: list | None = None,
        show_unfiled: bool = False,
        unfiled_count: int = 0,
    ) -> None:
        """폴더 카드(선택적) + 미분류 카드(선택적) + 재생목록 카드를 그리드로 표시한다."""
        # 이전 카드 전부 제거
        old_layout = self._container.layout()
        if old_layout is not None:
            while old_layout.count():
                item = old_layout.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()
            QWidget().setLayout(old_layout)

        from PyQt6.QtWidgets import QGridLayout  # noqa: PLC0415
        grid = QGridLayout(self._container)
        grid.setSpacing(12)
        grid.setContentsMargins(12, 12, 12, 12)
        cols = 3
        idx = 0

        # ── 폴더 카드 ──
        for f in (folders or []):
            card = _FolderCard(f, self._container)
            card.clicked.connect(self.folder_selected)
            grid.addWidget(card, idx // cols, idx % cols)
            idx += 1

        # ── 미분류 카드 ──
        if show_unfiled:
            card = _UnfiledCard(unfiled_count, self._container)
            card.clicked.connect(lambda: self.folder_selected.emit(None))
            grid.addWidget(card, idx // cols, idx % cols)
            idx += 1

        # ── 재생목록 카드 ──
        for pl in playlists:
            card = _PlaylistCard(pl, get_first_item, self._container)
            card.clicked.connect(self.playlist_selected)
            grid.addWidget(card, idx // cols, idx % cols)
            idx += 1

        if idx > 0:
            grid.setColumnStretch(cols, 1)
            grid.setRowStretch((idx - 1) // cols + 1, 1)
        self._grid = grid

        if idx == 0:
            lbl = QLabel("이 폴더에 재생목록이 없습니다.")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color:#888; font-size:11pt;")
            grid.addWidget(lbl, 0, 0)


# ── 브랜치 인디케이터 화살표 픽스맵 헬퍼 ─────────────────────────────────────

_arrow_cache: dict[str, str] = {}   # (state+color) → 임시 png 경로


def _write_branch_arrow_pixmap(state: str, color: str) -> str:
    """QSS image:url() 에 주입할 화살표 PNG를 생성해 임시 파일 경로를 반환한다.

    state: "closed" → ▶(오른쪽), "open" → ▼(아래쪽)
    결과를 _arrow_cache에 캐싱해 동일 색상 재호출을 방지한다.
    """
    import os  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    from PyQt6.QtGui import QPainter, QColor, QPolygonF  # noqa: PLC0415
    from PyQt6.QtCore import QPointF  # noqa: PLC0415

    key = f"{state}:{color}"
    if key in _arrow_cache and os.path.exists(_arrow_cache[key]):
        return _arrow_cache[key]

    size = 12
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor(color)
    painter.setBrush(c)
    painter.setPen(Qt.PenStyle.NoPen)

    half = size / 2
    if state == "closed":
        # ▶ 오른쪽 삼각형
        poly = QPolygonF([
            QPointF(3, 2), QPointF(size - 3, half), QPointF(3, size - 2),
        ])
    else:
        # ▼ 아래쪽 삼각형
        poly = QPolygonF([
            QPointF(2, 3), QPointF(size - 2, 3), QPointF(half, size - 3),
        ])
    painter.drawPolygon(poly)
    painter.end()

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp.close()
    pm.save(tmp.name, "PNG")
    # QSS image:url() 는 반드시 슬래시(/)만 허용한다.
    # Windows 백슬래시 경로를 그대로 넣으면 QSS가 파싱 실패해 이미지가 표시되지 않는다.
    fwd_path = tmp.name.replace("\\", "/")
    _arrow_cache[key] = fwd_path
    return fwd_path


class _BreadcrumbBar(QWidget):
    """경로 탐색 바 — 즐겨찾기 바 위. 각 세그먼트는 클릭 가능하고 선택된 태그를 우측에 ✕ 칩으로 표시."""

    segment_clicked = pyqtSignal(object)  # category_id UUID | None
    tag_removed     = pyqtSignal(object)  # tag UUID

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(26)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(8, 0, 8, 0)
        self._row.setSpacing(0)
        self.hide()

    def update_path(
        self,
        segments: list,    # list[tuple[str, click_val]] — click_val=None → 비클릭(마지막)
        tag_pairs: list,   # list[tuple[UUID, str]]
    ) -> None:
        while self._row.count():
            item = self._row.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not segments:
            self.hide()
            return

        tok = _t()
        n = len(segments)
        for i, (name, click_val) in enumerate(segments):
            is_last = (i == n - 1)
            is_clickable = not is_last and click_val is not None
            btn = QPushButton(name)
            btn.setFlat(True)
            if is_last:
                btn.setStyleSheet(
                    f"color:{tok.text_primary};font-size:9pt;font-weight:600;"
                    "background:transparent;border:none;padding:0 3px;"
                )
                btn.setCursor(Qt.CursorShape.ArrowCursor)
            elif is_clickable:
                btn.setStyleSheet(
                    f"color:{tok.accent};font-size:9pt;"
                    "background:transparent;border:none;padding:0 3px;"
                    "text-decoration:underline;"
                )
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                _cv = click_val
                btn.clicked.connect(lambda _, cv=_cv: self.segment_clicked.emit(cv))
            else:
                btn.setStyleSheet(
                    f"color:{tok.text_secondary};font-size:9pt;"
                    "background:transparent;border:none;padding:0 3px;"
                )
                btn.setCursor(Qt.CursorShape.ArrowCursor)
            self._row.addWidget(btn)

            if not is_last:
                sep = QLabel(" › ")
                sep.setStyleSheet(f"color:{tok.text_muted};font-size:9pt;")
                self._row.addWidget(sep)

        if tag_pairs:
            div = QLabel("  :  ")
            div.setStyleSheet(f"color:{tok.text_muted};font-size:9pt;")
            self._row.addWidget(div)
            for tag_id, tname in tag_pairs:
                color = _TAG_PALETTE[hash(tname) % len(_TAG_PALETTE)]
                chip = QPushButton(f"#{tname}  ✕")
                chip.setFlat(True)
                chip.setStyleSheet(
                    f"color:#ffffff;font-size:8pt;"
                    f"background:{color};border-radius:4px;padding:2px 8px;"
                    "border:none;"
                )
                chip.setCursor(Qt.CursorShape.PointingHandCursor)
                chip.setToolTip(f"#{tname} 태그 필터 제거")
                _tid = tag_id
                chip.clicked.connect(lambda _, tid=_tid: self.tag_removed.emit(tid))
                self._row.addWidget(chip)

        self._row.addStretch()
        self.show()


class _PlaylistPanel(QWidget):
    """통합 사이드바 패널 — 로컬 트리 + YouTube 트리 분리."""

    playlist_selected             = pyqtSignal(object)         # UUID | None
    folder_selected               = pyqtSignal(object)         # folder UUID
    unfiled_selected              = pyqtSignal(object)         # source str — 미분류 디렉토리
    category_selected             = pyqtSignal(object)         # category UUID
    channel_selected              = pyqtSignal(str)            # 구독 채널 URL
    feed_all_selected             = pyqtSignal()               # 전체 구독 피드
    channels_root_selected        = pyqtSignal()               # "구독 채널" 노드 — 채널 목록 그리드
    delete_playlist_req           = pyqtSignal(object)         # playlist UUID
    rename_playlist_req           = pyqtSignal(object)         # playlist UUID
    playlist_move_req             = pyqtSignal(object, object) # (playlist_id, folder_id|None)
    import_yt_req                 = pyqtSignal()
    sync_all_yt_req               = pyqtSignal()               # 전체 YouTube 재생목록 동기화
    folder_create_req             = pyqtSignal(str)            # source
    folder_rename_req             = pyqtSignal(object, str)    # (folder_id, old_name)
    folder_delete_req             = pyqtSignal(object)         # folder UUID
    copy_yt_to_local_req          = pyqtSignal(object)         # yt_playlist_id str
    sync_yt_req                   = pyqtSignal(object)         # yt_playlist_id str
    push_to_yt_req                = pyqtSignal(object, bool)   # (playlist_id, move: bool)
    video_move_to_playlist_req    = pyqtSignal(object, object, object)  # (vid_str, src_pl_str, tgt_pl_id)
    video_reordered               = pyqtSignal(object, list)   # (playlist_id, list[UUID])
    add_category_req              = pyqtSignal(object)         # parent_id (UUID | None)
    rename_category_req           = pyqtSignal(object)         # category UUID
    delete_category_req           = pyqtSignal(object)         # category UUID
    category_reparented           = pyqtSignal(object, object) # (cat_id, new_parent_id | None)
    yt_playlist_to_category_req   = pyqtSignal(str, object)    # (yt_playlist_id, cat_id UUID)
    favorite_toggle_req           = pyqtSignal(str, str, str)  # (type, id, name)
    video_assign_category_req      = pyqtSignal(object, object) # (video_id UUID, cat_id UUID | None)
    local_playlist_to_category_req = pyqtSignal(object, object) # (playlist_id UUID, parent_cat_id UUID | None)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ── 로컬 섹션 + YouTube 섹션 분리 (수직 스플리터) ──
        self._splitter = QSplitter(Qt.Orientation.Vertical)

        # 로컬 섹션
        local_container = QWidget()
        local_layout = QVBoxLayout(local_container)
        local_layout.setContentsMargins(0, 0, 0, 0)
        local_layout.setSpacing(2)
        local_hdr_row = QHBoxLayout()
        local_hdr_row.setContentsMargins(0, 0, 0, 0)
        local_hdr = QPushButton("📁  로컬")
        local_hdr.setObjectName("playlist_section_header_local")
        local_hdr.setFlat(True)
        local_hdr.setCursor(Qt.CursorShape.PointingHandCursor)
        local_hdr.setToolTip("클릭: 카테고리 전체 영상 표시")
        local_hdr.clicked.connect(lambda: self.category_selected.emit(None))
        local_hdr_row.addWidget(local_hdr, stretch=1)
        local_cat_btn = QToolButton()
        local_cat_btn.setText("🏷+")
        local_cat_btn.setToolTip("새 카테고리 만들기")
        local_cat_btn.setFixedHeight(18)
        local_cat_btn.clicked.connect(lambda: self.add_category_req.emit(None))
        local_hdr_row.addWidget(local_cat_btn)
        local_layout.addLayout(local_hdr_row)
        self._local_tree = _PlaylistTree(section="local")
        local_layout.addWidget(self._local_tree, stretch=1)
        self._splitter.addWidget(local_container)

        # YouTube 섹션
        yt_container = QWidget()
        yt_layout = QVBoxLayout(yt_container)
        yt_layout.setContentsMargins(0, 0, 0, 0)
        yt_layout.setSpacing(2)
        yt_hdr_row = QHBoxLayout()
        yt_hdr_row.setContentsMargins(2, 0, 2, 0)
        yt_hdr_row.setSpacing(4)
        # YouTube 헤더 — 클릭 시 재생목록 가져오기 다이얼로그 열기
        self._yt_title_btn = QPushButton("▶  YouTube")
        self._yt_title_btn.setObjectName("playlist_section_header_yt_btn")
        self._yt_title_btn.setFlat(True)
        self._yt_title_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._yt_title_btn.setToolTip("클릭 — YouTube 재생목록 가져오기")
        self._yt_title_btn.clicked.connect(self.import_yt_req)
        yt_hdr_row.addWidget(self._yt_title_btn, stretch=1)
        # 동기화 버튼 (순환 화살표 ⟳)
        yt_sync_btn = QToolButton()
        yt_sync_btn.setText("⟳")
        yt_sync_btn.setToolTip("YouTube 재생목록 전체 동기화")
        yt_sync_btn.setFixedHeight(18)
        yt_sync_btn.clicked.connect(self.sync_all_yt_req)
        yt_hdr_row.addWidget(yt_sync_btn)
        yt_folder_btn = QToolButton()
        yt_folder_btn.setText("📂+")
        yt_folder_btn.setToolTip("새 YouTube 폴더 만들기")
        yt_folder_btn.setFixedHeight(18)
        yt_folder_btn.clicked.connect(lambda: self.folder_create_req.emit("youtube"))
        yt_hdr_row.addWidget(yt_folder_btn)
        yt_layout.addLayout(yt_hdr_row)
        self._yt_tree = _PlaylistTree(section="youtube")
        yt_layout.addWidget(self._yt_tree, stretch=1)
        self._splitter.addWidget(yt_container)

        self._splitter.setStretchFactor(0, 3)
        self._splitter.setStretchFactor(1, 2)
        layout.addWidget(self._splitter, stretch=1)

        self._connect_tree(self._local_tree)
        self._connect_tree(self._yt_tree)

    def _connect_tree(self, tree: _PlaylistTree) -> None:
        tree.playlist_selected.connect(self.playlist_selected)
        tree.folder_selected.connect(self.folder_selected)
        tree.unfiled_selected.connect(self.unfiled_selected)
        tree.category_selected.connect(self.category_selected)
        tree.channel_selected.connect(self.channel_selected)
        tree.feed_all_selected.connect(self.feed_all_selected)
        tree.channels_root_selected.connect(self.channels_root_selected)
        tree.playlist_delete_req.connect(self.delete_playlist_req)
        tree.playlist_rename_req.connect(self.rename_playlist_req)
        tree.playlist_move_req.connect(self.playlist_move_req)
        tree.folder_create_req.connect(self.folder_create_req)
        tree.folder_rename_req.connect(self.folder_rename_req)
        tree.folder_delete_req.connect(self.folder_delete_req)
        tree.copy_yt_to_local_req.connect(self.copy_yt_to_local_req)
        tree.sync_yt_req.connect(self.sync_yt_req)
        tree.import_yt_req.connect(self.import_yt_req)
        tree.push_to_yt_req.connect(self.push_to_yt_req)
        tree.video_move_to_playlist_req.connect(self.video_move_to_playlist_req)
        tree.add_category_req.connect(self.add_category_req)
        tree.rename_category_req.connect(self.rename_category_req)
        tree.delete_category_req.connect(self.delete_category_req)
        tree.category_reparented.connect(self.category_reparented)
        tree.yt_playlist_to_category_req.connect(self.yt_playlist_to_category_req)
        tree.favorite_toggle_req.connect(self.favorite_toggle_req)
        tree.video_assign_category_req.connect(self.video_assign_category_req)
        tree.local_playlist_to_category_req.connect(self.local_playlist_to_category_req)

    @property
    def trees(self) -> list:
        return [self._local_tree, self._yt_tree]

    def refresh(self, playlists, folders=None, categories=None, subscriptions=None) -> None:
        self._local_tree.load(playlists, folders or [], categories or [])
        self._yt_tree.load(playlists, folders or [], subscriptions=subscriptions or [])

    def select_playlist(self, playlist_id) -> None:
        """두 트리에서 해당 재생목록 항목을 선택한다."""
        self._local_tree._restore_selection(playlist_id)
        self._yt_tree._restore_selection(playlist_id)

    def select_snapshot(self, snap: dict) -> None:
        """뒤로/앞으로 복원 시 스냅샷에 해당하는 트리 노드를 강조한다.

        시그널을 차단해 선택 변경이 핸들러를 재실행하지 않도록 한다(이중 실행 방지).
        일치 노드를 찾은 트리만 선택하고 나머지 트리는 선택 해제한다.
        """
        matched = None
        for tr in self.trees:
            if matched is None and tr.select_for_snapshot(snap):
                matched = tr
        for tr in self.trees:
            if tr is not matched:
                tr.blockSignals(True)
                tr.clearSelection()
                tr.blockSignals(False)


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
        # Windows에서 브라우저 드래그 시 dragEnter 단계에 MIME 내용이 없을 수 있어
        # 포맷 존재 여부로 판단한다 — 실제 URL 검증은 dropEvent에서 수행
        self._ext_url_drag = _mime_may_contain_url(mime)
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
    path_changed       = pyqtSignal(str)   # 현재 위치 경로 문자열 (breadcrumb)

    def __init__(
        self,
        vm: LibraryViewModel,
        clip_vm=None,
        download_vm=None,
        playlist_vm=None,
        feed_vm=None,
        monitoring_vm=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._vm = vm
        self._clip_vm = clip_vm
        self._download_vm = download_vm
        self._playlist_vm = playlist_vm
        self._feed_vm = feed_vm
        self._monitoring_vm = monitoring_vm
        self._all_tags: list = []
        self._active_tag_ids: set[UUID] = set()
        self._current_cat_id: UUID | None = None
        self._current_playlist_id: UUID | None = None
        self._current_folder_id: UUID | None = None
        self._feed_show_channel: bool = True   # 피드 카드에 채널명 표시 여부
        self._icon_delegate = _IconDelegate()
        self._list_delegate = _ListDelegate()
        self._refresh_dlg: QProgressDialog | None = None
        # 내비게이션 히스토리 (최대 50개 상태 보존) + 앞으로가기 스택
        self._nav_history: list[dict] = []
        self._nav_future: list[dict] = []
        self._is_restoring: bool = False
        self._current_channel_url: str = ""      # 단일 채널 피드 복원용
        self._current_detail_payload: object = None  # 상세 화면 재진입용(UUID|FeedVideoDTO)
        self._setup_ui()
        self._connect_signals()
        vm.load()
        if playlist_vm is not None:
            playlist_vm.load()

    # ── Layout ─────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        outer_splitter = _PreviewSplitter(Qt.Orientation.Horizontal, self)

        # ── 1. Left: 통합 트리 (카테고리 + 재생목록) + 태그 ──
        left = QWidget()
        left.setMaximumWidth(220)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(2)

        # 트리(상단) + 태그 섹션(하단)을 일반 세로 레이아웃으로 쌓는다. 태그 섹션은
        # 카테고리 선택 시에만 보이며(_set_popular_tags_visible), 숨기면 트리가 그
        # 공간을 차지한다. (이전에는 QSplitter로 묶었으나, 스플리터 자식의 가시성
        # 토글이 레이아웃 재분배 thrash → 깜빡임·프리징을 유발해 일반 레이아웃으로 교체.)
        nav_container = QWidget()
        nav_layout = QVBoxLayout(nav_container)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(4)
        self._playlist_panel = _PlaylistPanel()
        self._apply_sidebar_tree_style()
        nav_layout.addWidget(self._playlist_panel, stretch=2)

        self._tag_section = QWidget()
        tag_section_layout = QVBoxLayout(self._tag_section)
        tag_section_layout.setContentsMargins(0, 0, 0, 0)
        tag_section_layout.setSpacing(4)

        self._popular_hdr = QLabel("인기 태그")
        self._popular_hdr.setStyleSheet(
            f"font-size:8pt;color:{_t().text_muted};font-weight:600;padding:2px 4px;"
        )
        tag_section_layout.addWidget(self._popular_hdr)

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

        nav_layout.addWidget(self._tag_section, stretch=1)
        left_layout.addWidget(nav_container, stretch=1)

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

        # ── 경로 탐색 바 (즐겨찾기 바 위) ──
        self._breadcrumb_bar = _BreadcrumbBar()
        centre_layout.addWidget(self._breadcrumb_bar)

        # ── 즐겨찾기 바 ──
        self._favorites_bar = _FavoritesBar()
        centre_layout.addWidget(self._favorites_bar)

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
        self._btn_reorder = QToolButton()
        self._btn_reorder.setText("⇅")
        self._btn_reorder.setToolTip("카테고리 영상 순서 편집 (드래그로 재정렬)")
        self._btn_reorder.setCheckable(True)
        self._btn_reorder.setChecked(False)
        self._btn_reorder.setFixedSize(28, 28)
        self._btn_reorder.hide()   # 카테고리 선택 시에만 표시
        toolbar.addWidget(self._btn_reorder)


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

        # 폴더 내 재생목록 카드 그리드 뷰 (_VIEW_FOLDER = 3)
        self._folder_view = _FolderContentsView()
        self._view_stack.addWidget(self._folder_view)

        # 구독 채널/전체 피드 카드 그리드 뷰 (_VIEW_FEED = 4) — feed_panel 부품 재사용
        self._feed_view = self._build_feed_view()
        self._view_stack.addWidget(self._feed_view)

        # 구독 채널 목록(아바타 카드) 그리드 뷰 (_VIEW_CHANNELS = 5)
        self._channels_view = self._build_channels_view()
        self._view_stack.addWidget(self._channels_view)

        centre_layout.addWidget(self._view_stack, stretch=1)
        self._nav_stack.addWidget(centre_content)

        self._detail_widget = VideoDetailWidget(clip_vm=self._clip_vm)
        self._nav_stack.addWidget(self._detail_widget)

        outer_splitter.addWidget(self._nav_stack)

        # 미리보기 패널 제거 — 영상 단일 클릭 시 곧바로 상세화면(YouTube 시청 페이지)으로
        # 전환하므로 우측 미리보기 패널은 더 이상 사용하지 않는다.
        outer_splitter.setStretchFactor(0, 0)
        outer_splitter.setStretchFactor(1, 1)
        outer_splitter.setSizes([200, 800])

        self._outer_splitter = outer_splitter

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(outer_splitter)

    # ── Signal wiring ──────────────────────────────────────────────

    def _connect_signals(self) -> None:
        self._vm.videos_changed.connect(self._on_videos_changed)
        self._vm.categories_changed.connect(self._on_categories_changed)
        self._vm.tags_changed.connect(self._on_tags_changed)
        self._vm.scoped_tags_changed.connect(self._refresh_popular_tags)
        ThemeManager.instance().theme_changed.connect(lambda _: self._apply_sidebar_tree_style())

        # 재생목록 탭 시그널
        # playlist_selected → 뷰 전환 포함 통합 핸들러 (폴더 뷰 → 목록 뷰 복귀 버그 수정)
        self._playlist_panel.playlist_selected.connect(self._on_playlist_selected_from_tree)
        self._playlist_panel.delete_playlist_req.connect(self._on_delete_playlist)
        self._playlist_panel.rename_playlist_req.connect(self._on_rename_playlist)
        self._playlist_panel.playlist_move_req.connect(self._on_playlist_move)
        self._playlist_panel.import_yt_req.connect(self._on_import_yt_playlist)
        self._playlist_panel.sync_all_yt_req.connect(self._on_sync_all_yt)
        self._playlist_panel.video_reordered.connect(self._on_playlist_reordered)
        self._playlist_panel.folder_create_req.connect(self._on_folder_create)
        self._playlist_panel.folder_rename_req.connect(self._on_folder_rename)
        self._playlist_panel.folder_delete_req.connect(self._on_folder_delete)
        self._playlist_panel.copy_yt_to_local_req.connect(self._on_copy_yt_to_local)
        self._playlist_panel.sync_yt_req.connect(self._on_sync_yt_playlist)
        self._playlist_panel.push_to_yt_req.connect(self._on_push_to_youtube)
        self._playlist_panel.video_move_to_playlist_req.connect(self._on_video_move_to_playlist_from_dnd)
        self._playlist_panel.folder_selected.connect(self._on_folder_selected)
        self._playlist_panel.unfiled_selected.connect(self._on_unfiled_selected)
        self._playlist_panel.channel_selected.connect(self._on_channel_selected)
        self._playlist_panel.feed_all_selected.connect(self._on_feed_all_selected)
        self._playlist_panel.channels_root_selected.connect(self._on_channels_root_selected)
        self._folder_view.playlist_selected.connect(self._on_folder_playlist_selected)
        self._folder_view.folder_selected.connect(self._on_folder_selected)
        if self._playlist_vm is not None:
            self._playlist_vm.playlists_changed.connect(self._on_playlists_changed)
            self._playlist_vm.folders_changed.connect(self._on_playlists_changed)
            self._playlist_vm.error_occurred.connect(
                lambda err: self._vm.error_occurred.emit(err)
            )
        # 구독 피드 VM (구독 채널 트리에 통합)
        if self._feed_vm is not None:
            self._feed_vm.feed_changed.connect(self._on_feed_changed)
            self._feed_vm.channel_infos_changed.connect(self._on_channel_infos_changed)
            self._feed_vm.loading_changed.connect(self._on_feed_loading_changed)
            self._feed_vm.error_occurred.connect(self._on_feed_error)
        # 채널 모니터링 VM — 구독 목록을 YouTube 트리에 반영
        if self._monitoring_vm is not None:
            self._monitoring_vm.subscriptions_changed.connect(self._refresh_unified_tree)
            self._monitoring_vm.load()
        self._vm.yt_import_finished.connect(self._on_yt_import_finished)

        self._view_group.idClicked.connect(self._switch_view)
        self._search_box.textChanged.connect(self._vm.set_search_text)
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        self._btn_reorder.toggled.connect(self._on_reorder_toggled)
        self._model.reordered.connect(self._on_category_reordered)

        self._playlist_panel.category_selected.connect(self._on_cat_filter_changed)
        self._playlist_panel.add_category_req.connect(self._on_add_category)
        self._playlist_panel.rename_category_req.connect(self._on_rename_category)
        self._playlist_panel.delete_category_req.connect(self._on_delete_category)
        self._playlist_panel.category_reparented.connect(self._on_category_reparented)
        self._playlist_panel.yt_playlist_to_category_req.connect(self._on_yt_playlist_to_category)
        self._playlist_panel.favorite_toggle_req.connect(self._toggle_favorite)
        self._playlist_panel.video_assign_category_req.connect(self._on_video_moved)
        self._playlist_panel.local_playlist_to_category_req.connect(self._on_local_playlist_to_category)
        self._breadcrumb_bar.segment_clicked.connect(self._on_breadcrumb_nav)
        self._breadcrumb_bar.tag_removed.connect(self._on_active_tag_removed)
        self._vm.metadata_refresh_progress.connect(self._on_refresh_progress)
        self._vm.metadata_refresh_finished.connect(self._on_refresh_finished)
        self._tag_list.itemClicked.connect(self._on_tag_clicked)
        self._tag_list.delete_requested.connect(self._on_tag_delete_requested)
        self._tag_list.favorite_toggled.connect(self._toggle_favorite)
        self._tag_filter_input.textChanged.connect(self._on_tag_filter_text_changed)
        self._favorites_bar.item_clicked.connect(self._on_favorite_clicked)
        self._favorites_bar.unfav_requested.connect(self._on_fav_unfav_requested)
        self._favorites_bar.refresh()

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

        self._detail_widget.back_requested.connect(self._on_detail_back_requested)
        self._detail_widget.tag_filter_requested.connect(self._on_tag_filter_requested)
        self._detail_widget.tags_updated.connect(self._on_detail_tags_updated)
        self._detail_widget.download_requested.connect(self.download_requested.emit)
        self._detail_widget.item_selected.connect(self._on_related_item_selected)

        # 구독 피드/채널 카드 단일 클릭 → 스트리밍 상세
        self._feed_grid.video_clicked.connect(self._open_stream_detail)

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
        self._refresh_unified_tree()

    def _refresh_unified_tree(self) -> None:
        """카테고리 또는 재생목록이 변경될 때 통합 트리를 갱신한다."""
        subs = self._monitoring_vm.subscriptions if self._monitoring_vm is not None else []
        if self._playlist_vm is not None:
            self._playlist_panel.refresh(
                self._playlist_vm.playlists,
                self._playlist_vm.folders,
                self._vm.categories,
                subscriptions=subs,
            )
        else:
            self._playlist_panel.refresh([], [], self._vm.categories, subscriptions=subs)
        self._favorites_bar.refresh(self._get_fav_counts())

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

    def _apply_sidebar_tree_style(self) -> None:
        tok = _t()
        style = f"""
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
            QTreeWidget::branch {{
                background: transparent;
            }}
            QTreeWidget::branch:hover {{
                background: {tok.bg_overlay};
                border-radius: 3px;
            }}
        """
        # 로컬 트리 branch 컬럼에 화살표 인디케이터를 픽스맵으로 그린다.
        # 테마 accent 색상 기반 ▶(접힘) / ▼(펼침) 아이콘을 임시 파일에 저장해 QSS에 주입.
        arrow_color = tok.accent
        arrow_closed_path = _write_branch_arrow_pixmap("closed", arrow_color)
        arrow_open_path   = _write_branch_arrow_pixmap("open",   arrow_color)
        branch_style = style + f"""
            QTreeWidget::branch:has-children:!has-siblings:closed,
            QTreeWidget::branch:closed:has-children:has-siblings {{
                image: url({arrow_closed_path});
            }}
            QTreeWidget::branch:open:has-children:!has-siblings,
            QTreeWidget::branch:open:has-children:has-siblings {{
                image: url({arrow_open_path});
            }}
        """
        hdr_style = f"""
            QLabel#playlist_section_header {{
                font-size: 9pt;
                font-weight: 700;
                color: {tok.text_secondary};
                padding: 4px 6px 2px 4px;
                background: transparent;
            }}
            QPushButton#playlist_section_header_local {{
                font-size: 9pt;
                font-weight: 700;
                color: {tok.text_secondary};
                padding: 4px 6px 2px 4px;
                background: transparent;
                border: none;
                text-align: left;
            }}
            QPushButton#playlist_section_header_local:hover {{
                color: {tok.text_primary};
                background: transparent;
            }}
            QPushButton#playlist_section_header_yt_btn {{
                font-size: 9pt;
                font-weight: 700;
                color: #ff7070;
                padding: 2px 4px;
                background: transparent;
                border: none;
                text-align: left;
            }}
            QPushButton#playlist_section_header_yt_btn:hover {{
                color: #ff9090;
                text-decoration: underline;
            }}
        """
        local_tree, yt_tree = self._playlist_panel.trees
        local_tree.setStyleSheet(branch_style)   # 로컬: branch indicator 있음
        yt_tree.setStyleSheet(branch_style)      # YouTube: "구독 채널" 등 자식 노드에 펼침 세모 표시
        self._playlist_panel.setStyleSheet(hdr_style)

    def _refresh_active_tags_bar(self) -> None:
        self._refresh_breadcrumb()
        self._refresh_popular_tags()

    def _set_popular_tags_visible(self, visible: bool) -> None:
        """태그 섹션(인기/전체 태그)은 카테고리 선택 시에만 보인다. 재생목록·폴더·
        피드·채널 뷰에서는 숨겨 재생목록 트리가 그 공간을 차지하도록 한다."""
        self._tag_section.setVisible(visible)

    def _refresh_popular_tags(self) -> None:
        from config.settings import load_hidden_tag_names  # noqa: PLC0415
        hidden_names = load_hidden_tag_names()
        while self._popular_tags_layout.count():
            item = self._popular_tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        # 현재 트리 노드 스코프 태그(카테고리/재생목록). 비면 라이브러리 전체로 폴백.
        source = self._vm.scoped_tags or self._all_tags
        top_tags = sorted(
            (t for t in source if t.name not in hidden_names),
            key=lambda t: -t.count,
        )[:5]
        for tag in top_tags:
            selected = tag.id in self._active_tag_ids
            color = _TAG_PALETTE[hash(tag.name) % len(_TAG_PALETTE)]
            btn = _PopularTagButton(tag.name, tag.count, color, selected)
            btn.clicked.connect(lambda _, tid=tag.id: self._on_popular_tag_clicked(tid))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, b=btn, tid=tag.id, tname=tag.name: self._show_popular_tag_context_menu(pos, b, tid, tname)
            )
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
            for _t_ in self._playlist_panel.trees:
                _t_.clearSelection()

    def _show_popular_tag_context_menu(self, pos, btn, tag_id: UUID, tag_name: str) -> None:
        from application.library.favorites import is_favorite  # noqa: PLC0415
        tag_id_str = str(tag_id)
        menu = QMenu(self)
        fav_label = "★ 즐겨찾기 제거" if is_favorite(tag_id_str, "tag") else "☆ 즐겨찾기 추가"
        fav_act = QAction(fav_label, self)
        fav_act.triggered.connect(lambda: self._toggle_favorite("tag", tag_id_str, tag_name))
        menu.addAction(fav_act)
        menu.exec(btn.mapToGlobal(pos))

    def _update_delegate_tags(self) -> None:
        names = [t.name for t in self._all_tags if t.id in self._active_tag_ids]
        self._icon_delegate.active_tag_names = names
        self._list_delegate.active_tag_names = names
        self._icon_view.viewport().update()
        self._list_view.viewport().update()

    def _on_favorite_clicked(self, fav_type: str, fav_id: str) -> None:
        """즐겨찾기 바 항목 클릭 — 해당 카테고리/재생목록/태그를 활성화한다."""
        try:
            uid = UUID(fav_id)
        except (ValueError, AttributeError):
            return
        if fav_type == "category":
            self._on_cat_filter_changed(uid)
        elif fav_type == "playlist":
            self._on_playlist_selected_from_tree(uid)
        elif fav_type == "tag":
            if not self._is_restoring:
                self._push_nav_state()
            self._active_tag_ids = {uid}
            self._vm.set_tag_filter([uid])
            self._refresh_active_tags_bar()
            self._update_delegate_tags()

    def _toggle_favorite(self, fav_type: str, fav_id: str, name: str) -> None:
        from application.library.favorites import FavoriteItem, add_favorite, is_favorite, remove_favorite  # noqa: PLC0415
        if is_favorite(fav_id, fav_type):
            remove_favorite(fav_id, fav_type)
        else:
            add_favorite(FavoriteItem(type=fav_type, id=fav_id, name=name))
        self._favorites_bar.refresh(self._get_fav_counts())
        self._refresh_unified_tree()

    def _get_fav_counts(self) -> dict[str, int]:
        """즐겨찾기 바에 표시할 항목별 영상/아이템 수를 반환한다.

        카테고리는 직속 영상 수와 모든 하위 카테고리 영상 수를 합산한다.
        """
        counts: dict[str, int] = {}

        # 카테고리: 직속 카운트 + 하위 카테고리 재귀 합산
        cat_direct: dict[str, int] = {str(cat.id): cat.video_count for cat in self._vm.categories}
        children_map: dict[str, list[str]] = {}
        for cat in self._vm.categories:
            parent_key = str(cat.parent_id) if cat.parent_id else ""
            children_map.setdefault(parent_key, []).append(str(cat.id))

        def _subtree_count(cat_id_str: str) -> int:
            total = cat_direct.get(cat_id_str, 0)
            for child in children_map.get(cat_id_str, []):
                total += _subtree_count(child)
            return total

        for cat in self._vm.categories:
            counts[f"category:{cat.id}"] = _subtree_count(str(cat.id))

        for t in self._all_tags:
            counts[f"tag:{t.id}"] = t.count
        if self._playlist_vm is not None:
            for pl in self._playlist_vm.playlists:
                counts[f"playlist:{pl.id}"] = pl.item_count
        return counts

    def _on_fav_unfav_requested(self, fav_type: str, fav_id: str, name: str) -> None:
        """즐겨찾기 바의 카운트 배지 클릭 → 해제 확인 후 제거."""
        reply = QMessageBox.question(
            self, "즐겨찾기 해제",
            f"'{name}'을(를) 즐겨찾기에서 제거하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._toggle_favorite(fav_type, fav_id, name)

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
        return self._current_cat_id

    def _build_category_path(self, cat_id) -> str:
        """카테고리 ID로부터 전체 경로 문자열을 생성한다. 예: '로컬 > Game > Hardware > PS5'"""
        cats_by_id = {c.id: c for c in self._vm.categories}
        parts: list[str] = []
        current = cat_id
        while current:
            c = cats_by_id.get(current)
            if c is None:
                break
            parts.append(c.name)
            current = c.parent_id
        parts.reverse()
        return "로컬 > " + " > ".join(parts) if parts else "라이브러리"

    def _build_breadcrumb_segments(self, cat_id) -> list:
        """(이름, click_val) 리스트 반환. 루트 '로컬'은 항상 포함.
        cat_id가 있을 때 '로컬' click_val="root" → 클릭 시 카테고리 root(전체) 이동.
        이미 root에 있으면(cat_id=None) 마지막 세그먼트라 비클릭."""
        if cat_id is None:
            # 이미 루트 → "로컬"은 마지막이므로 click_val=None (비클릭)
            return [("로컬", None)]
        segments: list = [("로컬", "root")]
        cats_by_id = {c.id: c for c in self._vm.categories}
        parts: list = []
        current = cat_id
        while current:
            c = cats_by_id.get(current)
            if c is None:
                break
            parts.append((c.name, c.id))
            current = c.parent_id
        parts.reverse()
        return segments + parts

    def _build_playlist_breadcrumb_segments(self, playlist_id) -> list:
        """재생목록 ID로부터 클릭 가능한 경로 세그먼트 리스트를 생성한다.
        click_val: "root" → 전체, ("folder", uuid) → 폴더 뷰, None → 비클릭(마지막)"""
        if not self._playlist_vm:
            return []
        pl = next((p for p in self._playlist_vm.playlists if p.id == playlist_id), None)
        if not pl:
            return []
        if pl.source == "youtube":
            prefix, root_val = "YouTube", "section:youtube"
        else:
            prefix, root_val = "로컬", "root"
        segs = [(prefix, root_val)]
        if pl.folder_id:
            folder = next((f for f in self._playlist_vm.folders if f.id == pl.folder_id), None)
            if folder:
                segs.append((folder.name, ("folder", folder.id)))
        segs.append((pl.title, None))
        return segs

    def _build_folder_breadcrumb_segments(self, folder_id) -> list:
        """폴더 ID로부터 클릭 가능한 경로 세그먼트 리스트를 생성한다."""
        if not self._playlist_vm:
            return []
        folder = next((f for f in self._playlist_vm.folders if f.id == folder_id), None)
        if not folder:
            return []
        if folder.source == "youtube":
            prefix, root_val = "YouTube", "section:youtube"
        else:
            prefix, root_val = "로컬", "root"
        return [(prefix, root_val), (folder.name, None)]

    def _channel_name_for_url(self, url: str) -> str:
        """구독 URL로 채널 표시명을 조회한다(브레드크럼용)."""
        if not url or self._monitoring_vm is None:
            return ""
        for s in self._monitoring_vm.subscriptions:
            if s.channel_url == url:
                return s.channel_name
        return ""

    def _refresh_breadcrumb(self) -> None:
        # 구독 채널/피드 뷰는 _current_playlist_id/_current_folder_id가 None이라
        # 카테고리 분기로 빠지므로(stale 경로), 뷰 기반으로 먼저 처리한다.
        view = self._view_stack.currentIndex()
        if view == _VIEW_CHANNELS:
            self._breadcrumb_bar.update_path(
                [("YouTube", "section:youtube"), ("구독 채널", None)], [])
            return
        if view == _VIEW_FEED:
            if self._feed_show_channel:
                segments = [("YouTube", "section:youtube"), ("전체 구독 피드", None)]
            else:
                name = self._channel_name_for_url(self._current_channel_url) or "채널"
                segments = [("YouTube", "section:youtube"),
                            ("구독 채널", "channels_root"), (name, None)]
            self._breadcrumb_bar.update_path(segments, [])
            return
        if self._current_playlist_id is not None:
            segments = self._build_playlist_breadcrumb_segments(self._current_playlist_id)
            self._breadcrumb_bar.update_path(segments, [])
        elif self._current_folder_id is not None:
            segments = self._build_folder_breadcrumb_segments(self._current_folder_id)
            self._breadcrumb_bar.update_path(segments, [])
        else:
            segments = self._build_breadcrumb_segments(self._current_cat_id)
            tag_pairs = [(t.id, t.name) for t in self._all_tags if t.id in self._active_tag_ids]
            self._breadcrumb_bar.update_path(segments, tag_pairs)

    def _on_breadcrumb_nav(self, val) -> None:
        """브레드크럼 세그먼트 클릭 → 카테고리·폴더·섹션루트 분기 처리."""
        if isinstance(val, tuple) and len(val) == 2 and val[0] == "folder":
            self._on_folder_selected(val[1])
        elif isinstance(val, UUID):
            self._on_cat_filter_changed(val)
        elif val == "channels_root":
            self._on_channels_root_selected()
        elif isinstance(val, str) and val.startswith("section:"):
            # "section:youtube" 또는 "section:local" → 섹션 루트 뷰 (폴더+미분류 카드)
            self._on_section_root_selected(val.split(":", 1)[1])
        else:
            # "root" → 로컬 카테고리 전체 영상 (카테고리 필터 해제)
            self._on_cat_filter_changed(None)

    def _on_cat_filter_changed(self, cat_id) -> None:
        self._push_nav_state()          # 전환 직전 화면 보존
        self._leave_detail_if_open()    # 상세 화면이면 목록으로 복귀
        self._current_cat_id = cat_id
        self._current_playlist_id = None
        self._current_folder_id = None
        # 폴더 카드 뷰/피드 뷰에서 카테고리를 고르면 영상 리스트 뷰로 복귀
        if self._view_stack.currentIndex() in (_VIEW_FOLDER, _VIEW_FEED):
            self._switch_view(self._view_group.checkedId())
        self._active_tag_ids.clear()
        self._tag_list.blockSignals(True)
        self._tag_list.clearSelection()
        self._tag_list.blockSignals(False)
        self._refresh_active_tags_bar()
        self._update_delegate_tags()
        self._vm.set_category_filter(cat_id)  # also clears tag filter internally
        # 카테고리 스코프 인기 태그 갱신 + 패널 표시
        self._set_popular_tags_visible(True)
        self._vm.refresh_scoped_tags()
        # Update delegates so they know which category is selected (for subcategory label)
        self._icon_delegate.filter_cat_id = cat_id
        self._list_delegate.filter_cat_id = cat_id
        # 순서 편집 버튼 — 카테고리 선택 시에만 표시
        if cat_id is not None:
            self._btn_reorder.show()
            self.path_changed.emit(self._build_category_path(cat_id))
        else:
            self._btn_reorder.setChecked(False)
            self._btn_reorder.hide()
            self._model.set_reorder_mode(False)
            self.path_changed.emit("라이브러리")
        self._refresh_breadcrumb()

    def _on_reorder_toggled(self, checked: bool) -> None:
        self._model.set_reorder_mode(checked)
        for view in (self._icon_view, self._list_view):
            if checked:
                view.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            else:
                view.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)

    def _on_category_reordered(self, video_ids: list) -> None:
        if self._current_cat_id is not None:
            self._vm.reorder_category_videos(self._current_cat_id, video_ids)
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
        self._refresh_breadcrumb()
        # 재생목록 컨텍스트에서는 트리 선택을 유지해 재생목록∩태그 교집합으로 필터링한다.
        # (재생목록이 아닌 뷰에서는 기존대로 트리 선택을 해제한다.)
        if self._active_tag_ids and self._current_playlist_id is None:
            for _t_ in self._playlist_panel.trees:
                _t_.clearSelection()

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
        self._refresh_breadcrumb()

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
        for _t_ in self._playlist_panel.trees:
            _t_.clearSelection()
        if self._nav_stack.currentIndex() == 1:
            self._on_back_from_detail()

    # ── In-place navigation ────────────────────────────────────────

    def _open_detail(self, video_id: UUID) -> None:
        """로컬 영상 상세화면을 연다. 연관 목록 = 현재 보고 있는 영상 목록(같은
        카테고리/재생목록), 자기 자신 제외."""
        detail = self._vm.get_video_detail(video_id)
        if detail is None:
            return
        if not self._is_restoring:
            self._push_nav_state()
        tag_ids = {t.name: t.id for t in self._vm.tags}
        related = [
            self._related_from_video(v)
            for v in self._vm.videos if v.id != video_id
        ][:30]
        self._detail_widget.load(detail, tag_ids, resume_ms=0, related=related)
        self._current_detail_payload = video_id
        self._nav_stack.setCurrentIndex(1)

    def _open_stream_detail(self, feed_dto) -> None:
        """구독 피드/채널의 스트리밍 영상 상세화면을 연다. 연관 목록 = 같은 채널의
        최근 영상(현재 로드된 피드 기준), 없으면 현재 피드 목록."""
        if self._feed_vm is None:
            return
        if not self._is_restoring:
            self._push_nav_state()
        related = self._feed_related_items(feed_dto)
        self._detail_widget.load_stream(feed_dto, related=related)
        self._current_detail_payload = feed_dto
        self._nav_stack.setCurrentIndex(1)

    def _on_related_item_selected(self, payload) -> None:
        """연관 영상 클릭 — payload 타입에 따라 로컬/스트리밍 상세로 재진입."""
        from application.library.dtos import FeedVideoDTO  # noqa: PLC0415
        if isinstance(payload, UUID):
            self._open_detail(payload)
        elif isinstance(payload, FeedVideoDTO):
            self._open_stream_detail(payload)

    def _related_from_video(self, v: VideoDTO) -> RelatedItem:
        meta = []
        if v.view_count:
            meta.append(f"조회수 {v.view_count:,}회")
        rel = _relative_time(v.published_at)
        if rel:
            meta.append(rel)
        return RelatedItem(
            key=str(v.id),
            title=v.title,
            channel=v.channel_name,
            duration_sec=v.duration_sec,
            meta_text="  ·  ".join(meta),
            payload=v.id,
            thumb_path=v.thumbnail_path or "",
        )

    def _feed_related_items(self, clicked) -> list[RelatedItem]:
        feed = self._feed_vm.feed if self._feed_vm else []
        same = [
            f for f in feed
            if f.channel_id and f.channel_id == clicked.channel_id and f.url != clicked.url
        ]
        pool = same if same else [f for f in feed if f.url != clicked.url]
        items = []
        for f in pool[:30]:
            meta = []
            if f.view_count:
                meta.append(f"조회수 {f.view_count:,}회")
            rel = _relative_time(f.published_at)
            if rel:
                meta.append(rel)
            items.append(RelatedItem(
                key=f.yt_video_id or f.url,
                title=f.title,
                channel=f.channel_name,
                duration_sec=f.duration_sec,
                meta_text="  ·  ".join(meta),
                payload=f,
                thumb_path=f.thumbnail_path or "",
                thumb_url=f.thumbnail_url or "",
            ))
        return items

    def _on_detail_back_requested(self) -> None:
        """상세 화면 뒤로가기 버튼 — 히스토리 기반으로 직전 화면 복원."""
        if self._nav_history:
            self._go_back()
        else:
            self._on_back_from_detail()

    def _on_back_from_detail(self) -> None:
        self._detail_widget.stop_player()
        self._nav_stack.setCurrentIndex(0)

    def _on_detail_tags_updated(self, video_id: UUID, tags: list) -> None:
        """Called when user manually adds a tag in the detail view."""
        self._vm.update_video_tags(video_id, tags)
        if self._nav_stack.currentIndex() == 1:
            detail = self._vm.get_video_detail(video_id)
            if detail:
                tag_ids = {t.name: t.id for t in self._vm.tags}
                related = [
                    self._related_from_video(v)
                    for v in self._vm.videos if v.id != video_id
                ][:30]
                self._detail_widget.load(detail, tag_ids, related=related)

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
                    logger.exception("스마트폴더 태그 선택 복원 실패")
        self._vm.set_tag_filter(list(self._active_tag_ids))
        self._vm.set_duration_filter(sf.min_duration_sec, sf.max_duration_sec)
        self._vm.set_favorite_filter(sf.favorite_only)
        self._refresh_active_tags_bar()

    def _on_sf_context_menu(self, pos) -> None:
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
            if event.button() == Qt.MouseButton.ForwardButton:
                self._go_forward()
                return True
        return super().eventFilter(obj, event)

    def _cycle_view(self, direction: int) -> None:
        """Ctrl+휠로 뷰 타입을 순환 전환한다. direction=1: 이전, -1: 다음."""
        views = [_VIEW_ICON, _VIEW_LIST, _VIEW_DETAIL]
        current = self._view_stack.currentIndex()
        # 폴더 뷰(_VIEW_FOLDER)는 순환에서 제외
        idx = views.index(current) if current in views else 0
        new_id = views[(idx - direction) % len(views)]
        self._switch_view(new_id)

    # ── 내비게이션 히스토리 ────────────────────────────────────────────

    def _leave_detail_if_open(self) -> None:
        """상세 화면(_nav_stack 인덱스 1)이 열려 있으면 목록 컨테이너로 복귀한다."""
        if self._nav_stack.currentIndex() == 1:
            self._on_back_from_detail()

    def _capture_screen(self) -> dict:
        """현재 화면을 완전 스냅샷으로 캡처한다(트리 노드 종류 + 뷰 + 태그)."""
        view_idx = self._view_stack.currentIndex()
        if view_idx == _VIEW_CHANNELS:
            kind = "channels_root"
        elif view_idx == _VIEW_FEED:
            kind = "feed_all" if self._feed_show_channel else "channel"
        elif view_idx == _VIEW_FOLDER:
            kind = "folder"
        elif self._current_playlist_id is not None:
            kind = "playlist"
        else:
            kind = "category"
        return {
            "kind": kind,
            "cat_id": self._current_cat_id,
            "playlist_id": self._current_playlist_id,
            "folder_id": self._current_folder_id,
            "channel_url": self._current_channel_url,
            "nav_idx": self._nav_stack.currentIndex(),
            "detail_payload": self._current_detail_payload,
            "tag_ids": frozenset(self._active_tag_ids),
        }

    def _push_nav_state(self) -> None:
        """전환 직전 화면을 히스토리 스택에 저장한다(복원 중에는 무시).

        사용자가 새 분기로 이동하는 것이므로 앞으로가기 스택은 무효화한다
        (브라우저 표준 동작)."""
        if self._is_restoring:
            return
        self._nav_history.append(self._capture_screen())
        if len(self._nav_history) > 50:
            self._nav_history.pop(0)
        self._nav_future.clear()

    def _reopen_detail(self, payload) -> None:
        """히스토리 복원 시 직전 상세 화면을 다시 연다."""
        from application.library.dtos import FeedVideoDTO  # noqa: PLC0415
        if isinstance(payload, UUID):
            self._open_detail(payload)
        elif isinstance(payload, FeedVideoDTO):
            self._open_stream_detail(payload)

    def _restore_list_screen(self, snap: dict) -> None:
        """스냅샷의 트리 노드(kind)로 실제 이동한다."""
        kind = snap.get("kind", "category")
        if kind == "playlist":
            self._on_playlist_selected_from_tree(snap.get("playlist_id"))
        elif kind == "folder":
            self._on_folder_selected(snap.get("folder_id"))
        elif kind == "feed_all":
            self._on_feed_all_selected()
        elif kind == "channel":
            self._on_channel_selected(snap.get("channel_url") or "")
        elif kind == "channels_root":
            self._on_channels_root_selected()
        else:  # category
            self._on_cat_filter_changed(snap.get("cat_id"))

    def _screen_matches(self, snap: dict) -> bool:
        """상세 화면 아래에 깔린 현재 목록이 스냅샷과 동일한 노드인지(재로딩 회피용)."""
        view_idx = self._view_stack.currentIndex()
        kind = snap.get("kind")
        list_views = (_VIEW_ICON, _VIEW_LIST, _VIEW_DETAIL)
        if kind == "feed_all":
            return view_idx == _VIEW_FEED and self._feed_show_channel
        if kind == "channel":
            return (view_idx == _VIEW_FEED and not self._feed_show_channel
                    and self._current_channel_url == (snap.get("channel_url") or ""))
        if kind == "channels_root":
            return view_idx == _VIEW_CHANNELS
        if kind == "folder":
            return view_idx == _VIEW_FOLDER and self._current_folder_id == snap.get("folder_id")
        if kind == "playlist":
            return view_idx in list_views and self._current_playlist_id == snap.get("playlist_id")
        return (view_idx in list_views and self._current_playlist_id is None
                and self._current_cat_id == snap.get("cat_id"))

    def _restore_screen(self, snap: dict) -> None:
        """스냅샷에 따라 직전 화면을 정확히 복원한다."""
        self._is_restoring = True
        try:
            target_detail = (snap.get("nav_idx") == 1
                             and snap.get("detail_payload") is not None)

            # 상세 아래에 그대로 깔려 있던 직전 목록으로 복귀 — 재로딩 없이 빠르게
            if (not target_detail and self._nav_stack.currentIndex() == 1
                    and self._screen_matches(snap)):
                self._on_back_from_detail()
                self._restore_tags(snap)
                self._playlist_panel.select_snapshot(snap)
                return

            # 그 외엔 목록 화면을 실제로 재구성한다
            if self._nav_stack.currentIndex() == 1:
                self._on_back_from_detail()
            self._restore_list_screen(snap)
            self._restore_tags(snap)
            # 좌측 트리 강조를 복원된 노드에 맞춰 동기화(경로 표현 자연스럽게)
            self._playlist_panel.select_snapshot(snap)

            # 직전이 상세였다면(연관영상 체인) 올바른 목록 위에 상세를 다시 연다
            if target_detail:
                self._reopen_detail(snap["detail_payload"])
        finally:
            self._is_restoring = False

    def _restore_tags(self, snap: dict) -> None:
        """화면 복원 뒤 태그 필터를 덮어쓴다(핸들러가 태그를 비울 수 있으므로)."""
        saved_tags: frozenset = snap.get("tag_ids", frozenset())
        if not saved_tags:
            return
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
        self._icon_view.viewport().update()
        self._list_view.viewport().update()

    def _go_back(self) -> None:
        """히스토리에서 직전 화면을 꺼내 복원한다. 현재 화면은 앞으로가기 스택에 보존."""
        if not self._nav_history:
            return
        self._nav_future.append(self._capture_screen())
        snap = self._nav_history.pop()
        self._restore_screen(snap)

    def _go_forward(self) -> None:
        """앞으로가기 스택에서 다음 화면을 꺼내 복원한다. 현재 화면은 뒤로가기 스택에 보존."""
        if not self._nav_future:
            return
        self._nav_history.append(self._capture_screen())
        snap = self._nav_future.pop()
        self._restore_screen(snap)

    def _on_hidden_tags_changed(self) -> None:
        """설정에서 숨김 태그가 변경되면 태그 표시 목록을 즉시 갱신한다."""
        self._refresh_tag_display()
        self._refresh_popular_tags()

    # ── URL dropped onto video list ────────────────────────────────

    def _on_list_url_dropped(self, url: str) -> None:
        self._vm.add_video(url, self._current_cat_id)

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

    def _on_rename_category(self, category_id) -> None:
        cats = self._vm.categories
        current_name = next((c.name for c in cats if c.id == category_id), "")
        new_name, ok = QInputDialog.getText(
            self, "카테고리 이름 변경", "새 이름:", text=current_name
        )
        if ok and new_name.strip():
            self._vm.rename_category(category_id, new_name.strip())

    def _on_category_reparented(self, cat_id: UUID, new_parent_id) -> None:
        self._vm.reparent_category(cat_id, new_parent_id)

    def _on_delete_category(self, category_id) -> None:
        cats = self._vm.categories
        name = next((c.name for c in cats if c.id == category_id), "")
        reply = QMessageBox.question(
            self, "카테고리 삭제",
            f"'{name}' 카테고리를 삭제하시겠습니까?\n영상은 '미분류'로 이동됩니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._vm.delete_category(category_id)

    # ── Item click / double-click ──────────────────────────────────

    def _on_item_clicked(self, index: QModelIndex, view: QListView) -> None:
        """단일 클릭 → 상세화면 진입. Ctrl/Shift 클릭은 다중 선택·드래그용으로 유지."""
        mods = QApplication.keyboardModifiers()
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            return
        dto: VideoDTO | None = self._model.data(index, VideoListModel.DtoRole)
        if dto:
            self.video_selected.emit(dto)
            self._open_detail(dto.id)

    def _on_double_click(self, index: QModelIndex) -> None:
        dto: VideoDTO | None = self._model.data(index, VideoListModel.DtoRole)
        if dto:
            self._open_detail(dto.id)

    def _on_table_clicked(self, index: QModelIndex) -> None:
        mods = QApplication.keyboardModifiers()
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            return
        item = self._table.item(index.row(), 0)
        if item:
            vid_id = item.data(Qt.ItemDataRole.UserRole)
            if vid_id:
                self._open_detail(vid_id)

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

        active_pl_id = self._vm.active_playlist_id
        in_playlist  = active_pl_id is not None and self._playlist_vm is not None

        dl_act = QAction("일괄 다운로드", self)
        dl_act.triggered.connect(lambda: self._on_batch_download(dtos))
        menu.addAction(dl_act)

        tag_act = QAction("태그 추가", self)
        tag_act.triggered.connect(lambda: self._on_bulk_add_tags(video_ids))
        menu.addAction(tag_act)

        menu.addSeparator()

        # 재생목록 모드: "이 재생목록에서 일괄 제거"
        if in_playlist:
            rm_pl_act = QAction(f"이 재생목록에서 제거 ({len(video_ids)}개)", self)
            rm_pl_act.triggered.connect(
                lambda: self._confirm_bulk_remove_from_playlist(video_ids, active_pl_id)
            )
            menu.addAction(rm_pl_act)
            menu.addSeparator()

        # 재생목록으로 복사 (모든 모드에서 사용 가능)
        if self._playlist_vm is not None:
            pl_copy_menu = menu.addMenu("재생목록으로 복사")
            for pl in self._playlist_vm.playlists:
                if in_playlist and pl.id == active_pl_id:
                    continue
                act = QAction(
                    f"{'[YT] ' if pl.source == 'youtube' else ''}{pl.title}  ({pl.item_count})",
                    self,
                )
                pid = pl.id
                act.triggered.connect(lambda _, p=pid: self._on_bulk_copy_to_playlist(video_ids, p))
                pl_copy_menu.addAction(act)
            if not pl_copy_menu.actions():
                pl_copy_menu.setEnabled(False)
            menu.addSeparator()

        cat_menu_label = "카테고리 일괄 복사" if in_playlist else "카테고리 일괄 변경"
        cat_menu = menu.addMenu(cat_menu_label)
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
                history = getattr(self, "_download_vm", None)
                if history is not None and hasattr(history, "load_history"):
                    skipped_urls = {j.url for j in history.load_history(200) if j.status == "COMPLETED"}
            except Exception:
                logger.exception("기존 다운로드 이력 조회 실패 (중복 건너뛰기)")
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

        active_pl_id = self._vm.active_playlist_id
        cat_menu_label = "카테고리로 복사" if active_pl_id is not None else "카테고리 이동"
        cat_menu = menu.addMenu(cat_menu_label)
        uncat_act = QAction("미분류", self)
        uncat_act.triggered.connect(lambda: self._on_video_moved(dto.id, None))
        cat_menu.addAction(uncat_act)
        cat_menu.addSeparator()
        self._add_cat_actions(cat_menu, self._vm.categories, None, dto.id)

        # 재생목록이 활성화되어 있을 때만 재생목록 이전 메뉴 표시
        if active_pl_id is not None and self._playlist_vm is not None:
            menu.addSeparator()

            remove_act = QAction("이 재생목록에서 제거", self)
            remove_act.triggered.connect(
                lambda: self._on_remove_video_from_playlist(dto.id, active_pl_id)
            )
            menu.addAction(remove_act)

            pl_move_menu = menu.addMenu("다른 재생목록으로 이전…")
            for pl in self._playlist_vm.playlists:
                if pl.id == active_pl_id:
                    continue
                act = QAction(
                    f"{'[YT] ' if pl.source == 'youtube' else ''}{pl.title}  ({pl.item_count})",
                    self,
                )
                target_id = pl.id
                act.triggered.connect(
                    lambda _, tid=target_id: self._on_move_video_to_playlist(dto.id, active_pl_id, tid)
                )
                pl_move_menu.addAction(act)
            if not pl_move_menu.actions():
                pl_move_menu.setEnabled(False)

        menu.addSeparator()

        fav_act = QAction("즐겨찾기 해제" if dto.favorite else "즐겨찾기 추가", self)
        fav_act.triggered.connect(lambda: self._toggle_video_favorite(dto))
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

    def _toggle_video_favorite(self, dto: VideoDTO) -> None:
        from application.library.commands import UpdateVideoCommand
        try:
            self._vm._update_video.handle(
                UpdateVideoCommand(video_id=dto.id, favorite=not dto.favorite)
            )
            self._vm._refresh_videos()
        except Exception as exc:
            self._vm.error_occurred.emit(str(exc))

    def _confirm_delete(self, dto: VideoDTO) -> None:
        active_pl_id = self._vm.active_playlist_id
        in_playlist  = active_pl_id is not None and self._playlist_vm is not None

        msg = (
            f"'{dto.title}'\n이 영상을 라이브러리에서 완전히 삭제하시겠습니까?\n"
            + ("(재생목록에서도 제거되며, YouTube 재생목록에도 반영됩니다)" if in_playlist
               else "(라이브러리에서 완전히 삭제됩니다)")
        )
        reply = QMessageBox.question(
            self, "영상 삭제",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # 재생목록 뷰 상태일 때: YouTube API 포함 재생목록 제거 먼저 처리
        if in_playlist:
            self._playlist_vm.remove_video_from_playlist(active_pl_id, dto.id)

        self._vm.delete_video(dto.id)

    # ── Playlist handlers ──────────────────────────────────────────

    def _on_playlists_changed(self) -> None:
        self._refresh_unified_tree()

    def _on_delete_playlist(self, playlist_id: UUID) -> None:
        if self._playlist_vm is None:
            return
        reply = QMessageBox.question(
            self, "재생목록 삭제",
            "이 재생목록을 삭제하시겠습니까?\n(라이브러리의 영상은 유지됩니다)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._playlist_vm.delete_playlist(playlist_id)
            self._vm.set_playlist_filter(None)

    def _on_rename_playlist(self, playlist_id: UUID) -> None:
        if self._playlist_vm is None:
            return
        pls = self._playlist_vm.playlists
        current = next((p.title for p in pls if p.id == playlist_id), "")
        title, ok = QInputDialog.getText(
            self, "재생목록 이름 변경", "새 이름:", text=current
        )
        if ok and title.strip():
            self._playlist_vm.rename_playlist(playlist_id, title.strip())

    def _on_playlist_move(self, playlist_id, folder_id) -> None:
        if self._playlist_vm is None:
            return
        self._playlist_vm.move_playlist_to_folder(playlist_id, folder_id)

    def _on_folder_create(self, source: str) -> None:
        if self._playlist_vm is None:
            return
        name, ok = QInputDialog.getText(self, "새 폴더", "폴더 이름:")
        if ok and name.strip():
            self._playlist_vm.create_folder(name.strip(), source)

    def _on_folder_rename(self, folder_id, old_name: str) -> None:
        if self._playlist_vm is None:
            return
        name, ok = QInputDialog.getText(
            self, "폴더 이름 변경", "새 이름:", text=old_name
        )
        if ok and name.strip():
            self._playlist_vm.rename_folder(folder_id, name.strip())

    def _on_folder_delete(self, folder_id) -> None:
        if self._playlist_vm is None:
            return
        reply = QMessageBox.question(
            self, "폴더 삭제",
            "폴더를 삭제하시겠습니까?\n(폴더 안의 재생목록은 미분류로 이동됩니다)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._playlist_vm.delete_folder(folder_id)

    def _on_yt_playlist_to_category(self, yt_playlist_id: str, cat_id) -> None:
        """YouTube 재생목록을 드래그앤드랍으로 카테고리에 드랍 — 영상 임포트."""
        if not yt_playlist_id:
            return
        cookie_opts = self._playlist_vm.get_ytdlp_cookie_opts() if self._playlist_vm else {}
        self._vm.import_youtube_to_category(yt_playlist_id, cat_id, cookie_opts)

    def _on_local_playlist_to_category(self, playlist_id, parent_cat_id) -> None:
        """로컬 재생목록의 영상 전체를 재생목록 이름의 새 카테고리로 복사한다."""
        if self._playlist_vm is None:
            return
        try:
            playlist_id = UUID(str(playlist_id)) if not isinstance(playlist_id, UUID) else playlist_id
        except (ValueError, AttributeError):
            return

        playlist = next((pl for pl in self._playlist_vm.playlists if pl.id == playlist_id), None)
        if playlist is None:
            return

        video_ids = self._vm.get_playlist_video_ids(playlist_id)
        if not video_ids:
            QMessageBox.information(
                self, "재생목록 복사",
                f"재생목록 '{playlist.title}'에 영상이 없습니다.",
            )
            return

        self._vm.create_category(playlist.title, parent_id=parent_cat_id)

        new_cat = next(
            (c for c in self._vm.categories if c.name == playlist.title and c.parent_id == parent_cat_id),
            None,
        )
        if new_cat is None:
            return

        self._vm.assign_category_bulk(video_ids, new_cat.id)

    def _on_copy_yt_to_local(self, yt_playlist_id: str) -> None:
        """YouTube 재생목록의 영상들을 선택한 카테고리로 가져온다."""
        if not yt_playlist_id:
            return
        categories = self._vm.categories
        if not categories:
            QMessageBox.information(
                self, "카테고리 없음",
                "카테고리가 없습니다.\n카테고리 트리에서 먼저 카테고리를 만들어 주세요.",
            )
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("가져올 카테고리 선택")
        dlg.setMinimumWidth(360)
        dlg.setMinimumHeight(440)
        dlg_layout = QVBoxLayout(dlg)
        dlg_layout.setSpacing(8)

        lbl = QLabel("YouTube 재생목록 영상들을 가져올 카테고리를 선택하세요:")
        lbl.setWordWrap(True)
        dlg_layout.addWidget(lbl)

        # QTreeWidget으로 카테고리 계층 구조를 실제 트리 형태로 표시
        tw = QTreeWidget()
        tw.setHeaderHidden(True)
        tw.setIndentation(18)
        tw.setAnimated(True)
        tw.setRootIsDecorated(True)
        tw.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tok = _t()
        tw.setStyleSheet(
            f"QTreeWidget {{"
            f"  background:{tok.bg_surface};"
            f"  border:1px solid {tok.border};"
            f"  border-radius:4px;"
            f"  font-size:9pt;"
            f"}}"
            f"QTreeWidget::item {{"
            f"  padding:4px 2px;"
            f"  color:{tok.text_primary};"
            f"}}"
            f"QTreeWidget::item:selected {{"
            f"  background:{tok.accent};"
            f"  color:{tok.text_on_accent};"
            f"}}"
            f"QTreeWidget::item:hover:!selected {{"
            f"  background:{tok.bg_overlay};"
            f"}}"
        )

        # BFS로 메인 카테고리 트리와 동일한 순서로 구축
        tw_items: dict = {}

        def _child_count(cat_id) -> int:
            return sum(1 for c in categories if c.parent_id == cat_id)

        roots = [c for c in categories if c.parent_id is None]
        for c in roots:
            count = _child_count(c.id)
            label = f"🏷  {c.name}  ({count})" if count > 0 else f"🏷  {c.name}"
            ti = QTreeWidgetItem([label])
            ti.setData(0, Qt.ItemDataRole.UserRole, c.id)
            tw.addTopLevelItem(ti)
            tw_items[c.id] = ti

        queue = list(roots)
        while queue:
            parent_cat = queue.pop(0)
            parent_ti = tw_items[parent_cat.id]
            for c in categories:
                if c.parent_id == parent_cat.id:
                    count = _child_count(c.id)
                    label = f"🏷  {c.name}  ({count})" if count > 0 else f"🏷  {c.name}"
                    ti = QTreeWidgetItem([label])
                    ti.setData(0, Qt.ItemDataRole.UserRole, c.id)
                    parent_ti.addChild(ti)
                    tw_items[c.id] = ti
                    queue.append(c)

        tw.expandAll()
        if tw.topLevelItemCount() > 0:
            tw.setCurrentItem(tw.topLevelItem(0))

        dlg_layout.addWidget(tw, 1)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        dlg_layout.addWidget(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        sel = tw.currentItem()
        if sel is None:
            return
        category_id = sel.data(0, Qt.ItemDataRole.UserRole)

        # 로컬에 이미 가져온 재생목록 데이터를 사용 (YouTube 재다운로드 없음)
        if self._playlist_vm is not None:
            local_pl = next(
                (pl for pl in self._playlist_vm.playlists if pl.yt_playlist_id == yt_playlist_id),
                None,
            )
            if local_pl is not None:
                video_ids = self._vm.get_playlist_video_ids(local_pl.id)
                if video_ids:
                    self._vm.assign_category_bulk(video_ids, category_id)
                    QMessageBox.information(
                        self, "복사 완료",
                        f"영상 {len(video_ids)}개를 카테고리로 복사했습니다.",
                    )
                    return
                QMessageBox.information(
                    self, "알림",
                    f"재생목록 '{local_pl.title}'에 영상이 없습니다.",
                )
                return

        # 로컬 캐시 없으면 YouTube에서 가져오기
        cookie_opts = self._playlist_vm.get_ytdlp_cookie_opts() if self._playlist_vm else {}
        self._vm.import_youtube_to_category(yt_playlist_id, category_id, cookie_opts)

    def _on_yt_import_finished(self, count: int) -> None:
        if count > 0:
            QMessageBox.information(
                self, "가져오기 완료",
                f"YouTube 재생목록에서 영상 {count}개를 카테고리로 가져왔습니다.",
            )

    def _on_sync_yt_playlist(self, yt_playlist_id: str) -> None:
        if self._playlist_vm is None or not yt_playlist_id:
            return
        self._playlist_vm.import_youtube_playlist(yt_playlist_id)

    def _on_sync_all_yt(self) -> None:
        """YouTube 재생목록 전체를 동기화한다."""
        if self._playlist_vm is None:
            return
        yt_pls = [pl for pl in self._playlist_vm.playlists if pl.source == "youtube" and pl.yt_playlist_id]
        if not yt_pls:
            QMessageBox.information(self, "동기화", "동기화할 YouTube 재생목록이 없습니다.")
            return
        for pl in yt_pls:
            self._playlist_vm.import_youtube_playlist(pl.yt_playlist_id)

    def _on_remove_video_from_playlist(self, video_id, playlist_id) -> None:
        if self._playlist_vm is None:
            return
        self._playlist_vm.remove_video_from_playlist(playlist_id, video_id)
        self._vm.set_playlist_filter(playlist_id)  # 목록 갱신

    def _on_move_video_to_playlist(self, video_id, src_pl_id, tgt_pl_id) -> None:
        if self._playlist_vm is None:
            return
        self._playlist_vm.move_video_to_playlist(video_id, src_pl_id, tgt_pl_id)
        self._vm.set_playlist_filter(src_pl_id)  # 현재 재생목록 뷰 갱신

    def _on_video_move_to_playlist_from_dnd(self, vid_id_str: str, src_pl_str: str, tgt_pl_id) -> None:
        """DnD로 영상을 다른 재생목록으로 이전."""
        if self._playlist_vm is None:
            return
        from uuid import UUID  # noqa: PLC0415
        try:
            video_id = UUID(vid_id_str)
            src_pl_id = UUID(src_pl_str) if src_pl_str else None
        except (ValueError, AttributeError):
            return
        self._playlist_vm.move_video_to_playlist(video_id, src_pl_id, tgt_pl_id)
        if src_pl_id is not None:
            self._vm.set_playlist_filter(src_pl_id)

    def _on_push_to_youtube(self, playlist_id, move: bool) -> None:
        if self._playlist_vm is None:
            return
        action = "이동" if move else "복사"
        reply = QMessageBox.question(
            self,
            f"YouTube로 {action}",
            f"이 재생목록을 YouTube에 {action}하시겠습니까?\n"
            + ("(로컬 항목이 YouTube 재생목록으로 전환됩니다)" if move
               else "(로컬 재생목록은 유지되고 YouTube에 새 재생목록이 생성됩니다)"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._playlist_vm.push_to_youtube(playlist_id, move=move)

    # ── 구독 피드 뷰 ─────────────────────────────────────────────────

    def _build_feed_view(self) -> QWidget:
        """feed_panel의 카드 그리드를 재사용한 구독/채널 피드 뷰를 만든다."""
        from gui.panels.feed_panel import _FeedGrid  # noqa: PLC0415
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self._feed_status = QLabel()
        self._feed_status.setContentsMargins(12, 6, 12, 6)
        self._feed_status.hide()
        v.addWidget(self._feed_status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._feed_grid = _FeedGrid()
        scroll.setWidget(self._feed_grid)
        v.addWidget(scroll, stretch=1)

        self._feed_grid.download_requested.connect(self._on_feed_card_download)
        self._feed_grid.add_to_category_requested.connect(self._on_feed_card_to_category)
        self._feed_grid.add_to_playlist_requested.connect(self._on_feed_card_to_playlist)
        return container

    def _build_channels_view(self) -> QWidget:
        """구독 채널 목록(아바타 카드) 그리드 뷰."""
        from gui.panels.feed_panel import _ChannelGrid  # noqa: PLC0415
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self._channels_status = QLabel()
        self._channels_status.setContentsMargins(12, 6, 12, 6)
        self._channels_status.hide()
        v.addWidget(self._channels_status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._channel_grid = _ChannelGrid()
        scroll.setWidget(self._channel_grid)
        v.addWidget(scroll, stretch=1)

        self._channel_grid.channel_clicked.connect(self._on_channel_selected)
        return container

    def _on_channels_root_selected(self) -> None:
        """"구독 채널" 노드 클릭 — 등록된 채널을 아바타 카드 그리드로 표시."""
        if self._feed_vm is None:
            return
        self._push_nav_state()
        self._leave_detail_if_open()
        subs = self._monitoring_vm.subscriptions if self._monitoring_vm is not None else []
        channels = [(s.channel_id, s.channel_name, s.channel_url) for s in subs]
        self._current_playlist_id = None
        self._current_folder_id = None
        self._current_cat_id = None
        self._set_popular_tags_visible(False)
        self._channels_status.setText("로딩 중…" if channels else "구독 중인 채널이 없습니다.")
        self._channels_status.setVisible(True)
        self._view_stack.setCurrentIndex(_VIEW_CHANNELS)
        if channels:
            self._feed_vm.load_channel_infos(channels)
        self._refresh_breadcrumb()

    def _on_channel_infos_changed(self) -> None:
        if self._feed_vm is None:
            return
        infos = self._feed_vm.channel_infos
        self._channel_grid.set_channels(infos)
        if self._view_stack.currentIndex() == _VIEW_CHANNELS:
            if infos:
                self._channels_status.hide()
            else:
                self._channels_status.setText("채널 정보를 가져오지 못했습니다.")
                self._channels_status.show()

    def _show_feed_view(self, status: str | None = None) -> None:
        if status:
            self._feed_status.setText(status)
            self._feed_status.show()
        else:
            self._feed_status.hide()
        self._view_stack.setCurrentIndex(_VIEW_FEED)

    def _on_channel_selected(self, channel_url: str) -> None:
        """구독 채널 노드 클릭 — 해당 채널 영상을 피드 그리드에 로드."""
        if self._feed_vm is None or not channel_url:
            return
        self._push_nav_state()
        self._leave_detail_if_open()
        self._current_playlist_id = None
        self._current_folder_id = None
        self._current_cat_id = None
        self._current_channel_url = channel_url
        self._feed_show_channel = False   # 이미 채널을 아는 화면이라 채널명 숨김
        self._set_popular_tags_visible(False)
        self._show_feed_view("로딩 중…")
        self._feed_vm.load_channel(channel_url)
        self._refresh_breadcrumb()

    def _on_feed_all_selected(self) -> None:
        """전체 구독 피드 노드 클릭 — 모든 구독 채널 최신 영상을 로드."""
        if self._feed_vm is None:
            return
        self._push_nav_state()
        self._leave_detail_if_open()
        self._current_playlist_id = None
        self._current_folder_id = None
        self._current_cat_id = None
        self._feed_show_channel = True    # 여러 채널이 섞이므로 채널명 표시
        self._set_popular_tags_visible(False)
        self._show_feed_view("로딩 중…")
        self._feed_vm.refresh()
        self._refresh_breadcrumb()

    def _on_feed_changed(self) -> None:
        if self._feed_vm is None:
            return
        items = self._feed_vm.feed
        self._feed_grid.set_feed(items, show_channel=self._feed_show_channel)
        if self._view_stack.currentIndex() == _VIEW_FEED:
            self._feed_status.hide() if items else self._show_feed_view("영상이 없습니다.")

    def _on_feed_loading_changed(self, loading: bool) -> None:
        if loading and self._view_stack.currentIndex() == _VIEW_FEED:
            self._feed_status.setText("로딩 중…")
            self._feed_status.show()

    def _on_feed_error(self, msg: str) -> None:
        idx = self._view_stack.currentIndex()
        if idx not in (_VIEW_FEED, _VIEW_CHANNELS):
            return
        if "cookie" in msg.lower() or "Could not copy" in msg:
            display = "YouTube 로그인 필요 — 사이드바 계정 버튼에서 로그인하세요."
        else:
            display = f"오류: {msg[:120]}"
        status = self._feed_status if idx == _VIEW_FEED else self._channels_status
        status.setText(display)
        status.show()

    def _on_feed_card_download(self, url: str, title: str) -> None:
        from domain.download.value_objects import DownloadSettings  # noqa: PLC0415
        self.download_requested.emit(url, title, DownloadSettings())

    def _on_feed_card_to_category(self, url: str) -> None:
        self._vm.add_video(url)

    def _on_feed_card_to_playlist(self, url: str) -> None:
        # 재생목록 선택 UI가 없으므로 우선 라이브러리에 등록한다.
        self._vm.add_video(url)

    # ── 폴더 뷰 핸들러 ───────────────────────────────────────────────

    def _on_playlist_selected_from_tree(self, playlist_id) -> None:
        """트리에서 재생목록 선택 — 폴더 카드 뷰에 있다면 정상 뷰로 복귀 후 필터 적용."""
        self._push_nav_state()
        self._leave_detail_if_open()
        self._vm.set_playlist_filter(playlist_id)
        self._icon_view.set_playlist_context(playlist_id)
        self._list_view.set_playlist_context(playlist_id)
        if self._view_stack.currentIndex() in (_VIEW_FOLDER, _VIEW_FEED):
            self._switch_view(self._view_group.checkedId())
        self._current_playlist_id = playlist_id
        self._current_folder_id = None
        # 재생목록 선택 시에는 태그 섹션을 숨겨 트리가 더 넓게 보이도록 한다
        self._set_popular_tags_visible(False)
        self._refresh_breadcrumb()

    def _on_folder_selected(self, folder_id) -> None:
        """폴더 클릭 — 폴더 내 재생목록을 카드 그리드로 표시한다.
        folder_id=None이면 '미분류' 디렉터리 뷰."""
        if self._playlist_vm is None:
            return
        self._push_nav_state()
        self._leave_detail_if_open()
        folder_pls = [pl for pl in self._playlist_vm.playlists if pl.folder_id == folder_id]
        self._folder_view.load(folder_pls, get_first_item=self._vm.get_playlist_first_item)
        self._view_stack.setCurrentIndex(_VIEW_FOLDER)
        self._vm.set_playlist_filter(None)
        self._current_folder_id = folder_id
        self._current_playlist_id = None
        self._set_popular_tags_visible(False)   # 폴더(재생목록 묶음) 뷰에서도 숨김
        self._refresh_breadcrumb()

    def _on_unfiled_selected(self, source: str) -> None:
        """미분류 클릭 — 해당 섹션의 폴더 없는 재생목록을 카드 그리드로 표시한다."""
        self._on_folder_selected(None)

    def _on_section_root_selected(self, source: str) -> None:
        """섹션 루트('로컬'/'YouTube') 클릭 — 해당 섹션의 폴더 + 미분류 카드를 표시한다.
        (경로 바에서 'YouTube' 세그먼트 클릭 시 호출)"""
        if self._playlist_vm is None:
            return
        folders = [f for f in self._playlist_vm.folders if f.source == source]
        unfiled_pls = [pl for pl in self._playlist_vm.playlists
                       if pl.source == source and pl.folder_id is None]
        self._folder_view.load(
            playlists=[],
            get_first_item=self._vm.get_playlist_first_item,
            folders=folders,
            show_unfiled=True,
            unfiled_count=len(unfiled_pls),
        )
        self._view_stack.setCurrentIndex(_VIEW_FOLDER)
        self._vm.set_playlist_filter(None)
        # 섹션 루트 — 폴더도 재생목록도 아닌 상태
        self._current_folder_id = None
        self._current_playlist_id = None
        self._set_popular_tags_visible(False)
        # 경로 바: "YouTube" 또는 "로컬" 단독 (클릭 안 되는 마지막 세그먼트)
        label = "YouTube" if source == "youtube" else "로컬"
        self._breadcrumb_bar.update_path([(label, None)], [])
        self._breadcrumb_bar.show()

    def _on_folder_playlist_selected(self, playlist_id) -> None:
        """폴더 뷰에서 카드 클릭 — 해당 재생목록을 선택하고 정상 뷰로 돌아간다."""
        self._playlist_panel.select_playlist(playlist_id)
        self._vm.set_playlist_filter(playlist_id)
        self._icon_view.set_playlist_context(playlist_id)
        self._list_view.set_playlist_context(playlist_id)
        self._switch_view(self._view_group.checkedId())   # 이전 뷰 모드로 복귀
        self._current_playlist_id = playlist_id
        self._current_folder_id = None
        self._refresh_breadcrumb()

    # ── 다중 선택 일괄 처리 ────────────────────────────────────────────

    def _confirm_bulk_remove_from_playlist(self, video_ids: list, playlist_id) -> None:
        """재생목록에서 다중 영상 일괄 제거 확인 다이얼로그."""
        if self._playlist_vm is None:
            return
        reply = QMessageBox.question(
            self, "일괄 제거",
            f"{len(video_ids)}개 영상을 재생목록에서 제거하시겠습니까?\n"
            "(YouTube 재생목록이면 YouTube에도 반영됩니다)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for vid_id in video_ids:
            try:
                self._playlist_vm.remove_video_from_playlist(playlist_id, vid_id)
            except Exception:
                logger.exception("재생목록에서 영상 일괄 제거 실패")
        self._vm.set_playlist_filter(playlist_id)

    def _on_bulk_copy_to_playlist(self, video_ids: list, playlist_id) -> None:
        """다중 영상을 재생목록으로 복사한다."""
        if self._playlist_vm is None:
            return
        count = 0
        for vid_id in video_ids:
            try:
                self._playlist_vm.add_video_to_playlist(playlist_id, vid_id)
                count += 1
            except Exception:
                logger.exception("재생목록으로 영상 일괄 복사 실패")
        if count > 0:
            QMessageBox.information(self, "복사 완료", f"{count}개 영상을 재생목록에 복사했습니다.")

    def _on_import_yt_playlist(self) -> None:
        if self._playlist_vm is None:
            return
        # YouTube 계정 재생목록 목록 먼저 가져오기
        self._playlist_vm.yt_playlists_ready.connect(self._on_yt_playlists_ready, Qt.ConnectionType.SingleShotConnection)
        self._playlist_vm.fetch_youtube_playlists()

    def _on_yt_playlists_ready(self, playlists: list) -> None:
        if not playlists:
            # 목록이 없으면 수동 입력 fallback
            import urllib.parse  # noqa: PLC0415
            pl_id, ok = QInputDialog.getText(
                self, "YouTube 재생목록 가져오기",
                "계정 재생목록을 찾지 못했습니다.\nYouTube 재생목록 ID 또는 URL을 직접 입력하세요:",
            )
            if not ok or not pl_id.strip():
                return
            yt_id = pl_id.strip()
            if "list=" in yt_id:
                import urllib.parse  # noqa: PLC0415
                parsed = urllib.parse.urlparse(yt_id)
                params = urllib.parse.parse_qs(parsed.query)
                yt_id = params.get("list", [yt_id])[0]
            self._playlist_vm.import_youtube_playlist(yt_id)
            return

        # 재생목록 선택 다이얼로그
        from PyQt6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QScrollArea  # noqa: PLC0415
        dlg = QDialog(self)
        dlg.setWindowTitle("YouTube 재생목록 가져오기")
        dlg.setMinimumWidth(400)
        dlg.setMinimumHeight(360)
        layout = QVBoxLayout(dlg)

        lbl = QLabel(f"YouTube 계정에서 재생목록 {len(playlists)}개를 찾았습니다.\n가져올 재생목록을 선택하세요:")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        check_container = QWidget()
        check_layout = QVBoxLayout(check_container)
        check_layout.setContentsMargins(4, 4, 4, 4)
        check_layout.setSpacing(4)

        checkboxes: list[tuple[QCheckBox, str]] = []  # (checkbox, yt_playlist_id)
        for pl in playlists:
            pl_id = pl.get("id") or ""
            pl_title = pl.get("title") or pl_id
            pl_count = pl.get("count") or 0
            label = f"{pl_title}  ({pl_count}개)"
            cb = QCheckBox(label)
            cb.setChecked(True)
            check_layout.addWidget(cb)
            checkboxes.append((cb, pl_id))

        check_layout.addStretch()
        scroll.setWidget(check_container)
        layout.addWidget(scroll, 1)

        sel_row = QHBoxLayout()
        btn_all = QPushButton("전체 선택")
        btn_none = QPushButton("전체 해제")
        btn_all.setFixedWidth(80)
        btn_none.setFixedWidth(80)
        btn_all.clicked.connect(lambda: [cb.setChecked(True) for cb, _ in checkboxes])
        btn_none.clicked.connect(lambda: [cb.setChecked(False) for cb, _ in checkboxes])
        sel_row.addWidget(btn_all)
        sel_row.addWidget(btn_none)
        sel_row.addStretch()
        layout.addLayout(sel_row)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        selected_ids = [pl_id for cb, pl_id in checkboxes if cb.isChecked() and pl_id]
        for yt_id in selected_ids:
            self._playlist_vm.import_youtube_playlist(yt_id)

    def _on_import_yt_playlist_manual(self) -> None:
        if self._playlist_vm is None:
            return
        import urllib.parse  # noqa: PLC0415
        pl_id, ok = QInputDialog.getText(
            self, "YouTube 재생목록 가져오기",
            "YouTube 재생목록 ID 또는 URL을 입력하세요:",
        )
        if not ok or not pl_id.strip():
            return
        yt_id = pl_id.strip()
        if "list=" in yt_id:
            parsed = urllib.parse.urlparse(yt_id)
            params = urllib.parse.parse_qs(parsed.query)
            yt_id = params.get("list", [yt_id])[0]
        self._playlist_vm.import_youtube_playlist(yt_id)

    def _on_playlist_reordered(self, playlist_id: UUID, ordered_ids: list[UUID]) -> None:
        if self._playlist_vm is None:
            return
        self._playlist_vm.reorder_playlist(playlist_id, ordered_ids)
