"""Embedded video detail widget (no modal dialog).

_VideoDetailWidget is a QWidget displayed inline inside LibraryPanel.
It includes a back button, inline player, metadata, and clickable tags.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from PyQt6.QtCore import QEvent, QTime, QTimer, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont
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


def _t():
    return ThemeManager.instance().current()


def _fmt_dur(sec: int | None) -> str:
    if sec is None:
        return "—"
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


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

    def __init__(self, clip_vm=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._detail: VideoDetailDTO | None = None
        self._tag_add_input: QLineEdit | None = None
        self._clip_vm = clip_vm
        self._clip_source_file: str | None = None
        self._filter_on = False
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

        self._title_top = QLabel()
        self._title_top.setFont(_bold_font(11))
        self._title_top.setWordWrap(True)
        back_row.addWidget(self._title_top, stretch=1)
        root.addLayout(back_row)

        sep0 = _hline()
        root.addWidget(sep0)

        # ── Top splitter: player | metadata ─────────────────────────
        top_split = QSplitter(Qt.Orientation.Horizontal)

        # Left: inline player
        left_w = QWidget()
        left_w.setMinimumWidth(320)
        left_layout = QVBoxLayout(left_w)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        self._player = InlinePlayer(left_w)
        self._player.playback_failed.connect(self._on_play_failed)
        self._player.download_requested.connect(self.download_requested.emit)
        left_layout.addWidget(self._player, stretch=1)

        # 아이콘 버튼 (텍스트 없음)
        self._btn_browser = QPushButton("🌐")
        self._btn_browser.setFixedSize(28, 28)
        self._btn_browser.setToolTip("브라우저에서 열기")
        self._btn_browser.clicked.connect(self._on_open_browser)
        left_layout.addWidget(self._btn_browser)
        top_split.addWidget(left_w)

        # Right: metadata scroll area
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._meta_widget = QWidget()
        self._meta_layout = QVBoxLayout(self._meta_widget)
        self._meta_layout.setContentsMargins(12, 4, 4, 4)
        self._meta_layout.setSpacing(6)
        right_scroll.setWidget(self._meta_widget)
        top_split.addWidget(right_scroll)

        top_split.setStretchFactor(0, 1)
        top_split.setStretchFactor(1, 1)
        root.addWidget(top_split, stretch=2)

        sep1 = _hline()
        root.addWidget(sep1)

        # ── Tabs ─────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setMaximumHeight(260)

        # Tab: YouTube 정보
        self._yt_tab = QWidget()
        yt_layout = QVBoxLayout(self._yt_tab)
        yt_layout.setContentsMargins(8, 8, 8, 8)
        yt_desc_grp = QGroupBox("YouTube 영상 설명")
        yt_desc_inner = QVBoxLayout(yt_desc_grp)
        self._desc_edit = QPlainTextEdit()
        self._desc_edit.setReadOnly(True)
        self._desc_edit.setMaximumHeight(120)
        yt_desc_inner.addWidget(self._desc_edit)
        yt_layout.addWidget(yt_desc_grp)
        self._tabs.addTab(_wrap(self._yt_tab), "YouTube 정보")

        # Tab: 다운로드 파일
        self._dl_tab = QWidget()
        self._tabs.addTab(_wrap(self._dl_tab), "다운로드 파일")

        # Tab: 내 메모
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

        # Tab: 클립
        self._clip_tab_widget = QWidget()
        self._clip_tab_layout = QVBoxLayout(self._clip_tab_widget)
        self._clip_tab_layout.setContentsMargins(8, 8, 8, 8)
        self._tabs.addTab(_wrap(self._clip_tab_widget), "클립")

        self._tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self._tabs)

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

    def load(self, detail: VideoDetailDTO, tag_ids: dict[str, UUID], resume_ms: int = 0) -> None:
        """Populate all fields from *detail*. resume_ms > 0이면 해당 위치부터 이어서 재생."""
        self._detail = detail
        self._tag_ids = tag_ids

        self._player.load(detail.url, detail.downloads, resume_ms=resume_ms)
        if resume_ms > 0:
            QTimer.singleShot(150, self._player.play)
        self._title_top.setText(detail.title)

        # Rebuild metadata area
        _clear_layout(self._meta_layout)

        title_lbl = QLabel(detail.title)
        title_lbl.setFont(_bold_font(12))
        title_lbl.setWordWrap(True)
        self._meta_layout.addWidget(title_lbl)

        def _row(label: str, value: str) -> None:
            lbl = QLabel(f"<b>{label}</b>")
            lbl.setSizePolicy(lbl.sizePolicy().horizontalPolicy(), lbl.sizePolicy().verticalPolicy())
            val = QLabel(value)
            val.setWordWrap(True)
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(lbl, 0)
            row.addWidget(val, 1)
            self._meta_layout.addLayout(row)

        if detail.channel_name:
            _row("채널:", detail.channel_name)
        _row("재생 시간:", _fmt_dur(detail.duration_sec))
        if detail.published_at:
            _row("업로드:", detail.published_at)
        if detail.view_count is not None:
            _row("조회수:", f"{detail.view_count:,}회")

        statuses = []
        if detail.watched:
            statuses.append("✓ 시청완료")
        if detail.favorite:
            statuses.append("★ 즐겨찾기")
        if statuses:
            _row("상태:", "  ".join(statuses))

        # Clickable tag chips
        self._meta_layout.addWidget(QLabel("<b>태그:</b>"))
        if detail.tags:
            flow = _TagFlow(detail.tags, tag_ids, self._meta_widget)
            flow.tag_clicked.connect(self.tag_filter_requested.emit)
            self._meta_layout.addWidget(flow)

        # Manual tag add input
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

        self._meta_layout.addStretch()

        # Description
        self._desc_edit.setPlainText(detail.description or "(설명 없음)")

        # Downloads tab
        if self._dl_tab.layout():
            _clear_layout(self._dl_tab.layout())
            dl_layout = self._dl_tab.layout()
        else:
            dl_layout = QVBoxLayout(self._dl_tab)
        dl_layout.setContentsMargins(8, 8, 8, 4)
        dl_layout.setSpacing(8)
        if detail.downloads:
            for dl in detail.downloads:
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

        # Notes
        self._notes_edit.setPlainText(detail.notes)

        # Clip tab — 로컬 파일 탐색 및 탭 초기화
        self._clip_source_file = None
        if detail.downloads:
            for dl in detail.downloads:
                if dl.file_path and Path(dl.file_path).exists():
                    self._clip_source_file = dl.file_path
                    break
        self._build_clip_tab()

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
        if index == 3 and self._clip_vm is not None and self._detail is not None:
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
        if self._detail:
            QDesktopServices.openUrl(QUrl(self._detail.url))

    def _on_play_failed(self, err: str) -> None:
        if self._detail:
            QDesktopServices.openUrl(QUrl(self._detail.url))

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
