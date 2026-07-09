"""Embedded video detail widget (no modal dialog).

_VideoDetailWidget is a QWidget displayed inline inside LibraryPanel.
It includes a back button, inline player, metadata, and clickable tags.
"""
from __future__ import annotations

import html
import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from PyQt6.QtCore import (
    QEvent,
    QPoint,
    QRect,
    QSize,
    QThread,
    QTime,
    QTimer,
    Qt,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import QDesktopServices, QFont, QFontMetrics, QImage
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTextBrowser,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from application.library.dtos import FailedDownloadInfoDTO, VideoDetailDTO
from gui.themes.manager import ThemeManager
from gui.widgets.video_player import InlinePlayer

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# 연관 영상 목록 (우측 사이드바) — YouTube 시청 페이지 우측 목록
# ------------------------------------------------------------------

@dataclass
class RelatedItem:
    """상세화면 우측 연관 영상 1건.

    payload: 클릭 시 재진입에 사용 — 로컬 영상이면 VideoDTO.id(UUID),
    스트리밍(피드/채널) 영상이면 FeedVideoDTO.
    """
    key: str
    title: str
    channel: str
    duration_sec: int | None
    meta_text: str
    payload: object
    thumb_path: str = ""   # 로컬 썸네일 경로
    thumb_url: str = ""    # 원격 썸네일 URL
    yt_video_id: str = ""  # 스트리밍 항목 — 피드 그리드와 썸네일 캐시(feed_*) 공유용


def _fmt_dur(sec: int | None) -> str:
    if sec is None:
        return "—"
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _fmt_pub(value: str | None) -> str:
    """업로드일 표기. yt-dlp의 YYYYMMDD 또는 ISO 문자열 모두 처리."""
    if not value:
        return ""
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}.{value[4:6]}.{value[6:]}"
    return value


# 설명·요약의 타임스탬프(MM:SS / HH:MM:SS)를 seek 링크로 변환할 때 쓰는 정규식.
_TS_RE = re.compile(r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})")

# 설명·요약 속 URL을 클릭 가능한 링크로 변환할 때 쓰는 정규식.
_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")

# 마크다운 서식 렌더링용 정규식(설명·요약 공통).
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")          # **굵게**
_BOLD2_RE = re.compile(r"__(.+?)__")             # __굵게__
_ITALIC_RE = re.compile(r"\*(?!\s)(.+?)(?<!\s)\*")  # *기울임*
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")   # # 제목
_BULLET_RE = re.compile(r"^([-*•·])\s+(.*)$")    # 불릿 목록
_NUMBERED_RE = re.compile(r"^(\d+)[.)]\s+(.*)$")  # 번호 목록


class _RelatedRow(QFrame):
    """연관 영상 1행 — 작은 썸네일 + 제목 2줄 + 채널/메타. 단일 클릭으로 선택."""

    clicked = pyqtSignal(object)   # payload
    _TW, _TH = 168, 94

    def __init__(self, item: RelatedItem, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._item = item
        self._loader = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFrameShape(QFrame.Shape.NoFrame)
        # 행이 자연 높이(썸네일 기준 ~102px)를 초과해 세로로 늘어나지 않도록 고정
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._build_ui(item)
        self._apply_theme(ThemeManager.instance().current())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)

    def _build_ui(self, item: RelatedItem) -> None:
        from gui.panels.feed_panel import _RoundedThumbLabel  # noqa: PLC0415

        row = QHBoxLayout(self)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(8)

        self._thumb = _RoundedThumbLabel(self._TW, self._TH)
        if item.duration_sec:
            self._thumb.set_duration(_fmt_dur(item.duration_sec))
        row.addWidget(self._thumb, 0, Qt.AlignmentFlag.AlignTop)

        self._cache_key = ""
        self._load_thumb(item)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)
        self._title_lbl = QLabel(item.title)
        self._title_lbl.setWordWrap(True)
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
        tf = QFont()
        tf.setPointSize(9)
        tf.setWeight(QFont.Weight.Medium)
        self._title_lbl.setFont(tf)
        # 제목은 최대 3줄까지 표시 — 채널명이 제목을 가리지 않도록 높이를 넉넉히 확보
        self._title_lbl.setMaximumHeight(QFontMetrics(tf).lineSpacing() * 3 + 4)
        text_col.addWidget(self._title_lbl)

        # 제목과 채널/메타 사이 여백 — 채널·조회수·등록시기를 행 아래쪽에 배치해
        # 제목 표시를 덜 방해하도록 한다.
        text_col.addStretch()

        cf = QFont()
        cf.setPointSize(7)   # 채널/조회수/등록시기는 제목보다 1pt 작게
        self._chan_lbl = QLabel(item.channel)
        self._chan_lbl.setFont(cf)
        text_col.addWidget(self._chan_lbl)

        self._meta_lbl = QLabel(item.meta_text)
        self._meta_lbl.setFont(cf)
        text_col.addWidget(self._meta_lbl)
        row.addLayout(text_col, 1)

    def _load_thumb(self, item: RelatedItem) -> None:
        """썸네일 로드 — 로컬 경로 우선, 없으면 피드 그리드와 동일한 캐시를 공유.

        스트리밍 항목은 ``yt_video_id`` 기준으로 피드 그리드(_FeedCard)가 쓰는
        인메모리 ``_feed_thumb_cache``·디스크 ``feed_{id}.{ext}``를 그대로 재사용해
        중복 다운로드(prefix 불일치로 인한 재다운로드·스레드 경쟁)를 막는다.
        """
        from config.settings import THUMBNAIL_DIR  # noqa: PLC0415
        from gui.panels.feed_panel import _ThumbLoader, _feed_thumb_cache  # noqa: PLC0415

        # 1) 로컬 영상 — 저장된 썸네일 경로 우선
        if item.thumb_path and Path(item.thumb_path).exists():
            img = QImage(item.thumb_path)
            if not img.isNull():
                self._thumb.set_image(img)
            return

        # 2) 스트리밍 — 피드 그리드와 캐시/디스크(prefix "feed") 공유
        vid_id = item.yt_video_id
        if vid_id:
            self._cache_key = f"{vid_id}@{self._TW}x{self._TH}"
            cached_px = _feed_thumb_cache.get(self._cache_key)
            if cached_px is not None:
                self._thumb._pixmap = cached_px
                self._thumb.update()
                return
            for ext in ("jpg", "jpeg", "webp", "png"):
                cached = THUMBNAIL_DIR / f"feed_{vid_id}.{ext}"
                if cached.exists():
                    img = QImage(str(cached))
                    if not img.isNull():
                        self._thumb.set_image(img)
                        if self._cache_key:
                            _feed_thumb_cache.put(self._cache_key, self._thumb._pixmap)
                        return

        if not item.thumb_url:
            return
        self._loader = _ThumbLoader(
            item.thumb_url, vid_id or item.key, prefix="feed",
            size=(self._TW * 2, self._TH * 2),
        )
        self._loader.loaded.connect(self._on_remote_thumb)
        self._loader.start()

    def _on_remote_thumb(self, _id: str, im: QImage) -> None:
        from gui.panels.feed_panel import _feed_thumb_cache  # noqa: PLC0415
        try:
            self._thumb.set_image(im)
            if self._cache_key:
                _feed_thumb_cache.put(self._cache_key, self._thumb._pixmap)
        except RuntimeError:
            pass  # 행 소멸 후 콜백 도달 시 무시

    def mouseReleaseEvent(self, event) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            self.clicked.emit(self._item.payload)

    def _apply_theme(self, tok) -> None:
        self.setStyleSheet(
            f"QFrame{{background:transparent;border-radius:6px;}}"
            f"QFrame:hover{{background:{tok.bg_overlay};}}"
        )
        self._title_lbl.setStyleSheet(f"color:{tok.text_primary};")
        self._chan_lbl.setStyleSheet(f"color:{tok.text_secondary};")
        self._meta_lbl.setStyleSheet(f"color:{tok.text_muted};")


class _RelatedList(QScrollArea):
    """우측 연관 영상 세로 목록."""

    item_selected = pyqtSignal(object)   # payload

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumWidth(360)
        self._inner = QWidget()
        self._layout = QVBoxLayout(self._inner)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(4)
        self._header = QLabel("연관 영상")
        hf = QFont()
        hf.setPointSize(10)
        hf.setWeight(QFont.Weight.Bold)
        self._header.setFont(hf)
        self._layout.addWidget(self._header)
        self._layout.addStretch()
        self.setWidget(self._inner)

    def set_items(self, items: list[RelatedItem]) -> None:
        # 헤더(0)·스트레치(끝)는 유지하고 사이 행들만 제거
        while self._layout.count() > 2:
            item = self._layout.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
        if not items:
            empty = QLabel("표시할 연관 영상이 없습니다.")
            empty.setStyleSheet("color:#888;padding:8px;")
            self._layout.insertWidget(1, empty)
            return
        for i, it in enumerate(items):
            row = _RelatedRow(it)
            row.clicked.connect(self.item_selected.emit)
            self._layout.insertWidget(1 + i, row)


def _t():
    return ThemeManager.instance().current()


def _fmt_size(b: int | None) -> str:
    if b is None:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b //= 1024
    return f"{b:.1f} TB"


class _TagChip(QPushButton):
    """Small pill-shaped button for a single tag.

    폭은 태그 글자 길이에 맞춰 최소화한다(Fixed 사이즈 정책 + 좁은 padding).
    """

    def __init__(self, tag_id: UUID, tag_name: str, parent=None) -> None:
        super().__init__(f"#{tag_name}", parent)
        self.tag_id = tag_id
        self.tag_name = tag_name
        self.setFlat(True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        tok = _t()
        self.setStyleSheet(
            f"QPushButton{{"
            f"  border:1px solid {tok.border_muted}; border-radius:10px;"
            f"  background:{tok.bg_elevated}; color:{tok.text_secondary};"
            f"  padding:2px 8px; font-size:8pt;"
            f"}}"
            f"QPushButton:hover{{background:{tok.bg_overlay}; color:{tok.text_primary};}}"
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)


class _FlowLayout(QLayout):
    """가로로 채우다 폭이 부족하면 다음 줄로 넘기는 표준 flow 레이아웃.

    각 아이템은 자신의 sizeHint 폭만 차지하므로 태그 칩이 글자 길이만큼만
    넓어지고, 사용 가능한 폭에 맞춰 자동으로 줄바꿈된다.
    """

    def __init__(self, parent: QWidget | None = None, spacing: int = 4) -> None:
        super().__init__(parent)
        self._items: list = []
        self.setSpacing(spacing)
        if parent is not None:
            self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(
            margins.left() + margins.right(), margins.top() + margins.bottom()
        )
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        x = rect.x() + margins.left()
        y = rect.y() + margins.top()
        line_height = 0
        spacing = self.spacing()
        eff_right = rect.right() - margins.right()
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + spacing
            if next_x - spacing > eff_right and line_height > 0:
                x = rect.x() + margins.left()
                y = y + line_height + spacing
                next_x = x + hint.width() + spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()


class _TagFlow(QWidget):
    """Wrapping flow layout of tag chips."""

    tag_clicked = pyqtSignal(object, str)  # (tag_id: UUID, tag_name: str)

    def __init__(self, tags: list[str], tag_ids: dict[str, UUID], parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = _FlowLayout(self, spacing=4)
        for name in tags:
            tid = tag_ids.get(name)
            if tid is None:
                continue
            chip = _TagChip(tid, name, self)
            chip.clicked.connect(lambda _, i=tid, n=name: self.tag_clicked.emit(i, n))
            layout.addWidget(chip)


class _AutoHeightBrowser(QTextBrowser):
    """내용 높이를 ``sizeHint``로 노출하는 QTextBrowser(설명 섹션용).

    세로 여유가 있으면 내용 높이(sizeHint)만큼만 차지해 스크롤 없이 전체가 보이고,
    공간이 부족하면 ``minimumSizeHint``까지 줄며 그때만 내부 스크롤을 쓴다. 레이아웃이
    남는 세로 공간을 이 위젯에 몰아줄 수 있어(설명이 길수록 더 넓게) 스크롤이 최소화되며,
    아래 메모의 최소 높이는 메모 위젯 자체가 고정 확보한다.
    """

    def __init__(self, min_h: int = 48, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._min_h = min_h
        self._content_h = min_h
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.document().documentLayout().documentSizeChanged.connect(
            lambda _=None: self._recalc()
        )

    def _recalc(self) -> None:
        doc = self.document()
        self._content_h = max(
            self._min_h, int(doc.size().height() + 2 * doc.documentMargin()) + 2
        )
        self.updateGeometry()

    def sizeHint(self) -> QSize:
        return QSize(super().sizeHint().width(), self._content_h)

    def minimumSizeHint(self) -> QSize:
        return QSize(super().minimumSizeHint().width(), self._min_h)

    def resizeEvent(self, event) -> None:
        self.document().setTextWidth(self.viewport().width())
        super().resizeEvent(event)
        self._recalc()


class _AutoHeightPlainEdit(QPlainTextEdit):
    """내용 줄 수에 맞춰 ``min_lines``~``max_lines`` 사이에서 높이를 조절(메모용)."""

    def __init__(
        self, min_lines: int = 1, max_lines: int = 5, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._min_lines = min_lines
        self._max_lines = max_lines
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.document().documentLayout().documentSizeChanged.connect(
            lambda _=None: self._sync_height()
        )
        self._sync_height()

    def _sync_height(self) -> None:
        line_h = self.fontMetrics().lineSpacing()
        doc_lines = self.document().size().height()  # QPlainTextEdit: 줄 수 단위
        lines = max(self._min_lines, min(int(round(doc_lines)) or 1, self._max_lines))
        doc_margin = self.document().documentMargin()
        h = int(line_h * lines + 2 * doc_margin + 2 * self.frameWidth() + 4)
        self.setFixedHeight(h)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_height()


class VideoDetailWidget(QWidget):
    """Full video detail view (embedded, not a dialog).

    Signals:
        back_requested  — user clicked the back button
        tag_filter_requested(tag_id, tag_name) — user clicked a tag chip
        tags_updated(video_id, tag_names) — user added a tag manually
    """

    back_requested          = pyqtSignal()
    tag_filter_requested    = pyqtSignal(object, str)   # (UUID, str)
    tags_updated            = pyqtSignal(object, object)  # (UUID, list[str])
    download_requested      = pyqtSignal(str, str, object)  # (url, title, DownloadSettings)
    item_selected           = pyqtSignal(object)  # 연관 영상 클릭 — payload(UUID | FeedVideoDTO)
    notes_saved             = pyqtSignal(object, str)   # (video_id, notes)
    category_path_clicked   = pyqtSignal(object)  # (category_id: UUID)
    gemini_summary_saved    = pyqtSignal(object, str)   # (video_id, summary)
    downloads_refresh_requested = pyqtSignal(object)    # video_id
    detail_refresh_requested    = pyqtSignal(object)    # video_id — 제목행 ⟳ 버튼

    # 하단 탭 인덱스
    _TAB_INFO = 0       # 설명(태그~메모)
    _TAB_SUMMARY = 1
    _TAB_FILES = 2      # 다운로드 + 클립 병합

    def __init__(self, clip_vm=None, download_vm=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._detail: VideoDetailDTO | None = None
        self._tag_add_input: QLineEdit | None = None
        self._clip_vm = clip_vm
        self._download_vm = download_vm
        self._clip_source_file: str | None = None
        self._filter_on = False
        self._streaming = False          # 스트리밍(피드/채널) 모드 여부
        self._summary_raw = ""           # 요약 원문(편집 대상) — 렌더 전 텍스트
        self._current_url = ""           # 브라우저 열기/재생 실패 폴백용
        self._active_dl_frame: QFrame | None = None
        self._active_dl_bar: QProgressBar | None = None
        self._notes_timer = QTimer(self)
        self._notes_timer.setSingleShot(True)
        self._notes_timer.setInterval(1000)
        self._notes_timer.timeout.connect(self._save_notes)
        self._gemini_worker: object | None = None  # _GeminiSummaryWorker | None
        if download_vm is not None:
            download_vm.queue_changed.connect(self._on_queue_changed)
            download_vm.history_changed.connect(self._on_history_changed)
        self._setup_skeleton()

    # ── Skeleton (built once) ──────────────────────────────────────

    def _setup_skeleton(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── 상단 행: 뒤로가기 + 카테고리 경로(브레드크럼) 같은 줄 ──────────
        top_row = QHBoxLayout()
        self._btn_back = QPushButton("‹")
        self._btn_back.setFixedSize(28, 28)
        self._btn_back.setToolTip("목록으로 (Esc)")
        self._btn_back.clicked.connect(self.back_requested.emit)
        top_row.addWidget(self._btn_back)
        self._crumb_bar = QFrame()
        self._crumb_bar.setVisible(False)
        self._crumb_layout = QHBoxLayout(self._crumb_bar)
        self._crumb_layout.setContentsMargins(6, 0, 4, 0)
        self._crumb_layout.setSpacing(2)
        top_row.addWidget(self._crumb_bar)
        top_row.addStretch()
        root.addLayout(top_row)

        sep0 = _hline()
        root.addWidget(sep0)

        # ── 메인 분할: (좌)시청 컬럼 | (우)연관 영상 ─────────────────
        main_split = QSplitter(Qt.Orientation.Horizontal)

        # ── 좌측: 플레이어 + 정보 + 탭 (YouTube 시청 페이지) ──
        left_w = QWidget()
        left_w.setMinimumWidth(360)
        left_layout = QVBoxLayout(left_w)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        # 플레이어 — 상단 고정. 16:9 자연 높이(여백 없음); 창이 넓어지면 커지고
        # 나머지 요소는 아래 탭이 남는 공간을 흡수하며 자연스럽게 따라 내려간다.
        self._player = InlinePlayer(left_w)
        self._player.playback_failed.connect(self._on_play_failed)
        self._player.download_requested.connect(self.download_requested.emit)
        left_layout.addWidget(self._player)

        # ── 제목 행 (플레이어 바로 아래): 제목 + ⟳상세갱신 + 🌐브라우저 ──
        title_row = QHBoxLayout()
        title_row.setContentsMargins(4, 2, 4, 0)
        title_row.setSpacing(4)
        self._title_lbl = QLabel("")
        self._title_lbl.setFont(_bold_font(13))
        self._title_lbl.setWordWrap(True)
        self._title_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        title_row.addWidget(self._title_lbl, 1)
        self._btn_refresh = QPushButton("⟳")
        self._btn_refresh.setFixedSize(28, 28)
        self._btn_refresh.setToolTip("상세 정보 갱신")
        self._btn_refresh.clicked.connect(self._on_refresh_detail)
        title_row.addWidget(self._btn_refresh, 0, Qt.AlignmentFlag.AlignTop)
        self._btn_browser = QPushButton("🌐")
        self._btn_browser.setFixedSize(28, 28)
        self._btn_browser.setToolTip("브라우저에서 열기")
        self._btn_browser.clicked.connect(self._on_open_browser)
        title_row.addWidget(self._btn_browser, 0, Qt.AlignmentFlag.AlignTop)
        left_layout.addLayout(title_row)

        # ── 메타 행 (채널·조회수·등록일·재생시간 + 상태) — 제목 아래 고정 ──
        self._meta_widget = QWidget()
        self._meta_layout = QVBoxLayout(self._meta_widget)
        self._meta_layout.setContentsMargins(4, 0, 4, 2)
        self._meta_layout.setSpacing(2)
        left_layout.addWidget(self._meta_widget)

        # ── 하단 탭 3개: 설명(태그~메모) · 요약 · 다운로드/클립 ──
        self._tabs = QTabWidget()

        # 탭0: 설명 — 영속 위젯 스택(태그·설명·메모). 탭 자체는 스크롤하지 않는다.
        #   · 태그: flow + 최대 3줄만 보이는 스크롤(그 이상만 스크롤)
        #   · 설명: `_AutoHeightBrowser` — 내용에 맞추되 남는 세로 공간을 최대로 써
        #           스크롤을 최소화(공간 부족 시에만 자체 스크롤)
        #   · 메모: `_AutoHeightPlainEdit` — 설명 바로 아래, 1~5줄 최소 높이 확보
        info_tab = QWidget()
        info_col = QVBoxLayout(info_tab)
        info_col.setContentsMargins(6, 6, 6, 6)
        info_col.setSpacing(4)

        self._tags_header = QLabel("<b>태그</b>")
        info_col.addWidget(self._tags_header)
        self._tags_scroll = QScrollArea()
        self._tags_scroll.setWidgetResizable(True)
        self._tags_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._tags_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._tags_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._tags_holder = QWidget()
        self._tags_holder_layout = QVBoxLayout(self._tags_holder)
        self._tags_holder_layout.setContentsMargins(0, 0, 0, 0)
        self._tags_holder_layout.setSpacing(0)
        self._tags_scroll.setWidget(self._tags_holder)
        info_col.addWidget(self._tags_scroll)

        self._tag_add_container = QWidget()
        self._tag_add_layout = QHBoxLayout(self._tag_add_container)
        self._tag_add_layout.setContentsMargins(0, 2, 0, 0)
        self._tag_add_layout.setSpacing(4)
        info_col.addWidget(self._tag_add_container)

        self._desc_header = QLabel("<b>설명</b>")
        info_col.addWidget(self._desc_header)
        self._desc_view = _AutoHeightBrowser(min_h=48)
        self._desc_view.anchorClicked.connect(self._on_summary_anchor_clicked)
        info_col.addWidget(self._desc_view)

        self._notes_header = QLabel("<b>메모</b>")
        info_col.addWidget(self._notes_header)
        self._notes_edit = _AutoHeightPlainEdit(min_lines=1, max_lines=5)
        self._notes_edit.setPlaceholderText("메모를 입력하세요…")
        self._notes_edit.textChanged.connect(self._on_notes_changed)
        info_col.addWidget(self._notes_edit)

        # 맨 아래 stretch — 설명이 내용에 맞을 때(짧을 때) 남는 공간을 흡수해 메모가
        # 설명 바로 아래에 오게 하고, 설명이 길면 stretch가 0이 되며 설명이 공간을
        # 최대로 차지한다(그때만 설명 내부 스크롤).
        info_col.addStretch(1)
        self._tabs.addTab(info_tab, "설명")

        # 탭1: 요약 (헤더 라벨 + ⟳ 아이콘 갱신 버튼 + 상태 라벨)
        summary_tab = QWidget()
        summary_layout = QVBoxLayout(summary_tab)
        summary_layout.setContentsMargins(8, 8, 8, 8)
        summary_layout.setSpacing(6)
        refresh_row = QHBoxLayout()
        refresh_row.addWidget(QLabel("<b>요약</b>"))
        edit_hint = QLabel("(더블클릭하여 편집)")
        edit_hint.setStyleSheet("font-size: 8pt; color: #888;")
        refresh_row.addWidget(edit_hint)
        refresh_row.addStretch()
        self._summary_status_lbl = QLabel("")
        self._summary_status_lbl.setStyleSheet("font-size: 9pt; color: #888;")
        refresh_row.addWidget(self._summary_status_lbl)
        self._summary_refresh_btn = QPushButton("⟳")
        self._summary_refresh_btn.setFixedSize(28, 28)
        self._summary_refresh_btn.setToolTip("Gemini 요약 갱신")
        self._summary_refresh_btn.clicked.connect(self._on_refresh_summary)
        refresh_row.addWidget(self._summary_refresh_btn)
        summary_layout.addLayout(refresh_row)

        # 표시(QTextBrowser) ↔ 편집(QPlainTextEdit) 스택.
        # 표시 위젯 더블클릭 → 편집 모드, 편집 위젯 포커스 아웃 → 저장 후 표시 모드.
        self._summary_stack = QStackedWidget()
        self._summary_edit = QTextBrowser()
        self._summary_edit.setOpenLinks(False)
        self._summary_edit.setOpenExternalLinks(False)
        self._summary_edit.setPlaceholderText(
            "Gemini AI 요약이 없습니다.\n⟳ 버튼으로 갱신하거나 더블클릭하여 직접 입력하세요."
        )
        self._summary_edit.anchorClicked.connect(self._on_summary_anchor_clicked)
        self._summary_stack.addWidget(self._summary_edit)      # index 0: 표시
        self._summary_editor = QPlainTextEdit()
        self._summary_editor.setPlaceholderText("요약 내용을 입력하세요…")
        self._summary_stack.addWidget(self._summary_editor)    # index 1: 편집
        summary_layout.addWidget(self._summary_stack)
        self._tabs.addTab(_wrap(summary_tab), "요약")

        # 탭2: 다운로드(상단) + 클립(하단) 병합 — 수직 스플리터
        files_split = QSplitter(Qt.Orientation.Vertical)
        self._dl_tab = QWidget()
        files_split.addWidget(self._dl_tab)
        self._clip_tab_widget = QWidget()
        self._clip_tab_layout = QVBoxLayout(self._clip_tab_widget)
        self._clip_tab_layout.setContentsMargins(8, 8, 8, 8)
        files_split.addWidget(self._clip_tab_widget)
        files_split.setStretchFactor(0, 1)   # 다운로드 우선
        files_split.setStretchFactor(1, 1)
        self._tabs.addTab(_wrap(files_split), "다운로드 / 클립")

        self._tabs.currentChanged.connect(self._on_tab_changed)
        left_layout.addWidget(self._tabs, stretch=1)

        main_split.addWidget(left_w)

        # ── 우측: 연관 영상 목록 ──
        self._related = _RelatedList()
        self._related.item_selected.connect(self.item_selected.emit)
        main_split.addWidget(self._related)

        main_split.setStretchFactor(0, 3)
        main_split.setStretchFactor(1, 1)
        main_split.setSizes([720, 360])
        root.addWidget(main_split, stretch=1)

    # ── 이벤트 필터 (마우스 뒤로가기 버튼 감지) ───────────────────────

    def showEvent(self, event) -> None:
        if not self._filter_on:
            app = QApplication.instance()
            if app:
                app.installEventFilter(self)
                self._filter_on = True
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        if self._filter_on:
            app = QApplication.instance()
            if app:
                try:
                    app.removeEventFilter(self)
                except RuntimeError:
                    pass
            self._filter_on = False
        super().hideEvent(event)

    def eventFilter(self, obj, event) -> bool:
        et = event.type()
        if et == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.BackButton:
                self.back_requested.emit()
                return True
        elif et == QEvent.Type.MouseButtonDblClick:
            # 요약 표시 영역 더블클릭 → 편집 모드 진입(로컬 영상만)
            if (
                obj is self._summary_edit.viewport()
                and not self._streaming
                and self._detail is not None
            ):
                self._enter_summary_edit()
                return True
        elif et == QEvent.Type.FocusOut:
            # 요약 편집기 포커스 아웃 → 저장 후 표시 모드 복귀
            if obj is self._summary_editor:
                self._commit_summary_edit()
        return False

    # ── Populate ───────────────────────────────────────────────────

    def load(
        self,
        detail: VideoDetailDTO,
        tag_ids: dict[str, UUID],
        resume_ms: int = 0,
        related: list[RelatedItem] | None = None,
        category_path: list[tuple] | None = None,
    ) -> None:
        """라이브러리(로컬) 영상 상세를 채운다. resume_ms>0이면 이어서 재생."""
        self._detail = detail
        self._tag_ids = tag_ids
        self._streaming = False
        self._current_url = detail.url
        self._set_crumb_path(category_path)

        self._player.load(detail.url, detail.downloads, resume_ms=resume_ms)
        if resume_ms > 0:
            QTimer.singleShot(150, self._player.play)

        self._build_info(
            title=detail.title,
            channel=detail.channel_name,
            duration_sec=detail.duration_sec,
            published_at=detail.published_at,
            view_count=detail.view_count,
            favorite=detail.favorite,
            watched=detail.watched,
            description=detail.description,
            tags=list(detail.tags),
            tag_ids=tag_ids,
            allow_tag_edit=True,
        )

        # 하단 탭 — 모두 활성
        self._set_tabs_enabled(True)
        self._build_downloads_tab(detail.downloads, detail.failed_downloads)
        self._notes_edit.setReadOnly(False)
        self._notes_edit.blockSignals(True)
        self._notes_edit.setPlainText(detail.notes or "")
        self._notes_edit.blockSignals(False)
        self._summary_raw = detail.gemini_summary or ""
        self._summary_edit.setHtml(self._render_timestamped_html(self._summary_raw))
        self._summary_stack.setCurrentWidget(self._summary_edit)
        self._summary_status_lbl.setText("")
        self._summary_refresh_btn.setEnabled(True)

        # 클립 탭 — 로컬 파일 탐색 및 탭 초기화
        self._clip_source_file = None
        for dl in detail.downloads:
            if dl.file_path and Path(dl.file_path).exists():
                self._clip_source_file = dl.file_path
                break
        self._build_clip_tab()
        # 병합 탭이 기본 노출되므로 클립을 즉시 로드(지연 로드 불필요)
        if self._clip_vm is not None:
            self._clip_vm.load_clips(detail.id)

        self._btn_refresh.setEnabled(True)
        self.set_related(related or [])

    def load_stream(self, feed, related: list[RelatedItem] | None = None) -> None:
        """스트리밍(구독 피드/채널) 영상 상세 — URL 직접 재생.

        feed: FeedVideoDTO. 로컬 항목이 아니므로 클립/메모/태그 편집은 비활성.
        """
        self._detail = None
        self._tag_ids = {}
        self._streaming = True
        self._current_url = feed.url
        self._set_crumb_path(None)

        self._player.load(feed.url, [])
        QTimer.singleShot(150, self._player.play)

        self._build_info(
            title=feed.title,
            channel=feed.channel_name,
            duration_sec=feed.duration_sec,
            published_at=_fmt_pub(feed.published_at),
            view_count=feed.view_count,
            favorite=False,
            watched=False,
            description="",
            tags=[],
            tag_ids={},
            allow_tag_edit=False,
        )

        # 하단 탭 — 메모/클립 비활성, 다운로드 안내만
        self._set_tabs_enabled(False)
        self._build_downloads_tab([], [])
        self._notes_edit.setReadOnly(True)
        self._notes_edit.blockSignals(True)
        self._notes_edit.setPlainText("스트리밍 영상입니다. 다운로드 후 메모/클립을 사용할 수 있습니다.")
        self._notes_edit.blockSignals(False)
        self._clip_source_file = None
        _clear_layout(self._clip_tab_layout)
        info = QLabel("스트리밍 영상은 클립을 추출할 수 없습니다.\n다운로드 후 다시 시도해 주세요.")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.setStyleSheet("color:#888; font-size:10pt; padding:24px;")
        self._clip_tab_layout.addWidget(info)
        self._clip_tab_layout.addStretch()
        self._tabs.setCurrentIndex(self._TAB_FILES)

        self._btn_refresh.setEnabled(False)  # 스트리밍은 안정적 id 없음
        self.set_related(related or [])

    # ── 정보 영역 (제목·메타·태그·챕터·설명) ─────────────────────────

    def _build_info(
        self,
        *,
        title: str,
        channel: str,
        duration_sec: int | None,
        published_at: str | None,
        view_count: int | None,
        favorite: bool,
        watched: bool,
        description: str | None,
        tags: list[str],
        tag_ids: dict[str, UUID],
        allow_tag_edit: bool,
    ) -> None:
        _clear_layout(self._meta_layout)

        # 제목은 플레이어 아래 고정 행(_title_lbl)에 표시
        self._title_lbl.setText(title)

        # ── 제목 아래 메타 행: 채널 · 조회수 · 등록일 · 재생시간 (+ 상태) ──
        meta_parts = []
        if channel:
            meta_parts.append(channel)
        if view_count is not None:
            meta_parts.append(f"조회수 {view_count:,}회")
        if published_at:
            meta_parts.append(published_at)
        if duration_sec is not None:
            meta_parts.append(_fmt_dur(duration_sec))
        if meta_parts:
            meta_lbl = QLabel("  ·  ".join(meta_parts))
            meta_lbl.setWordWrap(True)
            meta_lbl.setStyleSheet(f"color:{_t().text_secondary};")
            self._meta_layout.addWidget(meta_lbl)

        statuses = []
        if watched:
            statuses.append("✓ 시청완료")
        if favorite:
            statuses.append("★ 즐겨찾기")
        if statuses:
            st_lbl = QLabel("  ".join(statuses))
            st_lbl.setStyleSheet(f"color:{_t().text_muted};")
            self._meta_layout.addWidget(st_lbl)

        # ── "설명" 탭 내용: 태그 · 설명 (영속 위젯을 갱신) ──
        # 태그 — 글자 길이만큼의 칩이 폭에 맞춰 줄바꿈. 최대 3줄까지만 보이고 그 이상은
        # 스크롤(3줄 미만이면 내용 높이에 맞춤).
        _clear_layout(self._tags_holder_layout)
        has_tags = bool(tags)
        self._tags_header.setVisible(has_tags)
        self._tags_scroll.setVisible(has_tags)
        if has_tags:
            flow = _TagFlow(tags, tag_ids)
            flow.tag_clicked.connect(self.tag_filter_requested.emit)
            self._tags_holder_layout.addWidget(flow)
            f8 = QFont()
            f8.setPointSize(8)
            row_h = QFontMetrics(f8).height() + 12   # 칩 한 줄 대략 높이
            self._fit_tags_scroll(flow, row_h * 3 + 8)   # 최대 3줄

        # 수동 태그 추가 (로컬 영상만)
        _clear_layout(self._tag_add_layout)
        self._tag_add_input = None
        self._tag_add_container.setVisible(allow_tag_edit)
        if allow_tag_edit:
            self._tag_add_input = QLineEdit()
            self._tag_add_input.setPlaceholderText("태그 추가... (쉼표로 구분)")
            self._tag_add_input.setStyleSheet("font-size:8pt;")
            self._tag_add_input.returnPressed.connect(self._on_add_tag)
            self._tag_add_layout.addWidget(self._tag_add_input, 1)
            add_btn = QPushButton("+")
            add_btn.setFixedSize(24, 24)
            add_btn.setStyleSheet("font-size:11pt; font-weight:bold;")
            add_btn.clicked.connect(self._on_add_tag)
            self._tag_add_layout.addWidget(add_btn)

        # 설명 — 마크다운 서식 + 타임스탬프 seek 링크 렌더링. 높이는 위 _AutoHeightBrowser가
        # 가용 공간을 최대로 활용해 자동 조절(스크롤 최소화). 별도 "챕터" 섹션은 설명 속
        # 타임라인과 중복되므로 설명 하나로 병합한다.
        has_desc = bool(description)
        self._desc_header.setVisible(has_desc)
        self._desc_view.setVisible(has_desc)
        if has_desc:
            self._desc_view.setHtml(self._render_timestamped_html(description))

    def _fit_tags_scroll(self, flow: QWidget, cap: int) -> None:
        """태그 스크롤 높이를 내용(flow) 높이에 맞추되 최대 ``cap``(3줄)로 제한."""
        def _apply() -> None:
            try:
                w = self._tags_scroll.viewport().width()
                fh = (
                    flow.layout().heightForWidth(w)
                    if w > 4 else flow.sizeHint().height()
                )
            except RuntimeError:
                return
            self._tags_scroll.setFixedHeight(min(max(fh + 4, 26), cap))

        _apply()
        # 최초 표시 시 viewport 폭이 확정된 뒤 한 번 더 맞춘다.
        QTimer.singleShot(0, _apply)

    def _render_timestamped_html(self, text: str) -> str:
        """요약/설명 텍스트를 마크다운 서식 + 링크가 적용된 HTML로 렌더링한다.

        - `# `~`###### ` → 제목, `**굵게**`/`__굵게__` → 굵게, `*기울임*` → 기울임
        - `- `/`* `/`• `/`· ` → 불릿, `1.`/`1)` → 번호 목록, 선행 공백 → 들여쓰기
        - `MM:SS`·`HH:MM:SS` → `seek:` 링크, URL → 링크
          (`_on_summary_anchor_clicked`가 seek는 재생 위치 이동, URL은 브라우저로 라우팅)
        """
        if not text:
            return ""
        accent = _t().accent

        def _link(m: re.Match) -> str:
            h = int(m.group(1)) if m.group(1) else 0
            sec = h * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            return (
                f'<a href="seek:{sec}" style="color:{accent}; '
                f'text-decoration:none; font-weight:bold;">{m.group(0)}</a>'
            )

        def _emphasis(escaped: str) -> str:
            # escape된 텍스트에 굵게/기울임/타임스탬프 서식을 적용(순서 중요:
            # **/__ 먼저 소비 후 남은 * 를 기울임 처리, 마지막에 타임스탬프 링크).
            escaped = _BOLD_RE.sub(r"<b>\1</b>", escaped)
            escaped = _BOLD2_RE.sub(r"<b>\1</b>", escaped)
            escaped = _ITALIC_RE.sub(r"<i>\1</i>", escaped)
            return _TS_RE.sub(_link, escaped)

        def _inline(seg: str) -> str:
            # URL은 escape/emphasis 전에 분리해 링크로 보존, 나머지 구간만 서식 적용.
            out: list[str] = []
            pos = 0
            for m in _URL_RE.finditer(seg):
                out.append(_emphasis(html.escape(seg[pos:m.start()])))
                url = m.group(0)
                out.append(
                    f'<a href="{html.escape(url, quote=True)}" '
                    f'style="color:{accent};">{html.escape(url)}</a>'
                )
                pos = m.end()
            out.append(_emphasis(html.escape(seg[pos:])))
            return "".join(out)

        def _render_line(line: str) -> str:
            stripped = line.lstrip(" \t")
            if not stripped:
                return '<div style="font-size:4pt;">&nbsp;</div>'   # 빈 줄 간격
            indent = len(line) - len(stripped)
            base = sum(4 if c == "\t" else 1 for c in line[:indent]) * 7  # 들여쓰기 px

            hm = _HEADING_RE.match(stripped)
            if hm:
                size = {1: "13pt", 2: "12pt", 3: "11pt"}.get(len(hm.group(1)), "10pt")
                return (
                    f'<div style="margin:6px 0 2px {base}px; font-weight:bold; '
                    f'font-size:{size};">{_inline(hm.group(2))}</div>'
                )
            bm = _BULLET_RE.match(stripped)
            if bm:
                return (
                    f'<div style="margin-left:{base + 14}px;">'
                    f'•&nbsp;{_inline(bm.group(2))}</div>'
                )
            nm = _NUMBERED_RE.match(stripped)
            if nm:
                return (
                    f'<div style="margin-left:{base + 16}px;">'
                    f'{nm.group(1)}.&nbsp;{_inline(nm.group(2))}</div>'
                )
            if base:
                return f'<div style="margin-left:{base}px;">{_inline(stripped)}</div>'
            return f"<div>{_inline(stripped)}</div>"

        return "".join(_render_line(line) for line in text.splitlines())

    def _on_summary_anchor_clicked(self, url: QUrl) -> None:
        """설명/요약 내 링크 클릭을 라우팅한다.

        `seek:` 링크는 재생 위치를 이동하고, http/https URL은 기본 브라우저로 연다.
        """
        s = url.toString()
        if s.startswith(("http://", "https://")):
            QDesktopServices.openUrl(url)
            return
        if not s.startswith("seek:"):
            return
        try:
            sec = int(s[len("seek:"):])
        except ValueError:
            return
        self._player.seek_to_ms(sec * 1000)
        if not self._player.is_playing():
            self._player.play()

    @staticmethod
    def _strip_ansi(text: str) -> str:
        import re
        return re.sub(r'\x1b\[[0-9;]*m', '', text)

    def _on_queue_changed(self) -> None:
        """다운로드 진행 중 progress bar 실시간 갱신."""
        if not self._download_vm or not self._current_url:
            return
        active_job = next(
            (j for j in self._download_vm.queue if j.url == self._current_url),
            None,
        )
        if self._active_dl_bar is None or self._active_dl_frame is None:
            return
        if active_job:
            pct = int(active_job.progress.percent)
            self._active_dl_bar.setValue(pct)
            speed = active_job.progress.speed_formatted()
            self._active_dl_bar.setFormat(f"{pct}%  {speed}")
            self._active_dl_frame.setVisible(True)
        else:
            self._active_dl_frame.setVisible(False)

    def _build_downloads_tab(
        self,
        downloads: list,
        failed_downloads: list[FailedDownloadInfoDTO] | None = None,
    ) -> None:
        if self._dl_tab.layout():
            _clear_layout(self._dl_tab.layout())
            dl_layout = self._dl_tab.layout()
        else:
            dl_layout = QVBoxLayout(self._dl_tab)
        dl_layout.setContentsMargins(8, 8, 8, 4)
        dl_layout.setSpacing(8)

        # ── 진행 중 다운로드 섹션 (최상단, 조건부 표시) ──────────────
        active_frame = QFrame()
        active_row = QHBoxLayout(active_frame)
        active_row.setContentsMargins(0, 0, 0, 4)
        active_row.setSpacing(8)
        active_lbl = QLabel("⬇ 다운로드 중")
        active_lbl.setStyleSheet("font-size:9pt; font-weight:bold;")
        active_bar = QProgressBar()
        active_bar.setRange(0, 100)
        active_bar.setTextVisible(True)
        active_bar.setMaximumHeight(18)
        active_row.addWidget(active_lbl)
        active_row.addWidget(active_bar, 1)
        dl_layout.addWidget(active_frame)
        self._active_dl_frame = active_frame
        self._active_dl_bar = active_bar

        # 현재 진행 중 여부 확인
        if self._download_vm and self._current_url:
            active_job = next(
                (j for j in self._download_vm.queue if j.url == self._current_url),
                None,
            )
            if active_job:
                pct = int(active_job.progress.percent)
                active_bar.setValue(pct)
                active_bar.setFormat(f"{pct}%  {active_job.progress.speed_formatted()}")
                active_frame.setVisible(True)
            else:
                active_frame.setVisible(False)
        else:
            active_frame.setVisible(False)

        if downloads:
            from PyQt6.QtWidgets import QGridLayout  # noqa: PLC0415
            # 폴더 열기 버튼 — 첫 번째 존재하는 파일의 폴더 기준, 우측 정렬
            first_folder = next(
                (str(Path(dl.file_path).parent)
                 for dl in downloads
                 if dl.file_path and Path(dl.file_path).exists()),
                None,
            )
            hdr_row = QHBoxLayout()
            hdr_row.addStretch()
            if first_folder:
                folder_btn = QPushButton("폴더 열기")
                folder_btn.setFixedHeight(26)
                folder_btn.setToolTip("파일 위치를 탐색기에서 열기")
                folder_btn.clicked.connect(lambda _, f=first_folder: _open_folder(f))
                hdr_row.addWidget(folder_btn)
            dl_layout.addLayout(hdr_row)

            # 표 그리드: 품질 | 포맷 | 크기 | 파일 열기
            grid_w = QWidget()
            grid = QGridLayout(grid_w)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(6)
            grid.setColumnStretch(3, 1)

            tok = _t()
            for row_idx, dl in enumerate(downloads):
                fp = Path(dl.file_path) if dl.file_path else None
                exists = fp is not None and fp.exists()
                size_bytes = fp.stat().st_size if exists else dl.file_size_bytes

                quality = dl.quality or "—"
                fmt = dl.fmt.upper() if dl.fmt else "—"

                for col_idx, (text, style) in enumerate([
                    (quality, f"color:{tok.text_primary}; font-size:9pt;"),
                    (fmt,     f"color:{tok.text_secondary}; font-size:9pt;"),
                    (_fmt_size(size_bytes), f"color:{tok.text_secondary}; font-size:9pt;"),
                ]):
                    lbl = QLabel(text)
                    lbl.setStyleSheet(style)
                    grid.addWidget(lbl, row_idx, col_idx)

                if exists:
                    open_btn = QPushButton("파일 열기")
                    open_btn.setFixedHeight(24)
                    open_btn.clicked.connect(lambda _, p=dl.file_path: _open_file(p))
                    grid.addWidget(open_btn, row_idx, 3, Qt.AlignmentFlag.AlignLeft)
                else:
                    na_lbl = QLabel("파일 없음")
                    na_lbl.setStyleSheet("color:#f44336; font-size:8pt;")
                    grid.addWidget(na_lbl, row_idx, 3)

            dl_layout.addWidget(grid_w)
        else:
            dl_layout.addWidget(QLabel("다운로드된 파일이 없습니다."))

        # 실패 이력 섹션
        if failed_downloads:
            fail_hdr = QLabel("다운로드 실패 이력")
            fail_hdr.setStyleSheet(
                "color:#f44336; font-weight:bold; font-size:9pt; margin-top:8px;"
            )
            dl_layout.addWidget(fail_hdr)
            for fd in failed_downloads:
                err_text = self._strip_ansi(fd.error_msg)
                date_str = (
                    fd.created_at.astimezone(tz=None).strftime("%Y-%m-%d %H:%M")
                    if fd.created_at else ""
                )
                row = QFrame()
                row.setStyleSheet(
                    "QFrame { border-left: 3px solid #f44336;"
                    " background: transparent; }"
                )
                rl = QVBoxLayout(row)
                rl.setContentsMargins(10, 4, 10, 6)
                rl.setSpacing(2)
                if date_str:
                    date_lbl = QLabel(date_str)
                    date_lbl.setStyleSheet("color:#888; font-size:8pt;")
                    rl.addWidget(date_lbl)
                err_lbl = QLabel(err_text)
                err_lbl.setWordWrap(True)
                err_lbl.setStyleSheet("color:#f44336; font-size:8pt;")
                rl.addWidget(err_lbl)
                dl_layout.addWidget(row)

        dl_layout.addStretch()

    def _set_tabs_enabled(self, local: bool) -> None:
        """스트리밍 모드면 요약 탭 비활성(메모·클립은 병합 탭/스크롤로 이동)."""
        self._tabs.setTabEnabled(self._TAB_SUMMARY, local)

    # ── 연관 영상 ──────────────────────────────────────────────────

    def set_related(self, items: list[RelatedItem]) -> None:
        self._related.set_items(items)

    # ── Clip tab ───────────────────────────────────────────────────

    def _build_clip_tab(self) -> None:
        # 오류3 방지: 레이아웃 삭제 전에 시그널 먼저 해제
        if self._clip_vm is not None:
            try:
                self._clip_vm.clips_changed.disconnect(self._refresh_clip_list)
            except Exception:
                logger.debug("클립 시그널 미연결 상태 — 첫 빌드 시 정상")
        _clear_layout(self._clip_tab_layout)

        if self._clip_vm is None or self._detail is None:
            self._clip_tab_layout.addWidget(QLabel("클립 기능을 사용할 수 없습니다."))
            self._clip_tab_layout.addStretch()
            return

        if not self._clip_source_file:
            info = QLabel("로컬 파일이 있어야 클립 추출이 가능합니다.\n다운로드 후 다시 시도해 주세요.")
            info.setAlignment(Qt.AlignmentFlag.AlignCenter)
            info.setStyleSheet("color: #888; font-size: 10pt; padding: 24px;")
            self._clip_tab_layout.addWidget(info)
            self._clip_tab_layout.addStretch()
            return

        # ── 구간 설정 영역 ──────────────────────────────────────────
        range_grp = QGroupBox("구간 설정")
        range_layout = QVBoxLayout(range_grp)
        # 상단 여백을 넉넉히 둬 QGroupBox 제목이 첫 행(시작 시간)과 겹치지 않게 한다.
        range_layout.setContentsMargins(10, 18, 10, 10)
        range_layout.setSpacing(8)

        time_row = QHBoxLayout()
        time_row.setSpacing(12)
        start_lbl = QLabel("시작")
        start_lbl.setFixedWidth(30)
        self._start_edit = QTimeEdit(QTime(0, 0, 0))
        self._start_edit.setDisplayFormat("HH:mm:ss")
        end_lbl = QLabel("끝")
        end_lbl.setFixedWidth(20)
        self._end_edit = QTimeEdit(QTime(0, 0, 0))
        self._end_edit.setDisplayFormat("HH:mm:ss")
        time_row.addWidget(start_lbl)
        time_row.addWidget(self._start_edit)
        time_row.addWidget(end_lbl)
        time_row.addWidget(self._end_edit)
        time_row.addStretch()
        range_layout.addLayout(time_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        set_start_btn = QPushButton("현재 위치 → 시작")
        set_start_btn.clicked.connect(self._set_start_from_player)
        set_end_btn = QPushButton("현재 위치 → 끝")
        set_end_btn.clicked.connect(self._set_end_from_player)
        btn_row.addWidget(set_start_btn)
        btn_row.addWidget(set_end_btn)
        btn_row.addStretch()
        range_layout.addLayout(btn_row)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_row.addWidget(QLabel("클립 제목"))
        self._clip_title_edit = QLineEdit()
        self._clip_title_edit.setPlaceholderText("클립 제목 입력…")
        title_row.addWidget(self._clip_title_edit, 1)
        range_layout.addLayout(title_row)

        extract_btn = QPushButton("클립 추출")
        extract_btn.setFixedHeight(28)
        extract_btn.clicked.connect(self._on_extract_clip)
        range_layout.addWidget(extract_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self._clip_status_lbl = QLabel("")
        self._clip_status_lbl.setStyleSheet("font-size: 9pt; color: #888;")
        range_layout.addWidget(self._clip_status_lbl)

        self._clip_tab_layout.addWidget(range_grp)

        # ── 클립 목록 ──────────────────────────────────────────────
        list_grp = QGroupBox("추출된 클립 목록")
        self._clip_list_layout = QVBoxLayout(list_grp)
        # 제목이 목록 첫 항목("추출된 클립이 없습니다.")과 겹치지 않게 상단 여백 확보.
        self._clip_list_layout.setContentsMargins(10, 18, 10, 10)
        self._clip_tab_layout.addWidget(list_grp)

        self._clip_tab_layout.addStretch()

        self._clip_vm.clips_changed.connect(self._refresh_clip_list)

    def _set_start_from_player(self) -> None:
        ms = self._player.position_ms
        t = QTime(0, 0, 0).addMSecs(ms)
        self._start_edit.setTime(t)

    def _set_end_from_player(self) -> None:
        ms = self._player.position_ms
        t = QTime(0, 0, 0).addMSecs(ms)
        self._end_edit.setTime(t)

    def _on_extract_clip(self) -> None:
        if self._clip_vm is None or self._detail is None or not self._clip_source_file:
            return
        start_t = self._start_edit.time()
        end_t = self._end_edit.time()
        start_sec = start_t.hour() * 3600 + start_t.minute() * 60 + start_t.second()
        end_sec = end_t.hour() * 3600 + end_t.minute() * 60 + end_t.second()
        if end_sec <= start_sec:
            self._clip_status_lbl.setText("끝 시간은 시작 시간보다 커야 합니다.")
            return
        title = self._clip_title_edit.text().strip() or f"clip_{start_sec}_{end_sec}"
        self._clip_status_lbl.setText("추출 중…")
        self._clip_vm.extract_clip(
            self._detail.id,
            self._clip_source_file,
            title,
            float(start_sec),
            float(end_sec),
        )

    def _set_crumb_path(self, path: list[tuple] | None) -> None:
        """브레드크럼 바를 path[(이름, category_id), ...]로 재구성한다."""
        while self._crumb_layout.count():
            item = self._crumb_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not path:
            self._crumb_bar.setVisible(False)
            return
        for i, (name, cat_id) in enumerate(path):
            if i > 0:
                sep = QLabel(" ›")
                sep.setStyleSheet("color:#888; font-size:9pt;")
                self._crumb_layout.addWidget(sep)
            btn = QPushButton(name)
            btn.setFlat(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton { color:#5a9fd4; font-size:9pt; border:none; padding:0;"
                " text-decoration:underline; background:transparent; }"
                " QPushButton:hover { color:#8dc4f0; }"
            )
            btn.clicked.connect(lambda _, cid=cat_id: self.category_path_clicked.emit(cid))
            self._crumb_layout.addWidget(btn)
        self._crumb_layout.addStretch()
        self._crumb_bar.setVisible(True)

    def _on_notes_changed(self) -> None:
        if not self._streaming and self._detail is not None:
            self._notes_timer.start()

    def _save_notes(self) -> None:
        if self._detail is None or self._streaming:
            return
        self.notes_saved.emit(self._detail.id, self._notes_edit.toPlainText())

    def _on_tab_changed(self, index: int) -> None:
        if (
            index == self._TAB_FILES
            and not self._streaming
            and self._clip_vm is not None
            and self._detail is not None
        ):
            self._clip_vm.load_clips(self._detail.id)

    def _refresh_clip_list(self) -> None:
        if not hasattr(self, "_clip_list_layout"):
            return
        try:
            _clear_layout(self._clip_list_layout)
        except RuntimeError:
            logger.debug("_clip_list_layout 이미 삭제됨 — 갱신 생략")
            return
        self._clip_status_lbl.setText("")
        clips = self._clip_vm.clips if self._clip_vm else []
        if not clips:
            self._clip_list_layout.addWidget(QLabel("추출된 클립이 없습니다."))
            return
        for clip in clips:
            row = QHBoxLayout()
            dur = clip.end_sec - clip.start_sec
            m, s = divmod(int(dur), 60)
            size_str = "—"
            fp = Path(clip.file_path) if clip.file_path else None
            if fp and fp.exists():
                size_str = _fmt_size(fp.stat().st_size)
            title_lbl = QLabel(clip.title)
            title_lbl.setMinimumWidth(120)
            dur_lbl = QLabel(f"{m}:{s:02d}")
            dur_lbl.setFixedWidth(48)
            size_lbl = QLabel(size_str)
            size_lbl.setFixedWidth(72)
            folder_btn = QPushButton("📂")
            folder_btn.setFixedSize(28, 28)
            folder_btn.setToolTip("파일 위치 열기")
            if fp and fp.exists():
                folder_btn.clicked.connect(lambda _, p=str(fp): _open_folder(p))
            else:
                folder_btn.setEnabled(False)
            del_btn = QPushButton("삭제")
            del_btn.setFixedWidth(48)
            cid = clip.id
            del_btn.clicked.connect(lambda _, i=cid: self._clip_vm.delete_clip(i, delete_file=True))
            row.addWidget(title_lbl, 1)
            row.addWidget(dur_lbl)
            row.addWidget(size_lbl)
            row.addWidget(folder_btn)
            row.addWidget(del_btn)
            container = QWidget()
            container.setLayout(row)
            self._clip_list_layout.addWidget(container)

    # ── Actions ────────────────────────────────────────────────────

    def _on_add_tag(self) -> None:
        if self._tag_add_input is None or self._detail is None:
            return
        text = self._tag_add_input.text().strip()
        if not text:
            return
        new_names = [
            t.strip().lstrip("#")
            for part in text.split(",")
            for t in part.split()
            if t.strip().lstrip("#")
        ]
        if not new_names:
            return
        merged = list(dict.fromkeys(list(self._detail.tags) + new_names))
        self.tags_updated.emit(self._detail.id, merged)
        self._tag_add_input.clear()

    def _on_open_browser(self) -> None:
        if self._current_url:
            QDesktopServices.openUrl(QUrl(self._current_url))

    def _on_refresh_detail(self) -> None:
        """제목행 ⟳ — 현재 상세 정보를 부모에 재조회 요청(제자리 갱신)."""
        if self._detail is not None and not self._streaming:
            self.detail_refresh_requested.emit(self._detail.id)

    def current_detail_id(self):
        """현재 표시 중인 로컬 영상 id(스트리밍/미표시면 None)."""
        return self._detail.id if self._detail is not None else None

    def set_refresh_busy(self, busy: bool) -> None:
        """상세 정보 갱신(⟳) 진행 표시 — 버튼 비활성 + 툴팁 변경."""
        self._btn_refresh.setEnabled(not busy)
        self._btn_refresh.setToolTip("갱신 중… (YouTube에서 정보 가져오는 중)" if busy else "상세 정보 갱신")

    def _on_play_failed(self, err: str) -> None:
        if self._current_url:
            QDesktopServices.openUrl(QUrl(self._current_url))

    def stop_player(self) -> None:
        self._player.stop()

    # ── 다운로드 히스토리 갱신 (오류2) ────────────────────────────────

    def _on_history_changed(self) -> None:
        """다운로드 완료/실패 시 호출 — 상세화면이 열려있으면 부모에 갱신 요청."""
        if self._detail is not None and not self._streaming:
            self.downloads_refresh_requested.emit(self._detail.id)

    def refresh_downloads(self, downloads: list, failed_downloads: list) -> None:
        """다운로드 파일 탭만 새로 그린다."""
        self._build_downloads_tab(downloads, failed_downloads)

    # ── Gemini 요약 갱신 (오류4) ──────────────────────────────────────

    def _on_refresh_summary(self) -> None:
        if self._detail is None or self._streaming:
            return
        self._summary_refresh_btn.setEnabled(False)
        self._summary_status_lbl.setText("추출 중…")
        worker = _GeminiSummaryWorker(self._detail.url, self._detail.id, self)
        worker.done.connect(self._on_gemini_done)
        worker.finished.connect(worker.deleteLater)
        worker.start()
        self._gemini_worker = worker

    def _on_gemini_done(self, video_id, summary: str) -> None:
        # 요청 시점의 영상과 현재 표시 중인 영상이 다르면(사용자가 다른 영상으로
        # 이동) 화면은 건드리지 않는다. 단, 유효한 요약은 원래 요청 영상 id로
        # 저장해 데이터 정합을 유지한다.
        is_current = self._detail is not None and video_id == self._detail.id
        if summary:
            self.gemini_summary_saved.emit(video_id, summary)
        if not is_current:
            return
        self._summary_refresh_btn.setEnabled(True)
        if summary:
            self._summary_raw = summary
            self._summary_edit.setHtml(self._render_timestamped_html(summary))
            self._summary_stack.setCurrentWidget(self._summary_edit)
            self._summary_status_lbl.setText("")
        else:
            self._summary_status_lbl.setText(
                "요약 추출 실패 — 설정에서 브라우저/프로필을 선택하거나 쿠키 파일을 등록하세요"
            )

    # ── 요약 편집 (더블클릭) ──────────────────────────────────────────

    def _enter_summary_edit(self) -> None:
        """요약 표시 영역 더블클릭 시 편집 모드로 전환한다(로컬 영상만)."""
        if self._streaming or self._detail is None:
            return
        self._summary_editor.setPlainText(self._summary_raw)
        self._summary_stack.setCurrentWidget(self._summary_editor)
        self._summary_editor.setFocus()

    def _commit_summary_edit(self) -> None:
        """편집 내용을 저장하고 표시 모드로 복귀한다.

        내용이 바뀌었으면 렌더링을 갱신하고 `gemini_summary_saved`로 영속화한다.
        """
        if self._summary_stack.currentWidget() is not self._summary_editor:
            return
        text = self._summary_editor.toPlainText()
        self._summary_stack.setCurrentWidget(self._summary_edit)
        if text != self._summary_raw:
            self._summary_raw = text
            self._summary_edit.setHtml(self._render_timestamped_html(text))
            if self._detail is not None and not self._streaming:
                self.gemini_summary_saved.emit(self._detail.id, text)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

class _GeminiSummaryWorker(QThread):
    """백그라운드에서 Gemini AI 요약을 추출한다."""

    done = pyqtSignal(object, str)  # (video_id, 요약 텍스트) — 실패 시 빈 문자열

    def __init__(self, url: str, video_id, parent=None) -> None:
        super().__init__(parent)
        self._url = url
        self._video_id = video_id

    def run(self) -> None:
        try:
            from infrastructure.browser.gemini_extractor import GeminiExtractor  # noqa: PLC0415
            result = GeminiExtractor().extract(self._url)
            self.done.emit(self._video_id, result or "")
        except Exception:
            logger.exception("Gemini 요약 워커 실패")
            self.done.emit(self._video_id, "")


def _bold_font(size: int) -> QFont:
    f = QFont()
    f.setPointSize(size)
    f.setBold(True)
    return f


def _hline() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setFrameShadow(QFrame.Shadow.Sunken)
    return sep


def _wrap(widget: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(widget)
    area.setFrameShape(QFrame.Shape.NoFrame)
    return area


def _clear_layout(layout) -> None:
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def _open_folder(file_path: str) -> None:
    p = Path(file_path)
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(p)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(p)])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.parent)))


def _open_file(file_path: str) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(file_path))
