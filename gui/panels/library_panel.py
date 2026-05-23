from __future__ import annotations

from pathlib import Path
from collections import OrderedDict
from uuid import UUID

from PyQt6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QSize,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QPixmap, QPixmapCache
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListView,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config.settings import LRU_THUMBNAIL_MAX, THUMBNAIL_DIR, THUMBNAIL_HEIGHT, THUMBNAIL_WIDTH
from domain.library.aggregates import VideoAggregate
from gui.view_models.library_vm import LibraryViewModel


# ------------------------------------------------------------------
# LRU thumbnail cache (max LRU_THUMBNAIL_MAX QPixmap objects in RAM)
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


_thumb_cache = _ThumbnailCache()


def _load_thumbnail(thumbnail_path: str) -> QPixmap:
    """Load thumbnail at display resolution; returns placeholder if missing."""
    if not thumbnail_path:
        return _placeholder_pixmap()
    cached = _thumb_cache.get(thumbnail_path)
    if cached is not None:
        return cached
    full = Path(THUMBNAIL_DIR) / thumbnail_path
    if not full.exists():
        return _placeholder_pixmap()
    img = QPixmap(str(full))
    if img.isNull():
        return _placeholder_pixmap()
    # Scale to display size at load time — never keep full-res in memory
    scaled = img.scaled(
        THUMBNAIL_WIDTH,
        THUMBNAIL_HEIGHT,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    _thumb_cache.put(thumbnail_path, scaled)
    return scaled


def _placeholder_pixmap() -> QPixmap:
    key = "__placeholder__"
    cached = _thumb_cache.get(key)
    if cached:
        return cached
    pm = QPixmap(THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT)
    pm.fill(Qt.GlobalColor.darkGray)
    _thumb_cache.put(key, pm)
    return pm


# ------------------------------------------------------------------
# Custom model for virtual scrolling (QListView — NOT QListWidget)
# ------------------------------------------------------------------

class VideoListModel(QAbstractListModel):
    """Model backed by a flat list of VideoAggregate.

    Only the data visible in the viewport is rendered by the delegate.
    """

    ThumbnailRole = Qt.ItemDataRole.UserRole + 1
    VideoIdRole   = Qt.ItemDataRole.UserRole + 2

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: list[VideoAggregate] = []

    def set_videos(self, videos: list[VideoAggregate]) -> None:
        self.beginResetModel()
        self._items = videos
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._items)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._items):
            return None
        agg = self._items[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return agg.video.title
        if role == self.ThumbnailRole:
            return _load_thumbnail(agg.video.thumbnail_path)
        if role == self.VideoIdRole:
            return agg.id
        if role == Qt.ItemDataRole.SizeHintRole:
            return QSize(THUMBNAIL_WIDTH + 8, THUMBNAIL_HEIGHT + 8)
        return None


# ------------------------------------------------------------------
# Library panel layout
# ------------------------------------------------------------------

class LibraryPanel(QWidget):
    video_selected = pyqtSignal(object)   # VideoAggregate

    def __init__(self, vm: LibraryViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vm = vm
        self._setup_ui()
        self._connect_vm()
        vm.load()

    def _setup_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal, self)

        # Left: category tree
        self._cat_tree = QTreeWidget()
        self._cat_tree.setHeaderHidden(True)
        self._cat_tree.setMaximumWidth(200)
        splitter.addWidget(self._cat_tree)

        # Center: virtual thumbnail grid
        self._model = VideoListModel()
        self._list_view = QListView()
        self._list_view.setModel(self._model)
        self._list_view.setViewMode(QListView.ViewMode.IconMode)
        self._list_view.setResizeMode(QListView.ResizeMode.Adjust)
        self._list_view.setUniformItemSizes(True)
        self._list_view.setSpacing(4)
        splitter.addWidget(self._list_view)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

    def _connect_vm(self) -> None:
        self._vm.videos_changed.connect(self._on_videos_changed)
        self._vm.categories_changed.connect(self._on_categories_changed)
        self._list_view.clicked.connect(self._on_item_clicked)

    def _on_videos_changed(self) -> None:
        self._model.set_videos(self._vm.videos)

    def _on_categories_changed(self) -> None:
        self._cat_tree.clear()
        all_item = QTreeWidgetItem(["All Videos"])
        all_item.setData(0, Qt.ItemDataRole.UserRole, None)
        self._cat_tree.addTopLevelItem(all_item)
        for cat in self._vm.categories:
            item = QTreeWidgetItem([cat.name])
            item.setData(0, Qt.ItemDataRole.UserRole, cat.id)
            self._cat_tree.addTopLevelItem(item)

    def _on_item_clicked(self, index: QModelIndex) -> None:
        agg = self._model._items[index.row()]
        self.video_selected.emit(agg)
