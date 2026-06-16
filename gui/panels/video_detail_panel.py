"""Embedded video detail widget (no modal dialog).

_VideoDetailWidget is a QWidget displayed inline inside LibraryPanel.
It includes a back button, inline player, metadata, and clickable tags.
"""
from __future__ import annotations

import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from PyQt6.QtCore import QEvent, QTime, QTimer, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont, QImage
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from application.library.dtos import VideoDetailDTO
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


_TS_RE = re.compile(r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})")


def _parse_chapters(description: str) -> list[tuple[int, str]]:
    """설명에서 타임스탬프(챕터)를 추출한다.

    각 줄에서 `MM:SS` 또는 `HH:MM:SS` 형태를 찾아 (초, 라벨)로 변환.
    라벨은 타임스탬프 뒤 텍스트(없으면 앞 텍스트). 2개 이상일 때만 챕터로 본다.
    """
    if not description:
        return []
    chapters: list[tuple[int, str]] = []
    strip_chars = " \t-–—:·•.)]"
    for line in description.splitlines():
        m = _TS_RE.search(line)
        if not m:
            continue
        h = int(m.group(1)) if m.group(1) else 0
        sec = h * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        label = line[m.end():].strip(strip_chars)
        if not label:
            label = line[:m.start()].strip(strip_chars)
        chapters.append((sec, label or _fmt_dur(sec)))
    return chapters if len(chapters) >= 2 else []


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
        self._build_ui(item)
        self._apply_theme(ThemeManager.instance().current())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)

    def _build_ui(self, item: RelatedItem) -> None:
        from gui.panels.feed_panel import _RoundedThumbLabel, _ThumbLoader  # noqa: PLC0415

        row = QHBoxLayout(self)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(8)

        self._thumb = _RoundedThumbLabel(self._TW, self._TH)
        if item.duration_sec:
            self._thumb.set_duration(_fmt_dur(item.duration_sec))
        row.addWidget(self._thumb)

        # 썸네일 로드: 로컬 경로 우선, 없으면 원격 URL 비동기
        if item.thumb_path and Path(item.thumb_path).exists():
            img = QImage(item.thumb_path)
            if not img.isNull():
                self._thumb.set_image(img)
        elif item.thumb_url:
            self._loader = _ThumbLoader(
                item.thumb_url, item.key, prefix="related",
                size=(self._TW * 2, self._TH * 2),
            )
            def _on_related_thumb(_id: str, im: QImage) -> None:
                try:
                    self._thumb.set_image(im)
                except RuntimeError:
                    pass  # 카드 소멸 후 콜백 도달 시 무시
            self._loader.loaded.connect(_on_related_thumb)
            self._loader.start()

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)
        self._title_lbl = QLabel(item.title)
        self._title_lbl.setWordWrap(True)
        self._title_lbl.setMaximumHeight(40)
        tf = QFont()
        tf.setPointSize(9)
        tf.setWeight(QFont.Weight.Medium)
        self._title_lbl.setFont(tf)
        text_col.addWidget(self._title_lbl)

        self._chan_lbl = QLabel(item.channel)
        cf = QFont()
        cf.setPointSize(8)
        self._chan_lbl.setFont(cf)
        text_col.addWidget(self._chan_lbl)

        self._meta_lbl = QLabel(item.meta_text)
        self._meta_lbl.setFont(cf)
        text_col.addWidget(self._meta_lbl)
        text_col.addStretch()
        row.addLayout(text_col, 1)

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
        self.setMinimumWidth(280)
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
    """Small pill-shaped button for a single tag."""

    def __init__(self, tag_id: UUID, tag_name: str, parent=None) -> None:
        super().__init__(f"#{tag_name}", parent)
        self.tag_id = tag_id
        self.tag_name = tag_name
        self.setFlat(True)
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


class _TagFlow(QWidget):
    """Wrapping flow layout of tag chips."""

    tag_clicked = pyqtSignal(object, str)  # (tag_id: UUID, tag_name: str)

    def __init__(self, tags: list[str], tag_ids: dict[str, UUID], parent=None) -> None:
        super().__init__(parent)
        layout = _FlowLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for name in tags:
            tid = tag_ids.get(name)
            if tid is None:
                continue
            chip = _TagChip(tid, name, self)
            chip.clicked.connect(lambda _, i=tid, n=name: self.tag_clicked.emit(i, n))
            layout.addWidget(chip)


class _FlowLayout:
    """Minimal horizontal-wrapping flow layout (manual add only)."""
    def __init__(self, parent: QWidget) -> None:
        self._outer = QVBoxLayout(parent)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)
        self._row: QHBoxLayout | None = None
        self._row_count = 0
        self._spacing = 4

    def setContentsMargins(self, *args) -> None:
        self._outer.setContentsMargins(*args)

    def setSpacing(self, s: int) -> None:
        self._spacing = s

    def addWidget(self, w: QWidget) -> None:  # type: ignore[override]
        if self._row is None or self._row_count >= 5:
            from PyQt6.QtWidgets import QHBoxLayout
            self._row = QHBoxLayout()
            self._row.setContentsMargins(0, 0, 0, 0)
            self._row.setSpacing(self._spacing)
            self._outer.addLayout(self._row)
            self._row_count = 0
        self._row.addWidget(w)
        self._row_count += 1


class VideoDetailWidget(QWidget):
    """Full video detail view (embedded, not a dialog).

    Signals:
        back_requested  — user clicked the back button
        tag_filter_requested(tag_id, tag_name) — user clicked a tag chip
        tags_updated(video_id, tag_names) — user added a tag manually
    """

    back_requested       = pyqtSignal()
    tag_filter_requested = pyqtSignal(object, str)   # (UUID, str)
    tags_updated         = pyqtSignal(object, object)  # (UUID, list[str])
    download_requested   = pyqtSignal(str, str, object)  # (url, title, DownloadSettings)
    item_selected        = pyqtSignal(object)  # 연관 영상 클릭 — payload(UUID | FeedVideoDTO)

    # 하단 탭 인덱스
    _TAB_DOWNLOADS = 0
    _TAB_NOTES = 1
    _TAB_CLIPS = 2

    def __init__(self, clip_vm=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._detail: VideoDetailDTO | None = None
        self._tag_add_input: QLineEdit | None = None
        self._clip_vm = clip_vm
        self._clip_source_file: str | None = None
        self._filter_on = False
        self._streaming = False          # 스트리밍(피드/채널) 모드 여부
        self._current_url = ""           # 브라우저 열기/재생 실패 폴백용
        self._setup_skeleton()

    # ── Skeleton (built once) ──────────────────────────────────────

    def _setup_skeleton(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Back button (‹ 아이콘, Esc 키로도 동작) ──────────────────
        back_row = QHBoxLayout()
        self._btn_back = QPushButton("‹")
        self._btn_back.setFixedSize(28, 28)
        self._btn_back.setToolTip("목록으로 (Esc)")
        self._btn_back.clicked.connect(self.back_requested.emit)
        back_row.addWidget(self._btn_back)
        back_row.addStretch()
        root.addLayout(back_row)

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

        self._player = InlinePlayer(left_w)
        self._player.playback_failed.connect(self._on_play_failed)
        self._player.download_requested.connect(self.download_requested.emit)
        left_layout.addWidget(self._player, stretch=3)

        # 액션 행: 브라우저 열기 버튼
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        self._btn_browser = QPushButton("🌐 브라우저에서 열기")
        self._btn_browser.setFixedHeight(26)
        self._btn_browser.clicked.connect(self._on_open_browser)
        action_row.addWidget(self._btn_browser)
        action_row.addStretch()
        left_layout.addLayout(action_row)

        # 정보 스크롤 (제목·메타·태그·챕터·설명)
        info_scroll = QScrollArea()
        info_scroll.setWidgetResizable(True)
        info_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._meta_widget = QWidget()
        self._meta_layout = QVBoxLayout(self._meta_widget)
        self._meta_layout.setContentsMargins(4, 4, 4, 4)
        self._meta_layout.setSpacing(6)
        info_scroll.setWidget(self._meta_widget)
        left_layout.addWidget(info_scroll, stretch=2)

        # ── 하단 탭 (다운로드 파일 / 내 메모 / 클립) ──
        self._tabs = QTabWidget()
        self._tabs.setMaximumHeight(240)

        self._dl_tab = QWidget()
        self._tabs.addTab(_wrap(self._dl_tab), "다운로드 파일")

        note_tab = QWidget()
        note_layout = QVBoxLayout(note_tab)
        note_layout.setContentsMargins(8, 8, 8, 8)
        note_grp = QGroupBox("내 메모")
        note_inner = QVBoxLayout(note_grp)
        self._notes_edit = QPlainTextEdit()
        self._notes_edit.setPlaceholderText("메모를 입력하세요…")
        note_inner.addWidget(self._notes_edit)
        note_layout.addWidget(note_grp)
        self._tabs.addTab(_wrap(note_tab), "내 메모")

        self._clip_tab_widget = QWidget()
        self._clip_tab_layout = QVBoxLayout(self._clip_tab_widget)
        self._clip_tab_layout.setContentsMargins(8, 8, 8, 8)
        self._tabs.addTab(_wrap(self._clip_tab_widget), "클립")

        self._tabs.currentChanged.connect(self._on_tab_changed)
        left_layout.addWidget(self._tabs)

        main_split.addWidget(left_w)

        # ── 우측: 연관 영상 목록 ──
        self._related = _RelatedList()
        self._related.item_selected.connect(self.item_selected.emit)
        main_split.addWidget(self._related)

        main_split.setStretchFactor(0, 3)
        main_split.setStretchFactor(1, 1)
        main_split.setSizes([720, 300])
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
        if event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.BackButton:
                self.back_requested.emit()
                return True
        return False

    # ── Populate ───────────────────────────────────────────────────

    def load(
        self,
        detail: VideoDetailDTO,
        tag_ids: dict[str, UUID],
        resume_ms: int = 0,
        related: list[RelatedItem] | None = None,
    ) -> None:
        """라이브러리(로컬) 영상 상세를 채운다. resume_ms>0이면 이어서 재생."""
        self._detail = detail
        self._tag_ids = tag_ids
        self._streaming = False
        self._current_url = detail.url

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
        self._build_downloads_tab(detail.downloads)
        self._notes_edit.setReadOnly(False)
        self._notes_edit.setPlainText(detail.notes)

        # 클립 탭 — 로컬 파일 탐색 및 탭 초기화
        self._clip_source_file = None
        for dl in detail.downloads:
            if dl.file_path and Path(dl.file_path).exists():
                self._clip_source_file = dl.file_path
                break
        self._build_clip_tab()

        self.set_related(related or [])

    def load_stream(self, feed, related: list[RelatedItem] | None = None) -> None:
        """스트리밍(구독 피드/채널) 영상 상세 — URL 직접 재생.

        feed: FeedVideoDTO. 로컬 항목이 아니므로 클립/메모/태그 편집은 비활성.
        """
        self._detail = None
        self._tag_ids = {}
        self._streaming = True
        self._current_url = feed.url

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
        self._build_downloads_tab([])
        self._notes_edit.setReadOnly(True)
        self._notes_edit.setPlainText("스트리밍 영상입니다. 다운로드 후 메모/클립을 사용할 수 있습니다.")
        self._clip_source_file = None
        _clear_layout(self._clip_tab_layout)
        info = QLabel("스트리밍 영상은 클립을 추출할 수 없습니다.\n다운로드 후 다시 시도해 주세요.")
        info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        info.setStyleSheet("color:#888; font-size:10pt; padding:24px;")
        self._clip_tab_layout.addWidget(info)
        self._clip_tab_layout.addStretch()
        self._tabs.setCurrentIndex(self._TAB_DOWNLOADS)

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
        self._tag_add_input = None

        title_lbl = QLabel(title)
        title_lbl.setFont(_bold_font(13))
        title_lbl.setWordWrap(True)
        self._meta_layout.addWidget(title_lbl)

        # 채널 · 조회수 · 업로드일 한 줄
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

        # 태그 칩
        if tags:
            self._meta_layout.addWidget(QLabel("<b>태그:</b>"))
            flow = _TagFlow(tags, tag_ids, self._meta_widget)
            flow.tag_clicked.connect(self.tag_filter_requested.emit)
            self._meta_layout.addWidget(flow)

        # 수동 태그 추가 (로컬 영상만)
        if allow_tag_edit:
            tag_add_row = QHBoxLayout()
            tag_add_row.setContentsMargins(0, 2, 0, 0)
            tag_add_row.setSpacing(4)
            self._tag_add_input = QLineEdit()
            self._tag_add_input.setPlaceholderText("태그 추가... (쉼표로 구분)")
            self._tag_add_input.setStyleSheet("font-size:8pt;")
            self._tag_add_input.returnPressed.connect(self._on_add_tag)
            tag_add_row.addWidget(self._tag_add_input, 1)
            add_btn = QPushButton("+")
            add_btn.setFixedSize(24, 24)
            add_btn.setStyleSheet("font-size:11pt; font-weight:bold;")
            add_btn.clicked.connect(self._on_add_tag)
            tag_add_row.addWidget(add_btn)
            self._meta_layout.addLayout(tag_add_row)

        # 챕터(타임라인) — 설명에서 추출, 클릭 시 해당 위치로 seek
        chapters = _parse_chapters(description or "")
        if chapters:
            self._meta_layout.addWidget(QLabel("<b>챕터:</b>"))
            for sec, label in chapters:
                btn = QPushButton(f"{_fmt_dur(sec)}  {label}")
                btn.setFlat(True)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setStyleSheet(
                    f"QPushButton{{text-align:left; border:none; padding:2px 4px;"
                    f" color:{_t().accent}; font-size:9pt;}}"
                    f"QPushButton:hover{{text-decoration:underline;}}"
                )
                btn.clicked.connect(lambda _, s=sec: self._on_chapter_clicked(s))
                self._meta_layout.addWidget(btn)

        # 설명
        if description:
            self._meta_layout.addWidget(QLabel("<b>설명:</b>"))
            desc_edit = QPlainTextEdit()
            desc_edit.setReadOnly(True)
            desc_edit.setPlainText(description)
            desc_edit.setMaximumHeight(160)
            self._meta_layout.addWidget(desc_edit)

        self._meta_layout.addStretch()

    def _on_chapter_clicked(self, sec: int) -> None:
        self._player.seek_to_ms(sec * 1000)
        if not self._player.is_playing():
            self._player.play()

    def _build_downloads_tab(self, downloads: list) -> None:
        if self._dl_tab.layout():
            _clear_layout(self._dl_tab.layout())
            dl_layout = self._dl_tab.layout()
        else:
            dl_layout = QVBoxLayout(self._dl_tab)
        dl_layout.setContentsMargins(8, 8, 8, 4)
        dl_layout.setSpacing(8)
        if downloads:
            for dl in downloads:
                fp = Path(dl.file_path) if dl.file_path else None
                exists = fp is not None and fp.exists()
                filename = fp.name if fp else "—"
                info = "  ·  ".join(filter(None, [
                    dl.quality or None,
                    dl.fmt.upper() if dl.fmt else None,
                    _fmt_size(dl.file_size_bytes) if dl.file_size_bytes else None,
                    "파일 있음 ✓" if exists else "파일 없음 ✗",
                ]))
                grp = QGroupBox(filename)
                grp.setMinimumHeight(90)
                gl = QVBoxLayout(grp)
                gl.setContentsMargins(10, 8, 10, 10)
                gl.setSpacing(6)
                info_lbl = QLabel(info)
                info_lbl.setStyleSheet(f"color:{_t().text_secondary}; font-size:9pt;")
                info_lbl.setMinimumHeight(22)
                gl.addWidget(info_lbl)
                if exists:
                    btn_row = QHBoxLayout()
                    btn_row.setSpacing(6)
                    folder_btn = QPushButton("폴더 열기")
                    folder_btn.setFixedHeight(28)
                    folder_btn.setToolTip("파일 위치를 탐색기에서 열기")
                    folder_btn.clicked.connect(lambda _, p=dl.file_path: _open_folder(p))
                    btn_row.addWidget(folder_btn)
                    open_btn = QPushButton("파일 열기")
                    open_btn.setFixedHeight(28)
                    open_btn.setToolTip("기본 앱으로 파일 열기 / 재생")
                    open_btn.clicked.connect(lambda _, p=dl.file_path: _open_file(p))
                    btn_row.addWidget(open_btn)
                    btn_row.addStretch()
                    gl.addLayout(btn_row)
                dl_layout.addWidget(grp)
        else:
            dl_layout.addWidget(QLabel("다운로드된 파일이 없습니다."))
        dl_layout.addStretch()

    def _set_tabs_enabled(self, local: bool) -> None:
        """스트리밍 모드면 메모·클립 탭 비활성."""
        self._tabs.setTabEnabled(self._TAB_NOTES, local)
        self._tabs.setTabEnabled(self._TAB_CLIPS, local)

    # ── 연관 영상 ──────────────────────────────────────────────────

    def set_related(self, items: list[RelatedItem]) -> None:
        self._related.set_items(items)

    # ── Clip tab ───────────────────────────────────────────────────

    def _build_clip_tab(self) -> None:
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
        self._clip_tab_layout.addWidget(list_grp)

        self._clip_tab_layout.addStretch()

        # 클립 VM 연결 (중복 연결 방지)
        try:
            self._clip_vm.clips_changed.disconnect(self._refresh_clip_list)
        except Exception:
            logger.exception("클립 시그널 중복 연결 해제 실패")
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

    def _on_tab_changed(self, index: int) -> None:
        if (
            index == self._TAB_CLIPS
            and not self._streaming
            and self._clip_vm is not None
            and self._detail is not None
        ):
            self._clip_vm.load_clips(self._detail.id)

    def _refresh_clip_list(self) -> None:
        if not hasattr(self, "_clip_list_layout"):
            return
        _clear_layout(self._clip_list_layout)
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

    def _on_play_failed(self, err: str) -> None:
        if self._current_url:
            QDesktopServices.openUrl(QUrl(self._current_url))

    def stop_player(self) -> None:
        self._player.stop()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

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
