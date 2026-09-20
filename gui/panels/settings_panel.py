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
    QInputDialog,
    QLabel,
    QLineEdit,
    QProgressBar,
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
        cleanup_fns=None,        # (중복찾기, 사라진파일찾기, 삭제, 원본소실찾기) | None
        subtitle_vm=None,        # SubtitleViewModel | None
        get_categories_fn: Callable | None = None,
        add_videos_fn: Callable | None = None,   # (urls, category_id) -> None
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._get_tags_fn = get_tags_fn
        self._subtitle_vm = subtitle_vm
        self._yt_oauth = yt_oauth
        self._song_vm = song_vm
        self._sync_vm = sync_vm
        self._transfer_vm = transfer_vm
        # 라이브러리 정리 — 조회·삭제를 콜백으로 받는다(설정 화면은 저장소를 모른다).
        self._cleanup_fns = cleanup_fns
        self._get_categories_fn = get_categories_fn
        # 북마크 가져오기가 영상을 담을 때 쓴다. 없으면 그 섹션을 만들지 않는다.
        self._add_videos_fn = add_videos_fn
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

        self._build_help_section(layout)
        self._add_divider(layout)
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
        self._build_watch_folder_section(layout)
        self._build_bookmark_section(layout)
        self._build_cleanup_section(layout)
        self._build_subtitle_index_section(layout)
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

    def _build_help_section(self, layout) -> None:
        """도움말 — 상세 설명서로 가는 길. F1과 같은 곳을 연다.

        설정은 "어디서 찾지?"를 가장 먼저 열어 보는 화면이라 맨 위에 둔다.
        """
        label = QLabel("도움말")
        label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 8px;"
        )
        layout.addWidget(label)
        hint = QLabel(
            "화면별 사용법과 화면 갈무리를 담은 상세 설명서를 기본 브라우저로 엽니다. "
            "어느 화면에서든 F1 을 눌러도 같은 문서가 열립니다."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size: 10px; color: {_t().text_secondary};")
        layout.addWidget(hint)
        button = QPushButton("상세 설명서 열기  (F1)")
        button.setToolTip("상세 설명서를 기본 브라우저로 엽니다 (F1)")
        button.clicked.connect(self._open_manual)
        layout.addWidget(button)
        layout.addSpacing(4)

    def _open_manual(self) -> None:
        from gui.help import open_manual  # noqa: PLC0415

        open_manual()

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

        self._build_notify_rows(layout)
        layout.addSpacing(28)

    # ── 알림 · 새 영상 감시 ───────────────────────────────────────

    def _build_notify_rows(self, layout) -> None:
        """트레이 알림과 구독 채널 새 영상 감시.

        다운로드는 몇 분~몇 시간이 걸린다. 그동안 사용자는 이 앱을 보고 있지 않아
        앱 안의 토스트로는 끝났다는 소식이 전달되지 않는다.
        """
        from config import settings as cfg  # noqa: PLC0415
        from domain.monitoring.watch import (  # noqa: PLC0415
            MAX_INTERVAL_MIN,
            MIN_INTERVAL_MIN,
            clamp_interval,
        )
        from gui.tray import AppTray  # noqa: PLC0415

        layout.addSpacing(10)
        self._tray_check = QCheckBox("작업이 끝나면 트레이로 알리기")
        self._tray_check.setChecked(bool(cfg.TRAY_NOTIFICATIONS))
        self._tray_check.checkStateChanged.connect(self._on_tray_notify_changed)
        layout.addWidget(self._tray_check)

        if not AppTray.is_available():
            # 트레이가 없는 데스크톱이 있다 — 켤 수 있게 두면 켜 놓고 안 온다고 한다.
            self._tray_check.setEnabled(False)
            self._tray_check.setToolTip("이 환경에는 시스템 트레이가 없습니다.")

        self._watch_check = QCheckBox("구독 채널에 새 영상이 올라오면 알리기")
        self._watch_check.setChecked(bool(cfg.WATCH_NEW_VIDEOS))
        self._watch_check.checkStateChanged.connect(self._on_watch_changed)
        layout.addWidget(self._watch_check)

        int_row = QHBoxLayout()
        int_row.setContentsMargins(22, 0, 0, 0)
        int_lbl = QLabel("확인 주기(분)")
        int_lbl.setFixedWidth(100)
        self._watch_spin = QSpinBox()
        self._watch_spin.setRange(MIN_INTERVAL_MIN, MAX_INTERVAL_MIN)
        self._watch_spin.setValue(clamp_interval(cfg.WATCH_INTERVAL_MIN))
        self._watch_spin.setFixedWidth(80)
        self._watch_spin.valueChanged.connect(self._on_watch_interval_changed)
        int_row.addWidget(int_lbl)
        int_row.addWidget(self._watch_spin)
        int_row.addStretch()
        layout.addLayout(int_row)

        hint = QLabel(
            "확인은 배경에서 조용히 이뤄지며 보고 있는 목록을 건드리지 않습니다. "
            "너무 자주 확인하면 YouTube가 요청을 막을 수 있어 최소 "
            f"{MIN_INTERVAL_MIN}분입니다. 바꾼 주기는 앱을 다시 켤 때 적용됩니다."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size: 10px; color: {_t().text_secondary}; margin-left: 22px;")
        layout.addWidget(hint)

    def _on_tray_notify_changed(self, _state) -> None:
        self._save_setting("tray_notifications", self._tray_check.isChecked())

    def _on_watch_changed(self, _state) -> None:
        self._save_setting("watch_new_videos", self._watch_check.isChecked())

    def _on_watch_interval_changed(self, value: int) -> None:
        from domain.monitoring.watch import clamp_interval  # noqa: PLC0415

        self._save_setting("watch_interval_min", clamp_interval(value))

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
        layout.addSpacing(18)

        self._build_preset_rows(layout)
        self._build_embed_rows(layout)
        layout.addSpacing(28)

    # ── 다운로드 프리셋 ───────────────────────────────────────────

    def _build_preset_rows(self, layout) -> None:
        """받는 방식을 이름 붙여 고르기.

        같은 사람이 영상을 받는 방식은 몇 가지로 갈린다(보관용·음악·가볍게). 그때마다
        아래 설정을 오가는 대신 골라 쓴다. **전송 옵션(속도·프록시)은 프리셋이 정하지
        않는다** — 회선의 성질이라 무엇을 받든 같기 때문이다.
        """
        from application.download.defaults import available_presets  # noqa: PLC0415
        from config import settings as cfg  # noqa: PLC0415

        layout.addSpacing(10)
        row = QHBoxLayout()
        lbl = QLabel("받는 방식")
        lbl.setFixedWidth(100)
        self._preset_combo = QComboBox()
        self._preset_combo.addItem("프리셋 없음 (아래 설정 그대로)", "")
        for preset in available_presets():
            self._preset_combo.addItem(preset.name, preset.key)
        idx = self._preset_combo.findData(cfg.ACTIVE_PRESET_KEY or "")
        self._preset_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._preset_combo.setFixedWidth(240)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        row.addWidget(lbl)
        row.addWidget(self._preset_combo)
        row.addStretch()

        self._preset_save_btn = QPushButton("지금 설정을 프리셋으로…")
        self._preset_save_btn.setFixedWidth(160)
        self._preset_save_btn.clicked.connect(self._on_preset_save)
        row.addWidget(self._preset_save_btn)

        self._preset_del_btn = QPushButton("프리셋 지우기")
        self._preset_del_btn.setFixedWidth(100)
        self._preset_del_btn.clicked.connect(self._on_preset_delete)
        row.addWidget(self._preset_del_btn)
        layout.addLayout(row)

        self._preset_hint = QLabel("")
        self._preset_hint.setWordWrap(True)
        self._preset_hint.setStyleSheet(
            f"font-size: 10px; color: {_t().text_secondary};"
        )
        layout.addWidget(self._preset_hint)
        self._refresh_preset_hint()

    def _refresh_preset_hint(self) -> None:
        from application.download.defaults import available_presets  # noqa: PLC0415
        from domain.download.download_presets import find  # noqa: PLC0415

        key = self._preset_combo.currentData() or ""
        preset = find(available_presets(), key) if key else None
        self._preset_del_btn.setEnabled(preset is not None)
        if preset is None:
            self._preset_hint.setText(
                "프리셋을 고르면 아래 화질·형식·자막·굽기 설정 대신 그 방식으로 받습니다. "
                "속도 제한·프록시 같은 전송 옵션은 프리셋과 무관하게 늘 적용됩니다."
            )
            return
        langs = preset.subtitle_langs or "자막 없음"
        self._preset_hint.setText(
            f"{preset.quality} · {preset.fmt} · 자막 {langs}"
            + (" · 광고 잘라내기" if preset.sponsorblock_remove else "")
        )

    def _on_preset_changed(self, _index: int) -> None:
        self._save_setting("active_preset_key", self._preset_combo.currentData() or "")
        self._refresh_preset_hint()

    def _on_preset_save(self) -> None:
        """지금 화면의 설정을 프리셋으로 굳힌다."""
        from config import settings as cfg  # noqa: PLC0415
        from domain.download.download_presets import (  # noqa: PLC0415
            DownloadPreset,
            quality_from_selector,
            unique_name,
        )
        from application.download.defaults import available_presets  # noqa: PLC0415
        import uuid as _uuid  # noqa: PLC0415

        name, ok = QInputDialog.getText(self, "프리셋 저장", "이름", text="내 프리셋")
        if not ok:
            return
        existing = [p.name for p in available_presets()]
        preset = DownloadPreset(
            key=f"user:{_uuid.uuid4().hex[:8]}",
            name=unique_name(name, existing),
            quality=quality_from_selector(self._quality_combo.currentData()),
            fmt=self._format_combo.currentText() or "mp4",
            subtitle_langs=self._sub_langs_edit.text().strip(),
            embed_subtitles=self._embed_subs_check.isChecked(),
            embed_thumbnail=self._embed_thumb_check.isChecked(),
            embed_chapters=self._embed_chapters_check.isChecked(),
            sponsorblock_remove=self._sb_remove_check.isChecked(),
        )
        saved = list(cfg.DOWNLOAD_PRESETS or []) + [preset.to_payload()]
        self._save_setting("download_presets", saved)
        self._preset_combo.addItem(preset.name, preset.key)
        self._preset_combo.setCurrentIndex(self._preset_combo.count() - 1)

    def _on_preset_delete(self) -> None:
        """고른 프리셋을 목록에서 뺀다.

        내장 프리셋은 지울 수 없으니 **숨긴다** — 코드에 있는 것을 설정으로 없앨
        방법이 달리 없고, 안 쓰는 항목이 목록에 남으면 고르기를 방해한다.
        """
        from config import settings as cfg  # noqa: PLC0415
        from domain.download.download_presets import BUILTIN_PREFIX  # noqa: PLC0415

        key = self._preset_combo.currentData() or ""
        if not key:
            return
        if key.startswith(BUILTIN_PREFIX):
            hidden = list(cfg.HIDDEN_PRESET_KEYS or [])
            if key not in hidden:
                hidden.append(key)
            self._save_setting("hidden_preset_keys", hidden)
        else:
            self._save_setting(
                "download_presets",
                [p for p in (cfg.DOWNLOAD_PRESETS or []) if p.get("key") != key],
            )
        self._preset_combo.removeItem(self._preset_combo.currentIndex())
        self._preset_combo.setCurrentIndex(0)

    def _build_embed_rows(self, layout) -> None:
        """부가 정보를 받은 파일 안에 굽는 설정(자막·표지·챕터·노래 태그)."""
        try:
            from config import settings as s
            cur_sub_langs = s.DOWNLOAD_SUBTITLE_LANGS
            cur_embed_subs = s.EMBED_SUBTITLES
            cur_embed_thumb = s.EMBED_THUMBNAIL
            cur_embed_chapters = s.EMBED_CHAPTERS
            cur_song_tags = s.WRITE_SONG_TAGS
        except Exception:
            logger.exception("굽기 설정 로드 실패")
            cur_sub_langs = ""
            cur_embed_subs = cur_embed_thumb = cur_embed_chapters = cur_song_tags = True

        embed_lbl = QLabel("파일에 포함")
        embed_lbl.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted};"
        )
        layout.addWidget(embed_lbl)
        layout.addSpacing(8)

        # 자막 언어 — 비우면 자막을 아예 받지 않는다(굽기 체크도 무의미해진다).
        sub_row = QHBoxLayout()
        sub_row.setContentsMargins(0, 0, 0, 0)
        sub_lbl = QLabel("자막 언어")
        sub_lbl.setFixedWidth(100)
        sub_lbl.setStyleSheet("font-size: 11px;")
        self._sub_langs_edit = QLineEdit(cur_sub_langs)
        self._sub_langs_edit.setPlaceholderText("비우면 자막을 받지 않습니다 (예: ko,en)")
        self._sub_langs_edit.editingFinished.connect(self._on_sub_langs_changed)
        sub_row.addWidget(sub_lbl)
        sub_row.addWidget(self._sub_langs_edit, 1)
        layout.addLayout(sub_row)
        layout.addSpacing(10)

        self._embed_subs_check = QCheckBox("자막을 영상 파일에 포함")
        self._embed_subs_check.setChecked(cur_embed_subs)
        self._embed_subs_check.checkStateChanged.connect(self._on_embed_subs_changed)
        layout.addWidget(self._embed_subs_check)

        self._embed_thumb_check = QCheckBox("썸네일을 표지로 포함")
        self._embed_thumb_check.setChecked(cur_embed_thumb)
        self._embed_thumb_check.checkStateChanged.connect(self._on_embed_thumb_changed)
        layout.addWidget(self._embed_thumb_check)

        self._embed_chapters_check = QCheckBox("챕터 정보를 포함")
        self._embed_chapters_check.setChecked(cur_embed_chapters)
        self._embed_chapters_check.checkStateChanged.connect(self._on_embed_chapters_changed)
        layout.addWidget(self._embed_chapters_check)

        self._song_tags_check = QCheckBox("음원에 노래 정보(가수·앨범·가사·표지) 기록")
        self._song_tags_check.setChecked(cur_song_tags)
        self._song_tags_check.checkStateChanged.connect(self._on_song_tags_changed)
        layout.addWidget(self._song_tags_check)

        embed_hint = QLabel(
            "받은 파일 하나만 옮겨도 자막·표지·챕터가 따라가므로 다른 플레이어·차량·"
            "휴대폰에서도 그대로 보입니다. 굽기를 켜면 자막은 별도 파일로 남기지 "
            "않습니다(플레이어가 같은 자막을 두 번 잡는 것을 막습니다)."
        )
        embed_hint.setWordWrap(True)
        embed_hint.setStyleSheet(
            f"font-size: 10px; color: {_t().text_secondary}; margin-left: 22px;"
        )
        layout.addWidget(embed_hint)
        layout.addSpacing(18)
        self._build_transfer_rows(layout)
        layout.addSpacing(18)
        self._build_sponsorblock_rows(layout)

    def _build_transfer_rows(self, layout) -> None:
        """전송 옵션(속도 제한·조각 병렬·프록시)과 예약 시간대."""
        from domain.download.schedule import MAX_CONCURRENT, MIN_CONCURRENT  # noqa: PLC0415

        try:
            from config import settings as s
            cur_rate = s.DOWNLOAD_RATE_LIMIT
            cur_frag = s.CONCURRENT_FRAGMENTS
            cur_proxy = s.DOWNLOAD_PROXY
            cur_win_on = s.DOWNLOAD_WINDOW_ENABLED
            cur_win_start = s.DOWNLOAD_WINDOW_START
            cur_win_end = s.DOWNLOAD_WINDOW_END
        except Exception:
            logger.exception("전송 옵션 로드 실패")
            cur_rate, cur_frag, cur_proxy = "", 1, ""
            cur_win_on, cur_win_start, cur_win_end = False, 23, 7

        tr_lbl = QLabel("전송")
        tr_lbl.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted};"
        )
        layout.addWidget(tr_lbl)
        layout.addSpacing(8)

        rate_row = QHBoxLayout()
        rate_row.setContentsMargins(0, 0, 0, 0)
        rate_lbl = QLabel("속도 제한")
        rate_lbl.setFixedWidth(100)
        rate_lbl.setStyleSheet("font-size: 11px;")
        self._rate_edit = QLineEdit(cur_rate)
        self._rate_edit.setPlaceholderText("비우면 무제한 (예: 2M, 500K)")
        self._rate_edit.editingFinished.connect(self._on_rate_limit_changed)
        rate_row.addWidget(rate_lbl)
        rate_row.addWidget(self._rate_edit, 1)
        layout.addLayout(rate_row)
        layout.addSpacing(10)

        frag_row = QHBoxLayout()
        frag_row.setContentsMargins(0, 0, 0, 0)
        frag_lbl = QLabel("조각 동시 수")
        frag_lbl.setFixedWidth(100)
        frag_lbl.setStyleSheet("font-size: 11px;")
        self._frag_spin = QSpinBox()
        self._frag_spin.setRange(1, 16)
        self._frag_spin.setValue(max(1, int(cur_frag or 1)))
        self._frag_spin.setFixedWidth(64)
        self._frag_spin.valueChanged.connect(self._on_fragments_changed)
        frag_hint = QLabel("1이면 끕니다. 고화질 영상에서 체감이 큽니다.")
        frag_hint.setStyleSheet(f"font-size: 10px; color: {_t().text_secondary};")
        frag_row.addWidget(frag_lbl)
        frag_row.addWidget(self._frag_spin)
        frag_row.addWidget(frag_hint)
        frag_row.addStretch()
        layout.addLayout(frag_row)
        layout.addSpacing(10)

        proxy_row = QHBoxLayout()
        proxy_row.setContentsMargins(0, 0, 0, 0)
        proxy_lbl = QLabel("프록시")
        proxy_lbl.setFixedWidth(100)
        proxy_lbl.setStyleSheet("font-size: 11px;")
        self._proxy_edit = QLineEdit(cur_proxy)
        self._proxy_edit.setPlaceholderText("비우면 사용 안 함 (예: socks5://127.0.0.1:1080)")
        self._proxy_edit.editingFinished.connect(self._on_proxy_changed)
        proxy_row.addWidget(proxy_lbl)
        proxy_row.addWidget(self._proxy_edit, 1)
        layout.addLayout(proxy_row)
        layout.addSpacing(14)

        # ── 예약 시간대 ──
        self._window_check = QCheckBox("정해진 시간대에만 받기")
        self._window_check.setChecked(cur_win_on)
        self._window_check.checkStateChanged.connect(self._on_window_toggled)
        layout.addWidget(self._window_check)

        win_row = QHBoxLayout()
        win_row.setContentsMargins(22, 4, 0, 0)
        self._win_start_spin = QSpinBox()
        self._win_start_spin.setRange(0, 23)
        self._win_start_spin.setValue(int(cur_win_start) % 24)
        self._win_start_spin.setSuffix("시")
        self._win_start_spin.setFixedWidth(64)
        self._win_start_spin.valueChanged.connect(self._on_window_hours_changed)
        self._win_end_spin = QSpinBox()
        self._win_end_spin.setRange(0, 23)
        self._win_end_spin.setValue(int(cur_win_end) % 24)
        self._win_end_spin.setSuffix("시")
        self._win_end_spin.setFixedWidth(64)
        self._win_end_spin.valueChanged.connect(self._on_window_hours_changed)
        win_row.addWidget(self._win_start_spin)
        win_row.addWidget(QLabel("~"))
        win_row.addWidget(self._win_end_spin)
        win_row.addStretch()
        layout.addLayout(win_row)

        self._window_hint = QLabel("")
        self._window_hint.setWordWrap(True)
        self._window_hint.setStyleSheet(
            f"font-size: 10px; color: {_t().text_secondary}; margin-left: 22px;"
        )
        layout.addWidget(self._window_hint)
        self._refresh_window_hint()

        tr_hint = QLabel(
            f"동시에 받는 영상 수는 위 '일반'의 동시 다운로드 수({MIN_CONCURRENT}~"
            f"{MAX_CONCURRENT})를 따릅니다. 자리가 찰 때까지 나머지는 대기합니다."
        )
        tr_hint.setWordWrap(True)
        tr_hint.setStyleSheet(f"font-size: 10px; color: {_t().text_secondary};")
        layout.addWidget(tr_hint)

    def _refresh_window_hint(self) -> None:
        from domain.download.schedule import DownloadWindow  # noqa: PLC0415

        window = DownloadWindow(
            enabled=self._window_check.isChecked(),
            start_hour=self._win_start_spin.value(),
            end_hour=self._win_end_spin.value(),
        )
        self._window_hint.setText(window.describe())
        for spin in (self._win_start_spin, self._win_end_spin):
            spin.setEnabled(self._window_check.isChecked())

    def _on_rate_limit_changed(self) -> None:
        self._save_setting("download_rate_limit", self._rate_edit.text().strip())

    def _on_fragments_changed(self, value: int) -> None:
        self._save_setting("concurrent_fragments", int(value))

    def _on_proxy_changed(self) -> None:
        self._save_setting("download_proxy", self._proxy_edit.text().strip())

    def _on_window_toggled(self, _state) -> None:
        self._save_setting("download_window_enabled", self._window_check.isChecked())
        self._refresh_window_hint()

    def _on_window_hours_changed(self, _value) -> None:
        self._save_setting("download_window_start", self._win_start_spin.value())
        self._save_setting("download_window_end", self._win_end_spin.value())
        self._refresh_window_hint()

    def _build_sponsorblock_rows(self, layout) -> None:
        """SponsorBlock — 재생 중 건너뛰기 / 다운로드 시 잘라내기."""
        from domain.clip.sponsor import SKIP_CATEGORY_NAMES  # noqa: PLC0415

        try:
            from config import settings as s
            cur_skip = s.SPONSORBLOCK_SKIP
            cur_remove = s.SPONSORBLOCK_REMOVE
            cur_cats = {c.strip() for c in s.SPONSORBLOCK_CATEGORIES.split(",") if c.strip()}
        except Exception:
            logger.exception("SponsorBlock 설정 로드 실패")
            cur_skip, cur_remove, cur_cats = True, False, set()

        sb_lbl = QLabel("SponsorBlock")
        sb_lbl.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted};"
        )
        layout.addWidget(sb_lbl)
        layout.addSpacing(8)

        self._sb_skip_check = QCheckBox("재생 중 자동으로 건너뛰기")
        self._sb_skip_check.setChecked(cur_skip)
        self._sb_skip_check.checkStateChanged.connect(self._on_sb_skip_changed)
        layout.addWidget(self._sb_skip_check)

        self._sb_remove_check = QCheckBox("다운로드한 파일에서 잘라내기")
        self._sb_remove_check.setChecked(cur_remove)
        self._sb_remove_check.checkStateChanged.connect(self._on_sb_remove_changed)
        layout.addWidget(self._sb_remove_check)

        # 카테고리 — 건너뛰기와 잘라내기가 **같은 목록**을 쓴다.
        self._sb_cat_checks: dict[str, QCheckBox] = {}
        cat_box = QVBoxLayout()
        cat_box.setContentsMargins(22, 4, 0, 0)
        cat_box.setSpacing(2)
        for key, name in SKIP_CATEGORY_NAMES.items():
            check = QCheckBox(name)
            check.setChecked(key in cur_cats)
            check.checkStateChanged.connect(self._on_sb_categories_changed)
            self._sb_cat_checks[key] = check
            cat_box.addWidget(check)
        layout.addLayout(cat_box)

        sb_hint = QLabel(
            "SponsorBlock은 사용자들이 모은 공개 구간 정보입니다. 조회는 영상 ID를 "
            "그대로 보내지 않고 해시 앞자리만 보내므로 어떤 영상을 보는지 서버가 알 수 "
            "없습니다. 잘라내기는 파일을 실제로 바꾸므로 되돌릴 수 없습니다."
        )
        sb_hint.setWordWrap(True)
        sb_hint.setStyleSheet(
            f"font-size: 10px; color: {_t().text_secondary}; margin-left: 22px;"
        )
        layout.addWidget(sb_hint)

    def _on_sb_skip_changed(self, _state) -> None:
        self._save_setting("sponsorblock_skip", self._sb_skip_check.isChecked())

    def _on_sb_remove_changed(self, _state) -> None:
        self._save_setting("sponsorblock_remove", self._sb_remove_check.isChecked())

    def _on_sb_categories_changed(self, _state) -> None:
        picked = ",".join(k for k, c in self._sb_cat_checks.items() if c.isChecked())
        self._save_setting("sponsorblock_categories", picked)

    @staticmethod
    def _save_setting(key: str, value) -> None:
        from config import settings as s  # noqa: PLC0415
        s.save_setting(key, value)

    def _on_sub_langs_changed(self) -> None:
        self._save_setting("download_subtitle_langs", self._sub_langs_edit.text().strip())

    def _on_embed_subs_changed(self, _state) -> None:
        self._save_setting("embed_subtitles", self._embed_subs_check.isChecked())

    def _on_embed_thumb_changed(self, _state) -> None:
        self._save_setting("embed_thumbnail", self._embed_thumb_check.isChecked())

    def _on_embed_chapters_changed(self, _state) -> None:
        self._save_setting("embed_chapters", self._embed_chapters_check.isChecked())

    def _on_song_tags_changed(self, _state) -> None:
        self._save_setting("write_song_tags", self._song_tags_check.isChecked())

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

    # ── 워치 폴더 ─────────────────────────────────────────────────

    def _build_watch_folder_section(self, layout) -> None:
        """주소가 담긴 파일을 떨구면 알아서 담는 폴더.

        브라우저에서 주소를 앱까지 끌어다 놓으려면 앱이 떠 있어야 한다. 폴더 하나를
        정해 두면 앱이 꺼져 있어도 거기 모아 뒀다가 켤 때 한꺼번에 담는다.
        """
        from config import settings as cfg  # noqa: PLC0415
        from domain.library.watch_folder import (  # noqa: PLC0415
            DONE_DIR_NAME,
            WATCHED_SUFFIXES,
        )

        self._add_divider(layout)
        label = QLabel("워치 폴더")
        label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted};"
        )
        layout.addWidget(label)
        layout.addSpacing(8)

        hint = QLabel(
            f"이 폴더에 주소가 든 파일({' · '.join(WATCHED_SUFFIXES)})을 넣어 두면 "
            "앱이 30초마다 훑어 라이브러리에 담습니다. 브라우저에서 링크를 폴더로 끌면 "
            f".url 파일이 생기므로 그것만으로 끝납니다. 담은 파일은 '{DONE_DIR_NAME}' "
            "폴더로 옮겨 둬, 무엇이 처리됐는지 폴더만 봐도 알 수 있습니다."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size: 10px; color: {_t().text_secondary};")
        layout.addWidget(hint)

        row = QHBoxLayout()
        row.setContentsMargins(0, 6, 0, 0)
        self._watch_edit = QLineEdit()
        self._watch_edit.setPlaceholderText("비워 두면 쓰지 않습니다")
        self._watch_edit.setText(cfg.WATCH_FOLDER or "")
        self._watch_edit.editingFinished.connect(self._on_watch_folder_changed)
        browse = QPushButton("찾기…")
        browse.setFixedWidth(60)
        browse.clicked.connect(self._on_watch_folder_browse)
        clear = QPushButton("사용 안 함")
        clear.setFixedWidth(80)
        clear.clicked.connect(self._on_watch_folder_clear)
        row.addWidget(self._watch_edit, 1)
        row.addWidget(browse)
        row.addWidget(clear)
        layout.addLayout(row)

        self._watch_status = QLabel("")
        self._watch_status.setWordWrap(True)
        self._watch_status.setStyleSheet(
            f"font-size: 10px; color: {_t().text_secondary};"
        )
        layout.addWidget(self._watch_status)
        layout.addSpacing(24)
        self._refresh_watch_status()

    def _refresh_watch_status(self) -> None:
        """설정된 폴더가 **실제로 있는지** 알린다.

        경로만 적어 두면 오타나 옮겨진 폴더를 알아차릴 수 없다 — 쿠키 파일에서
        똑같은 일이 있었다.
        """
        from pathlib import Path as _Path  # noqa: PLC0415

        raw = self._watch_edit.text().strip()
        if not raw:
            self._watch_status.setText("쓰지 않는 중입니다.")
            return
        if not _Path(raw).is_dir():
            self._watch_status.setText("⚠ 이 경로에 폴더가 없습니다.")
            return
        self._watch_status.setText(
            "폴더를 확인했습니다. 바뀐 설정은 앱을 다시 켤 때 적용됩니다."
        )

    def _on_watch_folder_changed(self) -> None:
        self._save_setting("watch_folder", self._watch_edit.text().strip())
        self._refresh_watch_status()

    def _on_watch_folder_browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "워치 폴더 선택")
        if folder:
            self._watch_edit.setText(folder)
            self._on_watch_folder_changed()

    def _on_watch_folder_clear(self) -> None:
        self._watch_edit.clear()
        self._on_watch_folder_changed()

    # ── 북마크에서 가져오기 ───────────────────────────────────────

    def _build_bookmark_section(self, layout) -> None:
        """브라우저 북마크(HTML)에서 영상을 담아온다.

        브라우저마다 내보내기 메뉴는 다르지만 결과 형식은 하나로 수렴한다
        (Netscape Bookmark File Format) — 파서 하나로 Chrome·Edge·Firefox·Safari를
        모두 받는다.
        """
        if self._add_videos_fn is None:
            return

        self._add_divider(layout)
        label = QLabel("북마크에서 가져오기")
        label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted};"
        )
        layout.addWidget(label)
        layout.addSpacing(8)

        hint = QLabel(
            "브라우저에서 북마크를 HTML로 내보낸 뒤 그 파일을 고르면, 담을 영상을 "
            "골라 라이브러리에 넣습니다. 북마크에는 영상이 아닌 링크도 섞여 있으므로 "
            "흔한 영상 사이트만 미리 골라 두고 나머지는 직접 고르게 합니다."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size: 10px; color: {_t().text_secondary};")
        layout.addWidget(hint)

        row = QHBoxLayout()
        row.setContentsMargins(0, 6, 0, 0)
        self._bookmark_btn = QPushButton("북마크 파일 고르기…")
        self._bookmark_btn.clicked.connect(self._on_bookmark_import_clicked)
        row.addWidget(self._bookmark_btn)
        row.addStretch()
        layout.addLayout(row)

        self._bookmark_status = QLabel("")
        self._bookmark_status.setWordWrap(True)
        self._bookmark_status.setStyleSheet(
            f"font-size: 10px; color: {_t().text_secondary};"
        )
        layout.addWidget(self._bookmark_status)
        layout.addSpacing(24)

    def _on_bookmark_import_clicked(self) -> None:
        from domain.library.bookmarks import parse_bookmarks  # noqa: PLC0415
        from gui.dialogs.bookmark_import_dialog import (  # noqa: PLC0415
            BookmarkImportDialog,
        )

        path, _ = QFileDialog.getOpenFileName(
            self, "북마크 파일 선택", "", "북마크 (*.html *.htm);;모든 파일 (*)"
        )
        if not path:
            return
        try:
            # 브라우저가 UTF-8로 쓰지만, 오래된 파일은 다른 인코딩일 수 있다.
            # 읽기 자체가 실패하면 아무것도 못 하므로 깨진 글자를 감수하고 읽는다.
            content = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.exception("북마크 파일 읽기 실패: %s", path)
            self._bookmark_status.setText(f"파일을 읽지 못했습니다: {exc}")
            return

        marks = parse_bookmarks(content)
        if not marks:
            self._bookmark_status.setText(
                "이 파일에서 주소를 찾지 못했습니다. 브라우저의 '북마크 내보내기'로 "
                "저장한 HTML 파일인지 확인해 주세요."
            )
            return

        categories = self._get_categories_fn() if self._get_categories_fn else []
        dlg = BookmarkImportDialog(marks, categories, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        urls = dlg.selected_urls()
        if not urls:
            return
        self._add_videos_fn(urls, dlg.selected_category_id())
        self._bookmark_status.setText(
            f"{len(urls)}개를 담는 중입니다 — 제목·썸네일은 조회되는 대로 채워집니다."
        )

    def _build_cleanup_section(self, layout) -> None:
        """라이브러리 정리 — 중복 영상·사라진 파일 점검(정리 콜백 주입 시에만 표시).

        찾아 주기만 하고 지우는 것은 사용자가 고른다(되돌릴 수 없는 작업이라 자동으로
        지우지 않는다).
        """
        if self._cleanup_fns is None:
            return
        label = QLabel("라이브러리 정리")
        label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted}; margin-bottom: 8px;"
        )
        layout.addWidget(label)
        hint = QLabel(
            "같은 영상이 두 번 들어왔거나, 다운로드한 파일이 사라진 기록을 찾습니다."
        )
        hint.setStyleSheet(f"font-size: 10px; color: {_t().text_secondary};")
        layout.addWidget(hint)
        button = QPushButton("라이브러리 정리 열기…")
        button.clicked.connect(self._open_cleanup_dialog)
        layout.addWidget(button)
        layout.addSpacing(24)

    def _open_cleanup_dialog(self) -> None:
        from gui.dialogs.library_cleanup_dialog import (  # noqa: PLC0415
            LibraryCleanupDialog,
        )

        # 콜백 개수는 조립 루트가 정한다. 옛 조립(3종)과도 맞물리도록 길이를 본다 —
        # 테스트·다른 진입점이 3종만 넘기는 경우가 있어 여기서 터지면 정리 화면 전체가
        # 열리지 않는다.
        fns = tuple(self._cleanup_fns or ())
        find_duplicates, find_broken, delete_videos = fns[:3]
        find_missing = fns[3] if len(fns) > 3 else None
        LibraryCleanupDialog(
            find_duplicates, find_broken, delete_videos, find_missing, self
        ).exec()

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
        # 확인만 자동이고 **받는 것은 누를 때**다 — 문구가 동작과 어긋나면
        # 사용자는 받는 줄 알고 기다린다.
        self._auto_update_check.setToolTip(
            "새 버전이 나왔는지 자동으로 확인합니다(내려받기는 눌러야 시작됩니다)"
        )
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
        """다운로드 완료 — 헤더 상태를 '준비됨'으로 바꾸고 설치 버튼을 노출한다."""
        self._pending_dto = dto
        self._upd_status_lbl.setText(f"업데이트 준비됨 · v{dto.version}")
        self._upd_status_lbl.setStyleSheet(
            f"font-size: 11px; color: {sem('danger')}; font-weight: 600;"
        )
        self._upd_install_btn.setText("지금 설치")
        self._upd_install_btn.setToolTip("앱을 재시작하여 업데이트를 설치합니다")
        self._upd_install_btn.show()

    def set_update_available(self, dto) -> None:
        """새 버전을 찾았지만 아직 받지 않은 상태(또는 받다가 실패한 상태).

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
            self._feed_status_lbl.setText(self._cookie_status_text(profile, cookiefile))
            self._reload_cookie_candidates()
        except Exception:
            logger.exception("브라우저 쿠키 설정 UI 반영 실패")

    @staticmethod
    def _cookie_status_text(profile: "str | None", cookiefile: "str | None") -> str:
        """지금 무엇으로 인증하는지 + **그게 쓸 수 있는 상태인지**.

        예전에는 경로만 적었다. 그래서 다른 PC에서 등록한 경로가 그대로 남아 있어도
        멀쩡해 보였고, 요약이 "로그인된 브라우저를 찾지 못했습니다"로 실패하는데
        설정 화면만 봐서는 원인을 알 수 없었다(실제 신고).
        """
        from infrastructure.auth.youtube_auth import (  # noqa: PLC0415
            COOKIE_EMPTY,
            COOKIE_NOT_COOKIES,
            COOKIE_NOT_FOUND,
            COOKIE_OK,
            cookie_file_state,
        )

        if cookiefile:
            state = cookie_file_state(cookiefile)
            if state == COOKIE_OK:
                return f"쿠키 파일: {cookiefile}"
            trouble = {
                COOKIE_NOT_FOUND: "이 경로에 파일이 없습니다(다른 PC에서 등록했거나 지워졌습니다)",
                COOKIE_EMPTY: "파일이 비어 있습니다",
                COOKIE_NOT_COOKIES: "쿠키 파일 형식이 아닙니다",
            }.get(state, "쓸 수 없는 파일입니다")
            return f"⚠ 쿠키 파일을 쓸 수 없습니다 — {trouble}\n{cookiefile}"
        if profile:
            return f"프로필: {profile}"
        return "미설정 — 로그인된 브라우저를 자동으로 찾습니다"

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

    def _build_subtitle_index_section(self, layout) -> None:
        """자막 색인 — 라이브러리 전체를 훑어 자막을 모아 둔다.

        **자동으로 돌지 않는다.** 영상당 네트워크 왕복이 1초 안팎이라 수백 건이면
        10분을 넘긴다 — 사용자가 시작을 누르고, 언제든 그만둘 수 있어야 한다.
        뷰모델이 없으면(다른 진입점에서 연 설정 화면) 섹션 자체를 만들지 않는다.
        """
        if self._subtitle_vm is None:
            return

        self._add_divider(layout)
        sub_label = QLabel("자막 색인")
        sub_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted};"
        )
        layout.addWidget(sub_label)
        layout.addSpacing(8)

        self._sub_cover_lbl = QLabel("")
        self._sub_cover_lbl.setStyleSheet("font-size: 11px;")
        layout.addWidget(self._sub_cover_lbl)

        row = QHBoxLayout()
        row.setContentsMargins(0, 6, 0, 0)
        self._sub_index_btn = QPushButton("전체 자막 색인 시작")
        self._sub_index_btn.clicked.connect(self._on_bulk_subtitle_clicked)
        row.addWidget(self._sub_index_btn)
        row.addStretch()
        layout.addLayout(row)

        self._sub_index_bar = QProgressBar()
        self._sub_index_bar.setVisible(False)
        self._sub_index_bar.setTextVisible(True)
        self._sub_index_bar.setMaximumHeight(16)
        layout.addWidget(self._sub_index_bar)

        self._sub_index_status = QLabel("")
        self._sub_index_status.setWordWrap(True)
        self._sub_index_status.setStyleSheet(
            f"font-size: 10px; color: {_t().text_secondary};"
        )
        layout.addWidget(self._sub_index_status)

        hint = QLabel(
            "색인해 두면 라이브러리 검색이 영상 속 대사까지 찾고, 상세화면 자막 탭에서 "
            "그 대사가 나온 시점으로 바로 건너뛸 수 있습니다. 영상마다 인터넷에 한 번씩 "
            "물어보므로 시간이 걸리며, 이미 색인된 영상은 건너뜁니다."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size: 10px; color: {_t().text_secondary};")
        layout.addWidget(hint)

        self._build_transcribe_rows(layout)
        layout.addSpacing(24)

        self._subtitle_vm.bulk_progress.connect(self._on_bulk_subtitle_progress)
        self._subtitle_vm.bulk_finished.connect(self._on_bulk_subtitle_finished)
        self._refresh_subtitle_coverage()

    # ── 음성 인식(자막 만들기) ────────────────────────────────────

    def _build_transcribe_rows(self, layout) -> None:
        """음성 인식 모델 고르기 + 받아 둔 모델 지우기.

        **크기가 곧 정확도이자 시간**이라 고를 수 있어야 한다. 목표 사양이 저사양 PC라
        "가장 좋은 것"을 기본값으로 두면 대부분에게 "몇 시간째 안 끝난다"가 된다
        (`domain/library/transcribe.py`). 그래서 콤보에 **디스크 크기**를 같이 적고,
        고른 것의 설명을 바로 아래에 띄운다.

        모델 파일은 한 번 받으면 계속 남으므로(small 은 484MB) **지우는 길**도 둔다.
        """
        from domain.library.transcribe import MODELS  # noqa: PLC0415 (도메인 카탈로그)

        layout.addSpacing(14)
        asr_label = QLabel("음성 인식으로 자막 만들기")
        asr_label.setStyleSheet(
            f"font-size: 9px; font-weight: 600; letter-spacing: 0.5px; "
            f"color: {_t().text_secondary};"
        )
        layout.addWidget(asr_label)

        model_row = QHBoxLayout()
        m_lbl = QLabel("모델")
        m_lbl.setFixedWidth(100)
        self._asr_model_combo = QComboBox()
        for model in MODELS:
            self._asr_model_combo.addItem(
                f"{model.name} · {model.disk_mb}MB", model.key
            )
        current = self._subtitle_vm.transcribe_model_key if self._subtitle_vm else ""
        idx = self._asr_model_combo.findData(current)
        self._asr_model_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._asr_model_combo.setFixedWidth(220)
        self._asr_model_combo.currentIndexChanged.connect(self._on_asr_model_changed)
        model_row.addWidget(m_lbl)
        model_row.addWidget(self._asr_model_combo)
        model_row.addStretch()
        layout.addLayout(model_row)

        self._asr_model_note = QLabel("")
        self._asr_model_note.setWordWrap(True)
        self._asr_model_note.setStyleSheet(
            f"font-size: 10px; color: {_t().text_secondary};"
        )
        layout.addWidget(self._asr_model_note)

        del_row = QHBoxLayout()
        del_row.setContentsMargins(0, 4, 0, 0)
        self._asr_installed_lbl = QLabel("")
        self._asr_installed_lbl.setWordWrap(True)
        self._asr_installed_lbl.setStyleSheet(
            f"font-size: 10px; color: {_t().text_secondary};"
        )
        self._asr_delete_btn = QPushButton("받아 둔 모델 지우기")
        self._asr_delete_btn.setFixedWidth(140)
        self._asr_delete_btn.clicked.connect(self._on_asr_delete_clicked)
        del_row.addWidget(self._asr_installed_lbl, 1)
        del_row.addWidget(self._asr_delete_btn)
        layout.addLayout(del_row)

        asr_hint = QLabel(
            "YouTube가 자막을 주지 않는 영상에서 씁니다. 상세화면 자막 탭의 "
            "'음성 인식으로 만들기'를 누르면 받아 둔 파일의 소리를 듣고 자막을 만듭니다. "
            "모델은 처음 한 번만 내려받으며, 인터넷 없이 이 PC에서 계산합니다."
        )
        asr_hint.setWordWrap(True)
        asr_hint.setStyleSheet(f"font-size: 10px; color: {_t().text_secondary};")
        layout.addWidget(asr_hint)

        self._refresh_transcribe_rows()

    def _refresh_transcribe_rows(self) -> None:
        """고른 모델의 설명과 '받아 둔 모델' 표시를 다시 채운다."""
        from domain.library.transcribe import resolve_model  # noqa: PLC0415

        key = self._asr_model_combo.currentData() or ""
        self._asr_model_note.setText(resolve_model(key).note)

        installed = self._subtitle_vm.installed_models() if self._subtitle_vm else set()
        if key in installed:
            disk = self._subtitle_vm.model_disk_mb(key) if self._subtitle_vm else 0
            self._asr_installed_lbl.setText(
                f"받아 둔 모델입니다 ({disk}MB) — 바로 쓸 수 있습니다."
                if disk
                else "받아 둔 모델입니다 — 바로 쓸 수 있습니다."
            )
            self._asr_delete_btn.setEnabled(True)
            return
        # 아직 안 받은 모델 — 처음 쓸 때 받는다는 것을 미리 알린다(몇 분이 걸린다).
        others = sorted(installed)
        tail = f" (받아 둔 것: {', '.join(others)})" if others else ""
        self._asr_installed_lbl.setText(f"처음 쓸 때 내려받습니다.{tail}")
        self._asr_delete_btn.setEnabled(False)

    def _on_asr_model_changed(self, _index: int) -> None:
        if self._subtitle_vm is None:
            return
        key = self._asr_model_combo.currentData()
        if key:
            self._subtitle_vm.set_transcribe_model(str(key))
        self._refresh_transcribe_rows()

    def _on_asr_delete_clicked(self) -> None:
        """받아 둔 모델을 지운다 — small 은 484MB라 되찾을 값이 있다."""
        if self._subtitle_vm is None:
            return
        key = str(self._asr_model_combo.currentData() or "")
        if not key:
            return
        if self._subtitle_vm.delete_model(key):
            self._asr_installed_lbl.setText("지웠습니다. 다음에 쓸 때 다시 받습니다.")
            self._asr_delete_btn.setEnabled(False)
        else:
            self._asr_installed_lbl.setText("지우지 못했습니다. 로그를 확인하세요.")

    def _refresh_subtitle_coverage(self) -> None:
        coverage = self._subtitle_vm.coverage() if self._subtitle_vm else None
        if coverage is None:
            self._sub_cover_lbl.setText("색인 현황을 읽을 수 없습니다.")
            return
        self._sub_cover_lbl.setText(
            f"영상 {coverage.total_videos}개 중 {coverage.indexed_videos}개 색인됨 "
            f"(남은 {coverage.remaining}개)"
        )

    def _on_bulk_subtitle_clicked(self) -> None:
        if self._subtitle_vm is None:
            return
        if self._subtitle_vm.is_bulk_running:
            self._subtitle_vm.stop_bulk_index()
            self._sub_index_btn.setText("중지하는 중…")
            self._sub_index_btn.setEnabled(False)
            return
        if not self._subtitle_vm.start_bulk_index():
            self._sub_index_status.setText("색인을 시작할 수 없습니다.")
            return
        self._sub_index_bar.setValue(0)
        self._sub_index_bar.setVisible(True)
        self._sub_index_btn.setText("중지")
        self._sub_index_status.setText("색인 중…")

    def _on_bulk_subtitle_progress(self, current: int, total: int, title: str) -> None:
        self._sub_index_bar.setMaximum(max(1, total))
        self._sub_index_bar.setValue(current)
        self._sub_index_bar.setFormat(f"{current}/{total}")
        self._sub_index_status.setText(f"확인 중 — {title}")

    def _on_bulk_subtitle_finished(self, result) -> None:
        self._sub_index_bar.setVisible(False)
        self._sub_index_btn.setText("전체 자막 색인 시작")
        self._sub_index_btn.setEnabled(True)
        if result is None:
            self._sub_index_status.setText("색인 중 오류가 발생했습니다. 로그를 확인하세요.")
            return
        parts = [f"{result.indexed}개 색인"]
        if result.no_subtitle:
            parts.append(f"{result.no_subtitle}개는 자막 없음")
        if result.stopped:
            parts.append("중단됨")
        self._sub_index_status.setText(" · ".join(parts))
        self._refresh_subtitle_coverage()
