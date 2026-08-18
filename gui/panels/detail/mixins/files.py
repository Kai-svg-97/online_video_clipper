"""FilesTabMixin — 상세화면의 files 영역.

    VideoDetailWidget에 섞여 들어가는 mixin이라 위젯 상태를 그대로 쓴다
    (런타임 클래스는 하나다).
"""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import (
    QTime,
    Qt,
)
from PyQt6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)


from application.library.dtos import FailedDownloadInfoDTO
from gui.themes.colors import sem


# ── 분할된 부품 (gui/panels/detail/*) ─────────────────────────────
# 이 파일에는 화면 조립·흐름 제어만 남기고 부품은 패키지로 옮겼다.
# 아래 재수출은 기존 임포트 경로를 유지하기 위한 것이다.
from gui.panels.detail.widgets import (  # noqa: F401
    _AutoHeightBrowser,
    _AutoHeightPlainEdit,
    _DblClickLabel,
    _EditableField,
    _FlowLayout,
    _LockedNotice,
    _SpinRefreshButton,
    _TagChip,
    _TagFlow,
    _bold_font,
    _clear_layout,
    _fmt_size,
    _hline,
    _open_file,
    _open_folder,
    _t,
    _wrap,
)
from gui.panels.detail.related import (  # noqa: F401
    RelatedItem,
    _RelatedList,
    _RelatedRow,
    _fmt_dur,
    _fmt_pub,
    _payload_key,
)
from gui.panels.detail.song_tab import (  # noqa: F401
    _LyricRow,
    _LyricsCandidateList,
    _SongTab,
    _candidate_tooltip,
)
from gui.panels.detail.workers import (  # noqa: F401
    _GeminiSummaryWorker,
)

logger = logging.getLogger(__name__)


class FilesTabMixin:
    """다운로드/클립 탭 — 파일 목록, 클립 추출, 진행률."""

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
                    na_lbl.setStyleSheet(f"color:{sem('danger')}; font-size:8pt;")
                    grid.addWidget(na_lbl, row_idx, 3)

            dl_layout.addWidget(grid_w)
        else:
            dl_layout.addWidget(QLabel("다운로드된 파일이 없습니다."))

        # 실패 이력 섹션
        if failed_downloads:
            fail_hdr = QLabel("다운로드 실패 이력")
            fail_hdr.setStyleSheet(
                f"color:{sem('danger')}; font-weight:bold; font-size:9pt; margin-top:8px;"
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
                    f"QFrame {{ border-left: 3px solid {sem('danger')};"
                    " background: transparent; }"
                )
                rl = QVBoxLayout(row)
                rl.setContentsMargins(10, 4, 10, 6)
                rl.setSpacing(2)
                if date_str:
                    date_lbl = QLabel(date_str)
                    date_lbl.setStyleSheet(f"color:{_t().text_secondary}; font-size:8pt;")
                    rl.addWidget(date_lbl)
                err_lbl = QLabel(err_text)
                err_lbl.setWordWrap(True)
                err_lbl.setStyleSheet(f"color:{sem('danger')}; font-size:8pt;")
                rl.addWidget(err_lbl)
                dl_layout.addWidget(row)

        dl_layout.addStretch()

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
            info.setStyleSheet(f"color: {_t().text_secondary}; font-size: 10pt; padding: 24px;")
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
        self._clip_status_lbl.setStyleSheet(f"font-size: 9pt; color: {_t().text_secondary};")
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

    def refresh_downloads(self, downloads: list, failed_downloads: list) -> None:
        """다운로드 파일 탭만 새로 그린다."""
        self._build_downloads_tab(downloads, failed_downloads)
