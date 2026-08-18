"""영상 상세화면 — 라이브러리 목록 자리에 인라인으로 뜨는 위젯(모달 아님).

이 파일은 **화면 뼈대(`_setup_skeleton`)와 로드 진입점(`load`/`load_stream`)만** 갖는다.
3,000줄짜리 한 파일이던 것을 두 축으로 나눴다.

* `gui/panels/detail/*` — **부품**: 소형 위젯(태그 칩·흐름 레이아웃·인라인 편집 필드),
  우측 목록(연관 영상+추천), 노래 탭, 백그라운드 워커, 렌더링 규칙·안내 문구.
* `gui/panels/detail/mixins/*` — **동작**: 정보(제목·태그·설명·메모)·요약 탭·노래 탭
  배선·다운로드/클립 탭·플레이어 연결. `VideoDetailWidget`에 섞여 들어가므로 런타임
  클래스는 하나이며 상태 공유 방식도 이전과 같다.

좌측은 플레이어 → 제목 행 → 메타 행 → 탭 4개(설명·요약·다운로드/클립·노래), 우측은
연관 영상 목록(재생목록 역할) 아래에 추천 영상 구역이 붙는다.
"""
from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID

from PyQt6.QtCore import (
    QEvent,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
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
    QVBoxLayout,
    QWidget,
)


from application.library.dtos import VideoDetailDTO
from gui.smooth_scroll import apply_smooth_scroll_tree
from gui.widgets.video_player import InlinePlayer


# ── 상세화면 동작 묶음 (gui/panels/detail/mixins/*) ────────────────
# 화면 뼈대(_setup_skeleton)와 로드 진입점만 이 파일에 남기고, 탭별 동작은
# 주제별 mixin으로 나눴다. 런타임 클래스는 하나라 상태 공유는 이전과 같다.
from gui.panels.detail.mixins.info import DetailInfoMixin
from gui.panels.detail.mixins.summary import SummaryTabMixin
from gui.panels.detail.mixins.song import SongTabMixin
from gui.panels.detail.mixins.files import FilesTabMixin
from gui.panels.detail.mixins.player import PlayerControlMixin

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


# ── 분할된 부품 (gui/panels/detail/*) ─────────────────────────────
# 이 파일에는 화면 조립·흐름 제어만 남기고 부품은 패키지로 옮겼다.
# 아래 재수출은 기존 임포트 경로를 유지하기 위한 것이다.
from gui.panels.detail.text_format import (  # noqa: F401
    _BOLD2_RE,
    _BOLD_RE,
    _BULLET_RE,
    _HEADING_RE,
    _ITALIC_RE,
    _NUMBERED_RE,
    _SUMMARY_PLACEHOLDERS,
    _SUMMARY_STATUS_LABELS,
    _TS_RE,
    _URL_RE,
    summary_failure_status_label,
    summary_placeholder,
)

logger = logging.getLogger(__name__)












class VideoDetailWidget(
    DetailInfoMixin,
    SummaryTabMixin,
    SongTabMixin,
    FilesTabMixin,
    PlayerControlMixin,
    QWidget,
):
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
    # 요약 실패 사유 저장 요청 — (video_id, SUMMARY_REASON_* 또는 "" = 지우기)
    summary_status_saved    = pyqtSignal(object, str)
    downloads_refresh_requested = pyqtSignal(object)    # video_id
    detail_refresh_requested    = pyqtSignal(object)    # video_id — 제목행 ⟳ 버튼
    song_field_saved            = pyqtSignal(object, str, str)  # (video_id, field, value)
    song_lyrics_saved           = pyqtSignal(object, object)    # (video_id, list[LyricsLine])
    song_candidates_requested   = pyqtSignal(object)    # video_id — 가사 후보 목록 검색
    song_candidate_chosen       = pyqtSignal(object, object)  # (video_id, LyricsCandidateDTO)
    song_translate_requested    = pyqtSignal(object)    # video_id — 현재 가사 재번역
    song_flag_toggled           = pyqtSignal(object, bool)      # (video_id, is_song)
    song_filter_requested       = pyqtSignal(str, str)   # (field, value) — 같은 가수/앨범 필터
    play_next_requested         = pyqtSignal(object)     # 재생목록 다음 항목 payload(자동재생)
    song_synced_requested       = pyqtSignal(object)     # video_id — 싱크 가사 찾기
    song_offset_saved           = pyqtSignal(object, int)  # (video_id, offset_ms)
    # 카테고리 지정 요청 — payload: 로컬이면 video_id(UUID), 스트리밍이면 FeedVideoDTO.
    # 스트리밍이면 라이브러리 등록까지 함께 이뤄져야 요약·가사 잠금이 풀린다.
    category_assign_requested   = pyqtSignal(object)

    # 하단 탭 인덱스
    _TAB_INFO = 0       # 설명(태그~메모)
    _TAB_SUMMARY = 1
    _TAB_FILES = 2      # 다운로드 + 클립 병합
    _TAB_SONG = 3       # 노래(가수·앨범·제목·가사)

    # 요약 탭 스택 인덱스
    _SUMMARY_VIEW = 0
    _SUMMARY_EDIT = 1
    _SUMMARY_LOCKED = 2   # 카테고리 미지정 — 안내판

    # 요약 렌더링 줄 간격(px) — Gemini 요약은 개행이 촘촘해 단락 여백을 벌려 읽기 편하게 한다.
    _SUMMARY_LINE_GAP = 1

    def __init__(self, clip_vm=None, download_vm=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._detail: VideoDetailDTO | None = None
        self._tag_add_input: QLineEdit | None = None
        self._clip_vm = clip_vm
        self._download_vm = download_vm
        self._clip_source_file: str | None = None
        self._filter_on = False
        self._streaming = False          # 스트리밍(피드/채널) 모드 여부
        self._stream_dto = None          # 스트리밍 모드의 FeedVideoDTO(카테고리 지정용)
        self._playlist: list = []        # 우측 목록 payload 순서 — 자동재생 다음곡 계산용
        self._current_key = ""           # 현재 재생 항목 키(RelatedItem.key) — 목록 강조용
        self._summary_raw = ""           # 요약 원문(편집 대상) — 렌더 전 텍스트
        self._current_url = ""           # 브라우저 열기/재생 실패 폴백용
        self._active_dl_frame: QFrame | None = None
        self._active_dl_bar: QProgressBar | None = None
        self._notes_timer = QTimer(self)
        self._notes_timer.setSingleShot(True)
        self._notes_timer.setInterval(1000)
        self._notes_timer.timeout.connect(self._save_notes)
        # 단축키 연타마다 DB에 쓰지 않도록 오프셋 저장을 묶는다.
        self._offset_timer = QTimer(self)
        self._offset_timer.setSingleShot(True)
        self._offset_timer.setInterval(500)
        self._offset_timer.timeout.connect(self._flush_offset)
        # (video_id, offset_ms) — 변경 시점의 video_id를 함께 담아, flush 시점에
        # self._detail이 이미 다른 영상으로 바뀌어 있어도 원래 영상에 저장한다.
        self._pending_offset: tuple[UUID, int] | None = None
        self._gemini_worker: object | None = None  # _GeminiSummaryWorker | None
        if download_vm is not None:
            download_vm.queue_changed.connect(self._on_queue_changed)
            download_vm.history_changed.connect(self._on_history_changed)
        self._setup_skeleton()
        apply_smooth_scroll_tree(self)

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
        self._player.playback_finished.connect(self._on_playback_finished)
        self._player.current_line_changed.connect(self._on_current_line_changed)
        self._player.subtitle_offset_changed.connect(self._on_subtitle_offset_changed)
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
        # 📁 카테고리 지정 — 로컬 영상은 이동, 스트리밍 영상은 등록까지 함께 이뤄진다.
        self._btn_category = QPushButton("📁")
        self._btn_category.setFixedSize(28, 28)
        self._btn_category.setToolTip("카테고리 지정")
        self._btn_category.clicked.connect(self._on_category_clicked)
        title_row.addWidget(self._btn_category, 0, Qt.AlignmentFlag.AlignTop)
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
        edit_hint.setStyleSheet(f"font-size: 8pt; color: {_t().text_secondary};")
        refresh_row.addWidget(edit_hint)
        refresh_row.addStretch()
        self._summary_status_lbl = QLabel("")
        self._summary_status_lbl.setStyleSheet(f"font-size: 9pt; color: {_t().text_secondary};")
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
        self._summary_edit.setPlaceholderText(_SUMMARY_PLACEHOLDERS[""])
        self._summary_edit.anchorClicked.connect(self._on_summary_anchor_clicked)
        self._summary_stack.addWidget(self._summary_edit)      # index 0: 표시
        self._summary_editor = QPlainTextEdit()
        self._summary_editor.setPlaceholderText("요약 내용을 입력하세요…")
        self._summary_stack.addWidget(self._summary_editor)    # index 1: 편집
        # index 2: 카테고리 미지정 안내 — 요약도 영상별로 저장되므로 로컬 영상이어야 한다.
        self._summary_locked = _LockedNotice(
            "이 영상은 아직 라이브러리에 없습니다.\n"
            "카테고리에 담으면 AI 요약을 가져오고 저장할 수 있습니다."
        )
        self._summary_locked.action_clicked.connect(self._on_category_clicked)
        self._summary_stack.addWidget(self._summary_locked)
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

        # 탭3: 노래 (가수·앨범·제목·가사)
        self._song_tab = _SongTab()
        self._song_tab.field_edited.connect(self._on_song_field_edited)
        self._song_tab.lyrics_edited.connect(self._on_song_lyrics_edited)
        self._song_tab.candidates_requested.connect(self._on_song_candidates)
        self._song_tab.candidate_chosen.connect(self._on_song_candidate_chosen)
        self._song_tab.translate_requested.connect(self._on_song_translate)
        self._song_tab.flag_toggled.connect(self._on_song_flag_toggled)
        self._song_tab.filter_requested.connect(self.song_filter_requested.emit)
        self._song_tab.synced_requested.connect(self._on_song_synced)
        self._song_tab.lyrics_seek_requested.connect(self._on_lyrics_seek)
        # 노래 탭 입력 필드 → 플레이어(단축키·메뉴와 동일 경로) → subtitle_offset_changed
        # → _on_subtitle_offset_changed(디바운스 저장). 탭이 직접 저장하지 않는 이유는
        # 위 경로 하나로 바·오버레이 갱신과 DB 저장 디바운스를 동시에 재사용하기 위해서다.
        self._song_tab.offset_changed.connect(self._player.set_subtitle_offset_ms)
        self._song_tab.category_requested.connect(self._on_category_clicked)
        self._tabs.addTab(_wrap(self._song_tab), "노래")

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
            # 가사 표시 영역 더블클릭 → 편집 모드 진입(로컬 영상만)
            if (
                obj is self._song_tab.lyrics_viewport()
                and not self._streaming
                and self._detail is not None
            ):
                self._song_tab.enter_lyrics_edit()
                return True
        elif et == QEvent.Type.FocusOut:
            # 요약 편집기 포커스 아웃 → 저장 후 표시 모드 복귀
            if obj is self._summary_editor:
                self._commit_summary_edit()
            elif obj is self._song_tab.lyrics_editor():
                self._song_tab.commit_lyrics_edit()
        return False

    # ── Populate ───────────────────────────────────────────────────

    def load(
        self,
        detail: VideoDetailDTO,
        tag_ids: dict[str, UUID],
        resume_ms: int = 0,
        related: list[RelatedItem] | None = None,
        category_path: list[tuple] | None = None,
        poster=None,
        autoplay: bool = False,
        related_header: str | None = None,
    ) -> None:
        """라이브러리(로컬) 영상 상세를 채운다.

        poster: 재생 전 표시할 포스터(목록 썸네일 QPixmap). autoplay: 재생목록 자동
        전환처럼 로드 직후 재생을 시작할지. resume_ms>0이면 이어서 재생.
        """
        self._detail = detail
        self._tag_ids = tag_ids
        self._streaming = False
        self._stream_dto = None
        self._current_url = detail.url
        self._current_key = str(detail.id)
        self._set_crumb_path(category_path)

        self._player.load(
            detail.url, detail.downloads, thumbnail_pixmap=poster, resume_ms=resume_ms
        )
        if resume_ms > 0 or autoplay:
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
        # 요약이 비어 있을 때 왜 없는지 알려준다(저장된 실패 사유 기준).
        self._summary_edit.setPlaceholderText(
            summary_placeholder(getattr(detail, "summary_status", ""))
        )
        self._summary_edit.setHtml(
            self._render_timestamped_html(self._summary_raw, line_gap=self._SUMMARY_LINE_GAP)
        )
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

        # 노래 탭 — 편집 가능. 실제 데이터는 LibraryPanel이 SongViewModel로 로드해
        # set_song_info로 채운다. 여기선 잠정적으로 비운다(이전 영상 잔상 방지).
        self._song_tab.set_editable(True)
        self._song_tab.set_busy(False)
        self._song_tab.set_info(None)

        self._btn_refresh.setEnabled(True)
        self.set_related(related or [], header=related_header)


    # ── 정보 영역 (제목·메타·태그·챕터·설명) ─────────────────────────


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


    def _set_tabs_enabled(self, local: bool) -> None:
        """요약·노래 탭의 잠금 상태를 맞춘다.

        **탭은 항상 열어 둔다.** 예전에는 스트리밍(라이브러리 밖) 영상에서 두 탭을
        비활성화했는데, 비활성 탭은 클릭조차 되지 않아 '왜 못 쓰는지'와 '어떻게 쓰는지'를
        전할 방법이 없었다. 이제 탭 안에 `_LockedNotice`가 떠서 카테고리에 담으면
        풀린다는 것과 담는 버튼을 함께 보여준다(요약·가사는 영상별로 DB에 저장되므로
        안정적인 로컬 video_id가 반드시 필요하다).
        """
        self._tabs.setTabEnabled(self._TAB_SUMMARY, True)
        self._tabs.setTabEnabled(self._TAB_SONG, True)
        self._summary_stack.setCurrentIndex(
            self._SUMMARY_VIEW if local else self._SUMMARY_LOCKED
        )
        self._song_tab.set_locked(not local)
        self._summary_refresh_btn.setEnabled(local)
        self._btn_category.setToolTip(
            "카테고리 지정 (다른 카테고리로 옮기기)" if local
            else "카테고리 지정 (라이브러리에 담아 요약·가사 잠금 해제)"
        )

    def _on_category_clicked(self) -> None:
        """📁 버튼·잠금 안내판 — 카테고리 지정을 상위(LibraryPanel)에 요청한다."""
        payload = self._detail.id if self._detail is not None else self._stream_dto
        if payload is None:
            return
        self.category_assign_requested.emit(payload)


    # ── 연관 영상 ──────────────────────────────────────────────────

    def set_related(self, items: list[RelatedItem], header: str | None = None) -> None:
        """우측 목록을 채운다. header가 있으면 "연관 영상" 대신 표시(가수/앨범 필터).

        목록은 재생목록으로 쓰이므로 payload 순서를 보관하고, 현재 재생 항목을 강조한다.
        """
        self._playlist = [it.payload for it in items]
        self._related.set_header(header or "연관 영상")
        self._related.set_items(items, current_key=self._current_key or None)

    def set_recommendations(self, items: list[RelatedItem]) -> None:
        """연관 영상 목록 아래에 추천 영상을 나열한다.

        추천은 재생목록(``_playlist``)에 넣지 않는다 — 자동 다음곡은 연관 영상
        (라이브러리/피드 목록) 안에서만 이어져야 한다.
        """
        self._related.set_recommendations(items)


    # ── Clip tab ───────────────────────────────────────────────────


    def _on_tab_changed(self, index: int) -> None:
        if (
            index == self._TAB_FILES
            and not self._streaming
            and self._clip_vm is not None
            and self._detail is not None
        ):
            self._clip_vm.load_clips(self._detail.id)


    # ── Actions ────────────────────────────────────────────────────


    def current_detail_id(self):
        """현재 표시 중인 로컬 영상 id(스트리밍/미표시면 None)."""
        return self._detail.id if self._detail is not None else None

    def set_refresh_busy(self, busy: bool) -> None:
        """상세 정보 갱신(⟳) 진행 표시 — 버튼 비활성 + 툴팁 변경."""
        self._btn_refresh.setEnabled(not busy)
        self._btn_refresh.setToolTip("갱신 중… (YouTube에서 정보 가져오는 중)" if busy else "상세 정보 갱신")


    # ── 다운로드 히스토리 갱신 (오류2) ────────────────────────────────

    def _on_history_changed(self) -> None:
        """다운로드 완료/실패 시 호출 — 상세화면이 열려있으면 부모에 갱신 요청."""
        if self._detail is not None and not self._streaming:
            self.downloads_refresh_requested.emit(self._detail.id)


    # ── Gemini 요약 갱신 (오류4) ──────────────────────────────────────


    # ── 요약 편집 (더블클릭) ──────────────────────────────────────────


