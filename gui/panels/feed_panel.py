"""구독 피드 패널 — 라이브러리 아이콘 카드와 동일한 크기·스타일."""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from uuid import UUID

import requests
from PyQt6.QtCore import QMimeData, QPoint, Qt, QSize, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QColor, QDesktopServices, QDrag, QFont, QImage, QPainter, QPainterPath, QPixmap,
)
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from application.library.dtos import CategoryDTO, ChannelInfoDTO, FeedVideoDTO, PlaylistDTO
from config.settings import THUMBNAIL_DIR
from gui.anim import fade_in
from gui.themes.manager import ThemeManager
from gui.workers import track_thread
from gui.view_models.feed_vm import FeedViewModel

from typing import TYPE_CHECKING
from gui.themes.colors import sem
if TYPE_CHECKING:
    from gui.view_models.library_vm import LibraryViewModel
    from gui.view_models.playlist_vm import PlaylistViewModel

logger = logging.getLogger(__name__)

# 동시 썸네일 다운로드 스레드 상한 — 피드 100개 카드 진입 시 스레드 폭발 방지
_THUMB_SEMA = threading.Semaphore(10)


class _ThumbnailCache:
    """스크롤·재진입 시 QPixmap 재변환을 방지하는 LRU 인메모리 캐시."""

    def __init__(self, maxsize: int = 150) -> None:
        self._cache: OrderedDict = OrderedDict()
        self._maxsize = maxsize

    def get(self, key: str):
        if key not in self._cache:
            return None
        self._cache.move_to_end(key)
        return self._cache[key]

    def put(self, key: str, pixmap) -> None:
        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            if len(self._cache) >= self._maxsize:
                self._cache.popitem(last=False)
            self._cache[key] = pixmap


_feed_thumb_cache = _ThumbnailCache(maxsize=150)


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _fmt_views(view_count: int | None) -> str:
    """라이브러리 아이콘 카드와 동일한 '조회수 1.2만 회' 형식."""
    if view_count is None:
        return ""
    if view_count < 1_000:
        return f"조회수 {view_count}회"
    if view_count < 10_000:
        return f"조회수 {view_count / 1000:.1f}천 회"
    if view_count < 100_000_000:
        return f"조회수 {view_count / 10000:.1f}만 회"
    return f"조회수 {view_count / 100_000_000:.1f}억 회"


def _fmt_duration(sec: int | None) -> str:
    if sec is None:
        return ""
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _relative_time(date_str: str | None) -> str:
    """라이브러리 카드와 동일한 '3일 전' 형식. yt-dlp의 YYYYMMDD·ISO 모두 처리."""
    if not date_str:
        return ""
    from datetime import date, datetime
    try:
        if len(date_str) == 8 and date_str.isdigit():        # YYYYMMDD
            pub = date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:]))
        elif "T" in date_str or " " in date_str:
            pub = datetime.fromisoformat(date_str.replace("Z", "+00:00")).date()
        else:
            pub = date.fromisoformat(date_str)
        days = (date.today() - pub).days
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


# ---------------------------------------------------------------------------
# 썸네일 비동기 로더 (QImage → 메인 스레드에서 QPixmap 변환)
# ---------------------------------------------------------------------------

def start_thumb_loader(
    url: str,
    vid_id: str,
    on_loaded,
    prefix: str = "feed",
    size: tuple[int, int] = (640, 360),
) -> "_ThumbLoader":
    """썸네일 로더를 안전하게 띄운다.

    카드는 목록을 다시 채울 때마다 지워지는데, 그 순간 실행 중인 로더가 파괴되면 Qt가
    프로세스를 죽인다. 그래서 **부모를 주지 않고** ``track_thread``가 끝날 때까지 붙든다.
    ``on_loaded``는 반드시 **QObject의 바운드 메서드**여야 한다 — 수신 위젯이 사라지면
    Qt가 연결을 자동으로 끊어 죽은 위젯을 건드리지 않는다(람다는 그 보호를 못 받는다).
    """
    loader = _ThumbLoader(url, vid_id, None, prefix=prefix, size=size)
    track_thread(loader)
    loader.loaded.connect(on_loaded)
    loader.start()
    return loader


class _ThumbLoader(QThread):
    loaded = pyqtSignal(str, QImage)   # id, QImage

    def __init__(
        self,
        url: str,
        vid_id: str,
        parent=None,
        prefix: str = "feed",
        size: tuple[int, int] = (640, 360),
    ) -> None:
        super().__init__(parent)
        self._url = url
        self._vid = vid_id
        self._prefix = prefix
        self._size = size

    def run(self) -> None:
        sw, sh = self._size
        with _THUMB_SEMA:
            for ext in ("jpg", "jpeg", "webp", "png"):
                cached = THUMBNAIL_DIR / f"{self._prefix}_{self._vid}.{ext}"
                if cached.exists():
                    img = QImage(str(cached))
                    if not img.isNull():
                        self.loaded.emit(self._vid, img.scaled(
                            sw, sh,
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
                    (THUMBNAIL_DIR / f"{self._prefix}_{self._vid}.{ext}").write_bytes(resp.content)
                    self.loaded.emit(self._vid, img.scaled(
                        sw, sh,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    ))
            except Exception:
                logger.exception("썸네일 다운로드/디코딩 실패")


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
        self._channel_text: str = ""
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

    def set_channel(self, text: str) -> None:
        self._channel_text = text
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

        f = QFont()
        f.setPointSize(8)
        painter.setFont(f)
        painter.setPen(QColor("white"))
        fm = painter.fontMetrics()
        th = fm.height() + 4

        # 재생시간 배지 (우측 하단)
        dur_tw = 0
        if self._dur_text:
            dur_tw = fm.horizontalAdvance(self._dur_text) + 8
            bx, by = self._w - dur_tw - 4, self._h - th - 4
            painter.fillRect(bx, by, dur_tw, th, QColor(0, 0, 0, 180))
            painter.drawText(bx + 4, by + th - 4, self._dur_text)

        # 채널명 배지 (좌측 하단) — 재생시간 배지와 겹치지 않게 폭 제한 + 말줄임
        if self._channel_text:
            avail = self._w - dur_tw - 16  # 좌4 + 우4 + 배지 사이 간격 여유
            if avail > 24:
                text = fm.elidedText(
                    self._channel_text, Qt.TextElideMode.ElideRight, avail
                )
                tw = fm.horizontalAdvance(text) + 8
                bx, by = 4, self._h - th - 4
                painter.fillRect(bx, by, tw, th, QColor(0, 0, 0, 180))
                painter.drawText(bx + 4, by + th - 4, text)

        painter.end()


# ---------------------------------------------------------------------------
# 피드 카드 — 라이브러리 _IconDelegate와 동일한 크기
# ---------------------------------------------------------------------------

class _FeedCard(QFrame):
    """라이브러리 아이콘 뷰와 동일한 320×180 카드."""

    add_to_category_requested = pyqtSignal(str)
    add_to_playlist_requested = pyqtSignal(str)
    download_requested        = pyqtSignal(str, str)   # url, title
    video_clicked             = pyqtSignal(object)      # FeedVideoDTO (단일 클릭 → 상세)

    _TW = 320
    _TH = 180

    def __init__(
        self,
        dto: FeedVideoDTO,
        parent: QWidget | None = None,
        show_channel: bool = True,
        thumb_size: tuple[int, int] | None = None,
        draggable: bool = False,
    ) -> None:
        super().__init__(parent)
        self._dto = dto
        self._show_channel = show_channel
        self._loader: _ThumbLoader | None = None
        if thumb_size is not None:
            # 인스턴스 속성으로 클래스 기본값(320×180)을 가린다 — 추천 스트립처럼
            # 세로 공간이 좁은 곳에서 같은 카드를 작게 쓰기 위한 것이다.
            self._TW, self._TH = thumb_size
        # 드래그로 카테고리 트리에 바로 담기(추천 스트립·피드 그리드 공용).
        self._draggable = draggable
        self._press_pos: QPoint | None = None
        self._dragged: bool = False
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
        if self._show_channel:
            self._thumb_lbl.set_channel(self._dto.channel_name)
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

        # 채널명 (개별 채널 피드에서는 중복이라 숨김). 테마 적용 안전을 위해
        # 라벨은 항상 생성하고, 표시할 때만 레이아웃에 추가한다.
        self._channel_lbl = QLabel(self._dto.channel_name)
        f2 = QFont()
        f2.setPointSize(9)
        self._channel_lbl.setFont(f2)
        if self._show_channel:
            layout.addWidget(self._channel_lbl)
        else:
            self._channel_lbl.hide()

        # 하단 행: 메타 (조회수·업로드일). 카테고리/재생목록 추가는 우클릭 메뉴로 일원화해
        # 라이브러리 아이콘 카드와 외형을 통일한다.
        meta_parts = []
        if self._dto.view_count:
            meta_parts.append(_fmt_views(self._dto.view_count))
        rel = _relative_time(self._dto.published_at)
        if rel:
            meta_parts.append(rel)
        self._meta_lbl = QLabel("  •  ".join(meta_parts))
        f3 = QFont()
        f3.setPointSize(8)
        self._meta_lbl.setFont(f3)
        layout.addWidget(self._meta_lbl)

        if self._dto.in_library:
            badge = QLabel("✓ 라이브러리")
            f4 = QFont()
            f4.setPointSize(8)
            badge.setFont(f4)
            badge.setStyleSheet(f"color: {sem('success')};")
            layout.addWidget(badge)

    def _start_thumb_load(self) -> None:
        vid_id = self._dto.yt_video_id or self._dto.url.split("v=")[-1].split("&")[0][:11]
        if not vid_id:
            return
        cache_key = f"{vid_id}@{self._TW}x{self._TH}"
        cached_px = _feed_thumb_cache.get(cache_key)
        if cached_px is not None:
            self._thumb_lbl._pixmap = cached_px
            self._thumb_lbl.update()
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
        # 캐시 키는 카드가 알고 있으므로 슬롯에서 다시 만든다 — 람다로 넘기면 카드가
        # 사라진 뒤에도 호출돼(수신자가 없어 자동 해제되지 않는다) 죽은 위젯을 건드린다.
        self._thumb_cache_key = cache_key
        self._loader = start_thumb_loader(url, vid_id, self._on_thumb_loaded)

    def _on_thumb_loaded(self, _vid_id: str, img: QImage, cache_key: str = "") -> None:
        cache_key = cache_key or getattr(self, "_thumb_cache_key", "")
        # 원격에서 막 도착한 그림이라 살짝 띄워 준다(캐시 적중은 이 경로를 타지 않는다).
        fade_in(self._thumb_lbl)
        from PyQt6.QtGui import QPixmap  # noqa: PLC0415
        px = QPixmap.fromImage(img).scaled(
            self._TW, self._TH,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        if cache_key:
            _feed_thumb_cache.put(cache_key, px)
        try:
            self._thumb_lbl._pixmap = px
            self._thumb_lbl.update()
        except RuntimeError:
            pass  # 카드가 소멸된 후 콜백 도달 시 무시

    # ── 마우스: 단일 클릭 → 상세화면 / 끌기 → URL 드래그 ──
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            self._dragged = False
            # 명시적으로 수락해 이후 move/release 이벤트가 이 카드로 오게 한다.
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (
            not self._draggable
            or self._press_pos is None
            or not (event.buttons() & Qt.MouseButton.LeftButton)
        ):
            super().mouseMoveEvent(event)
            return
        moved = (event.position().toPoint() - self._press_pos).manhattanLength()
        if moved < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return
        self._dragged = True
        self._start_url_drag()

    def mouseReleaseEvent(self, event) -> None:
        was_drag = self._dragged
        self._press_pos = None
        self._dragged = False
        if was_drag:
            return   # 드래그로 끝난 조작은 클릭(상세 진입)으로 처리하지 않는다
        if (
            event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            self.video_clicked.emit(self._dto)

    def _start_url_drag(self) -> None:
        """영상 URL을 담은 드래그를 시작한다.

        MIME은 ``text/uri-list``+``text/plain``으로, 브라우저에서 URL을 끌어다
        놓을 때와 **완전히 같은 형태**다 — 카테고리 트리의 기존 URL 드롭 경로를
        그대로 재사용하므로 받는 쪽에 추천 전용 처리가 필요하지 않다.
        """
        url = self._dto.url
        if not url:
            return
        mime = QMimeData()
        mime.setUrls([QUrl(url)])
        mime.setText(url)
        drag = QDrag(self)
        drag.setMimeData(mime)
        px = self._thumb_lbl._pixmap
        if px is not None and not px.isNull():
            preview = px.scaledToWidth(160, Qt.TransformationMode.SmoothTransformation)
            drag.setPixmap(preview)
            drag.setHotSpot(QPoint(preview.width() // 2, preview.height() // 2))
        drag.exec(Qt.DropAction.CopyAction)

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


# ---------------------------------------------------------------------------
# 피드 그리드
# ---------------------------------------------------------------------------

class _FeedGrid(QWidget):
    add_to_category_requested = pyqtSignal(str)
    add_to_playlist_requested = pyqtSignal(str)
    download_requested        = pyqtSignal(str, str)
    video_clicked             = pyqtSignal(object)   # FeedVideoDTO

    _CARD_W = _FeedCard._TW + 16 + 16

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._layout.setSpacing(16)
        self._cards: list[_FeedCard] = []
        self._cols = 0

    def minimumSizeHint(self) -> QSize:
        # 고정폭 카드 + QGridLayout의 기본 최소너비(= 현재 열 수 × 카드폭)는
        # 스크롤 영역(setWidgetResizable)이 그리드를 그 아래로 줄이지 못하게 막아
        # 창 축소 시 reflow를 방해한다. 최소너비를 한 칸으로 낮춰 1열까지 축소
        # 가능하게 하고, 실제 열 수는 resizeEvent가 결정한다.
        return QSize(self._CARD_W + 24, 0)

    def _calc_cols(self) -> int:
        return max(1, (self.width() - 24) // self._CARD_W)

    def set_feed(self, items: list[FeedVideoDTO], show_channel: bool = True) -> None:
        for card in self._cards:
            card.deleteLater()
        self._cards.clear()

        self._cols = self._calc_cols()
        for i, dto in enumerate(items):
            card = _FeedCard(dto, show_channel=show_channel, draggable=True)
            card.add_to_category_requested.connect(self.add_to_category_requested)
            card.add_to_playlist_requested.connect(self.add_to_playlist_requested)
            card.download_requested.connect(self.download_requested)
            card.video_clicked.connect(self.video_clicked)
            if dto.duration_sec:
                card._thumb_lbl.set_duration(_fmt_duration(dto.duration_sec))
            self._layout.addWidget(card, i // self._cols, i % self._cols)
            self._cards.append(card)

    def append_feed(self, items: list[FeedVideoDTO], show_channel: bool = True) -> None:
        """기존 카드를 유지하면서 새 항목만 추가한다 (부분 결과 스트리밍용)."""
        if not items:
            return
        if self._cols == 0:
            self._cols = self._calc_cols()
        start = len(self._cards)
        for i, dto in enumerate(items):
            card = _FeedCard(dto, show_channel=show_channel, draggable=True)
            card.add_to_category_requested.connect(self.add_to_category_requested)
            card.add_to_playlist_requested.connect(self.add_to_playlist_requested)
            card.download_requested.connect(self.download_requested)
            card.video_clicked.connect(self.video_clicked)
            if dto.duration_sec:
                card._thumb_lbl.set_duration(_fmt_duration(dto.duration_sec))
            row, col = divmod(start + i, self._cols)
            self._layout.addWidget(card, row, col)
            self._cards.append(card)

    def _relayout(self) -> None:
        """카드를 재생성하지 않고 현재 열 수에 맞춰 그리드 위치만 재배치한다."""
        for i, card in enumerate(self._cards):
            self._layout.addWidget(card, i // self._cols, i % self._cols)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        new_cols = self._calc_cols()
        if self._cards and new_cols != self._cols:
            self._cols = new_cols
            self._relayout()


# ---------------------------------------------------------------------------
# 추천 영상 스트립 — 영상 목록 아래 접이식 가로 스크롤 띠
# ---------------------------------------------------------------------------

class RecommendStrip(QWidget):
    """현재 목록과 관련 있을 만한 YouTube 영상을 가로로 나열하는 접이식 스트립.

    ``QSplitter``의 아래쪽 자식으로 들어가 핸들을 끌어 높이를 조절하고, 헤더의
    삼각형 버튼으로 본문만 접는다(헤더는 항상 남아 다시 펼칠 수 있다).
    카드는 ``_FeedCard``를 작은 썸네일로 재사용하며 **드래그 가능**이라,
    좌측 카테고리 트리에 바로 끌어다 놓아 라이브러리에 담을 수 있다.
    """

    refresh_requested         = pyqtSignal()
    load_more_requested       = pyqtSignal()         # 끝에 닿기 전 미리 더 받기
    expanded_changed          = pyqtSignal(bool)
    video_clicked             = pyqtSignal(object)   # FeedVideoDTO
    download_requested        = pyqtSignal(str, str)
    add_to_category_requested = pyqtSignal(str)
    add_to_playlist_requested = pyqtSignal(str)

    # 목록 아래 띠라서 아이콘 그리드 카드(320×180)보다 작게 쓴다.
    THUMB_SIZE = (192, 108)
    # 헤더만 남았을 때의 높이 — 스플리터 최소 높이 계산에 쓴다.
    HEADER_H = 30
    # 오른쪽 끝에서 이만큼 남았을 때 미리 다음 묶음을 받는다(카드 2장쯤 앞).
    PREFETCH_MARGIN_PX = 420

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cards: list[_FeedCard] = []
        self._expanded = True
        self._more_busy = False        # 추가분을 받는 중(중복 요청 방지)
        self._more_exhausted = False   # 더 받을 게 없다고 판명됨
        self._build_ui()
        self._apply_theme(ThemeManager.instance().current())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)

    # ── 구성 ────────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 헤더 = 접기 바
        self._bar = QWidget()
        self._bar.setFixedHeight(self.HEADER_H)
        bar_row = QHBoxLayout(self._bar)
        bar_row.setContentsMargins(8, 0, 8, 0)
        bar_row.setSpacing(6)

        self._toggle_btn = QToolButton()
        self._toggle_btn.setText("▾")
        self._toggle_btn.setFixedSize(18, 18)
        self._toggle_btn.setAutoRaise(True)
        self._toggle_btn.setToolTip("추천 영상 접기/펼치기")
        self._toggle_btn.clicked.connect(self.toggle)
        bar_row.addWidget(self._toggle_btn)

        self._title_lbl = QLabel("추천 영상")
        f = QFont()
        f.setPointSize(9)
        f.setWeight(QFont.Weight.DemiBold)
        self._title_lbl.setFont(f)
        bar_row.addWidget(self._title_lbl)

        self._hint_lbl = QLabel("— 카드를 왼쪽 카테고리로 끌어다 놓으면 담깁니다")
        fh = QFont()
        fh.setPointSize(8)
        self._hint_lbl.setFont(fh)
        bar_row.addWidget(self._hint_lbl)

        bar_row.addStretch(1)

        self._status_lbl = QLabel()
        self._status_lbl.setFont(fh)
        bar_row.addWidget(self._status_lbl)

        self._refresh_btn = QToolButton()
        self._refresh_btn.setText("⟳")
        self._refresh_btn.setFixedSize(20, 20)
        self._refresh_btn.setAutoRaise(True)
        self._refresh_btn.setToolTip("추천 다시 받기")
        self._refresh_btn.clicked.connect(self.refresh_requested)
        bar_row.addWidget(self._refresh_btn)

        root.addWidget(self._bar)

        # 본문 = 카드 가로 스크롤
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._row_widget = QWidget()
        self._row = QHBoxLayout(self._row_widget)
        self._row.setContentsMargins(8, 6, 8, 6)
        self._row.setSpacing(10)
        self._row.addStretch(1)
        self._scroll.setWidget(self._row_widget)
        self._scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        # 끝에 도달하기 **전에** 다음 묶음을 미리 받는다 — 끝까지 밀고 나서야 받으면
        # 빈 공백을 마주한 뒤 기다리게 된다.
        self._scroll.horizontalScrollBar().valueChanged.connect(self._on_hscroll)
        root.addWidget(self._scroll, stretch=1)

        self._empty_lbl = QLabel("추천할 영상이 없습니다.")
        self._empty_lbl.setFont(fh)
        self._empty_lbl.setContentsMargins(12, 8, 12, 8)
        self._empty_lbl.hide()
        root.addWidget(self._empty_lbl)

    def _apply_theme(self, tokens) -> None:
        self._bar.setStyleSheet(
            f"background: {tokens.bg_surface};"
            f"border-top: 1px solid {tokens.border};"
        )
        self._title_lbl.setStyleSheet(f"color: {tokens.text_primary}; border: none;")
        self._hint_lbl.setStyleSheet(f"color: {tokens.text_muted}; border: none;")
        self._status_lbl.setStyleSheet(f"color: {tokens.text_secondary}; border: none;")
        self._empty_lbl.setStyleSheet(f"color: {tokens.text_muted};")
        self._scroll.setStyleSheet(f"background: {tokens.bg_base};")

    # ── 상태 ────────────────────────────────────────────────────────────────
    @property
    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool, notify: bool = True) -> None:
        self._expanded = expanded
        self._toggle_btn.setText("▾" if expanded else "▸")
        self._scroll.setVisible(expanded)
        self._empty_lbl.setVisible(expanded and not self._cards)
        if notify:
            self.expanded_changed.emit(expanded)

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_status(self, text: str) -> None:
        self._status_lbl.setText(text)

    # 검색어로 채워졌는지 목록 기반 추천인지 헤더에서 바로 알 수 있게 한다.
    DEFAULT_TITLE = "추천 영상"

    def set_title(self, text: str = "") -> None:
        """헤더 제목을 바꾼다(빈 문자열이면 기본 제목으로 되돌린다)."""
        self._title_lbl.setText(text or self.DEFAULT_TITLE)

    def set_loading(self, loading: bool) -> None:
        self._refresh_btn.setEnabled(not loading)
        if loading:
            self._status_lbl.setText("추천 받는 중…")
        elif self._status_lbl.text() == "추천 받는 중…":
            self._status_lbl.setText("")

    def count(self) -> int:
        return len(self._cards)

    # ── 미리 받기 ───────────────────────────────────────────────────────────
    def set_more_loading(self, loading: bool) -> None:
        """추가분 조회 중 표시. 조회 중에는 다시 요청하지 않는다."""
        self._more_busy = loading
        if loading:
            self._status_lbl.setText("더 불러오는 중…")
        elif self._status_lbl.text() == "더 불러오는 중…":
            self._status_lbl.setText("")

    def set_more_exhausted(self, exhausted: bool) -> None:
        """더 받을 게 없으면 스크롤할 때마다 헛되이 조회하지 않는다."""
        self._more_exhausted = exhausted

    def _on_hscroll(self, value: int) -> None:
        if not self._expanded or self._more_busy or self._more_exhausted:
            return
        bar = self._scroll.horizontalScrollBar()
        if bar.maximum() <= 0:
            return   # 스크롤할 것도 없다(다 보이는 상태)
        margin = max(self.PREFETCH_MARGIN_PX, self._scroll.viewport().width() // 2)
        if bar.maximum() - value <= margin:
            self.load_more_requested.emit()

    # ── 카드 ────────────────────────────────────────────────────────────────
    def clear(self) -> None:
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()
        self._empty_lbl.setVisible(self._expanded)

    def set_items(self, items: list[FeedVideoDTO]) -> None:
        self.clear()
        self._more_exhausted = False   # 씨앗이 바뀌면 다시 더 받을 수 있다
        self.append_items(items)

    def append_items(self, items: list[FeedVideoDTO]) -> None:
        if not items:
            self._empty_lbl.setVisible(self._expanded and not self._cards)
            return
        for dto in items:
            card = _FeedCard(
                dto,
                show_channel=True,
                thumb_size=self.THUMB_SIZE,
                draggable=True,
            )
            card.video_clicked.connect(self.video_clicked)
            card.download_requested.connect(self.download_requested)
            card.add_to_category_requested.connect(self.add_to_category_requested)
            card.add_to_playlist_requested.connect(self.add_to_playlist_requested)
            if dto.duration_sec:
                card._thumb_lbl.set_duration(_fmt_duration(dto.duration_sec))
            # 마지막 stretch 앞에 삽입해 카드가 왼쪽부터 채워지게 한다.
            self._row.insertWidget(self._row.count() - 1, card)
            self._cards.append(card)
        self._empty_lbl.hide()


# ---------------------------------------------------------------------------
# 채널 카드 — 구독 채널 목록(아바타 + 구독자수 + 영상수)
# ---------------------------------------------------------------------------

def _fmt_count(count: int | None, unit: str) -> str:
    """구독자/영상 수 포맷. 예: 12.3만, 1,234."""
    if count is None:
        return ""
    if count >= 100_000_000:
        return f"{count / 100_000_000:.1f}억{unit}"
    if count >= 10_000:
        return f"{count / 10_000:.1f}만{unit}"
    return f"{count:,}{unit}"


class _ChannelCard(QFrame):
    """구독 채널 카드 — 원형 아바타 + 채널명 + 구독자수 + 영상수."""

    channel_clicked = pyqtSignal(str)   # channel_url

    _AVATAR = 72
    _W = 200

    def __init__(self, dto: ChannelInfoDTO, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dto = dto
        self._loader: _ThumbLoader | None = None
        self.setFixedWidth(self._W)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._build_ui()
        self._apply_theme(ThemeManager.instance().current())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)
        self._start_avatar_load()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 14, 10, 14)
        layout.setSpacing(6)

        self._avatar = _RoundedThumbLabel(self._AVATAR, self._AVATAR)
        layout.addWidget(self._avatar, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._name_lbl = QLabel(self._dto.channel_name)
        self._name_lbl.setWordWrap(True)
        self._name_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._name_lbl.setMaximumHeight(40)
        fn = QFont()
        fn.setPointSize(10)
        fn.setWeight(QFont.Weight.Medium)
        self._name_lbl.setFont(fn)
        layout.addWidget(self._name_lbl)

        meta_parts = []
        subs = _fmt_count(self._dto.subscriber_count, "")
        if subs:
            meta_parts.append(f"구독자 {subs}")
        vids = _fmt_count(self._dto.video_count, "")
        if vids:
            meta_parts.append(f"영상 {vids}")
        self._meta_lbl = QLabel("  •  ".join(meta_parts))
        self._meta_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        fm = QFont()
        fm.setPointSize(8)
        self._meta_lbl.setFont(fm)
        layout.addWidget(self._meta_lbl)

        # 최근 업로드 영상이 얼마나 지났는지 (있을 때만)
        rel = _relative_time(getattr(self._dto, "latest_video_published_at", None))
        self._latest_lbl = QLabel(f"최근 영상 {rel}" if rel else "")
        self._latest_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        fl = QFont()
        fl.setPointSize(8)
        self._latest_lbl.setFont(fl)
        self._latest_lbl.setVisible(bool(rel))
        layout.addWidget(self._latest_lbl)

    def _start_avatar_load(self) -> None:
        if not self._dto.channel_id:
            return
        cache_key = f"ch_{self._dto.channel_id}@{self._AVATAR}x{self._AVATAR}"
        cached_px = _feed_thumb_cache.get(cache_key)
        if cached_px is not None:
            self._avatar._pixmap = cached_px
            self._avatar.update()
            return
        if not self._dto.thumbnail_url:
            return
        self._avatar_cache_key = cache_key
        self._loader = start_thumb_loader(
            self._dto.thumbnail_url, self._dto.channel_id, self._on_avatar_loaded,
            prefix="channel", size=(self._AVATAR, self._AVATAR),
        )

    def _on_avatar_loaded(self, _id: str, img: QImage) -> None:
        fade_in(self._avatar)
        from PyQt6.QtGui import QPixmap  # noqa: PLC0415
        px = QPixmap.fromImage(img).scaled(
            self._AVATAR, self._AVATAR,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        _feed_thumb_cache.put(getattr(self, "_avatar_cache_key", ""), px)
        try:
            self._avatar._pixmap = px
            self._avatar.update()
        except RuntimeError:
            logger.debug("카드가 소멸된 뒤 아바타 콜백 도달 — 무시")

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dto.channel_url:
            self.channel_clicked.emit(self._dto.channel_url)

    def update_meta(self, dto: ChannelInfoDTO) -> None:
        """API 보강 데이터로 카드 내용을 in-place 갱신한다 (카드 재생성 없음)."""
        self._dto = dto
        self._name_lbl.setText(dto.channel_name)
        meta_parts = []
        subs = _fmt_count(dto.subscriber_count, "")
        if subs:
            meta_parts.append(f"구독자 {subs}")
        vids = _fmt_count(dto.video_count, "")
        if vids:
            meta_parts.append(f"영상 {vids}")
        self._meta_lbl.setText("  •  ".join(meta_parts))
        rel = _relative_time(dto.latest_video_published_at)
        self._latest_lbl.setText(f"최근 영상 {rel}" if rel else "")
        self._latest_lbl.setVisible(bool(rel))
        if dto.thumbnail_url and self._loader is None and not self._avatar._pixmap:
            self._start_avatar_load()

    def _apply_theme(self, tok) -> None:
        self.setStyleSheet(f"""
            QFrame {{
                background: {tok.bg_elevated};
                border: 1px solid {tok.border};
                border-radius: 8px;
            }}
            QFrame:hover {{ border-color: {tok.accent}; }}
        """)
        self._name_lbl.setStyleSheet(f"color: {tok.text_primary};")
        self._meta_lbl.setStyleSheet(f"color: {tok.text_muted};")
        self._latest_lbl.setStyleSheet(f"color: {tok.text_secondary};")


class _ChannelGrid(QWidget):
    """구독 채널 카드 그리드 — _FeedGrid와 동일한 리사이즈 reflow."""

    channel_clicked = pyqtSignal(str)

    _CARD_W = _ChannelCard._W + 16

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._layout = QGridLayout(self)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._layout.setSpacing(16)
        self._cards: list[_ChannelCard] = []
        self._cols = 0

    def minimumSizeHint(self) -> QSize:
        return QSize(self._CARD_W + 24, 0)

    def _calc_cols(self) -> int:
        return max(1, (self.width() - 24) // self._CARD_W)

    def set_channels(self, items: list[ChannelInfoDTO]) -> None:
        for card in self._cards:
            card.deleteLater()
        self._cards.clear()
        self._cols = self._calc_cols()
        for i, dto in enumerate(items):
            card = _ChannelCard(dto)
            card.channel_clicked.connect(self.channel_clicked)
            self._layout.addWidget(card, i // self._cols, i % self._cols)
            self._cards.append(card)

    def update_cards(self, dtos: list[ChannelInfoDTO]) -> None:
        """channel_url 매핑으로 기존 카드를 in-place 업데이트한다 (카드 재생성 없음)."""
        by_url = {dto.channel_url: dto for dto in dtos}
        for card in self._cards:
            dto = by_url.get(card._dto.channel_url)
            if dto:
                card.update_meta(dto)

    def _relayout(self) -> None:
        for i, card in enumerate(self._cards):
            self._layout.addWidget(card, i // self._cols, i % self._cols)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        new_cols = self._calc_cols()
        if self._cards and new_cols != self._cols:
            self._cols = new_cols
            self._relayout()


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
