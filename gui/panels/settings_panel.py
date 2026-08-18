"""설정 패널 — 인라인 QWidget (다이얼로그 아님).

사이드바 ⚙ 아이콘 클릭 시 메인 콘텐츠 스택에 표시된다.
테마 프리셋 선택 + 일반/다운로드 설정 + 저장 경로 표시 + 숨김 태그 관리.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from gui.smooth_scroll import apply_smooth_scroll_tree
from gui.themes.manager import ThemeManager
from gui.workers import track_thread
from gui.themes.tokens import PRESETS, ThemeTokens
from version import __version__
from gui.themes.colors import sem


# ── 분할된 부품 (gui/panels/settings/*) ─────────────────────────────
# 이 파일에는 화면 조립·흐름 제어만 남기고 부품은 패키지로 옮겼다.
# 아래 재수출은 기존 임포트 경로를 유지하기 위한 것이다.
from gui.panels.settings.theme_cards import (  # noqa: F401
    _ThemeCard,
    _ThemePreview,
)
from gui.panels.settings.hidden_tags import (  # noqa: F401
    _HiddenTagsSection,
    _TagMoveDelegate,
    _TagMoveList,
)
from gui.panels.settings.sections import (  # noqa: F401
    _CloudSyncSection,
    _ImportExportSection,
    _LyricsSourcesSection,
)


# ── 분할된 부품 (gui/panels/settings/*) ─────────────────────────────
# 이 파일에는 화면 조립·흐름 제어만 남기고 부품은 패키지로 옮겼다.
# 아래 재수출은 기존 임포트 경로를 유지하기 위한 것이다.
from gui.panels.settings.helpers import (  # noqa: F401
    _t,
    open_folder,
)

logger = logging.getLogger(__name__)






# 쿠키 파일 등록 방법 안내 — "이건 컴퓨터 전문가용 앱이 아니다"는 사용자 신고에 따라,
# 브라우저 프로필 자동 감지가 전혀 동작하지 않는 환경(기업 보안 정책, 지원되지 않는
# 브라우저 등)에서도 일반 사용자가 이해할 수 있는 대체 경로를 안내한다.
COOKIE_HELP_TEXT = (
    "브라우저/프로필 자동 감지가 계속 실패한다면, 쿠키 파일을 직접 등록하는 "
    "방법이 가장 확실합니다.\n\n"
    "1. 사용 중인 브라우저의 웹 스토어에서 'Get cookies.txt LOCALLY' (또는 "
    "'cookies.txt') 확장 프로그램을 설치하세요.\n"
    "2. www.youtube.com 에 접속해 로그인되어 있는지 확인하세요.\n"
    "3. 확장 프로그램 아이콘을 클릭하고 '내보내기(Export)'를 눌러 쿠키 파일을 "
    "저장하세요. 특별히 지정하지 않으면 보통 다운로드 폴더에 저장됩니다.\n"
    "4. 이 설정 화면으로 돌아와 '다시 검색'을 누르면 저장한 파일이 "
    "'감지된 쿠키 파일' 목록에 나타납니다. 선택하면 끝입니다.\n\n"
    "문제가 계속되면 아래 '로그 폴더 열기'로 연 폴더의 app.log 파일을 함께 "
    "보내주세요."
)






# ---------------------------------------------------------------------------
# 태그 이동 목록 (드래그 앤 드롭 지원)
# ---------------------------------------------------------------------------









# ---------------------------------------------------------------------------
# 설정 패널
# ---------------------------------------------------------------------------








class SettingsPanel(QWidget):
    """설정 패널 (인라인, QDialog 아님)."""

    hidden_tags_changed = pyqtSignal()
    feed_workers_changed = pyqtSignal(int)
    check_update_requested = pyqtSignal()
    install_update_requested = pyqtSignal(object)   # UpdateDTO

    def __init__(
        self,
        get_tags_fn: Callable | None = None,
        yt_oauth=None,   # YouTubeOAuthAdapter | None
        song_vm=None,    # SongViewModel | None
        sync_vm=None,    # SyncViewModel | None
        transfer_vm=None,        # LibraryTransferViewModel | None
        get_categories_fn: Callable | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._get_tags_fn = get_tags_fn
        self._yt_oauth = yt_oauth
        self._song_vm = song_vm
        self._sync_vm = sync_vm
        self._transfer_vm = transfer_vm
        self._get_categories_fn = get_categories_fn
        self._theme_cards: dict[str, _ThemeCard] = {}
        self._yt_auth_worker = None
        self._pending_dto = None
        self._flash_timer = None
        self._flash_count = 0
        self._build_ui()
        apply_smooth_scroll_tree(self)
        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)
        self._on_theme_changed(ThemeManager.instance().current())

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        scroll = QScrollArea(self)
        self._scroll_area = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(0)

        # 헤더 + 우측 컴팩트 업데이트 상태
        header_row = QHBoxLayout()
        header = QLabel("설정")
        header.setStyleSheet("font-size: 16px; font-weight: 600;")
        header_row.addWidget(header)
        header_row.addStretch()
        header_row.addWidget(self._build_update_header())
        layout.addLayout(header_row)
        layout.addSpacing(20)

        self._build_theme_section(layout)
        self._add_divider(layout)
        self._build_paths_section(layout)
        self._add_divider(layout)
        self._build_general_section(layout)
        self._add_divider(layout)
        self._build_download_section(layout)
        self._build_lyrics_sources_section(layout)
        self._build_cloud_sync_section(layout)
        self._build_transfer_section(layout)
        self._build_youtube_api_section(layout)
        self._build_cookie_section(layout)
        self._build_hidden_tags_section(layout)

        layout.addStretch()

    def _add_divider(self, layout) -> None:
        """섹션 사이 구분선."""
        # ── 구분선 ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {_t().border};")
        layout.addWidget(sep)
        layout.addSpacing(24)

    def _build_theme_section(self, layout) -> None:
        """테마 프리셋 격자."""
        # ── 테마 섹션 ──
        theme_label = QLabel("테마")
        theme_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 12px;"
        )
        layout.addWidget(theme_label)
        layout.addSpacing(10)

        # 프리셋이 늘어 한 줄에 다 들어가지 않으므로 격자로 배치한다.
        cards_grid = QGridLayout()
        cards_grid.setContentsMargins(0, 0, 0, 0)
        cards_grid.setHorizontalSpacing(16)
        cards_grid.setVerticalSpacing(14)
        per_row = 6
        for i, (name, tokens) in enumerate(PRESETS.items()):
            card = _ThemeCard(tokens)
            self._theme_cards[name] = card
            cards_grid.addWidget(card, i // per_row, i % per_row)
        cards_grid.setColumnStretch(per_row, 1)

        layout.addLayout(cards_grid)
        layout.addSpacing(8)

        hint = QLabel("클릭하면 즉시 적용됩니다. 재시작 후에도 유지됩니다.")
        hint.setStyleSheet(f"font-size: 10px; color: {_t().text_muted}; margin-top: 4px;")
        layout.addWidget(hint)
        layout.addSpacing(28)

    def _build_paths_section(self, layout) -> None:
        """저장 경로(DB·다운로드·썸네일·로그) + 폴더 열기 버튼."""
        # ── 저장 경로 섹션 ──
        path_label = QLabel("저장 경로")
        path_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 12px;"
        )
        layout.addWidget(path_label)
        layout.addSpacing(10)

        try:
            from config import settings as s
            paths = {
                "데이터베이스": str(s.DATABASE_PATH),
                "다운로드 폴더": str(s.DOWNLOAD_DIR),
                "썸네일 폴더": str(s.THUMBNAIL_DIR),
                "로그 폴더": str(s.LOG_DIR),
            }
        except Exception:
            logger.exception("설정 경로 로드 실패")
            paths = {}

        for label_text, path_text in paths.items():
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(12)
            lbl = QLabel(label_text)
            lbl.setFixedWidth(90)
            lbl.setStyleSheet(f"font-size: 11px; color: {_t().text_muted};")
            val = QLabel(path_text)
            val.setStyleSheet(
                f"font-size: 10px; color: {_t().text_muted}; font-family: monospace;"
            )
            val.setWordWrap(False)
            val.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            open_btn = QPushButton("열기")
            open_btn.setFixedWidth(48)
            open_btn.clicked.connect(lambda _checked=False, p=path_text: open_folder(p))
            row.addWidget(lbl)
            row.addWidget(val, 1)
            row.addWidget(open_btn)
            layout.addLayout(row)
            layout.addSpacing(6)

        note = QLabel("경로를 변경하려면 data/config.yaml 을 편집하세요.")
        note.setStyleSheet(f"font-size: 10px; color: {_t().text_muted}; margin-top: 8px;")
        layout.addWidget(note)
        layout.addSpacing(28)

    def _build_general_section(self, layout) -> None:
        """일반 설정(테마 적용 방식·자동 보강 등)."""
        # ── 일반 섹션 ──
        gen_label = QLabel("일반")
        gen_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 12px;"
        )
        layout.addWidget(gen_label)
        layout.addSpacing(10)

        try:
            from config import settings as s
            cur_concurrent = s.MAX_CONCURRENT_DOWNLOADS
            cur_feed_workers = s.MAX_CONCURRENT_FEED_WORKERS
            cur_clipboard = s.CLIPBOARD_MONITORING
            cur_auto_enrich = s.AUTO_ENRICH_ON_ADD
        except Exception:
            logger.exception("일반 설정 로드 실패")
            cur_concurrent = 3
            cur_feed_workers = 4
            cur_clipboard = True
            cur_auto_enrich = True

        # 동시 다운로드 수
        concurrent_row = QHBoxLayout()
        concurrent_row.setContentsMargins(0, 0, 0, 0)
        concurrent_lbl = QLabel("동시 다운로드 수")
        concurrent_lbl.setFixedWidth(130)
        concurrent_lbl.setStyleSheet("font-size: 11px;")
        self._concurrent_spin = QSpinBox()
        self._concurrent_spin.setRange(1, 8)
        self._concurrent_spin.setValue(cur_concurrent)
        self._concurrent_spin.setFixedWidth(64)
        self._concurrent_spin.valueChanged.connect(self._on_concurrent_changed)
        concurrent_row.addWidget(concurrent_lbl)
        concurrent_row.addWidget(self._concurrent_spin)
        concurrent_row.addStretch()
        layout.addLayout(concurrent_row)
        layout.addSpacing(10)

        # 노드 동시 로딩 수 (피드·채널·카테고리·재생목록 등 모든 트리 노드 공통)
        feed_workers_row = QHBoxLayout()
        feed_workers_row.setContentsMargins(0, 0, 0, 0)
        feed_workers_lbl = QLabel("노드 동시 로딩 수")
        feed_workers_lbl.setFixedWidth(130)
        feed_workers_lbl.setStyleSheet("font-size: 11px;")
        self._feed_workers_spin = QSpinBox()
        self._feed_workers_spin.setRange(1, 8)
        self._feed_workers_spin.setValue(cur_feed_workers)
        self._feed_workers_spin.setFixedWidth(64)
        self._feed_workers_spin.valueChanged.connect(self._on_feed_workers_changed)
        feed_workers_row.addWidget(feed_workers_lbl)
        feed_workers_row.addWidget(self._feed_workers_spin)
        feed_workers_row.addStretch()
        layout.addLayout(feed_workers_row)
        layout.addSpacing(10)

        # 클립보드 URL 자동 감지
        self._clipboard_check = QCheckBox("클립보드 URL 자동 감지")
        self._clipboard_check.setChecked(cur_clipboard)
        self._clipboard_check.checkStateChanged.connect(self._on_clipboard_changed)
        layout.addWidget(self._clipboard_check)
        layout.addSpacing(10)

        # 등록 시 요약·가사 자동 채우기
        self._auto_enrich_check = QCheckBox("등록 시 요약·가사 자동 채우기")
        self._auto_enrich_check.setChecked(cur_auto_enrich)
        self._auto_enrich_check.checkStateChanged.connect(self._on_auto_enrich_changed)
        layout.addWidget(self._auto_enrich_check)

        enrich_hint = QLabel(
            "영상을 한 건씩 등록할 때 음원용 영상은 가사를, 그 외 영상은 Gemini 요약을 "
            "백그라운드에서 채웁니다. 재생목록·채널 일괄 가져오기는 대상이 아닙니다.\n"
            "요약은 YouTube 로그인 쿠키가 필요합니다 — Chrome 127 이상은 쿠키 자동 추출이 "
            "불가하므로 아래 인증 섹션에서 쿠키 파일을 직접 등록해야 합니다."
        )
        enrich_hint.setWordWrap(True)
        enrich_hint.setStyleSheet(f"font-size: 10px; color: {_t().text_secondary}; margin-left: 22px;")
        layout.addWidget(enrich_hint)
        layout.addSpacing(28)

    def _build_download_section(self, layout) -> None:
        """다운로드 기본값(화질·형식·경로)."""
        # ── 다운로드 섹션 ──
        dl_label = QLabel("다운로드")
        dl_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 12px;"
        )
        layout.addWidget(dl_label)
        layout.addSpacing(10)

        try:
            from config import settings as s
            cur_dl_dir = str(s.DOWNLOAD_DIR)
            cur_quality = s.DEFAULT_QUALITY
            cur_format = s.DEFAULT_FORMAT
        except Exception:
            logger.exception("다운로드 설정 로드 실패")
            cur_dl_dir = ""
            cur_quality = "best[ext=mp4]/best"
            cur_format = "mp4"

        # 다운로드 폴더
        folder_row = QHBoxLayout()
        folder_row.setContentsMargins(0, 0, 0, 0)
        folder_lbl = QLabel("다운로드 폴더")
        folder_lbl.setFixedWidth(100)
        folder_lbl.setStyleSheet("font-size: 11px;")
        self._folder_edit = QLineEdit(cur_dl_dir)
        self._folder_edit.setReadOnly(True)
        self._folder_edit.setStyleSheet("font-size: 10px; font-family: monospace;")
        browse_btn = QPushButton("찾아보기")
        browse_btn.setFixedWidth(72)
        browse_btn.clicked.connect(self._on_browse_folder)
        folder_row.addWidget(folder_lbl)
        folder_row.addWidget(self._folder_edit, 1)
        folder_row.addWidget(browse_btn)
        layout.addLayout(folder_row)
        layout.addSpacing(10)

        # 기본 품질
        quality_row = QHBoxLayout()
        quality_row.setContentsMargins(0, 0, 0, 0)
        quality_lbl = QLabel("기본 품질")
        quality_lbl.setFixedWidth(100)
        quality_lbl.setStyleSheet("font-size: 11px;")
        self._quality_combo = QComboBox()
        quality_options = [
            ("자동 (최고 품질)", "best[ext=mp4]/best"),
            ("4K / UHD (2160p)", "bestvideo[height<=2160][ext=mp4]+bestaudio/best[height<=2160]"),
            ("1440p / QHD", "bestvideo[height<=1440][ext=mp4]+bestaudio/best[height<=1440]"),
            ("1080p / FHD", "bestvideo[height<=1080][ext=mp4]+bestaudio/best[height<=1080]"),
            ("720p / HD", "bestvideo[height<=720][ext=mp4]+bestaudio/best[height<=720]"),
            ("480p", "bestvideo[height<=480][ext=mp4]+bestaudio/best[height<=480]"),
            ("360p", "bestvideo[height<=360][ext=mp4]+bestaudio/best[height<=360]"),
        ]
        for label, fmt in quality_options:
            self._quality_combo.addItem(label, fmt)
        matched = next((i for i, (_, f) in enumerate(quality_options) if f == cur_quality), 0)
        self._quality_combo.setCurrentIndex(matched)
        self._quality_combo.currentIndexChanged.connect(self._on_quality_changed)
        quality_row.addWidget(quality_lbl)
        quality_row.addWidget(self._quality_combo)
        quality_row.addStretch()
        layout.addLayout(quality_row)
        layout.addSpacing(10)

        # 기본 포맷
        format_row = QHBoxLayout()
        format_row.setContentsMargins(0, 0, 0, 0)
        format_lbl = QLabel("기본 포맷")
        format_lbl.setFixedWidth(100)
        format_lbl.setStyleSheet("font-size: 11px;")
        self._format_combo = QComboBox()
        for fmt in ("mp4", "mkv", "webm", "mp3", "m4a"):
            self._format_combo.addItem(fmt)
        fmt_idx = self._format_combo.findText(cur_format)
        self._format_combo.setCurrentIndex(fmt_idx if fmt_idx >= 0 else 0)
        self._format_combo.currentIndexChanged.connect(self._on_format_changed)
        format_row.addWidget(format_lbl)
        format_row.addWidget(self._format_combo)
        format_row.addStretch()
        layout.addLayout(format_row)
        layout.addSpacing(28)

    def _build_lyrics_sources_section(self, layout) -> None:
        """가사 출처 관리(노래 탭 조회 순서/사용여부)."""
        # ── 가사 출처 관리 섹션 (노래 탭 가사 조회 순서/사용여부) ──
        if self._song_vm is not None:
            layout.addSpacing(24)
            sep_lyr = QFrame()
            sep_lyr.setFrameShape(QFrame.Shape.HLine)
            sep_lyr.setStyleSheet(f"color: {_t().border};")
            layout.addWidget(sep_lyr)
            layout.addSpacing(24)
            lyr_label = QLabel("가사 출처 관리")
            lyr_label.setStyleSheet(
                "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
                f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 12px;"
            )
            layout.addWidget(lyr_label)
            layout.addSpacing(10)
            self._lyrics_sources_section = _LyricsSourcesSection(self._song_vm)
            layout.addWidget(self._lyrics_sources_section)

    def _build_cloud_sync_section(self, layout) -> None:
        """클라우드 동기화(여러 PC 간 라이브러리 공유)."""
        # ── 클라우드 동기화 섹션 (여러 PC 간 라이브러리 동기화) ──
        if self._sync_vm is not None:
            layout.addSpacing(24)
            sep_sync = QFrame()
            sep_sync.setFrameShape(QFrame.Shape.HLine)
            sep_sync.setStyleSheet(f"color: {_t().border};")
            layout.addWidget(sep_sync)
            layout.addSpacing(24)
            sync_label = QLabel("클라우드 동기화")
            sync_label.setStyleSheet(
                "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
                f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 12px;"
            )
            layout.addWidget(sync_label)
            layout.addSpacing(10)
            self._cloud_sync_section = _CloudSyncSection(self._sync_vm)
            layout.addWidget(self._cloud_sync_section)

    def _build_transfer_section(self, layout) -> None:
        """라이브러리 가져오기/내보내기."""
        # ── 라이브러리 가져오기/내보내기 섹션 ──
        if self._transfer_vm is not None:
            layout.addSpacing(24)
            sep_transfer = QFrame()
            sep_transfer.setFrameShape(QFrame.Shape.HLine)
            sep_transfer.setStyleSheet(f"color: {_t().border};")
            layout.addWidget(sep_transfer)
            layout.addSpacing(24)
            transfer_label = QLabel("라이브러리 가져오기/내보내기")
            transfer_label.setStyleSheet(
                "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
                f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 12px;"
            )
            layout.addWidget(transfer_label)
            layout.addSpacing(10)
            self._import_export_section = _ImportExportSection(
                self._transfer_vm, self._get_categories_fn
            )
            layout.addWidget(self._import_export_section)

    def _build_youtube_api_section(self, layout) -> None:
        """YouTube API 연동(번들 OAuth 로그인)."""
        # ── YouTube API 연동 섹션 ──
        layout.addSpacing(20)
        yt_label = QLabel("YouTube API 연동")
        yt_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 12px;"
        )
        layout.addWidget(yt_label)
        layout.addSpacing(10)

        yt_desc = QLabel(
            "Google 계정을 연결하면 YouTube 재생목록 동기화(읽기·쓰기)와\n"
            "구독 채널 가져오기를 사용할 수 있습니다.\n"
            "로그인은 기본 브라우저의 Google 페이지에서 안전하게 진행됩니다."
        )
        yt_desc.setStyleSheet(f"font-size: 9pt; color: {_t().text_secondary};")
        yt_desc.setWordWrap(True)
        layout.addWidget(yt_desc)
        layout.addSpacing(8)

        yt_btn_row = QHBoxLayout()
        self._yt_auth_btn = QPushButton("Google 계정으로 연결")
        self._yt_auth_btn.setFixedWidth(160)
        self._yt_auth_btn.clicked.connect(self._on_yt_auth)
        yt_btn_row.addWidget(self._yt_auth_btn)

        self._yt_disconnect_btn = QPushButton("연결 해제")
        self._yt_disconnect_btn.setFixedWidth(80)
        self._yt_disconnect_btn.clicked.connect(self._on_yt_disconnect)
        yt_btn_row.addWidget(self._yt_disconnect_btn)
        yt_btn_row.addStretch()
        layout.addLayout(yt_btn_row)
        layout.addSpacing(6)

        self._yt_status_lbl = QLabel()
        self._yt_status_lbl.setWordWrap(True)
        layout.addWidget(self._yt_status_lbl)
        self._refresh_yt_status()

    def _build_cookie_section(self, layout) -> None:
        """구독 피드용 브라우저 쿠키(YouTube API에 피드 엔드포인트가 없다)."""
        # ── 구독 피드 브라우저 쿠키 (YouTube API에는 피드 엔드포인트 없음) ──
        layout.addSpacing(16)
        feed_label = QLabel("구독 피드 — 브라우저 쿠키 (선택)")
        feed_label.setStyleSheet(
            f"font-size: 9px; font-weight: 600; letter-spacing: 0.5px; color: {_t().text_secondary};"
        )
        layout.addWidget(feed_label)
        feed_hint = QLabel(
            "YouTube API는 구독 피드(최신 영상 목록) 엔드포인트를 제공하지 않아\n"
            "브라우저 쿠키가 필요합니다. 가장 확실한 방법은 아래 '쿠키 파일 등록 "
            "방법 보기'입니다 — 평소 쓰던 브라우저로 직접 로그인한 뒤 내보내는 "
            "방식이라 항상 동작합니다."
        )
        feed_hint.setWordWrap(True)
        feed_hint.setStyleSheet(f"font-size: 8pt; color: {_t().text_secondary};")
        layout.addWidget(feed_hint)
        layout.addSpacing(6)

        self._browser_login_btn = QPushButton("브라우저 열어서 로그인")
        self._browser_login_btn.setToolTip(
            "이 앱이 직접 띄운 브라우저 창에서 로그인합니다. Google이 자동화된\n"
            "브라우저로 판단해 \"로그인할 수 없음\"으로 거부할 수 있습니다 —\n"
            "그런 경우 아래 '쿠키 파일 등록 방법 보기'를 이용하세요."
        )
        self._browser_login_btn.clicked.connect(self._on_open_auth_dialog)
        layout.addWidget(self._browser_login_btn)
        layout.addSpacing(10)

        adv_label = QLabel("고급: 기존 브라우저 프로필 직접 선택")
        adv_label.setStyleSheet(f"font-size: 8pt; color: {_t().text_muted};")
        layout.addWidget(adv_label)

        browser_row = QHBoxLayout()
        b_lbl = QLabel("브라우저")
        b_lbl.setFixedWidth(100)
        self._feed_browser_combo = QComboBox()
        self._feed_browser_combo.addItems(["firefox", "chrome", "edge", "chromium"])
        self._feed_browser_combo.setFixedWidth(120)
        self._feed_browser_combo.currentTextChanged.connect(self._on_feed_browser_changed)
        browser_row.addWidget(b_lbl)
        browser_row.addWidget(self._feed_browser_combo)
        browser_row.addStretch()
        layout.addLayout(browser_row)

        profile_row = QHBoxLayout()
        p_lbl = QLabel("프로필")
        p_lbl.setFixedWidth(100)
        self._feed_profile_combo = QComboBox()
        self._feed_profile_combo.setFixedWidth(220)
        self._feed_profile_combo.setToolTip("브라우저 프로필을 선택하세요")
        self._feed_profile_combo.currentIndexChanged.connect(self._on_feed_profile_changed)
        profile_row.addWidget(p_lbl)
        profile_row.addWidget(self._feed_profile_combo, 1)
        layout.addLayout(profile_row)

        cand_row = QHBoxLayout()
        cand_lbl = QLabel("감지된 쿠키 파일")
        cand_lbl.setFixedWidth(100)
        self._feed_cookie_candidates_combo = QComboBox()
        self._feed_cookie_candidates_combo.setToolTip(
            "다운로드·데스크톱 폴더에서 자동으로 찾은 쿠키 파일입니다. 선택하면 "
            "아래 경로란에 채워집니다."
        )
        self._feed_cookie_candidates_combo.currentIndexChanged.connect(
            self._on_cookie_candidate_selected
        )
        cand_refresh = QPushButton("다시 검색")
        cand_refresh.setFixedWidth(70)
        cand_refresh.clicked.connect(self._reload_cookie_candidates)
        cand_row.addWidget(cand_lbl)
        cand_row.addWidget(self._feed_cookie_candidates_combo, 1)
        cand_row.addWidget(cand_refresh)
        layout.addLayout(cand_row)

        cookie_row = QHBoxLayout()
        ck_lbl = QLabel("또는 쿠키 파일")
        ck_lbl.setFixedWidth(100)
        self._feed_cookie_edit = QLineEdit()
        self._feed_cookie_edit.setPlaceholderText("Netscape 포맷 쿠키 파일 경로 (선택)")
        ck_browse = QPushButton("찾기…")
        ck_browse.setFixedWidth(48)
        ck_browse.clicked.connect(self._on_browse_cookie_file)
        cookie_row.addWidget(ck_lbl)
        cookie_row.addWidget(self._feed_cookie_edit, 1)
        cookie_row.addWidget(ck_browse)
        layout.addLayout(cookie_row)

        ck_apply = QPushButton("쿠키 파일 적용")
        ck_apply.setFixedWidth(110)
        ck_apply.clicked.connect(self._on_apply_cookie_file)
        layout.addWidget(ck_apply)

        help_row = QHBoxLayout()
        self._cookie_help_btn = QPushButton("쿠키 파일 등록 방법 보기")
        self._cookie_help_btn.setFixedWidth(160)
        self._cookie_help_btn.clicked.connect(self._on_show_cookie_help)
        self._open_log_dir_btn = QPushButton("로그 폴더 열기")
        self._open_log_dir_btn.setFixedWidth(100)
        self._open_log_dir_btn.clicked.connect(self._on_open_log_dir)
        help_row.addWidget(self._cookie_help_btn)
        help_row.addWidget(self._open_log_dir_btn)
        help_row.addStretch()
        layout.addLayout(help_row)

        self._feed_status_lbl = QLabel()
        self._feed_status_lbl.setWordWrap(True)
        self._feed_status_lbl.setStyleSheet(f"font-size: 8pt; color: {_t().text_secondary};")
        layout.addWidget(self._feed_status_lbl)
        self._refresh_feed_auth_ui()

    def _build_hidden_tags_section(self, layout) -> None:
        """숨김 태그 관리 — 목록이 길어 맨 아래에 둔다."""
        # ── 숨김 태그 관리 섹션 (맨 아래 — 긴 목록이 다른 설정 접근을 방해하지 않도록) ──
        layout.addSpacing(28)
        sep_hidden = QFrame()
        sep_hidden.setFrameShape(QFrame.Shape.HLine)
        sep_hidden.setStyleSheet(f"color: {_t().border};")
        layout.addWidget(sep_hidden)
        layout.addSpacing(24)

        hidden_label = QLabel("숨김 태그 관리")
        hidden_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 12px;"
        )
        layout.addWidget(hidden_label)
        layout.addSpacing(10)

        if self._get_tags_fn is not None:
            self._hidden_tags_section = _HiddenTagsSection(self._get_tags_fn)
            self._hidden_tags_section.changed.connect(self.hidden_tags_changed.emit)
            layout.addWidget(self._hidden_tags_section)
        else:
            no_tags_lbl = QLabel("태그 목록을 불러올 수 없습니다.")
            no_tags_lbl.setStyleSheet(f"font-size: 10px; color: {_t().text_muted};")
            layout.addWidget(no_tags_lbl)
            self._hidden_tags_section = None


    def _build_update_header(self) -> QWidget:
        """헤더 우측 컴팩트 업데이트 위젯 — 자동확인 토글 + 상태 + (준비 시)설치 버튼."""
        try:
            from config import settings as s  # noqa: PLC0415
            cur_auto = s.AUTO_UPDATE_CHECK
        except Exception:
            logger.exception("업데이트 설정 로드 실패")
            cur_auto = True
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self._auto_update_check = QCheckBox("자동 업데이트")
        self._auto_update_check.setToolTip("시작 시 자동으로 업데이트를 확인·다운로드합니다")
        self._auto_update_check.setChecked(cur_auto)
        self._auto_update_check.checkStateChanged.connect(self._on_auto_update_changed)
        row.addWidget(self._auto_update_check)
        self._upd_status_lbl = QLabel(f"v{__version__}")
        self._upd_status_lbl.setStyleSheet(f"font-size: 11px; color: {_t().text_secondary};")
        row.addWidget(self._upd_status_lbl)
        # 수동 확인 — 자동 확인은 1시간 간격이라, 실패한 뒤 바로 다시 시도할 길이 필요하다.
        self._upd_check_btn = QPushButton("확인")
        self._upd_check_btn.setToolTip("지금 업데이트를 확인합니다")
        self._upd_check_btn.clicked.connect(self.check_update_requested.emit)
        row.addWidget(self._upd_check_btn)
        self._upd_install_btn = QPushButton("지금 설치")
        self._upd_install_btn.setToolTip("앱을 재시작하여 업데이트를 설치합니다")
        self._upd_install_btn.clicked.connect(self._on_install_update)
        self._upd_install_btn.hide()
        row.addWidget(self._upd_install_btn)
        return w

    # ------------------------------------------------------------------
    def set_update_ready(self, dto) -> None:
        """자동 다운로드 완료 — 헤더 상태를 '준비됨'으로 바꾸고 설치 버튼을 노출한다."""
        self._pending_dto = dto
        self._upd_status_lbl.setText(f"업데이트 준비됨 · v{dto.version}")
        self._upd_status_lbl.setStyleSheet(
            f"font-size: 11px; color: {sem('danger')}; font-weight: 600;"
        )
        self._upd_install_btn.setText("지금 설치")
        self._upd_install_btn.setToolTip("앱을 재시작하여 업데이트를 설치합니다")
        self._upd_install_btn.show()

    def set_update_available(self, dto) -> None:
        """새 버전을 찾았지만 자동 설치 준비에 실패한 상태.

        예전에는 이때 기어의 빨간 점만 켜지고 설정 화면은 그대로여서, 사용자가
        업데이트를 진행할 방법이 화면에 없었다. 여기서 직접 내려받을 버튼을 준다.
        """
        self._pending_dto = dto
        self._upd_status_lbl.setText(f"업데이트 있음 · v{dto.version}")
        self._upd_status_lbl.setStyleSheet(
            f"font-size: 11px; color: {sem('warning')}; font-weight: 600;"
        )
        self._upd_install_btn.setText("설치하기")
        self._upd_install_btn.setToolTip("업데이트를 내려받아 설치합니다")
        self._upd_install_btn.show()

    def set_update_busy(self, busy: bool) -> None:
        """확인·다운로드 진행 중 표시(중복 요청 방지)."""
        self._upd_check_btn.setEnabled(not busy)
        if busy:
            self._upd_status_lbl.setText("확인 중…")
            self._upd_status_lbl.setStyleSheet(
                f"font-size: 11px; color: {_t().text_secondary};"
            )
        elif self._pending_dto is None:
            self._upd_status_lbl.setText(f"v{__version__}")
            self._upd_status_lbl.setStyleSheet(
                f"font-size: 11px; color: {_t().text_secondary};"
            )

    def scroll_and_flash_update_section(self) -> None:
        # 업데이트 상태가 헤더에 상시 노출되므로 스크롤/플래시는 불필요(no-op).
        pass

    def _on_install_update(self) -> None:
        """'지금 설치' — 저장된 DTO로 설치를 요청한다(앱 재시작 후 pending 설치)."""
        if self._pending_dto is not None:
            self.install_update_requested.emit(self._pending_dto)

    # ------------------------------------------------------------------
    def showEvent(self, event) -> None:  # type: ignore[override]
        """설정 패널이 표시될 때 숨김 태그 목록을 최신 상태로 갱신한다."""
        super().showEvent(event)
        if self._hidden_tags_section is not None:
            self._hidden_tags_section.refresh()
        self._refresh_yt_status()
        self._refresh_feed_auth_ui()

    # ------------------------------------------------------------------
    def _on_concurrent_changed(self, value: int) -> None:
        from config import settings as s
        s.save_setting("max_concurrent_downloads", value)

    def _on_feed_workers_changed(self, value: int) -> None:
        from config import settings as s
        s.save_setting("max_concurrent_feed_workers", value)
        self.feed_workers_changed.emit(value)

    def _on_clipboard_changed(self, state) -> None:
        from config import settings as s
        checked = (state == Qt.CheckState.Checked)
        s.save_setting("clipboard_monitoring", checked)

    def _on_auto_enrich_changed(self, state) -> None:
        from config import settings as s
        checked = (state == Qt.CheckState.Checked)
        s.save_setting("auto_enrich_on_add", checked)

    def _on_browse_folder(self) -> None:
        from config import settings as s
        folder = QFileDialog.getExistingDirectory(
            self, "다운로드 폴더 선택", self._folder_edit.text()
        )
        if folder:
            self._folder_edit.setText(folder)
            s.save_path_setting("downloads", folder)

    def _on_quality_changed(self, index: int) -> None:
        from config import settings as s
        fmt = self._quality_combo.itemData(index)
        if fmt:
            s.save_setting("default_quality", fmt)

    def _on_format_changed(self, index: int) -> None:
        from config import settings as s
        fmt = self._format_combo.currentText()
        s.save_setting("default_format", fmt)

    def _on_auto_update_changed(self, state) -> None:
        from config import settings as s
        s.save_setting("auto_update_check", state == Qt.CheckState.Checked)

    # ------------------------------------------------------------------
    def _on_theme_changed(self, tokens: ThemeTokens) -> None:
        """테마 변경 시 선택 상태를 업데이트한다."""
        for name, card in self._theme_cards.items():
            card.set_selected(name == tokens.name)

    # ── YouTube API OAuth ──────────────────────────────────────────────────

    _YT_BTN_DISCONNECTED = "Google 계정으로 연결"
    _YT_BTN_WORKING = "연결 중…"
    _YT_BTN_CONNECTED = "Google 계정 다시 연결"

    def _refresh_yt_status(self) -> None:
        if self._yt_oauth is None:
            self._yt_status_lbl.setText("○ YouTube API 미초기화")
            self._yt_status_lbl.setStyleSheet(f"font-size: 9pt; color: {_t().text_secondary};")
            self._yt_auth_btn.setEnabled(False)
            return
        if not self._yt_oauth.has_client_config():
            self._yt_status_lbl.setText(
                "YouTube OAuth 설정이 앱에 포함되지 않았습니다. 배포자에게 문의하세요."
            )
            self._yt_status_lbl.setStyleSheet(f"font-size: 9pt; color: {sem('warning')};")
            self._yt_auth_btn.setEnabled(False)
            self._yt_auth_btn.setText(self._YT_BTN_DISCONNECTED)
            return
        self._yt_auth_btn.setEnabled(True)
        if self._yt_oauth.is_authenticated():
            name = self._yt_oauth.get_channel_name() or "인증됨"
            self._yt_status_lbl.setText(
                f"● 연결됨: {name}\n앱을 다시 시작하면 모든 YouTube 연동 기능이 활성화됩니다."
            )
            self._yt_status_lbl.setStyleSheet(f"font-size: 9pt; color: {sem('success')};")
            self._yt_auth_btn.setText(self._YT_BTN_CONNECTED)
        else:
            self._yt_status_lbl.setText("○ 미연결 — Google 계정으로 연결하세요")
            self._yt_status_lbl.setStyleSheet(f"font-size: 9pt; color: {sem('danger')};")
            self._yt_auth_btn.setText(self._YT_BTN_DISCONNECTED)

    def _on_yt_auth(self) -> None:
        if self._yt_oauth is None or not self._yt_oauth.has_client_config():
            return

        from PyQt6.QtCore import QThread, pyqtSignal as _sig  # noqa: PLC0415

        class _AuthWorker(QThread):
            done = _sig(str)   # channel_name or ""
            err  = _sig(str)

            def __init__(self, oauth, parent=None):
                super().__init__(parent)
                self._oauth = oauth

            def run(self):
                try:
                    self._oauth.run_auth_flow()
                    name = self._oauth.get_channel_name() or "인증됨"
                    self.done.emit(name)
                except Exception as exc:
                    logger.exception("YouTube OAuth 인증 실패")
                    self.err.emit(str(exc))

        self._yt_auth_btn.setEnabled(False)
        self._yt_auth_btn.setText(self._YT_BTN_WORKING)
        self._yt_status_lbl.setText("브라우저에서 Google 계정으로 승인하세요…")
        self._yt_status_lbl.setStyleSheet(f"font-size: 9pt; color: {_t().text_secondary};")

        # 인증 창이 떠 있는 동안 설정 화면을 떠나도 스레드가 파괴되지 않게 등록한다.
        worker = track_thread(_AuthWorker(self._yt_oauth))

        def _on_done(name: str) -> None:
            self._yt_auth_btn.setEnabled(True)
            self._yt_auth_btn.setText(self._YT_BTN_CONNECTED)
            self._yt_status_lbl.setText(
                f"● 연결됨: {name}\n앱을 다시 시작하면 모든 YouTube 연동 기능이 활성화됩니다."
            )
            self._yt_status_lbl.setStyleSheet(f"font-size: 9pt; color: {sem('success')};")
            self._yt_auth_worker = None

        def _on_err(msg: str) -> None:
            self._yt_auth_btn.setEnabled(True)
            self._yt_auth_btn.setText(self._YT_BTN_DISCONNECTED)
            self._yt_status_lbl.setText(f"연결 실패: {msg[:120]}")
            self._yt_status_lbl.setStyleSheet(f"font-size: 9pt; color: {sem('danger')};")
            self._yt_auth_worker = None

        worker.done.connect(_on_done)
        worker.err.connect(_on_err)
        self._yt_auth_worker = worker
        worker.start()

    def _on_yt_disconnect(self) -> None:
        if self._yt_oauth is None:
            return
        self._yt_oauth.clear()
        self._refresh_yt_status()

    # ── 브라우저 쿠키 (구독 피드) ──────────────────────────────────────────────

    def _refresh_feed_auth_ui(self) -> None:
        """현재 저장된 브라우저 쿠키 설정을 UI에 반영한다."""
        try:
            import config.settings as s  # noqa: PLC0415
            browser = getattr(s, "YT_AUTH_BROWSER", "firefox") or "firefox"
            idx = self._feed_browser_combo.findText(browser)
            if idx >= 0:
                self._feed_browser_combo.setCurrentIndex(idx)
            self._reload_profiles(browser)
            cookiefile = getattr(s, "YT_AUTH_COOKIEFILE", None)
            if cookiefile:
                self._feed_cookie_edit.setText(cookiefile)
            profile = getattr(s, "YT_AUTH_PROFILE", None)
            self._feed_status_lbl.setText(
                f"프로필: {profile}" if profile else
                (f"쿠키 파일: {cookiefile}" if cookiefile else "미설정")
            )
            self._reload_cookie_candidates()
        except Exception:
            logger.exception("브라우저 쿠키 설정 UI 반영 실패")

    def _reload_cookie_candidates(self) -> None:
        """다운로드·데스크톱 폴더에서 쿠키 파일 후보를 다시 스캔해 목록에 채운다."""
        from infrastructure.auth.youtube_auth import (  # noqa: PLC0415
            find_cookie_file_candidates,
        )

        self._feed_cookie_candidates_combo.blockSignals(True)
        self._feed_cookie_candidates_combo.clear()
        try:
            candidates = find_cookie_file_candidates()
        except Exception:
            logger.exception("쿠키 파일 후보 탐색 실패")
            candidates = []
        if candidates:
            self._feed_cookie_candidates_combo.addItem("아래에서 선택하세요", None)
            for path in candidates:
                self._feed_cookie_candidates_combo.addItem(
                    f"{path.name}  ({path.parent.name})", str(path)
                )
        else:
            self._feed_cookie_candidates_combo.addItem(
                "다운로드·데스크톱에서 찾지 못함 — 아래 '찾기…'로 직접 선택", None
            )
        self._feed_cookie_candidates_combo.blockSignals(False)

    def _on_cookie_candidate_selected(self, _index: int) -> None:
        path = self._feed_cookie_candidates_combo.currentData()
        if not path:
            return
        self._feed_cookie_edit.setText(path)

    def _on_open_auth_dialog(self) -> None:
        """자체 브라우저 창을 띄워 로그인시키고 쿠키를 직접 캡처하는 다이얼로그를 연다.

        기존 브라우저의 쿠키 DB를 복사하지 않아(Chrome 잠금·App-Bound Encryption과
        무관) 자동 감지가 실패하는 환경에서도 동작한다. "쿠키를 왜 찾아야 하냐,
        브라우저를 띄워서 로그인시키면 안 되냐"는 사용자 요청으로 연결됨 —
        `YouTubeAuthDialog`는 이미 구현돼 있었지만 이 버튼이 생기기 전까지는
        앱 어디에서도 열리지 않는 코드였다.
        """
        from infrastructure.auth.youtube_auth import YouTubeAuthService  # noqa: PLC0415
        from gui.dialogs.youtube_auth_dialog import YouTubeAuthDialog  # noqa: PLC0415

        dialog = YouTubeAuthDialog(YouTubeAuthService(), self)
        dialog.auth_changed.connect(self._refresh_feed_auth_ui)
        dialog.exec()

    def _reload_profiles(self, browser: str) -> None:
        from infrastructure.auth.youtube_auth import YouTubeAuthService  # noqa: PLC0415
        import config.settings as s  # noqa: PLC0415
        self._feed_profile_combo.blockSignals(True)
        self._feed_profile_combo.clear()
        self._feed_profile_combo.addItem("(선택 안 함)", None)
        try:
            profiles = YouTubeAuthService().detect_profiles(browser)
            for p in profiles:
                self._feed_profile_combo.addItem(p.display_name, p.profile_key)
            # 현재 저장된 프로필 선택
            saved = getattr(s, "YT_AUTH_PROFILE", None)
            if saved:
                for i in range(self._feed_profile_combo.count()):
                    if self._feed_profile_combo.itemData(i) == saved:
                        self._feed_profile_combo.setCurrentIndex(i)
                        break
        except Exception:
            logger.exception("브라우저 프로필 목록 로드 실패")
        finally:
            self._feed_profile_combo.blockSignals(False)

    def _on_feed_browser_changed(self, browser: str) -> None:
        self._reload_profiles(browser)

    def _on_feed_profile_changed(self, _index: int) -> None:
        profile_key = self._feed_profile_combo.currentData()
        if profile_key is None:
            return
        from infrastructure.auth.youtube_auth import YouTubeAuthService  # noqa: PLC0415
        browser = self._feed_browser_combo.currentText()
        YouTubeAuthService().save_auth(browser=browser, profile_key=profile_key, cookiefile=None)
        self._feed_status_lbl.setText(
            f"저장됨: {self._feed_profile_combo.currentText()}"
        )
        self._feed_status_lbl.setStyleSheet(f"font-size: 8pt; color: {sem('success')};")

    def _on_browse_cookie_file(self) -> None:
        from PyQt6.QtWidgets import QFileDialog  # noqa: PLC0415
        path, _ = QFileDialog.getOpenFileName(
            self, "쿠키 파일 선택", "", "텍스트 파일 (*.txt);;모든 파일 (*)"
        )
        if path:
            self._feed_cookie_edit.setText(path)

    def _on_apply_cookie_file(self) -> None:
        cookiefile = self._feed_cookie_edit.text().strip()
        if not cookiefile:
            return
        from infrastructure.auth.youtube_auth import YouTubeAuthService  # noqa: PLC0415
        browser = self._feed_browser_combo.currentText()
        YouTubeAuthService().save_auth(browser=browser, profile_key=None, cookiefile=cookiefile)
        self._feed_status_lbl.setText("쿠키 파일이 설정되었습니다.")
        self._feed_status_lbl.setStyleSheet(f"font-size: 8pt; color: {sem('success')};")

    def _on_show_cookie_help(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("쿠키 파일 등록 방법")
        v = QVBoxLayout(dialog)
        text_lbl = QLabel(COOKIE_HELP_TEXT)
        text_lbl.setWordWrap(True)
        v.addWidget(text_lbl)
        btn_row = QHBoxLayout()
        dl_btn = QPushButton("다운로드 폴더 열기")
        dl_btn.clicked.connect(lambda: open_folder(Path.home() / "Downloads"))
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(dialog.accept)
        btn_row.addWidget(dl_btn)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        v.addLayout(btn_row)
        dialog.exec()

    def _on_open_log_dir(self) -> None:
        from config import settings as s  # noqa: PLC0415
        open_folder(s.LOG_DIR)
