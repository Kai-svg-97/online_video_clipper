"""Library panel — 3-pane browser: left sidebar | video list | preview pane.

Centre pane uses a navigation QStackedWidget (_nav_stack) so that double-clicking
a video replaces the list area with VideoDetailWidget inline (no modal dialog).
"""
from __future__ import annotations

import logging
import re
from uuid import UUID

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QModelIndex,
    QPoint,
    QSize,
    QTimer,
    QVariantAnimation,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction, QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

import config.settings as _settings
from application.library.dtos import CategoryDTO, VideoDTO
from domain.library.repositories import MUSIC_ROOT_CATEGORY_NAMES
from gui.dialogs.batch_download_dialog import BatchDownloadDialog
from gui.panels.video_detail_panel import (
    RelatedItem,
    VideoDetailWidget,
)
from gui.themes.manager import ThemeManager
from gui.view_models.feed_vm import CHANNELS_ROOT_KEY, FEED_ALL_KEY
from gui.view_models.library_vm import LibraryViewModel


# ── 분할된 부품 (gui/panels/library/*) ──────────────────────────────
# 화면 조립과 흐름 제어만 이 파일에 남기고, 위젯·모델·상수는 패키지로 옮겼다.
from gui.panels.library.constants import (  # noqa: F401
    MATCH_FIELD_LABELS,
    _BADGE_EMPTY_BG,
    _CAT_ID_ROLE,
    _CAT_PARENT_ROLE,
    _CHANNEL_URL_ROLE,
    _COLOR_ROLE,
    _COUNT_ROLE,
    _DETAIL_RECOMMEND_COUNT,
    _FAV_BADGE_W,
    _FOLDER_ID_ROLE,
    _GLYPH_ROLE,
    _ICON_PAD,
    _ICON_TEXT_H,
    _ITEM_TYPE_ROLE,
    _ITYPE_CATEGORY,
    _ITYPE_CHANNEL,
    _ITYPE_FEED_ALL,
    _ITYPE_FOLDER,
    _ITYPE_PLAYLIST,
    _ITYPE_ROOT,
    _MATCH_ROW_H,
    _MIME_CAT_ID,
    _MIME_PLAYLIST_ID,
    _MIME_PLAYLIST_SECTION,
    _MIME_VIDEO_ID,
    _MIME_YT_PLAYLIST_ID,
    _NAME_ROLE,
    _NAV_ALBUM_DETAIL,
    _NO_URL_TARGET,
    _ORIG_TEXT_ROLE,
    _PLAYLIST_ID_ROLE,
    _QWIDGET_MAX_H,
    _RECOMMEND_COUNT,
    _RECOMMEND_DEBOUNCE_MS,
    _RECOMMEND_REVEAL_MS,
    _RECOMMEND_SEED_LIMIT,
    _SEARCH_DEBOUNCE_MS,
    _SECTION_ROLE,
    _STAR_ROLE,
    _TAG_COUNT_W,
    _TAG_PALETTE,
    _THUMB_RENDER_SIZE_KINDS,
    _TH_ICON,
    _TH_LIST,
    _TH_PREV,
    _TW_ICON,
    _TW_LIST,
    _TW_PREV,
    _VIEW_ALBUMS,
    _VIEW_CHANNELS,
    _VIEW_DETAIL,
    _VIEW_FEED,
    _VIEW_FOLDER,
    _VIEW_ICON,
    _VIEW_LIST,
    _YT_BRAND_RED,
    _YT_BRAND_RED_HOVER,
)
from gui.panels.library.formatting import (  # noqa: F401
    _fmt_elapsed,
    _fmt_views,
    _mime_may_contain_url,
    _pub_sort_key,
    _relative_time,
    _t,
    _url_from_mime,
    chip_colors,
    tag_color,
)
from gui.panels.library.thumbnails import (  # noqa: F401
    _ThumbBgLoader,
    _ThumbnailCache,
    _load_thumb,
    _load_thumb_async,
    _thumb_cache,
)
from gui.panels.library.models import (  # noqa: F401
    VideoListModel,
    _VideoListView,
)
from gui.panels.library.delegates import (  # noqa: F401
    _FavChipDelegate,
    _IconDelegate,
    _ListDelegate,
    _TagChipDelegate,
    _TreeRowDelegate,
    _paint_duration_badge,
    _paint_match_badges,
)
from gui.panels.library.tag_widgets import (  # noqa: F401
    _ActiveTagsBar,
    _FavListWidget,
    _FavoritesBar,
    _PopularTagButton,
    _TagListWidget,
)
from gui.panels.library.cards import (  # noqa: F401
    _BaseCard,
    _FolderCard,
    _FolderContentsView,
    _PlaylistCard,
    _PlaylistThumbLabel,
    _UnfiledCard,
)
from gui.panels.library.splitter import (  # noqa: F401
    _CollapseHandle,
    _PreviewSplitter,
)
from gui.panels.library.tree import (  # noqa: F401
    _BreadcrumbBar,
    _PlaylistPanel,
    _PlaylistTree,
)

logger = logging.getLogger(__name__)
























# ------------------------------------------------------------------
# Multi-size LRU thumbnail cache
# ------------------------------------------------------------------





















# ------------------------------------------------------------------
# QListView subclass: emits empty_clicked on click on empty space
# ------------------------------------------------------------------



# ------------------------------------------------------------------
# Collapsible splitter handle (triangle toggle on rightmost handle)
# ------------------------------------------------------------------





# ------------------------------------------------------------------
# Shared helper: paint a duration badge over an already-drawn thumbnail
# ------------------------------------------------------------------



# ------------------------------------------------------------------
# Icon-grid delegate: YouTube-style card
# ------------------------------------------------------------------





# ------------------------------------------------------------------
# List-view delegate: YouTube list style
# ------------------------------------------------------------------



# ------------------------------------------------------------------
# VideoListModel
# ------------------------------------------------------------------



# ------------------------------------------------------------------
# 인기 태그 버튼 (이름 왼쪽 + 둥근 카운트 배지 오른쪽)
# ------------------------------------------------------------------



# ------------------------------------------------------------------
# 즐겨찾기 바 — 검색 필드 위, 드래그로 순서 변경
# ------------------------------------------------------------------









# ------------------------------------------------------------------
# Tag chip delegate + list widget
# ------------------------------------------------------------------





# ------------------------------------------------------------------
# Active tag filter bar (chips shown between category tree and tag list)
# ------------------------------------------------------------------



# ------------------------------------------------------------------
# Playlist panel (재생목록 탭)
# ------------------------------------------------------------------










# ------------------------------------------------------------------
# 폴더 카드 뷰 위젯들
# ------------------------------------------------------------------

















# ------------------------------------------------------------------
# Category tree
# ------------------------------------------------------------------



# ------------------------------------------------------------------
# Preview pane (right side)
# ------------------------------------------------------------------



# ------------------------------------------------------------------
# Library panel (3-pane: categories+tags | video list | preview)
# ------------------------------------------------------------------

class LibraryPanel(QWidget):
    video_selected     = pyqtSignal(object)
    download_requested = pyqtSignal(str, str, object)
    path_changed       = pyqtSignal(str)   # 현재 위치 경로 문자열 (breadcrumb)
    back_exhausted     = pyqtSignal()      # 뒤로가기 기록 소진(외부에서 원본 페이지 복귀용)

    def __init__(
        self,
        vm: LibraryViewModel,
        clip_vm=None,
        download_vm=None,
        playlist_vm=None,
        feed_vm=None,
        monitoring_vm=None,
        song_vm=None,
        recommend_vm=None,
        album_vm=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._vm = vm
        self._clip_vm = clip_vm
        self._download_vm = download_vm
        self._playlist_vm = playlist_vm
        self._feed_vm = feed_vm
        self._monitoring_vm = monitoring_vm
        self._song_vm = song_vm
        self._recommend_vm = recommend_vm
        self._album_vm = album_vm
        # 앨범 보기 상태 — 정렬 '앨범'을 고르면 켜지고, 다른 정렬로 바꾸면 꺼진다.
        self._album_mode: bool = False
        self._current_album_key: str | None = None
        self._all_tags: list = []
        self._active_tag_ids: set[UUID] = set()
        self._current_cat_id: UUID | None = None
        self._current_playlist_id: UUID | None = None
        self._current_folder_id: UUID | None = None
        self._feed_show_channel: bool = True   # 피드 카드에 채널명 표시 여부
        self._icon_delegate = _IconDelegate()
        self._list_delegate = _ListDelegate()
        self._refresh_dlg: QProgressDialog | None = None
        # 내비게이션 히스토리 (최대 50개 상태 보존) + 앞으로가기 스택
        self._nav_history: list[dict] = []
        self._nav_future: list[dict] = []
        self._is_restoring: bool = False
        self._current_channel_url: str = ""      # 단일 채널 피드 복원용
        self._current_detail_payload: object = None  # 상세 화면 재진입용(UUID|FeedVideoDTO)
        # 가수/앨범 필터 재생목록 컨텍스트 — 마우스 뒤로가기 재생 이력 되짚기용.
        # {items, header, prev_related, history}. None이면 재생목록 모드 아님.
        self._playlist_ctx: dict | None = None
        self._current_feed_key: str = ""         # 현재 화면에 표시 중인 피드 key
        self._thumb_load_gen: int = 0  # 썸네일 bg 로더 세대 (구 로더 UI 반영 방지용)
        self._active_thumb_loaders: list = []  # GC 방지용 강한 참조 보관
        # 표(상세) 뷰가 숨겨진 동안 목록이 바뀌었는지 — 표시될 때 한 번만 채운다.
        self._table_dirty: bool = False
        # 앨범 보기에서 되돌아갈 목록 뷰(아이콘/리스트/표) — 보기 버튼 그룹에 앨범이
        # 함께 들어 있어 checkedId()로는 복원할 수 없다.
        self._last_list_view: int = _VIEW_ICON
        # 상세화면에서 '카테고리에 담기'를 누른 스트리밍 영상의 URL — 등록이 끝나면
        # 그 영상의 로컬 상세로 갈아탄다(요약·가사 잠금 해제).
        self._pending_category_url: str = ""
        self._setup_ui()
        # 추천 스트립 자동 갱신 디바운스 — 목록이 바뀔 때마다 검색을 돌리면
        # (카테고리 전환·검색 타이핑) yt-dlp 검색이 폭주한다.
        self._recommend_timer = QTimer(self)
        self._recommend_timer.setSingleShot(True)
        self._recommend_timer.setInterval(_RECOMMEND_DEBOUNCE_MS)
        self._recommend_timer.timeout.connect(self._refresh_recommendations)
        self._connect_signals()
        QTimer.singleShot(0, vm.load)
        if playlist_vm is not None:
            QTimer.singleShot(0, playlist_vm.load)

    # ── Layout ─────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        outer_splitter = _PreviewSplitter(Qt.Orientation.Horizontal, self)

        # ── 1. Left: 통합 트리 (카테고리 + 재생목록) + 태그 ──
        left = QWidget()
        left.setMaximumWidth(220)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(2)

        # 트리(상단) + 태그 섹션(하단)을 일반 세로 레이아웃으로 쌓는다. 태그 섹션은
        # 카테고리 선택 시에만 보이며(_set_popular_tags_visible), 숨기면 트리가 그
        # 공간을 차지한다. (이전에는 QSplitter로 묶었으나, 스플리터 자식의 가시성
        # 토글이 레이아웃 재분배 thrash → 깜빡임·프리징을 유발해 일반 레이아웃으로 교체.)
        nav_container = QWidget()
        nav_layout = QVBoxLayout(nav_container)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(4)
        self._playlist_panel = _PlaylistPanel()
        self._apply_sidebar_tree_style()
        nav_layout.addWidget(self._playlist_panel, stretch=2)

        self._tag_section = QWidget()
        tag_section_layout = QVBoxLayout(self._tag_section)
        tag_section_layout.setContentsMargins(0, 0, 0, 0)
        tag_section_layout.setSpacing(4)

        self._popular_hdr = QLabel("인기 태그")
        self._popular_hdr.setStyleSheet(
            f"font-size:8pt;color:{_t().text_muted};font-weight:600;padding:2px 4px;"
        )
        tag_section_layout.addWidget(self._popular_hdr)

        self._popular_tags_widget = QWidget()
        self._popular_tags_layout = QVBoxLayout(self._popular_tags_widget)
        self._popular_tags_layout.setContentsMargins(4, 0, 4, 4)
        self._popular_tags_layout.setSpacing(2)
        tag_section_layout.addWidget(self._popular_tags_widget)

        tag_hdr = QLabel("전체 태그")
        tag_hdr.setStyleSheet(f"font-size:8pt;color:{_t().text_muted};padding:2px 4px;")
        tag_section_layout.addWidget(tag_hdr)

        self._tag_filter_input = QLineEdit()
        self._tag_filter_input.setPlaceholderText("태그 검색...")
        self._tag_filter_input.setClearButtonEnabled(True)
        self._tag_filter_input.setStyleSheet("font-size:8pt;")
        tag_section_layout.addWidget(self._tag_filter_input)

        self._tag_list = _TagListWidget()
        tag_section_layout.addWidget(self._tag_list)

        nav_layout.addWidget(self._tag_section, stretch=1)
        left_layout.addWidget(nav_container, stretch=1)

        # ── 스마트 폴더 섹션 ──
        sf_header_row = QHBoxLayout()
        sf_header_row.setContentsMargins(4, 4, 4, 2)
        sf_hdr_lbl = QLabel("스마트 폴더")
        sf_hdr_lbl.setStyleSheet(f"font-size:8pt;color:{_t().text_muted};")
        sf_header_row.addWidget(sf_hdr_lbl)
        sf_header_row.addStretch()
        sf_add_btn = QPushButton("+")
        sf_add_btn.setFixedSize(18, 18)
        sf_add_btn.setToolTip("현재 필터를 스마트 폴더로 저장")
        sf_add_btn.setFlat(True)
        sf_add_btn.clicked.connect(self._on_save_smart_folder)
        sf_header_row.addWidget(sf_add_btn)
        left_layout.addLayout(sf_header_row)

        self._sf_list = QListWidget()
        self._sf_list.setMaximumHeight(120)
        self._sf_list.setStyleSheet("font-size:8pt;")
        self._sf_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._sf_list.itemClicked.connect(self._on_smart_folder_clicked)
        self._sf_list.customContextMenuRequested.connect(self._on_sf_context_menu)
        left_layout.addWidget(self._sf_list)

        self._smart_folders: list = []
        self._load_smart_folders_ui()

        outer_splitter.addWidget(left)

        # ── 2. Centre: nav stack ──
        self._nav_stack = QStackedWidget()

        centre_content = QWidget()
        centre_layout = QVBoxLayout(centre_content)
        centre_layout.setContentsMargins(0, 0, 0, 0)
        centre_layout.setSpacing(0)

        # ── 경로 탐색 바 (즐겨찾기 바 위) ──
        self._breadcrumb_bar = _BreadcrumbBar()
        centre_layout.addWidget(self._breadcrumb_bar)

        # ── 즐겨찾기 바 ──
        self._favorites_bar = _FavoritesBar()
        centre_layout.addWidget(self._favorites_bar)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(4, 4, 4, 4)
        toolbar.setSpacing(4)

        self._btn_icon  = QToolButton()
        self._btn_icon.setText("⊞")
        self._btn_list  = QToolButton()
        self._btn_list.setText("☰")
        self._btn_table = QToolButton()
        self._btn_table.setText("⊟")
        # 앨범 보기 — 음악 계열 카테고리에서만 나타난다(_update_view_options).
        self._btn_album = QToolButton()
        self._btn_album.setText("💿")
        self._btn_album.setToolTip("앨범 보기 (음악 카테고리)")
        self._btn_album.hide()
        for btn in (self._btn_icon, self._btn_list, self._btn_table, self._btn_album):
            btn.setCheckable(True)
            btn.setFixedSize(28, 28)
        self._btn_icon.setChecked(True)
        self._view_group = QButtonGroup(self)
        self._view_group.addButton(self._btn_icon,  _VIEW_ICON)
        self._view_group.addButton(self._btn_list,  _VIEW_LIST)
        self._view_group.addButton(self._btn_table, _VIEW_DETAIL)
        self._view_group.addButton(self._btn_album, _VIEW_ALBUMS)
        toolbar.addWidget(self._btn_icon)
        toolbar.addWidget(self._btn_list)
        toolbar.addWidget(self._btn_table)
        toolbar.addWidget(self._btn_album)
        toolbar.addSpacing(12)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("검색... (Enter: 즉시 검색)")
        self._search_box.setClearButtonEnabled(True)
        toolbar.addWidget(self._search_box, stretch=1)
        # 입력 디바운스 — 키를 누를 때마다 조회하면(한글 IME는 조합 중에도 방출)
        # DB 조회 워커가 폭주해 메인 스레드가 멈춘다. 입력이 멎으면 한 번만 조회한다.
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(_SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self._apply_search_text)

        # 정렬 옵션
        toolbar.addSpacing(8)
        self._sort_combo = QComboBox()
        self._sort_combo.addItem("최신순", ("created_at", False))
        self._sort_combo.addItem("오래된순", ("created_at", True))
        self._sort_combo.addItem("제목순 ↑", ("title", True))
        self._sort_combo.addItem("제목순 ↓", ("title", False))
        self._sort_combo.addItem("채널순 ↑", ("channel_name", True))
        self._sort_combo.addItem("채널순 ↓", ("channel_name", False))
        self._sort_combo.addItem("길이 길순", ("duration_sec", False))
        self._sort_combo.addItem("길이 짧순", ("duration_sec", True))
        self._sort_combo.setFixedWidth(90)
        toolbar.addWidget(self._sort_combo)

        toolbar.addSpacing(8)
        self._btn_reorder = QToolButton()
        self._btn_reorder.setText("⇅")
        self._btn_reorder.setToolTip("카테고리 영상 순서 편집 (드래그로 재정렬)")
        self._btn_reorder.setCheckable(True)
        self._btn_reorder.setChecked(False)
        self._btn_reorder.setFixedSize(28, 28)
        self._btn_reorder.hide()   # 카테고리 선택 시에만 표시
        toolbar.addWidget(self._btn_reorder)


        centre_layout.addLayout(toolbar)

        self._view_stack = QStackedWidget()
        self._model = VideoListModel()

        # Icon grid
        self._icon_view = _VideoListView()
        self._icon_view.setModel(self._model)
        self._icon_view.setViewMode(QListView.ViewMode.IconMode)
        self._icon_view.setResizeMode(QListView.ResizeMode.Adjust)
        self._icon_view.setUniformItemSizes(True)
        self._icon_view.setSpacing(14)
        self._icon_view.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self._icon_view.setIconSize(QSize(_TW_ICON, _TH_ICON))
        self._icon_view.setItemDelegate(self._icon_delegate)
        self._icon_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._icon_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._icon_view.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self._view_stack.addWidget(self._icon_view)

        # List view
        self._list_view = _VideoListView()
        self._list_view.setModel(self._model)
        self._list_view.setItemDelegate(self._list_delegate)
        self._list_view.setViewMode(QListView.ViewMode.ListMode)
        self._list_view.setUniformItemSizes(True)
        self._list_view.setSpacing(2)
        self._list_view.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self._list_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list_view.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        self._view_stack.addWidget(self._list_view)

        # Detail table
        self._table = QTableWidget()
        self._table.setColumnCount(9)
        self._table.setHorizontalHeaderLabels(
            ["제목", "채널", "재생시간", "카테고리", "★", "✓", "등록 일시", "영상", "음원"]
        )
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._view_stack.addWidget(self._table)

        # 폴더 내 재생목록 카드 그리드 뷰 (_VIEW_FOLDER = 3)
        self._folder_view = _FolderContentsView()
        self._view_stack.addWidget(self._folder_view)

        # 구독 채널/전체 피드 카드 그리드 뷰 (_VIEW_FEED = 4) — feed_panel 부품 재사용
        self._feed_view = self._build_feed_view()
        self._view_stack.addWidget(self._feed_view)

        # 구독 채널 목록(아바타 카드) 그리드 뷰 (_VIEW_CHANNELS = 5)
        self._channels_view = self._build_channels_view()
        self._view_stack.addWidget(self._channels_view)

        # 앨범 자켓 그리드 (_VIEW_ALBUMS = 6) — 음악 카테고리에서 정렬 '앨범' 선택 시
        from gui.panels.album_panel import AlbumGrid  # noqa: PLC0415
        self._album_grid = AlbumGrid()
        self._view_stack.addWidget(self._album_grid)

        # ── 영상 목록 + 추천 스트립을 수직 스플리터로 묶는다 ──
        # 스플리터 핸들을 끌어 추천 영역 높이를 조절하고, 스트립 헤더의 삼각형
        # 버튼으로 본문만 접는다(헤더는 남아 다시 펼칠 수 있다). 스플리터 자식
        # 자체를 숨기지 않으므로 과거 태그 섹션에서 겪은 레이아웃 thrash가 없다.
        self._centre_splitter = QSplitter(Qt.Orientation.Vertical)
        self._centre_splitter.setChildrenCollapsible(False)
        self._centre_splitter.setHandleWidth(6)
        from gui.panels.feed_panel import RecommendStrip  # noqa: PLC0415
        self._centre_splitter.addWidget(self._view_stack)
        self._recommend_strip = RecommendStrip()
        self._centre_splitter.addWidget(self._recommend_strip)
        self._centre_splitter.setStretchFactor(0, 1)
        self._centre_splitter.setStretchFactor(1, 0)
        centre_layout.addWidget(self._centre_splitter, stretch=1)
        # 마지막 상태 복원 (기본: 펼침) — 접혀 있으면 네트워크 조회도 하지 않는다.
        self._recommend_height: int = max(
            int(getattr(_settings, "RECOMMEND_STRIP_HEIGHT", 250)),
            self._recommend_strip.HEADER_H + 40,
        )
        expanded = bool(getattr(_settings, "RECOMMEND_STRIP_EXPANDED", True))
        self._recommend_strip.set_expanded(expanded, notify=False)
        # 추천 목록이 모두 준비되기 전에는 스트립을 감춘다 — 준비되면 아래에서
        # 부드럽게 올라온다(_reveal_recommend_strip). 접혀 있으면 조회 자체를 하지
        # 않으므로(네트워크 절약) 헤더 바만 바로 띄워 다시 펼칠 수단을 남긴다.
        self._recommend_ready: bool = not expanded
        self._recommend_anim: QVariantAnimation | None = None
        self._recommend_strip.setVisible(not expanded)
        if not expanded:
            # 실제 높이 배분은 위젯이 크기를 가진 뒤에 적용한다(첫 표시 전 height()==0).
            QTimer.singleShot(0, lambda: self._sync_recommend_sizes(False, save=False))
        self._nav_stack.addWidget(centre_content)

        self._detail_widget = VideoDetailWidget(
            clip_vm=self._clip_vm,
            download_vm=self._download_vm,
        )
        self._nav_stack.addWidget(self._detail_widget)

        # 앨범 상세 (_nav_stack 인덱스 2) — 자켓·설명·수록곡 목록
        from gui.panels.album_panel import AlbumDetailPanel  # noqa: PLC0415
        self._album_detail = AlbumDetailPanel()
        self._nav_stack.addWidget(self._album_detail)

        outer_splitter.addWidget(self._nav_stack)

        # 미리보기 패널 제거 — 영상 단일 클릭 시 곧바로 상세화면(YouTube 시청 페이지)으로
        # 전환하므로 우측 미리보기 패널은 더 이상 사용하지 않는다.
        outer_splitter.setStretchFactor(0, 0)
        outer_splitter.setStretchFactor(1, 1)
        outer_splitter.setSizes([200, 800])

        self._outer_splitter = outer_splitter

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(outer_splitter)

    # ── Signal wiring ──────────────────────────────────────────────

    def _connect_signals(self) -> None:
        self._vm.videos_changed.connect(self._on_videos_changed)
        self._vm.categories_changed.connect(self._on_categories_changed)
        self._vm.tags_changed.connect(self._on_tags_changed)
        self._vm.scoped_tags_changed.connect(self._refresh_popular_tags)
        self._vm.loading_key_changed.connect(self._on_local_loading_key_changed)
        ThemeManager.instance().theme_changed.connect(lambda _: self._apply_sidebar_tree_style())

        # 재생목록 탭 시그널
        # playlist_selected → 뷰 전환 포함 통합 핸들러 (폴더 뷰 → 목록 뷰 복귀 버그 수정)
        self._playlist_panel.playlist_selected.connect(self._on_playlist_selected_from_tree)
        self._playlist_panel.delete_playlist_req.connect(self._on_delete_playlist)
        self._playlist_panel.rename_playlist_req.connect(self._on_rename_playlist)
        self._playlist_panel.playlist_move_req.connect(self._on_playlist_move)
        self._playlist_panel.import_yt_req.connect(self._on_import_yt_playlist)
        self._playlist_panel.sync_all_yt_req.connect(self._on_sync_all_yt)
        self._playlist_panel.video_reordered.connect(self._on_playlist_reordered)
        self._playlist_panel.folder_create_req.connect(self._on_folder_create)
        self._playlist_panel.folder_rename_req.connect(self._on_folder_rename)
        self._playlist_panel.folder_delete_req.connect(self._on_folder_delete)
        self._playlist_panel.copy_yt_to_local_req.connect(self._on_copy_yt_to_local)
        self._playlist_panel.sync_yt_req.connect(self._on_sync_yt_playlist)
        self._playlist_panel.push_to_yt_req.connect(self._on_push_to_youtube)
        self._playlist_panel.video_move_to_playlist_req.connect(self._on_video_move_to_playlist_from_dnd)
        self._playlist_panel.folder_selected.connect(self._on_folder_selected)
        self._playlist_panel.unfiled_selected.connect(self._on_unfiled_selected)
        self._playlist_panel.channel_selected.connect(self._on_channel_selected)
        self._playlist_panel.feed_all_selected.connect(self._on_feed_all_selected)
        self._playlist_panel.channels_root_selected.connect(self._on_channels_root_selected)
        self._playlist_panel.sync_subs_req.connect(self._on_sync_subscriptions)
        self._folder_view.playlist_selected.connect(self._on_folder_playlist_selected)
        self._folder_view.folder_selected.connect(self._on_folder_selected)
        if self._playlist_vm is not None:
            self._playlist_vm.playlists_changed.connect(self._on_playlists_changed)
            self._playlist_vm.folders_changed.connect(self._on_playlists_changed)
            self._playlist_vm.error_occurred.connect(
                lambda err: self._vm.error_occurred.emit(err)
            )
        # 구독 피드 VM (구독 채널 트리에 통합)
        if self._feed_vm is not None:
            self._feed_vm.feed_changed.connect(self._on_feed_changed)
            self._feed_vm.feed_batch_appended.connect(self._on_feed_batch_appended)
            self._feed_vm.channel_infos_changed.connect(self._on_channel_infos_changed)
            self._feed_vm.loading_changed.connect(self._on_feed_loading_changed)
            self._feed_vm.error_occurred.connect(self._on_feed_error)
            self._feed_vm.loading_key_changed.connect(self._on_feed_loading_key_changed)
            self._feed_vm.feed_key_changed.connect(self._on_feed_key_changed)
            self._feed_vm.feed_batch_ready.connect(self._on_feed_batch_ready)
        # 채널 모니터링 VM — 구독 목록을 YouTube 트리에 반영
        if self._monitoring_vm is not None:
            self._monitoring_vm.subscriptions_changed.connect(self._refresh_unified_tree)
            self._monitoring_vm.import_yt_finished.connect(self._on_subs_synced)
            self._monitoring_vm.error_occurred.connect(self._on_subs_sync_error)
            QTimer.singleShot(0, self._monitoring_vm.load)
        self._vm.yt_import_finished.connect(self._on_yt_import_finished)

        self._view_group.idClicked.connect(self._on_view_button_clicked)
        self._view_stack.currentChanged.connect(self._on_view_stack_changed)
        self._search_box.textChanged.connect(self._on_search_text_changed)
        self._search_box.returnPressed.connect(self._apply_search_text)
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        self._btn_reorder.toggled.connect(self._on_reorder_toggled)
        self._model.reordered.connect(self._on_category_reordered)

        self._playlist_panel.category_selected.connect(self._on_cat_filter_changed)
        self._playlist_panel.add_category_req.connect(self._on_add_category)
        self._playlist_panel.rename_category_req.connect(self._on_rename_category)
        self._playlist_panel.delete_category_req.connect(self._on_delete_category)
        self._playlist_panel.category_reparented.connect(self._on_category_reparented)
        self._playlist_panel.yt_playlist_to_category_req.connect(self._on_yt_playlist_to_category)
        self._playlist_panel.favorite_toggle_req.connect(self._toggle_favorite)
        self._playlist_panel.video_assign_category_req.connect(self._on_video_moved)
        self._playlist_panel.local_playlist_to_category_req.connect(self._on_local_playlist_to_category)
        # 트리에 URL을 끌어다 놓으면 그 카테고리로 등록한다(추천 카드·브라우저 주소 공용)
        self._playlist_panel.url_dropped.connect(self._on_url_dropped)

        # ── 추천 영상 스트립 ──
        self._recommend_strip.refresh_requested.connect(self._on_recommend_refresh_clicked)
        self._recommend_strip.expanded_changed.connect(self._on_recommend_expanded)
        self._recommend_strip.video_clicked.connect(self._open_stream_detail)
        self._recommend_strip.download_requested.connect(self._on_feed_card_download)
        self._recommend_strip.add_to_category_requested.connect(self._on_recommend_to_category)
        self._recommend_strip.add_to_playlist_requested.connect(self._on_feed_card_to_playlist)
        if self._recommend_vm is not None:
            self._recommend_vm.items_changed.connect(self._on_recommend_items)
            self._recommend_vm.partial_ready.connect(self._on_recommend_partial)
            self._recommend_vm.loading_changed.connect(self._recommend_strip.set_loading)
            self._recommend_vm.error_occurred.connect(self._on_recommend_error)
        else:
            self._recommend_strip.set_status("추천 기능을 사용할 수 없습니다.")
            # 조회가 아예 없으므로 노출 조건(결과 도착)이 영영 오지 않는다 —
            # 안내 문구를 보여줘야 하니 헤더 높이만큼 바로 띄운다.
            self._reveal_recommend_strip(False)
        # ── 앨범 보기 ──
        self._album_grid.album_clicked.connect(self._on_album_clicked)
        self._album_detail.back_requested.connect(self._on_album_back)
        self._album_detail.play_album_requested.connect(self._on_play_album)
        self._album_detail.track_clicked.connect(self._on_album_track_clicked)
        self._album_detail.refresh_requested.connect(self._on_album_refresh)
        self._album_detail.fill_requested.connect(self._on_album_fill_requested)
        self._album_detail.add_all_requested.connect(self._on_album_add_all)
        if self._album_vm is not None:
            self._album_vm.albums_changed.connect(self._on_albums_changed)
            self._album_vm.detail_ready.connect(self._on_album_detail_ready)
            self._album_vm.track_filled.connect(self._on_album_track_filled)
            self._album_vm.fill_finished.connect(self._on_album_fill_finished)
            self._album_vm.unknown_resolved.connect(self._on_album_unknown_resolved)
            self._album_vm.add_progress.connect(self._on_album_add_progress)
            self._album_vm.tracks_added.connect(self._on_album_tracks_added)
            self._album_vm.error_occurred.connect(self._on_album_error)

        self._breadcrumb_bar.segment_clicked.connect(self._on_breadcrumb_nav)
        self._breadcrumb_bar.tag_removed.connect(self._on_active_tag_removed)
        self._vm.metadata_refresh_progress.connect(self._on_refresh_progress)
        self._vm.metadata_refresh_finished.connect(self._on_refresh_finished)
        self._vm.video_metadata_refreshed.connect(self._on_video_metadata_refreshed)
        self._vm.enrich_finished.connect(self._on_enrich_finished)
        self._tag_list.itemClicked.connect(self._on_tag_clicked)
        self._tag_list.delete_requested.connect(self._on_tag_delete_requested)
        self._tag_list.favorite_toggled.connect(self._toggle_favorite)
        self._tag_filter_input.textChanged.connect(self._on_tag_filter_text_changed)
        self._favorites_bar.item_clicked.connect(self._on_favorite_clicked)
        self._favorites_bar.unfav_requested.connect(self._on_fav_unfav_requested)
        self._favorites_bar.refresh()

        self._icon_view.clicked.connect(
            lambda idx: self._on_item_clicked(idx, self._icon_view)
        )
        self._list_view.clicked.connect(
            lambda idx: self._on_item_clicked(idx, self._list_view)
        )
        self._icon_view.doubleClicked.connect(self._on_double_click)
        self._list_view.doubleClicked.connect(self._on_double_click)
        self._icon_view.empty_clicked.connect(self._on_empty_clicked)
        self._list_view.empty_clicked.connect(self._on_empty_clicked)
        self._icon_view.url_dropped.connect(self._on_list_url_dropped)
        self._list_view.url_dropped.connect(self._on_list_url_dropped)
        self._icon_view.customContextMenuRequested.connect(
            lambda pos: self._show_video_menu(pos, self._icon_view)
        )
        self._list_view.customContextMenuRequested.connect(
            lambda pos: self._show_video_menu(pos, self._list_view)
        )

        self._table.clicked.connect(self._on_table_clicked)
        self._table.doubleClicked.connect(self._on_table_double_click)
        self._table.customContextMenuRequested.connect(self._show_table_menu)

        self._detail_widget.back_requested.connect(self._on_detail_back_requested)
        self._detail_widget.tag_filter_requested.connect(self._on_tag_filter_requested)
        self._detail_widget.tags_updated.connect(self._on_detail_tags_updated)
        self._detail_widget.download_requested.connect(self.download_requested.emit)
        self._detail_widget.item_selected.connect(self._on_related_item_selected)
        self._detail_widget.notes_saved.connect(
            lambda vid_id, text: self._vm.save_notes(vid_id, text)
        )
        self._detail_widget.gemini_summary_saved.connect(
            lambda vid_id, text: self._vm.save_gemini_summary(vid_id, text)
        )
        self._detail_widget.summary_status_saved.connect(
            lambda vid_id, status: self._vm.save_summary_status(vid_id, status)
        )
        self._detail_widget.downloads_refresh_requested.connect(
            self._on_detail_downloads_refresh
        )
        self._detail_widget.detail_refresh_requested.connect(
            self._on_detail_refresh_requested
        )
        self._detail_widget.category_path_clicked.connect(self._on_cat_filter_changed)
        self._detail_widget.category_assign_requested.connect(
            self._on_detail_category_requested
        )
        # 스트리밍 영상을 카테고리에 담으면 등록 완료 후 로컬 상세로 갈아탄다.
        self._vm.video_add_finished.connect(self._on_video_added_for_detail)
        # 노래 탭 가수/앨범 » 필터 + 재생목록 다음곡 자동재생
        self._detail_widget.song_filter_requested.connect(self._on_song_filter_requested)
        self._detail_widget.play_next_requested.connect(self._on_play_next)

        # 노래 탭 ↔ SongViewModel 배선
        if self._song_vm is not None:
            self._song_vm.song_info_changed.connect(self._detail_widget.set_song_info)
            self._song_vm.busy_changed.connect(self._detail_widget.set_song_busy)
            self._song_vm.error_occurred.connect(
                lambda err: self._vm.error_occurred.emit(err)
            )
            self._detail_widget.song_field_saved.connect(self._song_vm.save_field)
            self._detail_widget.song_lyrics_saved.connect(self._song_vm.save_lyrics)
            # 가사 검색 → 후보 목록(출처·가수·제목·첫 줄·싱크). 결과는 도착하는 대로
            # 상세 위젯에 흘려보내고, 사용자가 고른 후보만 실제로 반영한다.
            self._detail_widget.song_candidates_requested.connect(
                self._song_vm.search_lyrics_candidates
            )
            self._detail_widget.song_candidate_chosen.connect(
                self._song_vm.apply_lyrics_candidate
            )
            self._song_vm.candidates_started.connect(
                self._detail_widget.song_candidates_started
            )
            self._song_vm.candidate_ready.connect(
                self._detail_widget.song_candidate_ready
            )
            self._song_vm.candidate_source_done.connect(
                self._detail_widget.song_candidate_source_done
            )
            self._song_vm.candidates_finished.connect(
                self._detail_widget.song_candidates_finished
            )
            self._detail_widget.song_translate_requested.connect(
                self._song_vm.translate_lyrics
            )
            self._detail_widget.song_flag_toggled.connect(self._song_vm.toggle_song)
            self._detail_widget.song_synced_requested.connect(
                self._song_vm.fetch_synced_lyrics
            )
            self._detail_widget.song_offset_saved.connect(self._song_vm.set_lyrics_offset)

        # 구독 피드/채널 카드 단일 클릭 → 스트리밍 상세
        self._feed_grid.video_clicked.connect(self._open_stream_detail)

        # Ctrl+휠 뷰 전환 & 마우스 BackButton 히스토리 이벤트 필터.
        # 앨범 그리드·앨범 상세도 포함해야 그 화면에서 마우스 뒤로가기가 동작한다
        # (영상 상세는 자체 app 레벨 필터로 처리한다).
        for w in (self._icon_view, self._list_view, self._table,
                  self._album_grid, self._album_detail):
            viewport = getattr(w, "viewport", None)
            if viewport:
                viewport().installEventFilter(self)
            w.installEventFilter(self)

    # ── 검색 ───────────────────────────────────────────────────────

    def _on_search_text_changed(self, text: str) -> None:
        """입력 중에는 타이머만 다시 시작하고, 지우기(빈 문자열)는 즉시 반영한다."""
        if not text.strip():
            self._search_timer.stop()
            self._apply_search_text()
            return
        self._search_timer.start()

    def _apply_search_text(self) -> None:
        """디바운스가 끝났거나 Enter를 눌렀을 때 실제 검색을 수행한다."""
        self._search_timer.stop()
        self._vm.set_search_text(self._search_box.text())

    # ── VM → UI ────────────────────────────────────────────────────

    def _on_videos_changed(self) -> None:
        videos = self._vm.videos
        self._model.set_videos(videos)
        # 표(상세) 뷰는 행마다 위젯을 만들고 다운로드 여부까지 조회하므로
        # 실제로 보고 있을 때만 채운다. 숨겨져 있으면 표시 시점으로 미룬다.
        if self._view_stack.currentIndex() == _VIEW_DETAIL:
            self._refresh_table()
        else:
            self._table_dirty = True
        self._start_thumb_preload(videos)
        self._schedule_recommend_refresh()

    # ── 추천 영상 스트립 ───────────────────────────────────────────────
    # 배경: YouTube Data API v3의 search.list(relatedToVideoId=)가 폐지돼
    # '관련 영상'을 직접 받을 수 없다. 지금 보고 있는 목록(제목·채널·태그)에서
    # 대표 검색어를 뽑아 검색으로 후보를 모은다(domain/library/recommendation.py).

    def _recommend_seeds(self) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        """현재 목록에서 (제목, 채널, 태그) 씨앗을 뽑는다."""
        videos = self._vm.videos[:_RECOMMEND_SEED_LIMIT]
        titles = tuple(v.title for v in videos if v.title)
        channels = tuple(v.channel_name for v in videos if v.channel_name)
        tags = tuple(t for v in videos for t in (v.tag_names or ()))
        return titles, channels, tags

    def _schedule_recommend_refresh(self) -> None:
        """목록 변경 후 추천 갱신을 예약한다(디바운스)."""
        if self._recommend_vm is None or not self._recommend_strip.is_expanded:
            return
        # 카드 그리드 뷰(폴더·피드·채널)는 라이브러리 목록이 아니라 씨앗이 어긋난다.
        if self._view_stack.currentIndex() in (_VIEW_FOLDER, _VIEW_FEED, _VIEW_CHANNELS):
            return
        self._recommend_timer.start()

    def _refresh_recommendations(self, force: bool = False) -> None:
        if self._recommend_vm is None or not self._recommend_strip.is_expanded:
            return
        titles, channels, tags = self._recommend_seeds()
        if not titles and not channels and not tags:
            self._recommend_strip.set_items([])
            self._recommend_strip.set_status("목록이 비어 있어 추천할 기준이 없습니다.")
            self._reveal_recommend_strip(False)
            return
        self._recommend_strip.set_status("")
        # 새 씨앗으로 조회를 시작한다 — 결과가 올 때까지 다시 감춘다(직전 카테고리의
        # 추천이 새 목록의 추천인 것처럼 남아 있지 않도록).
        self._hide_recommend_strip()
        self._recommend_vm.load(
            seed_titles=titles,
            seed_channels=channels,
            seed_tags=tags,
            limit=_RECOMMEND_COUNT,
            force=force,
        )

    def _on_recommend_refresh_clicked(self) -> None:
        self._recommend_timer.stop()
        self._refresh_recommendations(force=True)

    def _sync_recommend_sizes(self, expanded: bool, save: bool = True) -> None:
        """스플리터 높이 배분을 접힘 상태에 맞춘다.

        ``setChildrenCollapsible(False)``라 본문을 숨겨도 스플리터가 배분한 높이는
        그대로 남는다(빈 공간). 접을 때 헤더 높이만 남기고, 펼칠 때 직전 높이를
        복원한다.
        """
        sizes = self._centre_splitter.sizes()
        total = sum(sizes) or self._centre_splitter.height()
        header = self._recommend_strip.HEADER_H
        if total <= header:
            return
        if expanded:
            h = min(self._recommend_height, max(total - 120, header))
        else:
            if len(sizes) == 2 and sizes[1] > header + 20:
                self._recommend_height = sizes[1]   # 다음에 펼칠 때 복원할 높이
                if save:
                    _settings.save_setting("recommend_strip_height", int(sizes[1]))
            h = header
        self._centre_splitter.setSizes([max(total - h, 0), h])

    def _on_recommend_expanded(self, expanded: bool) -> None:
        _settings.save_setting("recommend_strip_expanded", expanded)
        self._sync_recommend_sizes(expanded)
        if expanded and self._recommend_strip.count() == 0:
            self._refresh_recommendations()

    def _on_recommend_partial(self, items: list) -> None:
        # 검색 직후의 부분 결과(조회수·게시일 없음)를 먼저 보여준다.
        self._recommend_strip.set_items(items)

    def _on_recommend_items(self, items: list) -> None:
        self._recommend_strip.set_items(items)
        self._recommend_strip.set_status("" if items else "추천할 영상을 찾지 못했습니다.")
        self._reveal_recommend_strip(bool(items))
        # 상세화면이 열려 있으면 우측 목록 아래 추천 구역도 함께 갱신한다.
        if self._nav_stack.currentIndex() == 1:
            self._detail_widget.set_recommendations(self._recommend_related_items())

    def _on_recommend_error(self, msg: str) -> None:
        logger.warning("추천 영상 조회 실패: %s", msg)
        self._recommend_strip.set_status("추천을 받지 못했습니다.")
        self._reveal_recommend_strip(False)

    # ── 스트립 등장/퇴장 연출 ─────────────────────────────────────────
    # 조회 중인 빈 띠(또는 직전 카테고리의 추천)가 자리를 차지하지 않도록, 목록이 다
    # 준비된 뒤에야 아래에서 밀려 올라오듯 노출한다. 새 조회가 시작되면(카테고리 전환·
    # 검색·⟳) 다시 아래로 접어 감췄다가 결과가 도착하면 올린다.

    def _reveal_recommend_strip(self, has_items: bool) -> None:
        """조회가 끝난 뒤 스트립을 노출한다.

        결과가 없거나 실패했을 때도 헤더 높이만큼은 띄운다 — 완전히 숨기면
        ⟳(다시 받기)와 접기 토글에 닿을 방법이 사라진다.
        """
        if self._recommend_ready:
            return
        self._recommend_ready = True
        if self._view_stack.currentIndex() in (_VIEW_FOLDER, _VIEW_FEED, _VIEW_CHANNELS):
            return   # 이 화면들은 원래 스트립을 감춘다(목록 뷰로 돌아올 때 표시됨)
        strip = self._recommend_strip
        target = self._recommend_height if (has_items and strip.is_expanded) else strip.HEADER_H
        self._animate_recommend_in(target)

    def _hide_recommend_strip(self) -> None:
        """새 조회를 시작할 때 다시 감춘다 — 준비되면 아래에서 올라온다.

        카테고리를 바꾸면 씨앗이 통째로 달라져 지금 걸린 카드는 새 목록과 무관하다.
        조회가 끝날 때까지 남겨 두면 '이미 준비된 추천'처럼 보이므로, 결과가 올 때까지
        접어 둔다(등장과 같은 연출의 역순).
        """
        if not self._recommend_ready:
            return
        self._recommend_ready = False
        strip = self._recommend_strip
        if strip.isHidden():
            return
        # 사용자가 핸들로 맞춰 둔 높이를 기억했다가 다시 올라올 때 그대로 복원한다.
        sizes = self._centre_splitter.sizes()
        if len(sizes) == 2 and strip.is_expanded and sizes[1] > strip.HEADER_H + 20:
            self._recommend_height = sizes[1]
        self._animate_recommend_out()

    def _animate_recommend_in(self, target: int) -> None:
        """스트립 높이를 0→target으로 늘려 아래에서 올라오는 것처럼 보이게 한다.

        스플리터는 자식의 ``maximumHeight``를 존중하므로(그리고 그 값이
        ``qSmartMinSize``의 상한이 되어 최소 높이도 함께 눌린다) ``setSizes``만으로는
        0에서 시작할 수 없다. 그래서 maximumHeight를 애니메이션하고, 끝나면 원래
        값(_QWIDGET_MAX_H)으로 되돌려 사용자가 핸들로 다시 조절할 수 있게 한다.
        """
        strip = self._recommend_strip
        splitter = self._centre_splitter
        target = max(int(target), strip.HEADER_H)
        # 접히는 중이었다면 그 높이에서 이어 올라간다(0으로 튀지 않게).
        start = 0 if strip.isHidden() else min(max(strip.height(), 0), target)
        self._stop_recommend_anim()
        total = sum(splitter.sizes()) or splitter.height()
        if total <= target + 80:
            # 공간이 부족하면 연출 없이 그냥 편다(찌그러진 애니메이션 방지).
            strip.setVisible(True)
            self._sync_recommend_sizes(strip.is_expanded, save=False)
            return
        strip.setMaximumHeight(start)
        strip.setVisible(True)

        def _done() -> None:
            strip.setMaximumHeight(_QWIDGET_MAX_H)
            splitter.setSizes([max(total - target, 0), target])
            self._recommend_anim = None

        self._start_recommend_anim(start, target, total, _done)

    def _animate_recommend_out(self) -> None:
        """스트립을 아래로 접으며 감춘다(등장 연출의 역순)."""
        strip = self._recommend_strip
        splitter = self._centre_splitter
        start = max(strip.height(), 0)
        self._stop_recommend_anim()
        total = sum(splitter.sizes()) or splitter.height()
        if start <= 0 or total <= start:
            strip.setVisible(False)      # 아직 배치 전 — 연출할 높이가 없다
            return

        def _done() -> None:
            strip.setVisible(False)
            strip.setMaximumHeight(_QWIDGET_MAX_H)
            self._recommend_anim = None

        self._start_recommend_anim(start, 0, total, _done)

    def _start_recommend_anim(self, start: int, end: int, total: int, on_done) -> None:
        """스트립 높이(maximumHeight + 스플리터 배분)를 start→end로 움직인다."""
        strip = self._recommend_strip
        splitter = self._centre_splitter

        def _step(value) -> None:
            h = int(value)
            strip.setMaximumHeight(h)
            splitter.setSizes([max(total - h, 0), h])

        anim = QVariantAnimation(self)
        anim.setStartValue(int(start))
        anim.setEndValue(int(end))
        anim.setDuration(_RECOMMEND_REVEAL_MS)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(_step)
        anim.finished.connect(on_done)
        self._recommend_anim = anim
        anim.start()

    def _stop_recommend_anim(self) -> None:
        anim = self._recommend_anim
        self._recommend_anim = None
        if anim is not None:
            anim.stop()
            self._recommend_strip.setMaximumHeight(_QWIDGET_MAX_H)

    def _recommend_related_items(self) -> list:
        """현재 추천 결과를 상세화면 우측 목록용 RelatedItem으로 변환한다.

        스트립과 같은 결과를 재사용한다 — 상세를 열 때마다 따로 조회하면 네트워크
        비용이 배가 되고, 추천 뷰모델이 하나뿐이라 스트립의 목록까지 뒤엎게 된다.
        """
        if self._recommend_vm is None:
            return []
        return [
            self._related_from_feed(f)
            for f in self._recommend_vm.items[:_DETAIL_RECOMMEND_COUNT]
        ]

    def _on_recommend_to_category(self, url: str) -> None:
        """추천 카드 우클릭 '카테고리에 추가' — 드래그하지 않고도 담을 수 있게.

        ``selected_id``는 **메서드**다 — 예전엔 괄호 없이 써서 항상 참이었고, 카테고리
        id 자리에 바운드 메서드가 그대로 넘어갔다(등록 실패).
        """
        ok, cat_id = self._pick_category()
        if ok:
            self._vm.add_video(url, cat_id)

    def _start_thumb_preload(self, videos: list) -> None:
        """현재 뷰 모드에 맞는 크기로 썸네일을 bg에서 프리로드한다."""
        # isVisible()은 위젯이 표시되기 전 False를 반환할 수 있으므로
        # currentWidget() 기준으로 활성 뷰를 판단한다.
        is_icon = self._view_stack.currentWidget() is not self._list_view
        w, h = (_TW_ICON, _TH_ICON) if is_icon else (_TW_LIST, _TH_LIST)
        items = [(dto.thumbnail_path, w, h) for dto in videos if dto.thumbnail_path]
        if not items:
            return
        self._thumb_load_gen += 1
        gen = self._thumb_load_gen
        # 이전 목록의 로더는 취소한다 — 이미 지나간 결과의 썸네일을 계속 디코딩하면
        # 검색어 입력 중 CPU를 붙잡아 키 입력이 밀린다(캐시된 배치는 이미 반영됨).
        for old in self._active_thumb_loaders:
            old.cancel()
        loader = _ThumbBgLoader(items)
        self._active_thumb_loaders.append(loader)

        def _on_loader_done(done=loader) -> None:
            try:
                self._active_thumb_loaders.remove(done)
            except ValueError:
                logger.debug("썸네일 로더가 이미 목록에서 제거됨 — 무시")
            done.deleteLater()

        loader.batch_ready.connect(lambda b, g=gen: self._on_thumb_batch(b, g))
        loader.finished.connect(_on_loader_done)
        loader.start()

    def _on_thumb_batch(self, batch: list, gen: int) -> None:
        """_ThumbBgLoader 배치 완료 처리: 항상 캐시에 저장, 현재 gen만 UI 갱신."""
        paths_updated: set[str] = set()
        for path, w, h, img in batch:
            key = f"{path}@{w}x{h}"
            if _thumb_cache.get(key) is None:  # 중복 방어 (main thread에서만 write)
                _thumb_cache.put(key, QPixmap.fromImage(img))
            paths_updated.add(path)
        if gen == self._thumb_load_gen:
            self._model.notify_thumb_cached(paths_updated)
        # gen 불일치(구 노드 로더)도 캐시에는 저장 완료 → 재방문 시 캐시 히트

    def _on_categories_changed(self) -> None:
        self._refresh_unified_tree()

    def _refresh_unified_tree(self) -> None:
        """카테고리 또는 재생목록이 변경될 때 통합 트리를 갱신한다."""
        subs = self._monitoring_vm.subscriptions if self._monitoring_vm is not None else []
        if self._playlist_vm is not None:
            self._playlist_panel.refresh(
                self._playlist_vm.playlists,
                self._playlist_vm.folders,
                self._vm.categories,
                subscriptions=subs,
            )
        else:
            self._playlist_panel.refresh([], [], self._vm.categories, subscriptions=subs)
        self._favorites_bar.refresh(self._get_fav_counts())

    def _on_tags_changed(self) -> None:
        self._all_tags = sorted(self._vm.tags, key=lambda t: t.name)
        # Drop active IDs that no longer exist (tag was deleted)
        existing = {t.id for t in self._all_tags}
        self._active_tag_ids &= existing
        self._refresh_tag_display()

    def _refresh_tag_display(self) -> None:
        from config.settings import load_hidden_tag_names  # noqa: PLC0415
        hidden_names = load_hidden_tag_names()
        filter_text = self._tag_filter_input.text().strip().lower()
        self._tag_list.blockSignals(True)
        self._tag_list.clear()
        for tag in self._all_tags:
            if tag.name in hidden_names:
                continue
            if filter_text and filter_text not in tag.name.lower():
                continue
            item = QListWidgetItem(f"#{tag.name}")
            item.setData(Qt.ItemDataRole.UserRole, tag.id)
            item.setData(Qt.ItemDataRole.UserRole + 1, tag.count)
            self._tag_list.addItem(item)
            if tag.id in self._active_tag_ids:
                item.setSelected(True)
        self._tag_list.blockSignals(False)
        self._refresh_active_tags_bar()

    def _on_tag_filter_text_changed(self) -> None:
        self._refresh_tag_display()

    def _apply_sidebar_tree_style(self) -> None:
        tok = _t()
        # 행 배경·선택 표시·셰브론은 모두 _TreeRowDelegate와 _PlaylistTree.drawBranches()가
        # 직접 그린다. 따라서 여기서는 ::item / ::branch 배경·이미지 규칙을 두지 않는다
        # (두면 델리게이트가 그린 위에 QSS가 겹쳐 그려질 위험이 있고, 실제로는 우회되어
        #  죽은 CSS가 된다). 컨테이너 속성만 남긴다.
        branch_style = """
            QTreeWidget {
                background: transparent;
                border: none;
                outline: none;
            }
        """
        hdr_style = f"""
            QLabel#playlist_section_header {{
                font-size: 9pt;
                font-weight: 700;
                color: {tok.text_secondary};
                padding: 4px 6px 2px 4px;
                background: transparent;
            }}
            QPushButton#playlist_section_header_local {{
                font-size: 9pt;
                font-weight: 700;
                color: {tok.text_muted};
                letter-spacing: 0.6px;
                padding: 4px 6px 2px 4px;
                background: transparent;
                border: none;
                text-align: left;
            }}
            QPushButton#playlist_section_header_local:hover {{
                color: {tok.text_primary};
                background: transparent;
            }}
            QPushButton#playlist_section_header_local:checked {{
                color: {tok.accent};
                background: {tok.bg_overlay};
                border-radius: 4px;
            }}
            QPushButton#playlist_section_header_yt_btn {{
                font-size: 9pt;
                font-weight: 700;
                color: {_YT_BRAND_RED};
                letter-spacing: 0.6px;
                padding: 2px 4px;
                background: transparent;
                border: none;
                text-align: left;
            }}
            QPushButton#playlist_section_header_yt_btn:hover {{
                color: {_YT_BRAND_RED_HOVER};
                text-decoration: underline;
            }}
            QWidget#yt_toggle_bar {{
                border-top: 1px solid {tok.border};
                background: {tok.bg_overlay};
            }}
            QToolButton#yt_toggle_arrow {{
                color: {_YT_BRAND_RED};
                font-size: 10pt;
                border: none;
                background: transparent;
            }}
            QToolButton#yt_toggle_arrow:hover {{
                color: {_YT_BRAND_RED_HOVER};
            }}
        """
        local_tree, yt_tree = self._playlist_panel.trees
        local_tree.setStyleSheet(branch_style)   # 로컬: branch indicator 있음
        yt_tree.setStyleSheet(branch_style)      # YouTube: "구독 채널" 등 자식 노드에 펼침 세모 표시
        self._playlist_panel.setStyleSheet(hdr_style)

    def _refresh_active_tags_bar(self) -> None:
        self._refresh_breadcrumb()
        self._refresh_popular_tags()

    def _set_popular_tags_visible(self, visible: bool) -> None:
        """태그 섹션(인기/전체 태그)은 카테고리 선택 시에만 보인다. 재생목록·폴더·
        피드·채널 뷰에서는 숨겨 재생목록 트리가 그 공간을 차지하도록 한다."""
        if self._tag_section.isVisible() == visible:
            return
        # (스플리터 제거 후로는 태그 섹션 가시성만 토글하면 된다 — 로컬/YouTube
        #  트리는 일반 레이아웃이라 재분배로 인한 위치 변동이 없다.)
        self._tag_section.setVisible(visible)

    def _refresh_popular_tags(self) -> None:
        from config.settings import load_hidden_tag_names  # noqa: PLC0415
        hidden_names = load_hidden_tag_names()
        while self._popular_tags_layout.count():
            item = self._popular_tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        # 현재 트리 노드 스코프 태그(카테고리/재생목록). 비면 라이브러리 전체로 폴백.
        source = self._vm.scoped_tags or self._all_tags
        top_tags = sorted(
            (t for t in source if t.name not in hidden_names),
            key=lambda t: -t.count,
        )[:5]
        for tag in top_tags:
            selected = tag.id in self._active_tag_ids
            color = tag_color(tag.name)
            btn = _PopularTagButton(tag.name, tag.count, color, selected)
            btn.clicked.connect(lambda _, tid=tag.id: self._on_popular_tag_clicked(tid))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, b=btn, tid=tag.id, tname=tag.name: self._show_popular_tag_context_menu(pos, b, tid, tname)
            )
            self._popular_tags_layout.addWidget(btn)

    def _on_popular_tag_clicked(self, tag_id: UUID) -> None:
        if not self._is_restoring:
            self._push_nav_state()
        if tag_id in self._active_tag_ids:
            self._active_tag_ids.discard(tag_id)
        else:
            self._active_tag_ids.add(tag_id)
        self._tag_list.blockSignals(True)
        for i in range(self._tag_list.count()):
            item = self._tag_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == tag_id:
                item.setSelected(tag_id in self._active_tag_ids)
                break
        self._tag_list.blockSignals(False)
        self._vm.set_tag_filter(list(self._active_tag_ids))
        self._refresh_active_tags_bar()
        self._update_delegate_tags()
        if self._active_tag_ids:
            for _t_ in self._playlist_panel.trees:
                _t_.clearSelection()

    def _show_popular_tag_context_menu(self, pos, btn, tag_id: UUID, tag_name: str) -> None:
        from application.library.favorites import is_favorite  # noqa: PLC0415
        tag_id_str = str(tag_id)
        menu = QMenu(self)
        fav_label = "★ 즐겨찾기 제거" if is_favorite(tag_id_str, "tag") else "☆ 즐겨찾기 추가"
        fav_act = QAction(fav_label, self)
        fav_act.triggered.connect(lambda: self._toggle_favorite("tag", tag_id_str, tag_name))
        menu.addAction(fav_act)
        menu.exec(btn.mapToGlobal(pos))

    def _update_delegate_tags(self) -> None:
        names = [t.name for t in self._all_tags if t.id in self._active_tag_ids]
        self._icon_delegate.active_tag_names = names
        self._list_delegate.active_tag_names = names
        self._icon_view.viewport().update()
        self._list_view.viewport().update()

    def _on_favorite_clicked(self, fav_type: str, fav_id: str) -> None:
        """즐겨찾기 바 항목 클릭 — 해당 카테고리/재생목록/태그를 활성화한다."""
        try:
            uid = UUID(fav_id)
        except (ValueError, AttributeError):
            return
        if fav_type == "category":
            self._on_cat_filter_changed(uid)
        elif fav_type == "playlist":
            self._on_playlist_selected_from_tree(uid)
        elif fav_type == "tag":
            if not self._is_restoring:
                self._push_nav_state()
            self._active_tag_ids = {uid}
            self._vm.set_tag_filter([uid])
            self._refresh_active_tags_bar()
            self._update_delegate_tags()

    def _toggle_favorite(self, fav_type: str, fav_id: str, name: str) -> None:
        from application.library.favorites import FavoriteItem, add_favorite, is_favorite, remove_favorite  # noqa: PLC0415
        if is_favorite(fav_id, fav_type):
            remove_favorite(fav_id, fav_type)
        else:
            add_favorite(FavoriteItem(type=fav_type, id=fav_id, name=name))
        self._favorites_bar.refresh(self._get_fav_counts())
        self._refresh_unified_tree()

    def _get_fav_counts(self) -> dict[str, int]:
        """즐겨찾기 바에 표시할 항목별 영상/아이템 수를 반환한다.

        카테고리는 직속 영상 수와 모든 하위 카테고리 영상 수를 합산한다.
        """
        counts: dict[str, int] = {}

        # 카테고리: 직속 카운트 + 하위 카테고리 재귀 합산
        cat_direct: dict[str, int] = {str(cat.id): cat.video_count for cat in self._vm.categories}
        children_map: dict[str, list[str]] = {}
        for cat in self._vm.categories:
            parent_key = str(cat.parent_id) if cat.parent_id else ""
            children_map.setdefault(parent_key, []).append(str(cat.id))

        def _subtree_count(cat_id_str: str) -> int:
            total = cat_direct.get(cat_id_str, 0)
            for child in children_map.get(cat_id_str, []):
                total += _subtree_count(child)
            return total

        for cat in self._vm.categories:
            counts[f"category:{cat.id}"] = _subtree_count(str(cat.id))

        for t in self._all_tags:
            counts[f"tag:{t.id}"] = t.count
        if self._playlist_vm is not None:
            for pl in self._playlist_vm.playlists:
                counts[f"playlist:{pl.id}"] = pl.item_count
        return counts

    def _on_fav_unfav_requested(self, fav_type: str, fav_id: str, name: str) -> None:
        """즐겨찾기 바의 카운트 배지 클릭 → 해제 확인 후 제거."""
        reply = QMessageBox.question(
            self, "즐겨찾기 해제",
            f"'{name}'을(를) 즐겨찾기에서 제거하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._toggle_favorite(fav_type, fav_id, name)

    def _on_tag_delete_requested(self, tag_id: UUID) -> None:
        tag = next((t for t in self._vm.tags if t.id == tag_id), None)
        if tag is None:
            return
        reply = QMessageBox.question(
            self, "태그 삭제",
            f"태그 '#{tag.name}'을(를) 삭제하시겠습니까?\n모든 영상에서 이 태그가 제거됩니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._vm.delete_tag(tag_id)

    # ── Table ──────────────────────────────────────────────────────

    def _cat_path(self, cat_id: UUID | None) -> str:
        if cat_id is None:
            return ""
        cats_by_id = {c.id: c for c in self._vm.categories}
        parts: list[str] = []
        current = cats_by_id.get(cat_id)
        while current:
            parts.insert(0, current.name)
            current = cats_by_id.get(current.parent_id) if current.parent_id else None
        return " > ".join(parts)

    def _refresh_table(self) -> None:
        def _fmt(s):
            if s is None:
                return "—"
            m, sec = divmod(s, 60)
            h, m = divmod(m, 60)
            return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"

        videos = self._vm.videos
        self._table_dirty = False
        # 영상/음원 배지는 한 번의 쿼리로 일괄 판정한다.
        # (행마다 get_video_detail 을 부르면 50행 × 수 쿼리 + 파일 stat 이
        #  메인 스레드에서 돌아 검색어 입력이 멈춘다.)
        dl_flags = self._vm.get_downloaded_flags([dto.url for dto in videos])
        self._table.setRowCount(len(videos))
        for row, dto in enumerate(videos):
            t = QTableWidgetItem(dto.title)
            t.setData(Qt.ItemDataRole.UserRole, dto.id)
            self._table.setItem(row, 0, t)
            self._table.setItem(row, 1, QTableWidgetItem(dto.channel_name))
            self._table.setItem(row, 2, QTableWidgetItem(_fmt(dto.duration_sec)))
            self._table.setItem(row, 3, QTableWidgetItem(self._cat_path(dto.category_id)))
            fav = QTableWidgetItem("★" if dto.favorite else "")
            fav.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 4, fav)
            wtc = QTableWidgetItem("✓" if dto.watched else "")
            wtc.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 5, wtc)
            # 등록 일시
            self._table.setItem(row, 6, QTableWidgetItem(dto.created_at or "—"))
            # 영상/음원 다운로드 여부 (일괄 조회 결과에서 조회)
            has_video, has_audio = dl_flags.get(dto.url, (False, False))
            v_item = QTableWidgetItem("✓" if has_video else "—")
            v_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 7, v_item)
            a_item = QTableWidgetItem("✓" if has_audio else "—")
            a_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 8, a_item)
        self._table.resizeColumnsToContents()

    # ── View mode ──────────────────────────────────────────────────

    def _switch_view(self, view_id: int) -> None:
        if view_id in (_VIEW_ICON, _VIEW_LIST, _VIEW_DETAIL):
            # 앨범 보기에서 빠져나올 때 되돌아갈 목록 뷰를 기억한다.
            self._last_list_view = view_id
        self._view_stack.setCurrentIndex(view_id)
        btn = self._view_group.button(view_id)
        if btn is not None and not btn.isChecked():
            btn.setChecked(True)
        # 숨어 있는 동안 목록이 바뀌었으면 이제 채운다(지연 갱신).
        if view_id == _VIEW_DETAIL and self._table_dirty:
            self._refresh_table()

    def _on_view_stack_changed(self, view_id: int) -> None:
        """카드 그리드 뷰(폴더·구독 피드·채널)에서는 추천 스트립을 감춘다.

        그 화면들은 라이브러리 목록이 아니라 추천 씨앗이 어긋나고, 이미 카드
        그리드라 아래에 또 카드 띠를 두면 화면이 산만해진다.
        """
        # 추천 목록이 아직 준비되지 않았으면 목록 뷰에서도 감춘 채로 둔다
        # (준비되면 _reveal_recommend_strip이 올려준다).
        show = view_id not in (_VIEW_FOLDER, _VIEW_FEED, _VIEW_CHANNELS) and self._recommend_ready
        # isVisible()이 아니라 isHidden()으로 비교한다 — isVisible()은 조상이 아직
        # 표시되지 않았을 때도 False라, 첫 전환에서 setVisible(False)가 건너뛰어진다.
        if show == (not self._recommend_strip.isHidden()):
            return
        if not show:
            self._stop_recommend_anim()
        self._recommend_strip.setVisible(show)
        if show:
            self._sync_recommend_sizes(self._recommend_strip.is_expanded, save=False)

    # ── Category / tag selection ───────────────────────────────────

    def current_category_id(self) -> UUID | None:
        return self._current_cat_id

    def _build_category_path(self, cat_id) -> str:
        """카테고리 ID로부터 전체 경로 문자열을 생성한다. 예: '로컬 > Game > Hardware > PS5'"""
        cats_by_id = {c.id: c for c in self._vm.categories}
        parts: list[str] = []
        current = cat_id
        while current:
            c = cats_by_id.get(current)
            if c is None:
                break
            parts.append(c.name)
            current = c.parent_id
        parts.reverse()
        return "로컬 > " + " > ".join(parts) if parts else "라이브러리"

    def _build_breadcrumb_segments(self, cat_id) -> list:
        """(이름, click_val) 리스트 반환. 루트 '로컬'은 항상 포함.
        cat_id가 있을 때 '로컬' click_val="root" → 클릭 시 카테고리 root(전체) 이동.
        이미 root에 있으면(cat_id=None) 마지막 세그먼트라 비클릭."""
        if cat_id is None:
            # 이미 루트 → "로컬"은 마지막이므로 click_val=None (비클릭)
            return [("로컬", None)]
        segments: list = [("로컬", "root")]
        cats_by_id = {c.id: c for c in self._vm.categories}
        parts: list = []
        current = cat_id
        while current:
            c = cats_by_id.get(current)
            if c is None:
                break
            parts.append((c.name, c.id))
            current = c.parent_id
        parts.reverse()
        return segments + parts

    def _build_playlist_breadcrumb_segments(self, playlist_id) -> list:
        """재생목록 ID로부터 클릭 가능한 경로 세그먼트 리스트를 생성한다.
        click_val: "root" → 전체, ("folder", uuid) → 폴더 뷰, None → 비클릭(마지막)"""
        if not self._playlist_vm:
            return []
        pl = next((p for p in self._playlist_vm.playlists if p.id == playlist_id), None)
        if not pl:
            return []
        if pl.source == "youtube":
            prefix, root_val = "YouTube", "section:youtube"
        else:
            prefix, root_val = "로컬", "root"
        segs = [(prefix, root_val)]
        if pl.folder_id:
            folder = next((f for f in self._playlist_vm.folders if f.id == pl.folder_id), None)
            if folder:
                segs.append((folder.name, ("folder", folder.id)))
        segs.append((pl.title, None))
        return segs

    def _build_folder_breadcrumb_segments(self, folder_id) -> list:
        """폴더 ID로부터 클릭 가능한 경로 세그먼트 리스트를 생성한다."""
        if not self._playlist_vm:
            return []
        folder = next((f for f in self._playlist_vm.folders if f.id == folder_id), None)
        if not folder:
            return []
        if folder.source == "youtube":
            prefix, root_val = "YouTube", "section:youtube"
        else:
            prefix, root_val = "로컬", "root"
        return [(prefix, root_val), (folder.name, None)]

    def _channel_name_for_url(self, url: str) -> str:
        """구독 URL로 채널 표시명을 조회한다(브레드크럼용)."""
        if not url or self._monitoring_vm is None:
            return ""
        for s in self._monitoring_vm.subscriptions:
            if s.channel_url == url:
                return s.channel_name
        return ""

    def _refresh_breadcrumb(self) -> None:
        # 구독 채널/피드 뷰는 _current_playlist_id/_current_folder_id가 None이라
        # 카테고리 분기로 빠지므로(stale 경로), 뷰 기반으로 먼저 처리한다.
        view = self._view_stack.currentIndex()
        if view == _VIEW_CHANNELS:
            self._breadcrumb_bar.update_path(
                [("YouTube", "section:youtube"), ("구독 채널", None)], [])
            return
        if view == _VIEW_FEED:
            if self._feed_show_channel:
                segments = [("YouTube", "section:youtube"), ("전체 구독 피드", None)]
            else:
                name = self._channel_name_for_url(self._current_channel_url) or "채널"
                segments = [("YouTube", "section:youtube"),
                            ("구독 채널", "channels_root"), (name, None)]
            self._breadcrumb_bar.update_path(segments, [])
            return
        if self._current_playlist_id is not None:
            segments = self._build_playlist_breadcrumb_segments(self._current_playlist_id)
            self._breadcrumb_bar.update_path(segments, [])
        elif self._current_folder_id is not None:
            segments = self._build_folder_breadcrumb_segments(self._current_folder_id)
            self._breadcrumb_bar.update_path(segments, [])
        else:
            segments = self._build_breadcrumb_segments(self._current_cat_id)
            tag_pairs = [(t.id, t.name) for t in self._all_tags if t.id in self._active_tag_ids]
            self._breadcrumb_bar.update_path(segments, tag_pairs)

    def _on_breadcrumb_nav(self, val) -> None:
        """브레드크럼 세그먼트 클릭 → 카테고리·폴더·섹션루트 분기 처리."""
        if isinstance(val, tuple) and len(val) == 2 and val[0] == "folder":
            self._on_folder_selected(val[1])
        elif isinstance(val, UUID):
            self._on_cat_filter_changed(val)
        elif val == "channels_root":
            self._on_channels_root_selected()
        elif isinstance(val, str) and val.startswith("section:"):
            # "section:youtube" 또는 "section:local" → 섹션 루트 뷰 (폴더+미분류 카드)
            self._on_section_root_selected(val.split(":", 1)[1])
        else:
            # "root" → 로컬 카테고리 전체 영상 (카테고리 필터 해제)
            self._on_cat_filter_changed(None)

    def navigate_to_category(self, cat_id) -> None:
        """외부(MainWindow 등)에서 특정 카테고리로 이동 요청 시 호출."""
        self._on_cat_filter_changed(cat_id)

    def _on_cat_filter_changed(self, cat_id) -> None:
        self._push_nav_state()          # 전환 직전 화면 보존
        self._leave_detail_if_open()    # 상세 화면이면 목록으로 복귀
        self._current_cat_id = cat_id
        self._current_playlist_id = None
        self._current_folder_id = None
        # 폴더 카드 뷰/피드 뷰/채널 뷰에서 카테고리를 고르면 영상 리스트 뷰로 복귀
        if self._view_stack.currentIndex() in (_VIEW_FOLDER, _VIEW_FEED, _VIEW_CHANNELS):
            self._switch_view(_VIEW_ALBUMS if self._album_mode else self._last_list_view)
        self._active_tag_ids.clear()
        self._tag_list.blockSignals(True)
        self._tag_list.clearSelection()
        self._tag_list.blockSignals(False)
        self._refresh_active_tags_bar()
        self._update_delegate_tags()
        node_key = f"cat:{cat_id}" if cat_id is not None else "local_root"
        self._vm.set_category_filter(cat_id, node_key=node_key)  # also clears tag filter internally
        # 카테고리 스코프 인기 태그 갱신 + 패널 표시
        self._set_popular_tags_visible(True)
        self._vm.refresh_scoped_tags()
        # Update delegates so they know which category is selected (for subcategory label)
        self._icon_delegate.filter_cat_id = cat_id
        self._list_delegate.filter_cat_id = cat_id
        # 순서 편집 버튼 — 카테고리 선택 시에만 표시
        if cat_id is not None:
            self._btn_reorder.show()
            self.path_changed.emit(self._build_category_path(cat_id))
        else:
            self._btn_reorder.setChecked(False)
            self._btn_reorder.hide()
            self._model.set_reorder_mode(False)
            self.path_changed.emit("라이브러리")
        self._refresh_breadcrumb()
        # 음악 카테고리에서만 보기 유형에 '앨범'을 노출한다(카테고리마다 달라진다).
        self._update_view_options()
        if self._album_mode:
            self._load_albums()

    # ── 앨범 보기 (음악 카테고리 전용) ───────────────────────────────
    # 앨범은 저장된 것이 아니라 노래 정보(가수·앨범)에서 파생되는 묶음이다. 그래서
    # '앨범'은 정렬이 아니라 **보기 유형**(⊞/☰/⊟ 옆의 💿 버튼)이며, 목록을 다시 정렬하는
    # 대신 화면 자체를 자켓 그리드로 바꾼다 — 리포지토리 정렬로는 표현할 수 없다.

    def _is_music_category(self, cat_id) -> bool:
        """이 카테고리의 최상위 조상 이름이 음악 계열인지(Music/Song/음악/노래/뮤직).

        판정 기준은 도메인 상수(MUSIC_ROOT_CATEGORY_NAMES)를 그대로 쓴다 — 가사 검색
        범위와 같은 규칙이어야 "가사는 되는데 앨범은 안 뜨는" 어긋남이 없다.
        """
        if cat_id is None:
            return False
        by_id = {c.id: c for c in self._vm.categories}
        node = by_id.get(cat_id)
        depth = 0
        while node is not None and depth < 32:   # 데이터가 순환해도 멈추도록 가드
            parent = by_id.get(node.parent_id) if node.parent_id else None
            if parent is None:
                return (node.name or "").strip().lower() in MUSIC_ROOT_CATEGORY_NAMES
            node = parent
            depth += 1
        return False

    def album_view_available(self) -> bool:
        """앨범 보기 버튼을 쓸 수 있는 화면인지(음악 계열 카테고리 + 앨범 VM 주입)."""
        return self._album_vm is not None and self._is_music_category(self._current_cat_id)

    def _on_view_button_clicked(self, view_id: int) -> None:
        """보기 유형 버튼 — 앨범만 단순 뷰 전환이 아니라 모드 진입/이탈이 필요하다."""
        if view_id == _VIEW_ALBUMS:
            if not self._album_mode:
                self._enter_album_mode()
            return
        if self._album_mode:
            self._exit_album_mode()
        self._switch_view(view_id)

    def _album_category_ids(self) -> list:
        """앨범 보기 대상 카테고리 — 현재 카테고리 + **모든 하위**.

        음악 라이브러리는 보통 'Music > 가수 > 곡' 구조라, 루트에서 앨범을 보면 하위에
        있는 곡이 전부 빠진다. 앨범은 카테고리 경계보다 '어떤 노래를 갖고 있나'가 중요해
        하위까지 포함한다(일반 목록 뷰는 기존대로 해당 카테고리만 보여 준다).
        """
        if self._current_cat_id is None:
            return []
        children: dict = {}
        for cat in self._vm.categories:
            children.setdefault(cat.parent_id, []).append(cat.id)
        out = [self._current_cat_id]
        queue = [self._current_cat_id]
        seen = {self._current_cat_id}
        while queue:
            node = queue.pop()
            for child in children.get(node, []):
                if child in seen:        # 데이터가 순환해도 멈춘다
                    continue
                seen.add(child)
                out.append(child)
                queue.append(child)
        return out

    def _update_view_options(self) -> None:
        """보기 유형 버튼 중 '앨범'을 음악 카테고리에서만 노출한다.

        앨범은 정렬이 아니라 **보기 방식**이다(같은 목록을 자켓 단위로 묶어 본다).
        음악이 아닌 카테고리로 옮기면 버튼을 감추고 앨범 모드도 함께 푼다 — 버튼이
        사라졌는데 화면만 앨범 그리드로 남으면 빠져나갈 방법이 없다.
        """
        want = self.album_view_available()
        self._btn_album.setVisible(want)
        if not want and self._album_mode:
            self._exit_album_mode()

    def _enter_album_mode(self) -> None:
        if self._album_vm is None:
            return
        self._push_nav_state()   # 앨범 그리드에서 뒤로 = 직전 목록 화면
        self._album_mode = True
        self._btn_album.setChecked(True)
        self._leave_detail_if_open()
        self._switch_view(_VIEW_ALBUMS)
        self._album_grid.set_status("앨범을 구성하는 중…")
        self._load_albums()
        # 앨범 값이 빈 노래는 외부 조회로 추정해 채운다(백그라운드, 실패는 재조회 안 함).
        self._album_vm.resolve_unknown_albums(
            category_id=self._current_cat_id, category_ids=self._album_category_ids()
        )

    def _exit_album_mode(self) -> None:
        self._album_mode = False
        self._current_album_key = None
        if self._album_vm is not None:
            self._album_vm.cancel_fill()
        if self._nav_stack.currentIndex() == _NAV_ALBUM_DETAIL:
            self._close_album_detail()
        if self._view_stack.currentIndex() == _VIEW_ALBUMS:
            # 앨범 버튼도 보기 그룹의 일원이라 checkedId()로 되돌리면 다시 앨범이다 —
            # 앨범 이전에 보던 목록 뷰로 복귀한다.
            self._switch_view(self._last_list_view)

    def _load_albums(self) -> None:
        if self._album_vm is None:
            return
        self._album_vm.load_albums(
            category_id=self._current_cat_id, category_ids=self._album_category_ids()
        )

    def _on_albums_changed(self, albums: list) -> None:
        if not self._album_mode:
            return
        self._album_grid.set_albums(albums)
        self._album_grid.set_status(
            "" if albums else "이 카테고리에는 앨범으로 묶을 노래가 없습니다."
        )

    def _on_album_clicked(self, album_key: str) -> None:
        """앨범 카드 클릭 — 상세를 연다(수록곡은 외부 조회라 백그라운드)."""
        if self._album_vm is None:
            return
        self._push_nav_state()   # 앨범 상세에서 뒤로 = 앨범 그리드
        self._current_album_key = album_key
        self._album_detail.set_detail(None, crumb="앨범 정보를 가져오는 중…")
        self._album_detail.set_busy(True)
        self._nav_stack.setCurrentIndex(_NAV_ALBUM_DETAIL)
        self._album_vm.load_detail(
            album_key, category_id=self._current_cat_id,
            category_ids=self._album_category_ids(),
        )

    def _on_album_detail_ready(self, detail) -> None:
        if not self._album_mode:
            return
        crumb = self._build_category_path(self._current_cat_id) if self._current_cat_id else ""
        self._album_detail.set_detail(detail, crumb=crumb)
        self._album_detail.set_busy(False)
        # 라이브러리에 없는 수록곡은 열자마자 백그라운드로 찾아 채운다(사용자 조작 없이).
        if detail is not None and detail.missing_count and self._album_vm is not None:
            self._album_detail.set_status(
                f"{self._album_detail.status_text()}  ·  빠진 곡 찾는 중…"
            )
            self._album_vm.fill_missing_tracks(
                detail.key, category_id=self._current_cat_id,
                category_ids=self._album_category_ids(),
            )

    def _on_album_track_filled(self, track) -> None:
        self._album_detail.apply_filled_track(track)

    def _on_album_fill_finished(self, count: int) -> None:
        if count:
            self._album_detail.set_status(
                f"{self._album_detail.status_text()}  ·  {count}곡 자동 매핑"
            )

    def _on_album_error(self, msg: str) -> None:
        logger.warning("앨범 조회 실패: %s", msg)
        self._album_grid.set_status("앨범 정보를 가져오지 못했습니다.")
        self._album_detail.set_busy(False)

    def _close_album_detail(self) -> None:
        """앨범 상세를 닫고 목록 컨테이너로 돌아온다(히스토리는 건드리지 않는다)."""
        self._nav_stack.setCurrentIndex(0)
        self._current_album_key = None
        if self._album_vm is not None:
            self._album_vm.cancel_fill()
            self._album_vm.cancel_add()

    def _on_album_add_all(self, detail) -> None:
        """수록곡 헤더의 '＋ 현재 카테고리에 등록' — 자동 매핑 곡을 지금 카테고리에 담는다."""
        if self._album_vm is None or detail is None:
            return
        self._album_detail.set_add_busy(True)
        self._album_detail.set_status("카테고리에 담는 중…")
        self._album_vm.add_tracks_to_category(detail, category_id=self._current_cat_id)

    def _on_album_add_progress(self, done: int, total: int) -> None:
        self._album_detail.set_status(f"카테고리에 담는 중… {done}/{total}곡")

    def _on_album_tracks_added(self, count: int) -> None:
        """담기 완료 — 목록과 앨범 상세를 다시 읽어 '내 등록'으로 바뀌게 한다."""
        self._album_detail.set_add_busy(False)
        if not count:
            self._album_detail.set_status("담을 곡이 없습니다.")
            return
        self._album_detail.set_status(f"{count}곡을 카테고리에 담았습니다.")
        self._vm.load()          # 라이브러리 목록·카테고리 개수 갱신
        if self._current_album_key:
            self._album_vm.load_detail(
                self._current_album_key, category_id=self._current_cat_id,
                category_ids=self._album_category_ids(),
            )

    def _on_album_back(self) -> None:
        """앨범 상세의 ‹ 버튼 — 영상 상세와 같이 화면 히스토리를 되짚는다."""
        if self._nav_history:
            self._go_back()
        else:
            self._close_album_detail()

    def _on_album_unknown_resolved(self, count: int) -> None:
        if count and self._album_mode:
            self._load_albums()   # 앨범을 찾은 곡들이 제 묶음으로 옮겨 간다

    def _on_album_refresh(self, album_key: str) -> None:
        if self._album_vm is None or not album_key:
            return
        self._album_detail.set_busy(True)
        self._album_vm.load_detail(
            album_key, category_id=self._current_cat_id,
            category_ids=self._album_category_ids(), refresh=True,
        )

    def _on_album_fill_requested(self, album_key: str) -> None:
        if self._album_vm is None or not album_key:
            return
        self._album_vm.fill_missing_tracks(
            album_key, category_id=self._current_cat_id,
            category_ids=self._album_category_ids(),
        )

    def _album_related_items(self, detail) -> list:
        """앨범 수록곡을 상세화면 재생목록(RelatedItem) 항목으로 바꾼다.

        로컬 곡은 video_id를, 자동 매핑 곡은 FeedVideoDTO를 payload로 싣는다 —
        상세화면의 기존 재생목록 경로(_open_playlist_payload)가 두 종류를 모두 다룬다.
        """
        from application.library.dtos import FeedVideoDTO  # noqa: PLC0415
        from application.song.album_dtos import (  # noqa: PLC0415
            TRACK_ORIGIN_AUTO,
            TRACK_ORIGIN_LIBRARY,
        )

        items = []
        for track in detail.tracks:
            if track.origin == TRACK_ORIGIN_LIBRARY and track.video_id is not None:
                video = next((v for v in self._vm.videos if v.id == track.video_id), None)
                if video is not None:
                    items.append(self._related_from_video(video))
                    continue
                # 현재 페이지에 없는 곡(다른 페이지·다른 정렬) — 최소 정보로 행을 만든다.
                items.append(RelatedItem(
                    key=str(track.video_id),
                    title=track.title,
                    channel=track.artist,
                    duration_sec=track.duration_sec,
                    meta_text="내 등록",
                    payload=track.video_id,
                    thumb_path=track.thumbnail_path,
                ))
            elif track.origin == TRACK_ORIGIN_AUTO and track.stream_url:
                dto = FeedVideoDTO(
                    url=track.stream_url,
                    title=track.stream_title or track.title,
                    channel_name=track.stream_channel or track.artist,
                    channel_id="",
                    thumbnail_url=(
                        f"https://i.ytimg.com/vi/{track.stream_yt_id}/hqdefault.jpg"
                        if track.stream_yt_id else ""
                    ),
                    thumbnail_path="",
                    published_at="",
                    view_count=None,
                    duration_sec=track.duration_sec,
                    in_library=False,
                    yt_video_id=track.stream_yt_id,
                )
                items.append(self._related_from_feed(dto))
        return items

    def _on_play_album(self, detail) -> None:
        """앨범 재생 — 수록곡을 재생목록으로 삼아 첫 곡부터 이어 재생한다."""
        items = self._album_related_items(detail)
        if not items:
            return
        self._start_album_playlist(detail, items, items[0].payload)

    def _on_album_track_clicked(self, track) -> None:
        """수록곡 클릭 — 그 곡부터 앨범을 이어 재생한다."""
        detail = self._album_vm.detail if self._album_vm is not None else None
        if detail is None:
            return
        items = self._album_related_items(detail)
        payload = None
        for item in items:
            if track.video_id is not None and item.payload == track.video_id:
                payload = item.payload
                break
            if track.stream_url and getattr(item.payload, "url", "") == track.stream_url:
                payload = item.payload
                break
        if payload is None:
            return
        self._start_album_playlist(detail, items, payload)

    def _start_album_playlist(self, detail, items: list, payload) -> None:
        """앨범 재생목록 컨텍스트를 세우고 지정한 곡을 연다.

        기존 '가수/앨범 필터' 재생목록과 같은 구조(_playlist_ctx)를 쓰므로 자동 다음곡·
        마우스 뒤로가기 되짚기가 그대로 동작한다.
        """
        # 재생목록 진입은 `push_nav=False`로 상세를 열기 때문에, 여기서 앨범 상세 화면을
        # 직접 쌓아 둬야 재생 이력을 다 되짚은 뒤 뒤로가기가 앨범 상세로 돌아온다.
        self._push_nav_state()
        self._playlist_ctx = {
            "items": items,
            "header": f"앨범: {detail.album_title}",
            "prev_related": items,
            "history": [payload],
        }
        self._open_playlist_payload(payload, autoplay=True)

    def _on_reorder_toggled(self, checked: bool) -> None:
        self._model.set_reorder_mode(checked)
        for view in (self._icon_view, self._list_view):
            if checked:
                view.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            else:
                view.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)

    def _on_category_reordered(self, video_ids: list) -> None:
        if self._current_cat_id is not None:
            self._vm.reorder_category_videos(self._current_cat_id, video_ids)
        self._icon_view.viewport().update()
        self._list_view.viewport().update()

    def _on_tag_clicked(self, item: QListWidgetItem) -> None:
        if not self._is_restoring:
            self._push_nav_state()
        tag_id: UUID = item.data(Qt.ItemDataRole.UserRole)
        # With MultiSelection, isSelected() already reflects post-click state
        if item.isSelected():
            self._active_tag_ids.add(tag_id)
        else:
            self._active_tag_ids.discard(tag_id)
        self._vm.set_tag_filter(list(self._active_tag_ids))
        self._refresh_active_tags_bar()
        self._update_delegate_tags()
        self._refresh_breadcrumb()
        # 재생목록 컨텍스트에서는 트리 선택을 유지해 재생목록∩태그 교집합으로 필터링한다.
        # (재생목록이 아닌 뷰에서는 기존대로 트리 선택을 해제한다.)
        if self._active_tag_ids and self._current_playlist_id is None:
            for _t_ in self._playlist_panel.trees:
                _t_.clearSelection()

    def _on_active_tag_removed(self, tag_id: UUID) -> None:
        """Called when ✕ is clicked on a chip in the active tags bar."""
        if not self._is_restoring:
            self._push_nav_state()
        self._active_tag_ids.discard(tag_id)
        self._vm.set_tag_filter(list(self._active_tag_ids))
        self._tag_list.blockSignals(True)
        for i in range(self._tag_list.count()):
            item = self._tag_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == tag_id:
                item.setSelected(False)
                break
        self._tag_list.blockSignals(False)
        self._refresh_active_tags_bar()
        self._update_delegate_tags()
        self._refresh_breadcrumb()

    def _on_tag_filter_requested(self, tag_id: UUID, _tag_name: str) -> None:
        """Called when a tag chip is clicked in the preview pane or detail view."""
        if not self._is_restoring:
            self._push_nav_state()
        self._active_tag_ids = {tag_id}
        self._vm.set_tag_filter([tag_id])
        self._tag_list.blockSignals(True)
        self._tag_list.clearSelection()
        for i in range(self._tag_list.count()):
            item = self._tag_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == tag_id:
                item.setSelected(True)
                break
        self._tag_list.blockSignals(False)
        self._refresh_active_tags_bar()
        self._update_delegate_tags()
        for _t_ in self._playlist_panel.trees:
            _t_.clearSelection()
        if self._nav_stack.currentIndex() == 1:
            self._on_back_from_detail()

    # ── In-place navigation ────────────────────────────────────────

    def _open_detail(
        self, video_id: UUID, autoplay: bool = False,
        related: list | None = None, header: str | None = None, push_nav: bool = True,
        resume_ms: int = 0,
    ) -> None:
        """로컬 영상 상세화면을 연다.

        related가 None이면 일반 진입 — 현재 목록으로 연관 목록을 구성하고 재생목록 모드를
        해제한다. related가 주어지면(재생목록 내 이동) 그 목록/헤더를 유지한다.
        push_nav=False면 화면 히스토리를 남기지 않는다(재생목록 내 이동)."""
        detail = self._vm.get_video_detail(video_id)
        if detail is None:
            return
        if push_nav and not self._is_restoring:
            self._push_nav_state()
        if related is None:
            # 일반 진입 — 재생목록 컨텍스트 해제 + 현재 목록(현재 영상 포함) 구성
            self._playlist_ctx = None
            related = [self._related_from_video(v) for v in self._vm.videos][:30]
        tag_ids = {t.name: t.id for t in self._vm.tags}
        cat_path = self._vm.get_category_path_with_ids(detail.category_id) if detail.category_id else []
        # 재생 전 포스터 = 목록에서 보던 썸네일(동일 캐시)
        poster = (
            _load_thumb(detail.thumbnail_path, _TW_ICON, _TH_ICON)
            if detail.thumbnail_path else None
        )
        self._detail_widget.load(detail, tag_ids, resume_ms=resume_ms, related=related,
                                 category_path=cat_path or None, poster=poster,
                                 autoplay=autoplay, related_header=header)
        self._detail_widget.set_recommendations(self._recommend_related_items())
        self._current_detail_payload = video_id
        self._nav_stack.setCurrentIndex(1)
        self._vm.request_thumbnail_refresh(video_id, detail.url)
        if self._song_vm is not None:
            self._song_vm.load(video_id)

    def _open_stream_detail(
        self, feed_dto, autoplay: bool = False,
        related: list | None = None, header: str | None = None, push_nav: bool = True,
    ) -> None:
        """구독 피드/채널의 스트리밍 영상 상세화면을 연다.

        related가 None이면 일반 진입(같은 채널 최근 영상, 현재 영상 포함)이며 재생목록
        모드를 해제한다. related가 주어지면 그 목록/헤더를 유지(재생목록 내 이동)."""
        if self._feed_vm is None:
            return
        if push_nav and not self._is_restoring:
            self._push_nav_state()
        if related is None:
            self._playlist_ctx = None
            related = self._feed_related_items(feed_dto)
        self._detail_widget.load_stream(feed_dto, related=related, related_header=header,
                                        poster=None)
        self._detail_widget.set_recommendations(self._recommend_related_items())
        self._current_detail_payload = feed_dto
        self._nav_stack.setCurrentIndex(1)

    def _open_playlist_payload(self, payload, autoplay: bool) -> None:
        """재생목록 컨텍스트를 유지한 채 payload(로컬/스트리밍) 상세를 연다."""
        from application.library.dtos import FeedVideoDTO  # noqa: PLC0415
        ctx = self._playlist_ctx
        if ctx is None:
            return
        if isinstance(payload, UUID):
            self._open_detail(payload, autoplay=autoplay, related=ctx["items"],
                              header=ctx["header"], push_nav=False)
        elif isinstance(payload, FeedVideoDTO):
            self._open_stream_detail(payload, autoplay=autoplay, related=ctx["items"],
                                     header=ctx["header"], push_nav=False)

    def _on_related_item_selected(self, payload) -> None:
        """연관 영상/재생목록 클릭 — 재생목록 모드면 이력에 쌓고 재생, 아니면 일반 진입."""
        from application.library.dtos import FeedVideoDTO  # noqa: PLC0415
        if self._playlist_ctx is not None:
            self._playlist_ctx["history"].append(payload)
            self._open_playlist_payload(payload, autoplay=True)
            return
        if isinstance(payload, UUID):
            self._open_detail(payload)
        elif isinstance(payload, FeedVideoDTO):
            self._open_stream_detail(payload)

    def _on_play_next(self, payload) -> None:
        """재생목록 자동재생 — 다음 항목을 로드하고 바로 재생한다."""
        from application.library.dtos import FeedVideoDTO  # noqa: PLC0415
        if self._playlist_ctx is not None:
            self._playlist_ctx["history"].append(payload)
            self._open_playlist_payload(payload, autoplay=True)
            return
        if isinstance(payload, UUID):
            self._open_detail(payload, autoplay=True)
        elif isinstance(payload, FeedVideoDTO):
            self._open_stream_detail(payload, autoplay=True)

    def _playlist_back(self) -> None:
        """재생목록 모드에서 마우스 뒤로가기 — 이전에 재생한 항목으로 되짚는다.

        이력이 더 없으면 재생목록 진입 직전의 '연관 영상' 목록으로 복귀한다."""
        ctx = self._playlist_ctx
        if ctx is None:
            return
        hist = ctx["history"]
        if len(hist) > 1:
            hist.pop()
            prev = hist[-1]
            self._open_playlist_payload(prev, autoplay=self._detail_widget.is_playing())
        else:
            # 이력 소진 → 연관 영상 목록 복귀(상세는 진입 영상 그대로 유지)
            self._detail_widget.set_related(ctx["prev_related"], header="연관 영상")
            self._playlist_ctx = None

    def _on_song_filter_requested(self, field: str, value: str) -> None:
        """노래 탭의 가수/앨범 » 클릭 — 같은 가수/앨범 영상을 재생목록으로 나열한다."""
        if not value:
            return
        videos = self._vm.get_videos_by_song(field, value)
        items = [self._related_from_video(v) for v in videos][:100]
        if not items:
            return
        header = (f"가수: {value}" if field == "artist" else f"앨범: {value}")
        if self._playlist_ctx is None:
            # 진입 — 현재 '연관 영상' 목록과 진입 영상을 보존
            prev_related = [self._related_from_video(v) for v in self._vm.videos][:30]
            self._playlist_ctx = {
                "items": items,
                "header": header,
                "prev_related": prev_related,
                "history": [self._current_detail_payload],
            }
        else:
            # 이미 재생목록 모드 — 새 필터로 교체(prev_related 보존)
            self._playlist_ctx["items"] = items
            self._playlist_ctx["header"] = header
            self._playlist_ctx["history"] = [self._current_detail_payload]
        self._detail_widget.set_related(items, header=header)

    def _related_from_video(self, v: VideoDTO) -> RelatedItem:
        meta = []
        if v.view_count:
            meta.append(f"조회수 {v.view_count:,}회")
        rel = _relative_time(v.published_at)
        if rel:
            meta.append(rel)
        # YouTube URL에서 영상 ID 추출 — 썸네일 파일이 없을 때 CDN 폴백용
        yt_vid_id = ""
        thumb_url = ""
        if v.url:
            m = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", v.url)
            if not m:
                m = re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", v.url)
            if m:
                yt_vid_id = m.group(1)
                thumb_url = f"https://i.ytimg.com/vi/{yt_vid_id}/hqdefault.jpg"
        return RelatedItem(
            key=str(v.id),
            title=v.title,
            channel=v.channel_name,
            duration_sec=v.duration_sec,
            meta_text="  ·  ".join(meta),
            payload=v.id,
            thumb_path=v.thumbnail_path or "",
            thumb_url=thumb_url,
            yt_video_id=yt_vid_id,
        )

    def _feed_related_items(self, clicked) -> list[RelatedItem]:
        feed = self._feed_vm.feed if self._feed_vm else []
        # 현재 영상도 포함(재생목록처럼) — 같은 채널 우선, 없으면 전체 피드
        same = [f for f in feed if f.channel_id and f.channel_id == clicked.channel_id]
        pool = same if same else list(feed)
        # 게시일 내림차순(최신 먼저)으로 정렬 — 피드 원본 순서가 채널별로 뭉쳐
        # 있어 무작위로 보이던 문제 교정. 게시일 없는 항목은 안정 정렬로 뒤에 둔다.
        pool = sorted(pool, key=lambda f: _pub_sort_key(f.published_at), reverse=True)
        return [self._related_from_feed(f) for f in pool[:30]]

    def _related_from_feed(self, f) -> RelatedItem:
        """FeedVideoDTO(구독 피드·추천) → 우측 목록 1행."""
        meta = []
        if f.view_count:
            meta.append(f"조회수 {f.view_count:,}회")
        rel = _relative_time(f.published_at)
        if rel:
            meta.append(rel)
        return RelatedItem(
            key=f.yt_video_id or f.url,
            title=f.title,
            channel=f.channel_name,
            duration_sec=f.duration_sec,
            meta_text="  ·  ".join(meta),
            payload=f,
            thumb_path=f.thumbnail_path or "",
            thumb_url=f.thumbnail_url or "",
            yt_video_id=f.yt_video_id or "",
        )

    def _on_detail_back_requested(self) -> None:
        """상세 화면 뒤로가기(마우스 뒤로가기·‹ 버튼) — 재생목록 모드면 재생 이력을
        되짚고, 아니면 화면 히스토리 기반으로 직전 화면을 복원한다."""
        if self._playlist_ctx is not None:
            self._playlist_back()
            return
        if self._nav_history:
            self._go_back()
        else:
            self._on_back_from_detail()

    def _on_back_from_detail(self) -> None:
        self._playlist_ctx = None   # 상세를 완전히 벗어남 — 재생목록 모드 해제
        self._detail_widget.stop_player()
        self._nav_stack.setCurrentIndex(0)

    def _on_detail_tags_updated(self, video_id: UUID, tags: list) -> None:
        """Called when user manually adds a tag in the detail view."""
        self._vm.update_video_tags(video_id, tags)

    def _on_detail_downloads_refresh(self, video_id: object) -> None:
        """다운로드 완료 후 상세화면의 다운로드 파일 탭을 갱신한다."""
        from uuid import UUID as _UUID  # noqa: PLC0415
        if not isinstance(video_id, _UUID):
            return
        try:
            detail = self._vm.get_video_detail(video_id)
            if detail is not None:
                self._detail_widget.refresh_downloads(detail.downloads, detail.failed_downloads)
        except Exception:
            logger.exception("다운로드 탭 갱신 실패: %s", video_id)
        if self._nav_stack.currentIndex() == 1:
            detail = self._vm.get_video_detail(video_id)
            if detail:
                tag_ids = {t.name: t.id for t in self._vm.tags}
                related = [self._related_from_video(v) for v in self._vm.videos][:30]
                poster = (
                    _load_thumb(detail.thumbnail_path, _TW_ICON, _TH_ICON)
                    if detail.thumbnail_path else None
                )
                self._detail_widget.load(detail, tag_ids, related=related, poster=poster)
                if self._song_vm is not None:
                    self._song_vm.load(video_id)

    def _on_detail_refresh_requested(self, video_id: object) -> None:
        """제목행 ⟳ — YouTube(yt-dlp)에서 메타데이터를 재수집(백그라운드)한다.

        기존에는 DB만 재조회해 저장된 오래된/부실한 정보가 그대로여서 유튜브 웹과
        달랐다. 이제 실제로 재수집해 DB를 갱신하고, 완료 시
        `video_metadata_refreshed` 신호로 상세를 제자리 재로드한다.
        """
        if not isinstance(video_id, UUID):
            return
        self._detail_widget.set_refresh_busy(True)
        self._vm.refresh_video_metadata(video_id)

    def _on_video_metadata_refreshed(self, video_id: object, ok: bool) -> None:
        """메타데이터 재수집 완료 — 현재 그 영상 상세가 열려 있으면 제자리 재로드."""
        self._detail_widget.set_refresh_busy(False)
        if not isinstance(video_id, UUID):
            return
        # 갱신 도중 다른 화면/영상으로 이동했으면 재로드하지 않는다.
        if self._detail_widget.current_detail_id() != video_id:
            return
        self._reload_detail_in_place(video_id)

    def _on_enrich_finished(self, url: str, kind: str, ok: bool, detail: str) -> None:
        """등록 후 자동 보강 완료 — 그 영상 상세가 열려 있으면 제자리 재로드.

        요약 추출은 수십 초가 걸려 그 사이 사용자가 영상을 열어 볼 수 있다.
        _reload_detail_in_place가 상세 DTO와 노래 정보를 함께 다시 읽으므로
        요약 탭·노래 탭 어느 쪽이 채워졌든 반영된다.
        """
        if not ok:
            return
        video_id = self._detail_widget.current_detail_id()
        if video_id is None:
            return
        enriched_id = self._vm.get_video_id_by_url(url)
        if enriched_id != video_id:
            return
        self._reload_detail_in_place(video_id)

    def _reload_detail_in_place(self, video_id: UUID) -> None:
        """DB의 최신 상세를 다시 읽어 상세 위젯에 재로드한다(nav 히스토리 미변경)."""
        try:
            detail = self._vm.get_video_detail(video_id)
            if detail is None:
                return
            tag_ids = {t.name: t.id for t in self._vm.tags}
            related = [self._related_from_video(v) for v in self._vm.videos][:30]
            cat_path = (
                self._vm.get_category_path_with_ids(detail.category_id)
                if detail.category_id else []
            )
            poster = (
                _load_thumb(detail.thumbnail_path, _TW_ICON, _TH_ICON)
                if detail.thumbnail_path else None
            )
            self._detail_widget.load(
                detail, tag_ids, related=related, category_path=cat_path or None,
                poster=poster,
            )
            if self._song_vm is not None:
                self._song_vm.load(video_id)
        except Exception:
            logger.exception("상세 정보 재로드 실패: %s", video_id)

    def _on_sort_changed(self, index: int) -> None:
        data = self._sort_combo.itemData(index)
        if not isinstance(data, tuple) or len(data) != 2:
            # 항목 제거 등으로 인덱스가 -1이 되면 데이터가 없다 — 아무것도 하지 않는다.
            return
        sort_by, sort_asc = data
        self._vm.set_sort(sort_by, sort_asc)

    # ── Smart Folders ──────────────────────────────────────────────

    def _load_smart_folders_ui(self) -> None:
        from application.library.smart_folders import load_smart_folders  # noqa: PLC0415
        self._smart_folders = load_smart_folders()
        self._sf_list.clear()
        for sf in self._smart_folders:
            item = QListWidgetItem(sf.name)
            item.setData(Qt.ItemDataRole.UserRole, sf.id)
            self._sf_list.addItem(item)

    def _on_save_smart_folder(self) -> None:
        from application.library.smart_folders import SmartFolder, load_smart_folders, save_smart_folders  # noqa: PLC0415
        name, ok = QInputDialog.getText(self, "스마트 폴더 저장", "폴더 이름:")
        if not ok or not name.strip():
            return
        sf = SmartFolder(
            name=name.strip(),
            tag_ids=[str(tid) for tid in self._active_tag_ids],
            min_duration_sec=getattr(self._vm, "_min_duration_sec", None),
            max_duration_sec=getattr(self._vm, "_max_duration_sec", None),
        )
        folders = load_smart_folders()
        folders.append(sf)
        save_smart_folders(folders)
        self._load_smart_folders_ui()

    def _on_smart_folder_clicked(self, item: QListWidgetItem) -> None:
        sf_id = item.data(Qt.ItemDataRole.UserRole)
        sf = next((f for f in self._smart_folders if f.id == sf_id), None)
        if sf is None:
            return
        if not self._is_restoring:
            self._push_nav_state()
        self._active_tag_ids.clear()
        self._tag_list.clearSelection()
        if sf.tag_ids:
            for tid_str in sf.tag_ids:
                try:
                    from uuid import UUID  # noqa: PLC0415
                    tid = UUID(tid_str)
                    self._active_tag_ids.add(tid)
                    for i in range(self._tag_list.count()):
                        tw_item = self._tag_list.item(i)
                        if tw_item.data(Qt.ItemDataRole.UserRole) == tid:
                            tw_item.setSelected(True)
                            break
                except Exception:
                    logger.exception("스마트폴더 태그 선택 복원 실패")
        self._vm.set_tag_filter(list(self._active_tag_ids))
        self._vm.set_duration_filter(sf.min_duration_sec, sf.max_duration_sec)
        self._vm.set_favorite_filter(sf.favorite_only)
        self._refresh_active_tags_bar()

    def _on_sf_context_menu(self, pos) -> None:
        item = self._sf_list.itemAt(pos)
        if item is None:
            return
        sf_id = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        rename_act = QAction("이름 변경", self)
        rename_act.triggered.connect(lambda: self._rename_smart_folder(sf_id))
        delete_act = QAction("삭제", self)
        delete_act.triggered.connect(lambda: self._delete_smart_folder(sf_id))
        menu.addAction(rename_act)
        menu.addAction(delete_act)
        menu.exec(self._sf_list.viewport().mapToGlobal(pos))

    def _rename_smart_folder(self, sf_id: str) -> None:
        from application.library.smart_folders import load_smart_folders, save_smart_folders  # noqa: PLC0415
        sf = next((f for f in self._smart_folders if f.id == sf_id), None)
        if sf is None:
            return
        name, ok = QInputDialog.getText(self, "이름 변경", "새 폴더 이름:", text=sf.name)
        if not ok or not name.strip():
            return
        sf.name = name.strip()
        folders = load_smart_folders()
        for i, f in enumerate(folders):
            if f.id == sf_id:
                folders[i] = sf
                break
        save_smart_folders(folders)
        self._load_smart_folders_ui()

    def _delete_smart_folder(self, sf_id: str) -> None:
        from application.library.smart_folders import load_smart_folders, save_smart_folders  # noqa: PLC0415
        folders = [f for f in load_smart_folders() if f.id != sf_id]
        save_smart_folders(folders)
        self._load_smart_folders_ui()

    # ── Empty space click ────────────────────────────────────────────

    def _on_empty_clicked(self) -> None:
        pass  # 빈 공간 클릭 시 미리보기 패널 상태 유지

    # ── 이벤트 필터: Ctrl+휠 뷰 전환 & 마우스 BackButton 히스토리 ────────

    def eventFilter(self, obj, event) -> bool:
        etype = event.type()
        if etype == QEvent.Type.Wheel:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                delta = event.angleDelta().y()
                self._cycle_view(1 if delta > 0 else -1)
                return True
        elif etype == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.BackButton:
                self._go_back()
                return True
            if event.button() == Qt.MouseButton.ForwardButton:
                self._go_forward()
                return True
        return super().eventFilter(obj, event)

    def _cycle_view(self, direction: int) -> None:
        """Ctrl+휠로 뷰 타입을 순환 전환한다. direction=1: 이전, -1: 다음."""
        views = [_VIEW_ICON, _VIEW_LIST, _VIEW_DETAIL]
        current = self._view_stack.currentIndex()
        # 폴더 뷰(_VIEW_FOLDER)는 순환에서 제외
        idx = views.index(current) if current in views else 0
        new_id = views[(idx - direction) % len(views)]
        self._switch_view(new_id)

    # ── 내비게이션 히스토리 ────────────────────────────────────────────

    def _leave_detail_if_open(self) -> None:
        """상세 화면이 열려 있으면 목록 컨테이너로 복귀한다.

        영상 상세(인덱스 1)뿐 아니라 **앨범 상세(인덱스 2)**도 함께 닫는다 — 트리에서
        다른 노드를 골랐는데 앨범 상세가 그대로 떠 있으면 목록만 바뀌고 화면은 그대로라
        먹통처럼 보인다.
        """
        idx = self._nav_stack.currentIndex()
        if idx == 1:
            self._on_back_from_detail()
        elif idx == _NAV_ALBUM_DETAIL:
            self._on_album_back()

    def _capture_screen(self) -> dict:
        """현재 화면을 완전 스냅샷으로 캡처한다(트리 노드 종류 + 뷰 + 태그)."""
        view_idx = self._view_stack.currentIndex()
        if view_idx == _VIEW_CHANNELS:
            kind = "channels_root"
        elif view_idx == _VIEW_FEED:
            kind = "feed_all" if self._feed_show_channel else "channel"
        elif view_idx == _VIEW_FOLDER:
            kind = "folder"
        elif self._current_playlist_id is not None:
            kind = "playlist"
        else:
            kind = "category"
        return {
            "kind": kind,
            "cat_id": self._current_cat_id,
            "playlist_id": self._current_playlist_id,
            "folder_id": self._current_folder_id,
            "channel_url": self._current_channel_url,
            "nav_idx": self._nav_stack.currentIndex(),
            "detail_payload": self._current_detail_payload,
            # 앨범 보기는 같은 카테고리 위의 '다른 화면'이라 kind로는 구분되지 않는다 —
            # 모드와 열려 있던 앨범 키를 따로 싣는다(nav_idx가 앨범 상세를 가리킨다).
            "album_mode": self._album_mode,
            "album_key": self._current_album_key,
            "tag_ids": frozenset(self._active_tag_ids),
        }

    def _push_nav_state(self) -> None:
        """전환 직전 화면을 히스토리 스택에 저장한다(복원 중에는 무시).

        사용자가 새 분기로 이동하는 것이므로 앞으로가기 스택은 무효화한다
        (브라우저 표준 동작)."""
        if self._is_restoring:
            return
        self._nav_history.append(self._capture_screen())
        if len(self._nav_history) > 50:
            self._nav_history.pop(0)
        self._nav_future.clear()

    def _reopen_detail(self, payload) -> None:
        """히스토리 복원 시 직전 상세 화면을 다시 연다."""
        from application.library.dtos import FeedVideoDTO  # noqa: PLC0415
        if isinstance(payload, UUID):
            self._open_detail(payload)
        elif isinstance(payload, FeedVideoDTO):
            self._open_stream_detail(payload)

    def _restore_list_screen(self, snap: dict) -> None:
        """스냅샷의 트리 노드(kind)로 실제 이동한다."""
        kind = snap.get("kind", "category")
        if kind == "playlist":
            self._on_playlist_selected_from_tree(snap.get("playlist_id"))
        elif kind == "folder":
            self._on_folder_selected(snap.get("folder_id"))
        elif kind == "feed_all":
            self._on_feed_all_selected()
        elif kind == "channel":
            self._on_channel_selected(snap.get("channel_url") or "")
        elif kind == "channels_root":
            self._on_channels_root_selected()
        else:  # category
            self._on_cat_filter_changed(snap.get("cat_id"))

    def _screen_matches(self, snap: dict) -> bool:
        """상세 화면 아래에 깔린 현재 목록이 스냅샷과 동일한 노드인지(재로딩 회피용)."""
        view_idx = self._view_stack.currentIndex()
        kind = snap.get("kind")
        list_views = (_VIEW_ICON, _VIEW_LIST, _VIEW_DETAIL)
        if kind == "feed_all":
            return view_idx == _VIEW_FEED and self._feed_show_channel
        if kind == "channel":
            return (view_idx == _VIEW_FEED and not self._feed_show_channel
                    and self._current_channel_url == (snap.get("channel_url") or ""))
        if kind == "channels_root":
            return view_idx == _VIEW_CHANNELS
        if kind == "folder":
            return view_idx == _VIEW_FOLDER and self._current_folder_id == snap.get("folder_id")
        if kind == "playlist":
            return view_idx in list_views and self._current_playlist_id == snap.get("playlist_id")
        if snap.get("album_mode"):
            # 앨범 상세 아래에는 앨범 그리드가 깔려 있다(일반 목록 뷰가 아니다).
            list_views = (*list_views, _VIEW_ALBUMS)
        return (view_idx in list_views and self._current_playlist_id is None
                and self._current_cat_id == snap.get("cat_id"))

    def _close_overlay_screens(self) -> None:
        """목록 위에 덮여 있는 화면(영상 상세·앨범 상세)을 닫고 목록 컨테이너로 돌아온다."""
        idx = self._nav_stack.currentIndex()
        if idx == 1:
            self._on_back_from_detail()
        elif idx == _NAV_ALBUM_DETAIL:
            self._close_album_detail()

    def _restore_album_mode(self, snap: dict) -> None:
        """스냅샷의 앨범 보기 모드를 복원한다(정렬 콤보를 통해 기존 경로를 그대로 탄다).

        모드 전환을 직접 수행하지 않고 콤보 선택을 바꾸는 이유는, 진입/이탈에 따라오는
        일들(뷰 전환·목록 조회·앨범 추정)이 모두 그 경로에 걸려 있기 때문이다.
        """
        want = bool(snap.get("album_mode"))
        if want == self._album_mode:
            if want and self._view_stack.currentIndex() != _VIEW_ALBUMS:
                # 목록 복원이 일반 뷰로 되돌렸을 수 있다 — 앨범 그리드를 다시 띄운다.
                self._switch_view(_VIEW_ALBUMS)
            return
        self._update_view_options()
        if want:
            if not self.album_view_available():
                return   # 앨범을 열 수 없는 카테고리 — 일반 목록으로 둔다
            self._enter_album_mode()
        else:
            self._exit_album_mode()

    def _restore_screen(self, snap: dict) -> None:
        """스냅샷에 따라 직전 화면을 정확히 복원한다."""
        self._is_restoring = True
        try:
            target_detail = (snap.get("nav_idx") == 1
                             and snap.get("detail_payload") is not None)
            target_album = (snap.get("nav_idx") == _NAV_ALBUM_DETAIL
                            and bool(snap.get("album_key")))
            overlay_open = self._nav_stack.currentIndex() in (1, _NAV_ALBUM_DETAIL)

            # 상세(영상·앨범) 아래에 그대로 깔려 있던 직전 목록으로 복귀 —
            # 재로딩 없이 덮개만 걷는다.
            if (not target_detail and not target_album and overlay_open
                    and bool(snap.get("album_mode")) == self._album_mode
                    and self._screen_matches(snap)):
                self._close_overlay_screens()
                self._restore_tags(snap)
                self._playlist_panel.select_snapshot(snap)
                return

            # 그 외엔 목록 화면을 실제로 재구성한다
            self._close_overlay_screens()
            self._restore_list_screen(snap)
            self._restore_tags(snap)
            # 좌측 트리 강조를 복원된 노드에 맞춰 동기화(경로 표현 자연스럽게)
            self._playlist_panel.select_snapshot(snap)
            # 앨범 그리드/일반 목록 중 어느 화면이었는지 되살린다(상세보다 먼저 — 앨범
            # 상세는 그 그리드 위에 열린다)
            self._restore_album_mode(snap)

            # 직전이 상세였다면(연관영상 체인) 올바른 목록 위에 상세를 다시 연다
            if target_detail:
                self._reopen_detail(snap["detail_payload"])
            elif target_album and self._album_mode:
                self._on_album_clicked(snap["album_key"])
        finally:
            self._is_restoring = False

    def _restore_tags(self, snap: dict) -> None:
        """화면 복원 뒤 태그 필터를 덮어쓴다(핸들러가 태그를 비울 수 있으므로)."""
        saved_tags: frozenset = snap.get("tag_ids", frozenset())
        if not saved_tags:
            return
        self._active_tag_ids = set(saved_tags)
        self._vm.set_tag_filter(list(self._active_tag_ids))
        self._tag_list.blockSignals(True)
        self._tag_list.clearSelection()
        for i in range(self._tag_list.count()):
            item = self._tag_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) in self._active_tag_ids:
                item.setSelected(True)
        self._tag_list.blockSignals(False)
        self._refresh_active_tags_bar()
        self._update_delegate_tags()
        self._icon_view.viewport().update()
        self._list_view.viewport().update()

    def _go_back(self) -> None:
        """히스토리에서 직전 화면을 꺼내 복원한다. 현재 화면은 앞으로가기 스택에 보존."""
        if not self._nav_history:
            # 라이브러리 내부 기록이 비었으면 외부(예: 통계에서 진입) 복귀를 위임한다.
            self.back_exhausted.emit()
            return
        self._nav_future.append(self._capture_screen())
        snap = self._nav_history.pop()
        self._restore_screen(snap)

    def _go_forward(self) -> None:
        """앞으로가기 스택에서 다음 화면을 꺼내 복원한다. 현재 화면은 뒤로가기 스택에 보존."""
        if not self._nav_future:
            return
        self._nav_history.append(self._capture_screen())
        snap = self._nav_future.pop()
        self._restore_screen(snap)

    def _on_hidden_tags_changed(self) -> None:
        """설정에서 숨김 태그가 변경되면 태그 표시 목록을 즉시 갱신한다."""
        self._refresh_tag_display()
        self._refresh_popular_tags()

    # ── URL dropped onto video list ────────────────────────────────

    def _on_list_url_dropped(self, url: str) -> None:
        self._vm.add_video(url, self._current_cat_id)

    # ── Category management ────────────────────────────────────────

    def _on_refresh_metadata(self, category_id) -> None:
        if self._refresh_dlg is not None:
            return  # already running
        self._refresh_dlg = QProgressDialog(
            "메타데이터 갱신 중...", None, 0, 100, self
        )
        self._refresh_dlg.setWindowTitle("메타데이터 일괄 갱신")
        self._refresh_dlg.setWindowModality(Qt.WindowModality.WindowModal)
        self._refresh_dlg.setMinimumDuration(0)
        self._refresh_dlg.setValue(0)
        self._refresh_dlg.show()
        self._vm.refresh_category_metadata(category_id)

    def _on_refresh_progress(self, current: int, total: int) -> None:
        if self._refresh_dlg is not None and total > 0:
            self._refresh_dlg.setValue(int(current / total * 100))

    def _on_refresh_finished(self, count: int) -> None:
        if self._refresh_dlg is not None:
            self._refresh_dlg.close()
            self._refresh_dlg = None

    def _on_add_category(self, parent_id) -> None:
        name, ok = QInputDialog.getText(self, "카테고리 추가", "카테고리 이름:")
        if ok and name.strip():
            self._vm.create_category(name.strip(), parent_id=parent_id)

    def _on_rename_category(self, category_id) -> None:
        cats = self._vm.categories
        current_name = next((c.name for c in cats if c.id == category_id), "")
        new_name, ok = QInputDialog.getText(
            self, "카테고리 이름 변경", "새 이름:", text=current_name
        )
        if ok and new_name.strip():
            self._vm.rename_category(category_id, new_name.strip())

    def _on_category_reparented(self, cat_id: UUID, new_parent_id) -> None:
        self._vm.reparent_category(cat_id, new_parent_id)

    def _on_delete_category(self, category_id) -> None:
        cats = self._vm.categories
        name = next((c.name for c in cats if c.id == category_id), "")
        reply = QMessageBox.question(
            self, "카테고리 삭제",
            f"'{name}' 카테고리를 삭제하시겠습니까?\n영상은 '미분류'로 이동됩니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._vm.delete_category(category_id)

    # ── Item click / double-click ──────────────────────────────────

    def _on_item_clicked(self, index: QModelIndex, view: QListView) -> None:
        """단일 클릭 → 상세화면 진입.
        Shift 클릭은 다중 선택·드래그용으로 유지."""
        mods = QApplication.keyboardModifiers()
        dto: VideoDTO | None = self._model.data(index, VideoListModel.DtoRole)
        if not dto:
            return
        if mods & Qt.KeyboardModifier.ShiftModifier:
            return
        self.video_selected.emit(dto)
        self._open_detail(dto.id)

    def _on_double_click(self, index: QModelIndex) -> None:
        dto: VideoDTO | None = self._model.data(index, VideoListModel.DtoRole)
        if dto:
            self._open_detail(dto.id)

    def _on_table_clicked(self, index: QModelIndex) -> None:
        mods = QApplication.keyboardModifiers()
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            return
        item = self._table.item(index.row(), 0)
        if item:
            vid_id = item.data(Qt.ItemDataRole.UserRole)
            if vid_id:
                self._open_detail(vid_id)

    def _on_table_double_click(self, index: QModelIndex) -> None:
        item = self._table.item(index.row(), 0)
        if item:
            vid_id = item.data(Qt.ItemDataRole.UserRole)
            if vid_id:
                self._open_detail(vid_id)

    # ── URL/video drop ─────────────────────────────────────────────

    def _on_url_dropped(self, url: str, category_id) -> None:
        self._vm.add_video(url, category_id)

    # ── 상세화면 카테고리 지정 ─────────────────────────────────────
    # 라이브러리 영상이든 추천/피드의 스트리밍 영상이든 같은 버튼 하나로 처리한다.
    # 스트리밍 영상은 '등록 + 카테고리 지정'이 한 번에 일어나야 요약·가사 잠금이 풀린다
    # (두 기능은 영상별로 DB에 저장돼 안정적인 로컬 video_id가 필요하다).

    def _pick_category(self) -> tuple[bool, object]:
        """카테고리 선택 다이얼로그 — (확인 여부, category_id | None)."""
        from gui.panels.feed_panel import _CategoryPickDialog  # noqa: PLC0415
        cats = self._vm.categories
        if not cats:
            # 카테고리가 하나도 없으면 미분류로 담는다(다이얼로그가 빈 채로 뜨지 않게).
            return True, None
        dlg = _CategoryPickDialog(cats, self)
        if not dlg.exec():
            return False, None
        return True, dlg.selected_id()

    def _on_detail_category_requested(self, payload) -> None:
        """상세화면 📁 버튼/잠금 안내판 — 카테고리를 골라 담는다."""
        from application.library.dtos import FeedVideoDTO  # noqa: PLC0415
        ok, cat_id = self._pick_category()
        if not ok:
            return
        if isinstance(payload, UUID):
            self._vm.assign_category(payload, cat_id)
            # 브레드크럼(카테고리 경로)을 즉시 반영한다.
            self._reload_detail_in_place(payload)
            return
        if not isinstance(payload, FeedVideoDTO):
            return
        url = getattr(payload, "url", "")
        if not url:
            return
        existing = self._vm.get_video_id_by_url(url)
        if existing is not None:
            # 이미 라이브러리에 있는 영상을 스트리밍으로 보고 있었다 — 이동만 하고 전환.
            self._vm.assign_category(existing, cat_id)
            self._switch_to_local_detail(existing)
            return
        self._pending_category_url = url
        self._vm.add_video(url, cat_id)

    def _on_video_added_for_detail(self, url: str) -> None:
        """등록 완료 — 상세에서 담기를 눌렀던 영상이면 로컬 상세로 갈아탄다."""
        if not url or url != self._pending_category_url:
            return
        self._pending_category_url = ""
        video_id = self._vm.get_video_id_by_url(url)
        if video_id is None:
            logger.warning("등록 직후 영상 id를 찾지 못했다: %s", url)
            return
        self._switch_to_local_detail(video_id)

    def _switch_to_local_detail(self, video_id: UUID) -> None:
        """스트리밍 상세 → 같은 영상의 로컬 상세로 전환(재생 위치·재생 여부 유지)."""
        if self._nav_stack.currentIndex() != 1:
            return   # 이미 상세를 떠났다 — 등록만 하고 끝
        resume = self._detail_widget.player_position_ms()
        playing = self._detail_widget.is_playing()
        self._open_detail(video_id, autoplay=playing, push_nav=False, resume_ms=resume)

    def _on_video_moved(self, video_id: UUID, category_id) -> None:
        self._vm.assign_category(video_id, category_id)

    # ── Context menus ──────────────────────────────────────────────

    def _show_video_menu(self, pos: QPoint, view: QListView) -> None:
        indexes = view.selectedIndexes()
        if not indexes:
            return
        global_pos = view.viewport().mapToGlobal(pos)
        if len(indexes) > 1:
            self._build_bulk_menu(indexes, global_pos)
        else:
            dto: VideoDTO = self._model.data(indexes[0], VideoListModel.DtoRole)
            if dto:
                self._build_video_menu(dto, global_pos)

    def _show_table_menu(self, pos: QPoint) -> None:
        row = self._table.rowAt(pos.y())
        if row < 0 or row >= len(self._vm.videos):
            return
        self._build_video_menu(self._vm.videos[row], self._table.viewport().mapToGlobal(pos))

    def _build_bulk_menu(self, indexes: list[QModelIndex], global_pos: QPoint) -> None:
        dtos = [
            self._model.data(idx, VideoListModel.DtoRole)
            for idx in indexes
            if self._model.data(idx, VideoListModel.DtoRole) is not None
        ]
        video_ids = [d.id for d in dtos]
        menu = QMenu(self)
        menu.addSection(f"{len(video_ids)}개 영상 선택됨")

        active_pl_id = self._vm.active_playlist_id
        in_playlist  = active_pl_id is not None and self._playlist_vm is not None

        dl_act = QAction("일괄 다운로드", self)
        dl_act.triggered.connect(lambda: self._on_batch_download(dtos))
        menu.addAction(dl_act)

        tag_act = QAction("태그 추가", self)
        tag_act.triggered.connect(lambda: self._on_bulk_add_tags(video_ids))
        menu.addAction(tag_act)

        menu.addSeparator()

        # 재생목록 모드: "이 재생목록에서 일괄 제거"
        if in_playlist:
            rm_pl_act = QAction(f"이 재생목록에서 제거 ({len(video_ids)}개)", self)
            rm_pl_act.triggered.connect(
                lambda: self._confirm_bulk_remove_from_playlist(video_ids, active_pl_id)
            )
            menu.addAction(rm_pl_act)
            menu.addSeparator()

        # 재생목록으로 복사 (모든 모드에서 사용 가능)
        if self._playlist_vm is not None:
            pl_copy_menu = menu.addMenu("재생목록으로 복사")
            for pl in self._playlist_vm.playlists:
                if in_playlist and pl.id == active_pl_id:
                    continue
                act = QAction(
                    f"{'[YT] ' if pl.source == 'youtube' else ''}{pl.title}  ({pl.item_count})",
                    self,
                )
                pid = pl.id
                act.triggered.connect(lambda _, p=pid: self._on_bulk_copy_to_playlist(video_ids, p))
                pl_copy_menu.addAction(act)
            if not pl_copy_menu.actions():
                pl_copy_menu.setEnabled(False)
            menu.addSeparator()

        cat_menu_label = "카테고리 일괄 복사" if in_playlist else "카테고리 일괄 변경"
        cat_menu = menu.addMenu(cat_menu_label)
        uncat_act = QAction("미분류", self)
        uncat_act.triggered.connect(lambda: self._vm.assign_category_bulk(video_ids, None))
        cat_menu.addAction(uncat_act)
        cat_menu.addSeparator()
        self._add_bulk_cat_actions(cat_menu, self._vm.categories, None, video_ids)

        menu.exec(global_pos)

    def _on_batch_download(self, dtos: list[VideoDTO]) -> None:
        dlg = BatchDownloadDialog(len(dtos), self)
        if dlg.exec() != BatchDownloadDialog.DialogCode.Accepted:
            return
        settings = dlg.build_settings()
        skip = dlg.skip_existing
        skipped_urls: set[str] = set()
        if skip:
            try:
                history = getattr(self, "_download_vm", None)
                if history is not None and hasattr(history, "load_history"):
                    skipped_urls = {j.url for j in history.load_history(200) if j.status == "COMPLETED"}
            except Exception:
                logger.exception("기존 다운로드 이력 조회 실패 (중복 건너뛰기)")
        for dto in dtos:
            if skip and dto.url in skipped_urls:
                continue
            self.download_requested.emit(dto.url, dto.title, settings)

    def _on_bulk_add_tags(self, video_ids: list[UUID]) -> None:
        tag_str, ok = QInputDialog.getText(
            self, "태그 추가",
            f"{len(video_ids)}개 영상에 추가할 태그를 입력하세요 (쉼표로 구분):",
        )
        if ok and tag_str.strip():
            tag_names = [
                t.strip().lstrip("#")
                for t in tag_str.split(",")
                if t.strip().lstrip("#")
            ]
            if tag_names:
                self._vm.add_tags_bulk(video_ids, tag_names)

    def _add_bulk_cat_actions(
        self, menu: QMenu, cats: list[CategoryDTO], parent_id, video_ids: list[UUID]
    ) -> None:
        for cat in cats:
            if cat.parent_id != parent_id:
                continue
            children = [c for c in cats if c.parent_id == cat.id]
            if children:
                sub = menu.addMenu(cat.name)
                mv = QAction(f"→ {cat.name}", self)
                cid = cat.id
                mv.triggered.connect(lambda _, c=cid: self._vm.assign_category_bulk(video_ids, c))
                sub.addAction(mv)
                sub.addSeparator()
                self._add_bulk_cat_actions(sub, cats, cat.id, video_ids)
            else:
                act = QAction(cat.name, self)
                cid = cat.id
                act.triggered.connect(lambda _, c=cid: self._vm.assign_category_bulk(video_ids, c))
                menu.addAction(act)

    def _build_video_menu(self, dto: VideoDTO, global_pos: QPoint) -> None:
        menu = QMenu(self)

        detail_act = QAction("상세 정보", self)
        detail_act.triggered.connect(lambda: self._open_detail(dto.id))
        menu.addAction(detail_act)

        menu.addSeparator()

        active_pl_id = self._vm.active_playlist_id
        cat_menu_label = "카테고리로 복사" if active_pl_id is not None else "카테고리 이동"
        cat_menu = menu.addMenu(cat_menu_label)
        uncat_act = QAction("미분류", self)
        uncat_act.triggered.connect(lambda: self._on_video_moved(dto.id, None))
        cat_menu.addAction(uncat_act)
        cat_menu.addSeparator()
        self._add_cat_actions(cat_menu, self._vm.categories, None, dto.id)

        # 재생목록이 활성화되어 있을 때만 재생목록 이전 메뉴 표시
        if active_pl_id is not None and self._playlist_vm is not None:
            menu.addSeparator()

            remove_act = QAction("이 재생목록에서 제거", self)
            remove_act.triggered.connect(
                lambda: self._on_remove_video_from_playlist(dto.id, active_pl_id)
            )
            menu.addAction(remove_act)

            pl_move_menu = menu.addMenu("다른 재생목록으로 이전…")
            for pl in self._playlist_vm.playlists:
                if pl.id == active_pl_id:
                    continue
                act = QAction(
                    f"{'[YT] ' if pl.source == 'youtube' else ''}{pl.title}  ({pl.item_count})",
                    self,
                )
                target_id = pl.id
                act.triggered.connect(
                    lambda _, tid=target_id: self._on_move_video_to_playlist(dto.id, active_pl_id, tid)
                )
                pl_move_menu.addAction(act)
            if not pl_move_menu.actions():
                pl_move_menu.setEnabled(False)

        menu.addSeparator()

        fav_act = QAction("즐겨찾기 해제" if dto.favorite else "즐겨찾기 추가", self)
        fav_act.triggered.connect(lambda: self._toggle_video_favorite(dto))
        menu.addAction(fav_act)

        watch_act = QAction("시청 완료 표시", self)
        watch_act.setEnabled(not dto.watched)
        watch_act.triggered.connect(lambda: self._vm.mark_watched(dto.id))
        menu.addAction(watch_act)

        menu.addSeparator()

        del_act = QAction("삭제", self)
        del_act.triggered.connect(lambda: self._confirm_delete(dto))
        menu.addAction(del_act)

        menu.exec(global_pos)

    def _add_cat_actions(
        self, menu: QMenu, cats: list[CategoryDTO], parent_id, video_id: UUID
    ) -> None:
        for cat in cats:
            if cat.parent_id != parent_id:
                continue
            children = [c for c in cats if c.parent_id == cat.id]
            if children:
                sub = menu.addMenu(cat.name)
                mv = QAction(f"→ {cat.name}", self)
                cid = cat.id
                mv.triggered.connect(lambda _, c=cid: self._on_video_moved(video_id, c))
                sub.addAction(mv)
                sub.addSeparator()
                self._add_cat_actions(sub, cats, cat.id, video_id)
            else:
                act = QAction(cat.name, self)
                cid = cat.id
                act.triggered.connect(lambda _, c=cid: self._on_video_moved(video_id, c))
                menu.addAction(act)

    def _toggle_video_favorite(self, dto: VideoDTO) -> None:
        from application.library.commands import UpdateVideoCommand
        try:
            self._vm._update_video.handle(
                UpdateVideoCommand(video_id=dto.id, favorite=not dto.favorite)
            )
            self._vm._refresh_videos()
        except Exception as exc:
            self._vm.error_occurred.emit(str(exc))

    def _confirm_delete(self, dto: VideoDTO) -> None:
        active_pl_id = self._vm.active_playlist_id
        in_playlist  = active_pl_id is not None and self._playlist_vm is not None

        msg = (
            f"'{dto.title}'\n이 영상을 라이브러리에서 완전히 삭제하시겠습니까?\n"
            + ("(재생목록에서도 제거되며, YouTube 재생목록에도 반영됩니다)" if in_playlist
               else "(라이브러리에서 완전히 삭제됩니다)")
        )
        reply = QMessageBox.question(
            self, "영상 삭제",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # 재생목록 뷰 상태일 때: YouTube API 포함 재생목록 제거 먼저 처리
        if in_playlist:
            self._playlist_vm.remove_video_from_playlist(active_pl_id, dto.id)

        self._vm.delete_video(dto.id)

    # ── Playlist handlers ──────────────────────────────────────────

    def _on_playlists_changed(self) -> None:
        self._refresh_unified_tree()

    def _on_delete_playlist(self, playlist_id: UUID) -> None:
        if self._playlist_vm is None:
            return
        reply = QMessageBox.question(
            self, "재생목록 삭제",
            "이 재생목록을 삭제하시겠습니까?\n(라이브러리의 영상은 유지됩니다)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._playlist_vm.delete_playlist(playlist_id)
            self._vm.set_playlist_filter(None)

    def _on_rename_playlist(self, playlist_id: UUID) -> None:
        if self._playlist_vm is None:
            return
        pls = self._playlist_vm.playlists
        current = next((p.title for p in pls if p.id == playlist_id), "")
        title, ok = QInputDialog.getText(
            self, "재생목록 이름 변경", "새 이름:", text=current
        )
        if ok and title.strip():
            self._playlist_vm.rename_playlist(playlist_id, title.strip())

    def _on_playlist_move(self, playlist_id, folder_id) -> None:
        if self._playlist_vm is None:
            return
        self._playlist_vm.move_playlist_to_folder(playlist_id, folder_id)

    def _on_folder_create(self, source: str) -> None:
        if self._playlist_vm is None:
            return
        name, ok = QInputDialog.getText(self, "새 폴더", "폴더 이름:")
        if ok and name.strip():
            self._playlist_vm.create_folder(name.strip(), source)

    def _on_folder_rename(self, folder_id, old_name: str) -> None:
        if self._playlist_vm is None:
            return
        name, ok = QInputDialog.getText(
            self, "폴더 이름 변경", "새 이름:", text=old_name
        )
        if ok and name.strip():
            self._playlist_vm.rename_folder(folder_id, name.strip())

    def _on_folder_delete(self, folder_id) -> None:
        if self._playlist_vm is None:
            return
        reply = QMessageBox.question(
            self, "폴더 삭제",
            "폴더를 삭제하시겠습니까?\n(폴더 안의 재생목록은 미분류로 이동됩니다)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._playlist_vm.delete_folder(folder_id)

    def _on_yt_playlist_to_category(self, yt_playlist_id: str, cat_id) -> None:
        """YouTube 재생목록을 드래그앤드랍으로 카테고리에 드랍 — 영상 임포트."""
        if not yt_playlist_id:
            return
        cookie_opts = self._playlist_vm.get_ytdlp_cookie_opts() if self._playlist_vm else {}
        self._vm.import_youtube_to_category(yt_playlist_id, cat_id, cookie_opts)

    def _on_local_playlist_to_category(self, playlist_id, parent_cat_id) -> None:
        """로컬 재생목록의 영상 전체를 재생목록 이름의 새 카테고리로 복사한다."""
        if self._playlist_vm is None:
            return
        try:
            playlist_id = UUID(str(playlist_id)) if not isinstance(playlist_id, UUID) else playlist_id
        except (ValueError, AttributeError):
            return

        playlist = next((pl for pl in self._playlist_vm.playlists if pl.id == playlist_id), None)
        if playlist is None:
            return

        video_ids = self._vm.get_playlist_video_ids(playlist_id)
        if not video_ids:
            QMessageBox.information(
                self, "재생목록 복사",
                f"재생목록 '{playlist.title}'에 영상이 없습니다.",
            )
            return

        self._vm.create_category(playlist.title, parent_id=parent_cat_id)

        new_cat = next(
            (c for c in self._vm.categories if c.name == playlist.title and c.parent_id == parent_cat_id),
            None,
        )
        if new_cat is None:
            return

        self._vm.assign_category_bulk(video_ids, new_cat.id)

    def _on_copy_yt_to_local(self, yt_playlist_id: str) -> None:
        """YouTube 재생목록의 영상들을 선택한 카테고리로 가져온다."""
        if not yt_playlist_id:
            return
        categories = self._vm.categories
        if not categories:
            QMessageBox.information(
                self, "카테고리 없음",
                "카테고리가 없습니다.\n카테고리 트리에서 먼저 카테고리를 만들어 주세요.",
            )
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("가져올 카테고리 선택")
        dlg.setMinimumWidth(360)
        dlg.setMinimumHeight(440)
        dlg_layout = QVBoxLayout(dlg)
        dlg_layout.setSpacing(8)

        lbl = QLabel("YouTube 재생목록 영상들을 가져올 카테고리를 선택하세요:")
        lbl.setWordWrap(True)
        dlg_layout.addWidget(lbl)

        # QTreeWidget으로 카테고리 계층 구조를 실제 트리 형태로 표시
        tw = QTreeWidget()
        tw.setHeaderHidden(True)
        tw.setIndentation(18)
        tw.setAnimated(True)
        tw.setRootIsDecorated(True)
        tw.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tok = _t()
        tw.setStyleSheet(
            f"QTreeWidget {{"
            f"  background:{tok.bg_surface};"
            f"  border:1px solid {tok.border};"
            f"  border-radius:4px;"
            f"  font-size:9pt;"
            f"}}"
            f"QTreeWidget::item {{"
            f"  padding:4px 2px;"
            f"  color:{tok.text_primary};"
            f"}}"
            f"QTreeWidget::item:selected {{"
            f"  background:{tok.accent};"
            f"  color:{tok.text_on_accent};"
            f"}}"
            f"QTreeWidget::item:hover:!selected {{"
            f"  background:{tok.bg_overlay};"
            f"}}"
        )

        # BFS로 메인 카테고리 트리와 동일한 순서로 구축
        tw_items: dict = {}

        def _child_count(cat_id) -> int:
            return sum(1 for c in categories if c.parent_id == cat_id)

        roots = [c for c in categories if c.parent_id is None]
        for c in roots:
            count = _child_count(c.id)
            label = f"🏷  {c.name}  ({count})" if count > 0 else f"🏷  {c.name}"
            ti = QTreeWidgetItem([label])
            ti.setData(0, Qt.ItemDataRole.UserRole, c.id)
            tw.addTopLevelItem(ti)
            tw_items[c.id] = ti

        queue = list(roots)
        while queue:
            parent_cat = queue.pop(0)
            parent_ti = tw_items[parent_cat.id]
            for c in categories:
                if c.parent_id == parent_cat.id:
                    count = _child_count(c.id)
                    label = f"🏷  {c.name}  ({count})" if count > 0 else f"🏷  {c.name}"
                    ti = QTreeWidgetItem([label])
                    ti.setData(0, Qt.ItemDataRole.UserRole, c.id)
                    parent_ti.addChild(ti)
                    tw_items[c.id] = ti
                    queue.append(c)

        tw.expandAll()
        if tw.topLevelItemCount() > 0:
            tw.setCurrentItem(tw.topLevelItem(0))

        dlg_layout.addWidget(tw, 1)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        dlg_layout.addWidget(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        sel = tw.currentItem()
        if sel is None:
            return
        category_id = sel.data(0, Qt.ItemDataRole.UserRole)

        # 로컬에 이미 가져온 재생목록 데이터를 사용 (YouTube 재다운로드 없음)
        if self._playlist_vm is not None:
            local_pl = next(
                (pl for pl in self._playlist_vm.playlists if pl.yt_playlist_id == yt_playlist_id),
                None,
            )
            if local_pl is not None:
                video_ids = self._vm.get_playlist_video_ids(local_pl.id)
                if video_ids:
                    self._vm.assign_category_bulk(video_ids, category_id)
                    QMessageBox.information(
                        self, "복사 완료",
                        f"영상 {len(video_ids)}개를 카테고리로 복사했습니다.",
                    )
                    return
                QMessageBox.information(
                    self, "알림",
                    f"재생목록 '{local_pl.title}'에 영상이 없습니다.",
                )
                return

        # 로컬 캐시 없으면 YouTube에서 가져오기
        cookie_opts = self._playlist_vm.get_ytdlp_cookie_opts() if self._playlist_vm else {}
        self._vm.import_youtube_to_category(yt_playlist_id, category_id, cookie_opts)

    def _on_yt_import_finished(self, count: int) -> None:
        if count > 0:
            QMessageBox.information(
                self, "가져오기 완료",
                f"YouTube 재생목록에서 영상 {count}개를 카테고리로 가져왔습니다.",
            )

    def _on_sync_yt_playlist(self, yt_playlist_id: str) -> None:
        if self._playlist_vm is None or not yt_playlist_id:
            return
        self._playlist_vm.import_youtube_playlist(yt_playlist_id)

    def _on_sync_all_yt(self) -> None:
        """YouTube 재생목록 전체를 동기화한다."""
        if self._playlist_vm is None:
            return
        yt_pls = [pl for pl in self._playlist_vm.playlists if pl.source == "youtube" and pl.yt_playlist_id]
        if not yt_pls:
            QMessageBox.information(self, "동기화", "동기화할 YouTube 재생목록이 없습니다.")
            return
        for pl in yt_pls:
            self._playlist_vm.import_youtube_playlist(pl.yt_playlist_id)

    def _on_remove_video_from_playlist(self, video_id, playlist_id) -> None:
        if self._playlist_vm is None:
            return
        self._playlist_vm.remove_video_from_playlist(playlist_id, video_id)
        self._vm.set_playlist_filter(playlist_id)  # 목록 갱신

    def _on_move_video_to_playlist(self, video_id, src_pl_id, tgt_pl_id) -> None:
        if self._playlist_vm is None:
            return
        self._playlist_vm.move_video_to_playlist(video_id, src_pl_id, tgt_pl_id)
        self._vm.set_playlist_filter(src_pl_id)  # 현재 재생목록 뷰 갱신

    def _on_video_move_to_playlist_from_dnd(self, vid_id_str: str, src_pl_str: str, tgt_pl_id) -> None:
        """DnD로 영상을 다른 재생목록으로 이전."""
        if self._playlist_vm is None:
            return
        from uuid import UUID  # noqa: PLC0415
        try:
            video_id = UUID(vid_id_str)
            src_pl_id = UUID(src_pl_str) if src_pl_str else None
        except (ValueError, AttributeError):
            return
        self._playlist_vm.move_video_to_playlist(video_id, src_pl_id, tgt_pl_id)
        if src_pl_id is not None:
            self._vm.set_playlist_filter(src_pl_id)

    def _on_push_to_youtube(self, playlist_id, move: bool) -> None:
        if self._playlist_vm is None:
            return
        action = "이동" if move else "복사"
        reply = QMessageBox.question(
            self,
            f"YouTube로 {action}",
            f"이 재생목록을 YouTube에 {action}하시겠습니까?\n"
            + ("(로컬 항목이 YouTube 재생목록으로 전환됩니다)" if move
               else "(로컬 재생목록은 유지되고 YouTube에 새 재생목록이 생성됩니다)"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._playlist_vm.push_to_youtube(playlist_id, move=move)

    # ── 구독 피드 뷰 ─────────────────────────────────────────────────

    def _build_feed_view(self) -> QWidget:
        """feed_panel의 카드 그리드를 재사용한 구독/채널 피드 뷰를 만든다."""
        from gui.panels.feed_panel import _FeedGrid  # noqa: PLC0415
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self._feed_status = QLabel()
        self._feed_status.setContentsMargins(12, 6, 12, 6)
        self._feed_status.setWordWrap(True)
        self._feed_status.hide()
        v.addWidget(self._feed_status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._feed_grid = _FeedGrid()
        scroll.setWidget(self._feed_grid)
        v.addWidget(scroll, stretch=1)

        self._feed_grid.download_requested.connect(self._on_feed_card_download)
        self._feed_grid.add_to_category_requested.connect(self._on_feed_card_to_category)
        self._feed_grid.add_to_playlist_requested.connect(self._on_feed_card_to_playlist)
        return container

    def _build_channels_view(self) -> QWidget:
        """구독 채널 목록(아바타 카드) 그리드 뷰."""
        from gui.panels.feed_panel import _ChannelGrid  # noqa: PLC0415
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self._channels_status = QLabel()
        self._channels_status.setContentsMargins(12, 6, 12, 6)
        self._channels_status.setWordWrap(True)
        self._channels_status.hide()
        v.addWidget(self._channels_status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._channel_grid = _ChannelGrid()
        scroll.setWidget(self._channel_grid)
        v.addWidget(scroll, stretch=1)

        self._channel_grid.channel_clicked.connect(self._on_channel_selected)
        return container

    def _on_channels_root_selected(self) -> None:
        """"구독 채널" 노드 클릭 — 등록된 채널을 아바타 카드 그리드로 표시."""
        if self._feed_vm is None:
            return
        self._push_nav_state()
        self._leave_detail_if_open()
        self._current_playlist_id = None
        self._current_folder_id = None
        self._current_cat_id = None
        self._set_popular_tags_visible(False)
        self._view_stack.setCurrentIndex(_VIEW_CHANNELS)
        self._populate_channels_grid()
        self._refresh_breadcrumb()

    def _populate_channels_grid(self) -> None:
        """현재 구독 목록으로 채널 카드 그리드를 채운다(예비 카드 → 캐시/API 보강).

        _on_channels_root_selected(노드 클릭)와 _on_subs_synced(재동기화 완료) 양쪽에서
        재사용한다 — 뷰 전환·nav 히스토리는 건드리지 않는다.
        """
        if self._feed_vm is None:
            return
        subs = self._monitoring_vm.subscriptions if self._monitoring_vm is not None else []
        channels = [(s.channel_id, s.channel_name, s.channel_url) for s in subs]

        if not channels:
            self._channel_grid.set_channels([])
            self._channels_status.setText("구독 중인 채널이 없습니다.")
            self._channels_status.setVisible(True)
            return

        # Phase 1: DB 정보만으로 예비 카드 즉시 표시 (API 없이)
        from application.library.dtos import ChannelInfoDTO  # noqa: PLC0415
        preliminary = sorted(
            [
                ChannelInfoDTO(
                    channel_id=s.channel_id,
                    channel_name=s.channel_name,
                    channel_url=s.channel_url,
                    thumbnail_url="",
                    subscriber_count=None,
                    video_count=None,
                    latest_video_published_at=None,
                )
                for s in subs
            ],
            key=lambda c: c.channel_name.lower(),
        )
        self._channels_status.setVisible(False)
        self._channel_grid.set_channels(preliminary)

        # Phase 2: API 보강 — 캐시 히트 시 즉시 채우고 스피너 없이 조용히 갱신,
        # 미스 시엔 "구독 채널" 노드에 스피너 띄우고 보강.
        cached = self._feed_vm.get_cached(CHANNELS_ROOT_KEY)
        if cached:
            self._channel_grid.update_cards(cached)
            self._feed_vm.load_channel_infos(channels, silent=True)
        else:
            self._feed_vm.load_channel_infos(channels)

    def _on_sync_subscriptions(self) -> None:
        """구독 채널 컨텍스트 메뉴 '새로고침' — YouTube 구독 목록을 재동기화한다.

        import_from_youtube가 YouTube에서 구독 전체를 다시 조회해 로컬 DB에 반영하면,
        MonitoringViewModel이 subscriptions_changed(→트리 갱신)와 import_yt_finished
        (→그리드 갱신)를 방출한다.
        """
        if self._monitoring_vm is None:
            return
        if self._view_stack.currentIndex() == _VIEW_CHANNELS:
            self._channels_status.setText("YouTube 구독 채널을 동기화하는 중…")
            self._channels_status.setVisible(True)
        self._monitoring_vm.import_from_youtube()

    def _on_subs_synced(self, count: int) -> None:
        """구독 재동기화 완료 — 채널 그리드가 열려 있으면 새 목록으로 다시 채운다."""
        if self._view_stack.currentIndex() == _VIEW_CHANNELS:
            self._populate_channels_grid()

    def _on_subs_sync_error(self, message: str) -> None:
        """구독 재동기화 실패 — 채널 그리드가 열려 있으면 사유를 표시한다."""
        if self._view_stack.currentIndex() == _VIEW_CHANNELS:
            self._channels_status.setText(f"구독 동기화 실패: {message}")
            self._channels_status.setVisible(True)

    def _on_channel_infos_changed(self) -> None:
        if self._feed_vm is None:
            return
        if self._view_stack.currentIndex() != _VIEW_CHANNELS:
            return
        infos = self._feed_vm.channel_infos
        if not infos:
            self._channels_status.setText("채널 정보를 가져오지 못했습니다.")
            self._channels_status.show()
            return
        self._channels_status.hide()
        self._channel_grid.update_cards(infos)   # 예비 카드 in-place 갱신 (카드 재생성 없음)

    def _show_feed_view(self, status: str | None = None) -> None:
        if status:
            self._feed_status.setText(status)
            self._feed_status.show()
        else:
            self._feed_status.hide()
        self._view_stack.setCurrentIndex(_VIEW_FEED)

    def _on_channel_selected(self, channel_url: str) -> None:
        """구독 채널 노드 클릭 — 해당 채널 영상을 피드 그리드에 로드."""
        if self._feed_vm is None or not channel_url:
            return
        self._push_nav_state()
        self._leave_detail_if_open()
        self._current_playlist_id = None
        self._current_folder_id = None
        self._current_cat_id = None
        self._current_channel_url = channel_url
        self._feed_show_channel = False   # 이미 채널을 아는 화면이라 채널명 숨김
        self._set_popular_tags_visible(False)
        self._current_feed_key = channel_url
        cached = self._feed_vm.get_cached(channel_url)
        if cached:
            # 채널별 캐시 히트: 즉시 표시 + 스피너 없이 조용히 백그라운드 갱신
            self._feed_grid.set_feed(cached, show_channel=False)
            self._show_feed_view()
            self._feed_vm.load_channel(channel_url, silent=True)
        else:
            self._show_feed_view("로딩 중…")
            self._feed_vm.load_channel(channel_url)
        self._refresh_breadcrumb()

    def _on_feed_all_selected(self) -> None:
        """전체 구독 피드 노드 클릭 — 모든 구독 채널 최신 영상을 로드."""
        if self._feed_vm is None:
            return
        self._push_nav_state()
        self._leave_detail_if_open()
        self._current_playlist_id = None
        self._current_folder_id = None
        self._current_cat_id = None
        self._feed_show_channel = True    # 여러 채널이 섞이므로 채널명 표시
        self._set_popular_tags_visible(False)
        self._current_feed_key = FEED_ALL_KEY
        cached = self._feed_vm.get_cached(FEED_ALL_KEY)
        if cached:
            # 전체 피드 캐시 히트: 즉시 표시 + 스피너 없이 조용히 백그라운드 갱신
            self._feed_grid.set_feed(cached, show_channel=True)
            self._show_feed_view()
            self._feed_vm.refresh(silent=True)
        else:
            self._show_feed_view("로딩 중…")
            self._feed_vm.refresh()
        self._refresh_breadcrumb()

    def _on_feed_batch_appended(self, batch: list) -> None:
        pass   # feed_batch_ready 시그널로 대체됨

    def _on_feed_changed(self) -> None:
        pass   # feed_key_changed 시그널로 대체됨

    def _on_feed_loading_changed(self, loading: bool) -> None:
        # 스피너는 loading_key_changed 전담; 상태 텍스트만 유지
        if loading and self._view_stack.currentIndex() == _VIEW_FEED:
            if not self._feed_vm.get_cached(self._current_feed_key):
                self._feed_status.setText("로딩 중…")
                self._feed_status.show()

    def _on_feed_loading_key_changed(self, key: str, loading: bool) -> None:
        """loading_key_changed 핸들러 — 해당 키 노드에 스피너 즉시 전환."""
        item = self._playlist_panel.find_yt_item_by_key(key)
        self._playlist_panel.set_yt_node_loading(key, item, loading)

    def _on_local_loading_key_changed(self, key: str, loading: bool) -> None:
        """로컬 트리 노드(카테고리/재생목록) 스피너 즉시 전환."""
        item = self._playlist_panel.find_local_item_by_key(key)
        self._playlist_panel.set_local_node_loading(key, item, loading)

    def _on_feed_key_changed(self, key: str, items: list) -> None:
        """채널 로딩 완료 — 현재 표시 중인 key와 일치할 때만 그리드 갱신."""
        if key != self._current_feed_key:
            return   # 백그라운드 채널 완료 — 캐시에만 저장됨
        show_channel = (key == FEED_ALL_KEY)
        self._feed_grid.set_feed(items, show_channel=show_channel)
        if self._view_stack.currentIndex() == _VIEW_FEED:
            self._feed_status.hide() if items else self._show_feed_view("영상이 없습니다.")

    def _on_feed_batch_ready(self, key: str, batch: list) -> None:
        """부분 결과 배치 — 현재 key 첫 로딩 시만 점진적으로 카드를 추가한다."""
        if key != self._current_feed_key:
            return
        if self._feed_vm.get_cached(key):
            return   # 재방문: feed_key_changed가 전체 교체
        if self._view_stack.currentIndex() != _VIEW_FEED:
            return
        show_channel = (key == FEED_ALL_KEY)
        self._feed_grid.append_feed(batch, show_channel=show_channel)
        self._feed_status.hide()

    def _on_feed_error(self, msg: str) -> None:
        idx = self._view_stack.currentIndex()
        if idx not in (_VIEW_FEED, _VIEW_CHANNELS):
            return
        ml = msg.lower()
        if "could not copy" in ml or ("database" in ml and "lock" in ml):
            display = (
                "Chrome이 실행 중입니다 — Chrome을 완전히 종료 후 재시도하거나,\n"
                "설정 > YouTube 계정에서 브라우저를 Firefox로 변경하세요."
            )
        elif "복호화" in msg or "dpapi" in ml or "failed to decrypt" in ml:
            # ytdlp_adapter가 이미 한국어 안내문으로 변환한 DPAPI 메시지를 그대로 표시
            display = msg
        elif "cookie" in ml or "쿠키" in msg:
            display = (
                "쿠키 인증 실패 — 설정 > YouTube 계정에서 Firefox로 변경하거나\n"
                "Chrome을 완전히 종료 후 재시도하세요."
            )
        elif "sign in" in ml or "로그인" in msg:
            display = "YouTube 로그인 필요 — 설정 > YouTube 계정에서 로그인하세요."
        else:
            display = f"오류: {msg[:200]}"
        status = self._feed_status if idx == _VIEW_FEED else self._channels_status
        status.setText(display)
        status.show()

    def _on_feed_card_download(self, url: str, title: str) -> None:
        from domain.download.value_objects import DownloadSettings  # noqa: PLC0415
        self.download_requested.emit(url, title, DownloadSettings())

    def _on_feed_card_to_category(self, url: str) -> None:
        self._vm.add_video(url)

    def _on_feed_card_to_playlist(self, url: str) -> None:
        # 재생목록 선택 UI가 없으므로 우선 라이브러리에 등록한다.
        self._vm.add_video(url)

    # ── 폴더 뷰 핸들러 ───────────────────────────────────────────────

    def _on_playlist_selected_from_tree(self, playlist_id) -> None:
        """트리에서 재생목록 선택 — 폴더 카드 뷰에 있다면 정상 뷰로 복귀 후 필터 적용."""
        self._push_nav_state()
        self._leave_detail_if_open()
        node_key = f"pl:{playlist_id}" if playlist_id is not None else None
        self._vm.set_playlist_filter(playlist_id, node_key=node_key)
        self._icon_view.set_playlist_context(playlist_id)
        self._list_view.set_playlist_context(playlist_id)
        if self._view_stack.currentIndex() in (_VIEW_FOLDER, _VIEW_FEED, _VIEW_CHANNELS):
            self._switch_view(_VIEW_ALBUMS if self._album_mode else self._last_list_view)
        self._current_playlist_id = playlist_id
        self._current_folder_id = None
        # 재생목록 선택 시에는 태그 섹션을 숨겨 트리가 더 넓게 보이도록 한다
        self._set_popular_tags_visible(False)
        self._refresh_breadcrumb()

    def _on_folder_selected(self, folder_id) -> None:
        """폴더 클릭 — 폴더 내 재생목록을 카드 그리드로 표시한다.
        folder_id=None이면 '미분류' 디렉터리 뷰."""
        if self._playlist_vm is None:
            return
        self._push_nav_state()
        self._leave_detail_if_open()
        folder_pls = [pl for pl in self._playlist_vm.playlists if pl.folder_id == folder_id]
        self._folder_view.load(folder_pls, get_first_item=self._vm.get_playlist_first_item)
        self._view_stack.setCurrentIndex(_VIEW_FOLDER)
        self._vm.set_playlist_filter(None)
        self._current_folder_id = folder_id
        self._current_playlist_id = None
        self._set_popular_tags_visible(False)   # 폴더(재생목록 묶음) 뷰에서도 숨김
        self._refresh_breadcrumb()

    def _on_unfiled_selected(self, source: str) -> None:
        """미분류 클릭 — 해당 섹션의 폴더 없는 재생목록을 카드 그리드로 표시한다."""
        self._on_folder_selected(None)

    def _on_section_root_selected(self, source: str) -> None:
        """섹션 루트('로컬'/'YouTube') 클릭 — 해당 섹션의 폴더 + 미분류 카드를 표시한다.
        (경로 바에서 'YouTube' 세그먼트 클릭 시 호출)"""
        if self._playlist_vm is None:
            return
        folders = [f for f in self._playlist_vm.folders if f.source == source]
        unfiled_pls = [pl for pl in self._playlist_vm.playlists
                       if pl.source == source and pl.folder_id is None]
        self._folder_view.load(
            playlists=[],
            get_first_item=self._vm.get_playlist_first_item,
            folders=folders,
            show_unfiled=True,
            unfiled_count=len(unfiled_pls),
        )
        self._view_stack.setCurrentIndex(_VIEW_FOLDER)
        self._vm.set_playlist_filter(None)
        # 섹션 루트 — 폴더도 재생목록도 아닌 상태
        self._current_folder_id = None
        self._current_playlist_id = None
        self._set_popular_tags_visible(False)
        # 경로 바: "YouTube" 또는 "로컬" 단독 (클릭 안 되는 마지막 세그먼트)
        label = "YouTube" if source == "youtube" else "로컬"
        self._breadcrumb_bar.update_path([(label, None)], [])
        self._breadcrumb_bar.show()

    def _on_folder_playlist_selected(self, playlist_id) -> None:
        """폴더 뷰에서 카드 클릭 — 해당 재생목록을 선택하고 정상 뷰로 돌아간다."""
        self._playlist_panel.select_playlist(playlist_id)
        self._vm.set_playlist_filter(playlist_id)
        self._icon_view.set_playlist_context(playlist_id)
        self._list_view.set_playlist_context(playlist_id)
        self._switch_view(_VIEW_ALBUMS if self._album_mode else self._last_list_view)   # 이전 뷰 모드로 복귀
        self._current_playlist_id = playlist_id
        self._current_folder_id = None
        self._refresh_breadcrumb()

    # ── 다중 선택 일괄 처리 ────────────────────────────────────────────

    def _confirm_bulk_remove_from_playlist(self, video_ids: list, playlist_id) -> None:
        """재생목록에서 다중 영상 일괄 제거 확인 다이얼로그."""
        if self._playlist_vm is None:
            return
        reply = QMessageBox.question(
            self, "일괄 제거",
            f"{len(video_ids)}개 영상을 재생목록에서 제거하시겠습니까?\n"
            "(YouTube 재생목록이면 YouTube에도 반영됩니다)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for vid_id in video_ids:
            try:
                self._playlist_vm.remove_video_from_playlist(playlist_id, vid_id)
            except Exception:
                logger.exception("재생목록에서 영상 일괄 제거 실패")
        self._vm.set_playlist_filter(playlist_id)

    def _on_bulk_copy_to_playlist(self, video_ids: list, playlist_id) -> None:
        """다중 영상을 재생목록으로 복사한다."""
        if self._playlist_vm is None:
            return
        count = 0
        for vid_id in video_ids:
            try:
                self._playlist_vm.add_video_to_playlist(playlist_id, vid_id)
                count += 1
            except Exception:
                logger.exception("재생목록으로 영상 일괄 복사 실패")
        if count > 0:
            QMessageBox.information(self, "복사 완료", f"{count}개 영상을 재생목록에 복사했습니다.")

    def _on_import_yt_playlist(self) -> None:
        if self._playlist_vm is None:
            return
        # YouTube 계정 재생목록 목록 먼저 가져오기
        self._playlist_vm.yt_playlists_ready.connect(self._on_yt_playlists_ready, Qt.ConnectionType.SingleShotConnection)
        self._playlist_vm.fetch_youtube_playlists()

    def _on_yt_playlists_ready(self, playlists: list) -> None:
        if not playlists:
            # 목록이 없으면 수동 입력 fallback
            import urllib.parse  # noqa: PLC0415
            pl_id, ok = QInputDialog.getText(
                self, "YouTube 재생목록 가져오기",
                "계정 재생목록을 찾지 못했습니다.\nYouTube 재생목록 ID 또는 URL을 직접 입력하세요:",
            )
            if not ok or not pl_id.strip():
                return
            yt_id = pl_id.strip()
            if "list=" in yt_id:
                import urllib.parse  # noqa: PLC0415
                parsed = urllib.parse.urlparse(yt_id)
                params = urllib.parse.parse_qs(parsed.query)
                yt_id = params.get("list", [yt_id])[0]
            self._playlist_vm.import_youtube_playlist(yt_id)
            return

        # 재생목록 선택 다이얼로그
        from PyQt6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QScrollArea  # noqa: PLC0415
        dlg = QDialog(self)
        dlg.setWindowTitle("YouTube 재생목록 가져오기")
        dlg.setMinimumWidth(400)
        dlg.setMinimumHeight(360)
        layout = QVBoxLayout(dlg)

        lbl = QLabel(f"YouTube 계정에서 재생목록 {len(playlists)}개를 찾았습니다.\n가져올 재생목록을 선택하세요:")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        check_container = QWidget()
        check_layout = QVBoxLayout(check_container)
        check_layout.setContentsMargins(4, 4, 4, 4)
        check_layout.setSpacing(4)

        checkboxes: list[tuple[QCheckBox, str]] = []  # (checkbox, yt_playlist_id)
        for pl in playlists:
            pl_id = pl.get("id") or ""
            pl_title = pl.get("title") or pl_id
            pl_count = pl.get("count") or 0
            label = f"{pl_title}  ({pl_count}개)"
            cb = QCheckBox(label)
            cb.setChecked(True)
            check_layout.addWidget(cb)
            checkboxes.append((cb, pl_id))

        check_layout.addStretch()
        scroll.setWidget(check_container)
        layout.addWidget(scroll, 1)

        sel_row = QHBoxLayout()
        btn_all = QPushButton("전체 선택")
        btn_none = QPushButton("전체 해제")
        btn_all.setFixedWidth(80)
        btn_none.setFixedWidth(80)
        btn_all.clicked.connect(lambda: [cb.setChecked(True) for cb, _ in checkboxes])
        btn_none.clicked.connect(lambda: [cb.setChecked(False) for cb, _ in checkboxes])
        sel_row.addWidget(btn_all)
        sel_row.addWidget(btn_none)
        sel_row.addStretch()
        layout.addLayout(sel_row)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        selected_ids = [pl_id for cb, pl_id in checkboxes if cb.isChecked() and pl_id]
        for yt_id in selected_ids:
            self._playlist_vm.import_youtube_playlist(yt_id)

    def _on_import_yt_playlist_manual(self) -> None:
        if self._playlist_vm is None:
            return
        import urllib.parse  # noqa: PLC0415
        pl_id, ok = QInputDialog.getText(
            self, "YouTube 재생목록 가져오기",
            "YouTube 재생목록 ID 또는 URL을 입력하세요:",
        )
        if not ok or not pl_id.strip():
            return
        yt_id = pl_id.strip()
        if "list=" in yt_id:
            parsed = urllib.parse.urlparse(yt_id)
            params = urllib.parse.parse_qs(parsed.query)
            yt_id = params.get("list", [yt_id])[0]
        self._playlist_vm.import_youtube_playlist(yt_id)

    def _on_playlist_reordered(self, playlist_id: UUID, ordered_ids: list[UUID]) -> None:
        if self._playlist_vm is None:
            return
        self._playlist_vm.reorder_playlist(playlist_id, ordered_ids)
