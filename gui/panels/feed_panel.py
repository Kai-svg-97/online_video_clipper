"""구독 피드 패널 — 라이브러리 아이콘 카드와 동일한 크기·스타일."""
from __future__ import annotations

import logging
from uuid import UUID

import requests
from PyQt6.QtCore import Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QColor, QDesktopServices, QFont, QImage, QPainter, QPainterPath, QPixmap,
)
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from application.library.dtos import CategoryDTO, FeedVideoDTO, PlaylistDTO
from config.settings import THUMBNAIL_DIR
from gui.themes.manager import ThemeManager
from gui.view_models.feed_vm import FeedViewModel

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from gui.view_models.library_vm import LibraryViewModel
    from gui.view_models.playlist_vm import PlaylistViewModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _fmt_views(count: int | None) -> str:
    if count is None:
        return ""
    if count >= 100_000_000:
        return f"{count / 100_000_000:.1f}억 회"
    if count >= 10_000:
        return f"{count / 10_000:.1f}만 회"
    if count >= 1_000:
        return f"{count / 1_000:.0f}천 회"
    return f"{count}회"


def _fmt_duration(sec: int | None) -> str:
    if sec is None:
        return ""
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _fmt_date(upload_date: str) -> str:
    if not upload_date:
        return ""
    if len(upload_date) == 8:
        return f"{upload_date[:4]}.{upload_date[4:6]}.{upload_date[6:]}"
    return upload_date


# ---------------------------------------------------------------------------
# 썸네일 비동기 로더 (QImage → 메인 스레드에서 QPixmap 변환)
# ---------------------------------------------------------------------------

class _ThumbLoader(QThread):
    loaded = pyqtSignal(str, QImage)   # yt_video_id, QImage

    def __init__(self, url: str, vid_id: str, parent=None) -> None:
        super().__init__(parent)
        self._url = url
        self._vid = vid_id

    def run(self) -> None:
        for ext in ("jpg", "jpeg", "webp", "png"):
            cached = THUMBNAIL_DIR / f"feed_{self._vid}.{ext}"
            if cached.exists():
                img = QImage(str(cached))
                if not img.isNull():
                    self.loaded.emit(self._vid, img.scaled(
                        640, 360,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    ))
                    return
        if not self._url:
            return
        try:
            resp = requests.get(self._url, timeout=10)
            resp.raise_for_status()
            img = QImage()
            img.loadFromData(resp.content)
            if not img.isNull():
                THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
                ext = self._url.rsplit(".", 1)[-1].split("?")[0].lower()
                if ext not in ("jpg", "jpeg", "png", "webp"):
                    ext = "jpg"
                (THUMBNAIL_DIR / f"feed_{self._vid}.{ext}").write_bytes(resp.content)
                self.loaded.emit(self._vid, img.scaled(
                    640, 360,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                ))
        except Exception:
            logger.exception("피드 썸네일 다운로드/디코딩 실패")


# ---------------------------------------------------------------------------
# 카테고리 선택 다이얼로그
# ---------------------------------------------------------------------------

class _CategoryPickDialog(QDialog):
    def __init__(self, categories: list[CategoryDTO], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("카테고리 선택")
        self.setMinimumWidth(280)
        self._selected_id: UUID | None = None

        layout = QVBoxLayout(self)
        lbl = QLabel("추가할 카테고리를 선택하세요:")
        layout.addWidget(lbl)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        layout.addWidget(self._tree, 1)

        cat_map: dict[UUID, QTreeWidgetItem] = {}
        roots: list[CategoryDTO] = []
        children: dict[UUID, list[CategoryDTO]] = {}
        for c in categories:
            if c.parent_id is None:
                roots.append(c)
            else:
                children.setdefault(c.parent_id, []).append(c)

        def _add(cat: CategoryDTO, parent_item: QTreeWidgetItem | None) -> None:
            item = QTreeWidgetItem([cat.name])
            item.setData(0, Qt.ItemDataRole.UserRole, cat.id)
            if parent_item is None:
                self._tree.addTopLevelItem(item)
            else:
                parent_item.addChild(item)
            cat_map[cat.id] = item
            for child in children.get(cat.id, []):
                _add(child, item)

        for root in roots:
            _add(root, None)

        self._tree.expandAll()
        self._tree.itemClicked.connect(lambda item, _: setattr(self, "_selected_id",
                                        item.data(0, Qt.ItemDataRole.UserRole)))

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def selected_id(self) -> UUID | None:
        return self._selected_id


# ---------------------------------------------------------------------------
# 재생목록 선택 다이얼로그
# ---------------------------------------------------------------------------

class _PlaylistPickDialog(QDialog):
    def __init__(self, playlists: list[PlaylistDTO], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("재생목록 선택")
        self.setMinimumWidth(280)
        self._selected_id: UUID | None = None

        layout = QVBoxLayout(self)
        lbl = QLabel("추가할 재생목록을 선택하세요:")
        layout.addWidget(lbl)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        layout.addWidget(self._tree, 1)

        for pl in playlists:
            item = QTreeWidgetItem([f"{pl.title}  ({pl.item_count}개)"])
            item.setData(0, Qt.ItemDataRole.UserRole, pl.id)
            self._tree.addTopLevelItem(item)

        self._tree.itemClicked.connect(lambda item, _: setattr(self, "_selected_id",
                                        item.data(0, Qt.ItemDataRole.UserRole)))

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def selected_id(self) -> UUID | None:
        return self._selected_id


# ---------------------------------------------------------------------------
# 둥근 모서리 썸네일 위젯 (라이브러리와 동일한 스타일)
# ---------------------------------------------------------------------------

class _RoundedThumbLabel(QWidget):
    def __init__(self, w: int, h: int, parent=None) -> None:
        super().__init__(parent)
        self._w = w
        self._h = h
        self._pixmap: QPixmap | None = None
        self._dur_text: str = ""
        self.setFixedSize(w, h)

    def set_image(self, img: QImage) -> None:
        self._pixmap = QPixmap.fromImage(img).scaled(
            self._w, self._h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.update()

    def set_duration(self, text: str) -> None:
        self._dur_text = text
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(0, 0, self._w, self._h, 6, 6)
        painter.setClipPath(path)

        if self._pixmap:
            px = self._pixmap
            dx = max(0, (px.width() - self._w) // 2)
            dy = max(0, (px.height() - self._h) // 2)
            painter.drawPixmap(0, 0, px, dx, dy, self._w, self._h)
        else:
            painter.fillRect(0, 0, self._w, self._h, QColor("#1a1a2e"))

        if self._dur_text:
            f = QFont()
            f.setPointSize(8)
            painter.setFont(f)
            painter.setPen(QColor("white"))
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(self._dur_text) + 8
            th = fm.height() + 4
            bx, by = self._w - tw - 4, self._h - th - 4
            painter.fillRect(bx, by, tw, th, QColor(0, 0, 0, 180))
            painter.drawText(bx + 4, by + th - 4, self._dur_text)

        painter.end()


# ---------------------------------------------------------------------------
# 피드 카드 — 라이브러리 _IconDelegate와 동일한 크기
# ---------------------------------------------------------------------------

class _FeedCard(QFrame):
    """라이브러리 아이콘 뷰와 동일한 320×180 카드."""

    add_to_category_requested = pyqtSignal(str)
    add_to_playlist_requested = pyqtSignal(str)
    download_requested        = pyqtSignal(str, str)   # url, title

    _TW = 320
    _TH = 180

    def __init__(self, dto: FeedVideoDTO, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dto = dto
        self._loader: _ThumbLoader | None = None
        self.setFixedWidth(self._TW + 16)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._build_ui()
        self._apply_theme(ThemeManager.instance().current())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)
        self._start_thumb_load()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 8)
        layout.setSpacing(4)

        # 썸네일
        self._thumb_lbl = _RoundedThumbLabel(self._TW, self._TH)
        layout.addWidget(self._thumb_lbl)

        # 제목 (2줄)
        self._title_lbl = QLabel(self._dto.title)
        self._title_lbl.setWordWrap(True)
        self._title_lbl.setMaximumHeight(44)
        f = QFont()
        f.setPointSize(10)
        f.setWeight(QFont.Weight.Medium)
        self._title_lbl.setFont(f)
        layout.addWidget(self._title_lbl)

        # 채널명
        self._channel_lbl = QLabel(self._dto.channel_name)
        f2 = QFont()
        f2.setPointSize(9)
        self._channel_lbl.setFont(f2)
        layout.addWidget(self._channel_lbl)

        # 하단 행: 메타 + 아이콘 버튼
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(4)

        meta_parts = []
        if self._dto.view_count:
            meta_parts.append(_fmt_views(self._dto.view_count))
        if self._dto.published_at:
            meta_parts.append(_fmt_date(self._dto.published_at))
        self._meta_lbl = QLabel("  •  ".join(meta_parts))
        f3 = QFont()
        f3.setPointSize(8)
        self._meta_lbl.setFont(f3)
        bottom.addWidget(self._meta_lbl, 1)

        self._cat_btn = QPushButton("📁")
        self._cat_btn.setFixedSize(24, 24)
        self._cat_btn.setToolTip("카테고리에 추가")
        self._cat_btn.setFlat(True)
        self._cat_btn.clicked.connect(
            lambda: self.add_to_category_requested.emit(self._dto.url)
        )
        bottom.addWidget(self._cat_btn)

        self._pl_btn = QPushButton("☰")
        self._pl_btn.setFixedSize(24, 24)
        self._pl_btn.setToolTip("재생목록에 추가")
        self._pl_btn.setFlat(True)
        self._pl_btn.clicked.connect(
            lambda: self.add_to_playlist_requested.emit(self._dto.url)
        )
        bottom.addWidget(self._pl_btn)

        layout.addLayout(bottom)

        if self._dto.in_library:
            badge = QLabel("✓ 라이브러리")
            f4 = QFont()
            f4.setPointSize(8)
            badge.setFont(f4)
            badge.setStyleSheet("color: #4caf50;")
            layout.addWidget(badge)

    def _start_thumb_load(self) -> None:
        vid_id = self._dto.yt_video_id or self._dto.url.split("v=")[-1].split("&")[0][:11]
        if not vid_id:
            return
        for ext in ("jpg", "jpeg", "webp", "png"):
            cached = THUMBNAIL_DIR / f"feed_{vid_id}.{ext}"
            if cached.exists():
                img = QImage(str(cached))
                if not img.isNull():
                    self._thumb_lbl.set_image(img)
                    return
        url = self._dto.thumbnail_url
        if not url:
            return
        self._loader = _ThumbLoader(url, vid_id)
        self._loader.loaded.connect(self._on_thumb_loaded)
        self._loader.start()

    def _on_thumb_loaded(self, _vid_id: str, img: QImage) -> None:
        self._thumb_lbl.set_image(img)

    # ── 더블클릭: 브라우저에서 열기 ──
    def mouseDoubleClickEvent(self, _event) -> None:
        if self._dto.url:
            QDesktopServices.openUrl(QUrl(self._dto.url))

    # ── 우클릭: 컨텍스트 메뉴 ──
    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        menu.addAction(
            "브라우저에서 열기",
            lambda: QDesktopServices.openUrl(QUrl(self._dto.url)),
        )
        menu.addAction(
            "다운로드",
            lambda: self.download_requested.emit(self._dto.url, self._dto.title),
        )
        menu.addSeparator()
        menu.addAction(
            "카테고리에 추가",
            lambda: self.add_to_category_requested.emit(self._dto.url),
        )
        menu.addAction(
            "재생목록에 추가",
            lambda: self.add_to_playlist_requested.emit(self._dto.url),
        )
        menu.exec(event.globalPos())

    def _apply_theme(self, tokens) -> None:
        tok = tokens
        self.setStyleSheet(f"""
            QFrame {{
                background: {tok.bg_elevated};
                border: 1px solid {tok.border};
                border-radius: 8px;
            }}
            QFrame:hover {{
                border-color: {tok.accent};
            }}
        """)
        self._title_lbl.setStyleSheet(f"color: {tok.text_primary};")
        self._channel_lbl.setStyleSheet(f"color: {tok.text_secondary};")
        self._meta_lbl.setStyleSheet(f"color: {tok.text_muted};")
        btn_style = (
            f"QPushButton {{ color: {tok.text_muted}; background: transparent; "
            f"border: none; border-radius: 3px; font-size: 13px; }}"
            f"QPushButton:hover {{ background: {tok.bg_overlay}; color: {tok.accent}; }}"
        )
        self._cat_btn.setStyleSheet(btn_style)
        self._pl_btn.setStyleSheet(btn_style)


# ---------------------------------------------------------------------------
# 피드 그리드
# ---------------------------------------------------------------------------

class _FeedGrid(QWidget):
    add_to_category_requested = pyqtSignal(str)
    add_to_playlist_requested = pyqtSignal(str)
    download_requested        = pyqtSignal(str, str)

    _CARD_W = _FeedCard._TW + 16 + 16

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._layout.setSpacing(16)
        self._cards: list[_FeedCard] = []

    def set_feed(self, items: list[FeedVideoDTO]) -> None:
        for card in self._cards:
            card.deleteLater()
        self._cards.clear()

        cols = max(1, (self.width() - 24) // self._CARD_W)
        for i, dto in enumerate(items):
            card = _FeedCard(dto)
            card.add_to_category_requested.connect(self.add_to_category_requested)
            card.add_to_playlist_requested.connect(self.add_to_playlist_requested)
            card.download_requested.connect(self.download_requested)
            if dto.duration_sec:
                card._thumb_lbl.set_duration(_fmt_duration(dto.duration_sec))
            self._layout.addWidget(card, i // cols, i % cols)
            self._cards.append(card)


# ---------------------------------------------------------------------------
# 피드 패널 (메인)
# ---------------------------------------------------------------------------

class FeedPanel(QWidget):
    video_to_category  = pyqtSignal(str, object)   # url, category_id (UUID)
    video_to_playlist  = pyqtSignal(str, object)   # url, playlist_id (UUID)
    download_requested = pyqtSignal(str, str)       # url, title

    def __init__(
        self,
        vm: FeedViewModel,
        library_vm: "LibraryViewModel | None" = None,
        playlist_vm: "PlaylistViewModel | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._vm = vm
        self._library_vm = library_vm
        self._playlist_vm = playlist_vm
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        hdr = QWidget()
        hdr.setFixedHeight(48)
        hdr_layout = QHBoxLayout(hdr)
        hdr_layout.setContentsMargins(16, 0, 16, 0)
        hdr_layout.setSpacing(8)

        title = QLabel("구독 피드")
        f = QFont()
        f.setPointSize(11)
        f.setWeight(QFont.Weight.Bold)
        title.setFont(f)
        hdr_layout.addWidget(title)
        hdr_layout.addStretch()

        self._refresh_btn = QPushButton("새로고침")
        self._refresh_btn.setFixedWidth(80)
        self._refresh_btn.clicked.connect(self._on_refresh)
        hdr_layout.addWidget(self._refresh_btn)

        self._status_lbl = QLabel()
        self._status_lbl.hide()
        hdr_layout.addWidget(self._status_lbl)

        layout.addWidget(hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._grid = _FeedGrid()
        scroll.setWidget(self._grid)
        layout.addWidget(scroll, stretch=1)

        self._grid.add_to_category_requested.connect(self._on_add_to_category)
        self._grid.add_to_playlist_requested.connect(self._on_add_to_playlist)
        self._grid.download_requested.connect(self.download_requested)

        self._apply_theme(ThemeManager.instance().current())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)

    def _connect_signals(self) -> None:
        self._vm.feed_changed.connect(self._on_feed_changed)
        self._vm.loading_changed.connect(self._on_loading_changed)
        self._vm.error_occurred.connect(self._on_error)

    def _on_refresh(self) -> None:
        self._status_lbl.hide()
        self._vm.refresh()

    def _on_feed_changed(self) -> None:
        self._grid.set_feed(self._vm.feed)

    def _on_loading_changed(self, loading: bool) -> None:
        self._refresh_btn.setEnabled(not loading)
        if loading:
            self._status_lbl.setText("로딩 중…")
            self._status_lbl.show()
        else:
            self._status_lbl.hide()

    def _on_error(self, msg: str) -> None:
        if "Could not copy" in msg and "cookie" in msg.lower():
            display = "쿠키 읽기 실패 — 사이드바 계정 버튼에서 로그인하세요."
        else:
            display = f"오류: {msg[:120]}"
        self._status_lbl.setText(display)
        self._status_lbl.show()

    def _on_add_to_category(self, url: str) -> None:
        categories = self._library_vm.categories if self._library_vm else []
        if not categories:
            self._status_lbl.setText("등록된 카테고리가 없습니다.")
            self._status_lbl.show()
            return
        dlg = _CategoryPickDialog(categories, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            cat_id = dlg.selected_id()
            if cat_id is not None:
                self.video_to_category.emit(url, cat_id)

    def _on_add_to_playlist(self, url: str) -> None:
        playlists = self._playlist_vm.playlists if self._playlist_vm else []
        if not playlists:
            self._status_lbl.setText("등록된 재생목록이 없습니다.")
            self._status_lbl.show()
            return
        dlg = _PlaylistPickDialog(playlists, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            pl_id = dlg.selected_id()
            if pl_id is not None:
                self.video_to_playlist.emit(url, pl_id)

    def _apply_theme(self, tokens) -> None:
        tok = tokens
        self.setStyleSheet(f"background: {tok.bg_base};")
