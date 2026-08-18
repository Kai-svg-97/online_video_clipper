"""영상 목록 모델/뷰 — 가상 스크롤 그리드의 데이터 공급자.

`QListWidget`이 아니라 `QAbstractListModel` + 델리게이트 조합을 쓰는 이유는 메모리
규칙 때문이다(보이는 항목만 그리고, 썸네일도 그때 로드한다).
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import (
    QAbstractListModel,
    QByteArray,
    QMimeData,
    QModelIndex,
    QSize,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QDrag, QPainter, QPixmap,
)
from PyQt6.QtWidgets import (
    QListView,
)

from application.library.dtos import VideoDTO

from gui.panels.library.constants import _ICON_PAD, _ICON_TEXT_H, _MATCH_ROW_H, _MIME_VIDEO_ID, _TH_ICON, _TW_ICON
from gui.panels.library.formatting import _mime_may_contain_url, _url_from_mime
from gui.panels.library.thumbnails import _load_thumb

logger = logging.getLogger(__name__)


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
        """영상 카드 드래그 — 두 경로 모두 반투명 픽스맵 적용."""
        indexes = [i for i in self.selectedIndexes() if i.column() == 0]
        if not indexes:
            return

        # MIME 구성: 재생목록 모드는 source-playlist-id 추가
        if self._current_playlist_id is not None:
            video_ids = [
                str(self.model().data(i, VideoListModel.VideoIdRole))
                for i in indexes
                if self.model().data(i, VideoListModel.VideoIdRole)
            ]
            if not video_ids:
                return
            mime = QMimeData()
            mime.setData(_MIME_VIDEO_ID, QByteArray(",".join(video_ids).encode()))
            mime.setData(
                "application/x-source-playlist-id",
                QByteArray(str(self._current_playlist_id).encode()),
            )
        else:
            mime = self.model().mimeData(indexes)
            if not mime:
                return

        # 반투명 드래그 픽스맵
        rects = [self.visualRect(i) for i in indexes]
        united = rects[0]
        for r in rects[1:]:
            united = united.united(r)
        raw = self.viewport().grab(united)
        transp = QPixmap(raw.size())
        transp.fill(Qt.GlobalColor.transparent)
        _p = QPainter(transp)
        _p.setOpacity(0.55)
        _p.drawPixmap(0, 0, raw)
        _p.end()

        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(transp)
        drag.setHotSpot(united.center() - united.topLeft())
        drag.exec(actions)

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
    MatchFieldsRole = Qt.ItemDataRole.UserRole + 14

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
        if role == self.MatchFieldsRole:
            return dto.match_fields
        if role == Qt.ItemDataRole.SizeHintRole:
            return QSize(_TW_ICON + _ICON_PAD * 2, _TH_ICON + _ICON_TEXT_H + _MATCH_ROW_H)
        return None

    def notify_thumb_cached(self, paths: set[str]) -> None:
        """지정 썸네일 경로가 캐시에 추가됐을 때 해당 행만 재그리기 요청한다."""
        for row, dto in enumerate(self._items):
            if dto.thumbnail_path in paths:
                idx = self.index(row)
                self.dataChanged.emit(idx, idx, [VideoListModel.ThumbPathRole])

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
