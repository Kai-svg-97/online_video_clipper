"""Embedded video detail widget (no modal dialog).

_VideoDetailWidget is a QWidget displayed inline inside LibraryPanel.
It includes a back button, inline player, metadata, and clickable tags.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from uuid import UUID

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
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
    QVBoxLayout,
    QWidget,
)

from application.library.dtos import VideoDetailDTO
from gui.widgets.video_player import InlinePlayer


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
        self.setStyleSheet(
            "QPushButton{"
            "  border:1px solid #3a6a9a; border-radius:10px;"
            "  background:#1e3a5a; color:#cde; padding:2px 8px; font-size:8pt;"
            "}"
            "QPushButton:hover{background:#2a5a8a;}"
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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._detail: VideoDetailDTO | None = None
        self._tag_add_input: QLineEdit | None = None
        self._setup_skeleton()

    # ── Skeleton (built once) ──────────────────────────────────────

    def _setup_skeleton(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Back button ─────────────────────────────────────────────
        back_row = QHBoxLayout()
        self._btn_back = QPushButton("← 목록으로")
        self._btn_back.setFixedHeight(28)
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

        # Single browser button (play/stop are already in InlinePlayer._Controls)
        self._btn_browser = QPushButton("🌐  브라우저에서 보기")
        self._btn_browser.setFixedHeight(28)
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

        root.addWidget(self._tabs)

    # ── Populate ───────────────────────────────────────────────────

    def load(self, detail: VideoDetailDTO, tag_ids: dict[str, UUID]) -> None:
        """Populate all fields from *detail*."""
        self._detail = detail
        self._tag_ids = tag_ids

        self._player.load(detail.url, detail.downloads)
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
        if detail.downloads:
            for i, dl in enumerate(detail.downloads, 1):
                grp = QGroupBox(f"다운로드 #{i}")
                gl = QVBoxLayout(grp)
                exists = dl.file_path and Path(dl.file_path).exists()
                p_lbl = QLabel(f"<b>경로:</b>  {dl.file_path or '—'}")
                p_lbl.setWordWrap(True)
                gl.addWidget(p_lbl)
                gl.addWidget(QLabel(f"<b>화질:</b> {dl.quality}   <b>포맷:</b> {dl.fmt}"))
                gl.addWidget(QLabel(f"<b>크기:</b> {_fmt_size(dl.file_size_bytes)}   <b>파일:</b> {'있음 ✓' if exists else '없음 ✗'}"))
                if exists:
                    ob = QPushButton("파일 위치 열기")
                    ob.clicked.connect(lambda _, p=dl.file_path: _open_folder(p))
                    gl.addWidget(ob)
                dl_layout.addWidget(grp)
        else:
            dl_layout.addWidget(QLabel("다운로드된 파일이 없습니다."))
        dl_layout.addStretch()

        # Notes
        self._notes_edit.setPlainText(detail.notes)

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
