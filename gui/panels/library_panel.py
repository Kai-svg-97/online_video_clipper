"""라이브러리 화면 — 좌측 트리 | 가운데 목록 | 우측(상세는 같은 자리에서 전환).

이 파일은 **화면 조립(`_setup_ui`)과 신호 배선(`_connect_signals`)만** 담당한다.
7,500줄짜리 한 파일이던 것을 두 축으로 나눴다.

* `gui/panels/library/*` — **부품**: 상수·포맷 함수·썸네일 캐시·목록 모델·델리게이트·
  태그 위젯·폴더 카드·좌측 트리. 패널을 몰라도 단독으로 읽고 테스트할 수 있다.
* `gui/panels/library/mixins/*` — **동작**: 앨범 보기·추천 스트립·화면 히스토리·상세
  진입·좌측 트리 조작·구독 피드·목록(검색/정렬/뷰)·우클릭 메뉴. `LibraryPanel`에
  섞여 들어가므로 런타임 클래스는 여전히 하나이고 상태 공유 방식도 이전과 같다 —
  파일을 나눈 목적은 "이 동작이 어디 있나"를 파일 이름으로 찾게 하는 것이다.

가운데 영역은 `_nav_stack`(0=목록, 1=영상 상세, 2=앨범 상세)으로 전환하며, 목록 자체는
`_view_stack`(아이콘/리스트/표/폴더/피드/채널/앨범)으로 다시 나뉜다.
"""
from __future__ import annotations

import logging
from uuid import UUID

from PyQt6.QtCore import (
    QSize,
    QTimer,
    QVariantAnimation,
    Qt,
    pyqtSignal,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QProgressDialog,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import config.settings as _settings
from gui.panels.video_detail_panel import (
    VideoDetailWidget,
)
from gui.smooth_scroll import apply_smooth_scroll_tree
from gui.themes.manager import ThemeManager
from gui.view_models.library_vm import LibraryViewModel


# ── LibraryPanel 동작 묶음 (gui/panels/library/mixins/*) ──────────
# 화면 조립(_setup_ui)·배선(_connect_signals)만 이 파일에 남기고, 나머지 동작은
# 주제별 mixin으로 나눴다. 런타임 클래스는 하나라 상태 공유는 이전과 같다.
from gui.panels.library.mixins.album import AlbumViewMixin
from gui.panels.library.mixins.recommend import RecommendStripMixin
from gui.panels.library.mixins.navigation import NavigationMixin
from gui.panels.library.mixins.detail import DetailNavigationMixin
from gui.panels.library.mixins.sidebar import SidebarTreeMixin
from gui.panels.library.mixins.feed import FeedViewMixin
from gui.panels.library.mixins.video_list import VideoListMixin
from gui.panels.library.mixins.context_menu import VideoContextMenuMixin
from gui.panels.library.mixins.shortcuts import ShortcutsMixin

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
# Library panel (3-pane: categories+tags | video list | preview)
# ------------------------------------------------------------------

class LibraryPanel(
    AlbumViewMixin,
    RecommendStripMixin,
    NavigationMixin,
    DetailNavigationMixin,
    SidebarTreeMixin,
    FeedViewMixin,
    VideoListMixin,
    VideoContextMenuMixin,
    ShortcutsMixin,
    QWidget,
):
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
        # 목록·트리·카드 그리드의 휠 스크롤을 픽셀 단위 + 보간으로 바꾼다
        # (기본값은 항목 단위라 카드 한 장씩 뚝뚝 점프한다).
        apply_smooth_scroll_tree(self)
        self._setup_shortcuts()
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
        self._search_box.setPlaceholderText("검색  (Ctrl+F, Enter: 즉시 검색, Esc: 지우기)")
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
        # 이어보기 흐름 — 최근에 보던 것부터 다시 집어 들 수 있게.
        self._sort_combo.addItem("최근 재생순", ("last_played_at", False))
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
        # 키보드만으로도 열 수 있게 — 방향키로 옮기고 Enter로 연다.
        # (activated는 Enter·더블클릭 모두에서 나므로 클릭 경로와 같은 핸들러를 쓴다.)
        self._icon_view.activated.connect(
            lambda idx: self._on_item_activated(idx, self._icon_view)
        )
        self._list_view.activated.connect(
            lambda idx: self._on_item_activated(idx, self._list_view)
        )
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
        self._detail_widget.playback_position_changed.connect(
            self._vm.save_playback_position
        )
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

        # Ctrl+휠 뷰 전환 필터. 마우스 ‹/›는 화면이 보이는 동안 앱 전역 필터가 받으므로
        # (NavigationMixin.showEvent) 위젯마다 걸 필요가 없지만, 이 목록·앨범 위젯에는
        # Ctrl+휠 전환 때문에 그대로 둔다 — 같은 eventFilter가 두 가지를 처리한다.
        for w in (self._icon_view, self._list_view, self._table,
                  self._album_grid, self._album_detail):
            viewport = getattr(w, "viewport", None)
            if viewport:
                viewport().installEventFilter(self)
            w.installEventFilter(self)

    # ── 검색 ───────────────────────────────────────────────────────


    # ── VM → UI ────────────────────────────────────────────────────


    # ── 추천 영상 스트립 ───────────────────────────────────────────────
    # 배경: YouTube Data API v3의 search.list(relatedToVideoId=)가 폐지돼
    # '관련 영상'을 직접 받을 수 없다. 지금 보고 있는 목록(제목·채널·태그)에서
    # 대표 검색어를 뽑아 검색으로 후보를 모은다(domain/library/recommendation.py).


    # ── 스트립 등장/퇴장 연출 ─────────────────────────────────────────
    # 조회 중인 빈 띠(또는 직전 카테고리의 추천)가 자리를 차지하지 않도록, 목록이 다
    # 준비된 뒤에야 아래에서 밀려 올라오듯 노출한다. 새 조회가 시작되면(카테고리 전환·
    # 검색·⟳) 다시 아래로 접어 감췄다가 결과가 도착하면 올린다.


        # gen 불일치(구 노드 로더)도 캐시에는 저장 완료 → 재방문 시 캐시 히트


    # ── Table ──────────────────────────────────────────────────────


    # ── View mode ──────────────────────────────────────────────────


    # ── Category / tag selection ───────────────────────────────────


    # ── 앨범 보기 (음악 카테고리 전용) ───────────────────────────────
    # 앨범은 저장된 것이 아니라 노래 정보(가수·앨범)에서 파생되는 묶음이다. 그래서
    # '앨범'은 정렬이 아니라 **보기 유형**(⊞/☰/⊟ 옆의 💿 버튼)이며, 목록을 다시 정렬하는
    # 대신 화면 자체를 자켓 그리드로 바꾼다 — 리포지토리 정렬로는 표현할 수 없다.


    # ── In-place navigation ────────────────────────────────────────


    # ── Smart Folders ──────────────────────────────────────────────


    # ── Empty space click ────────────────────────────────────────────


    # ── 이벤트 필터: Ctrl+휠 뷰 전환 & 마우스 BackButton 히스토리 ────────


    # ── 내비게이션 히스토리 ────────────────────────────────────────────


    # ── URL dropped onto video list ────────────────────────────────


    # ── Category management ────────────────────────────────────────


    # ── Item click / double-click ──────────────────────────────────


    # ── URL/video drop ─────────────────────────────────────────────


    # ── 상세화면 카테고리 지정 ─────────────────────────────────────
    # 라이브러리 영상이든 추천/피드의 스트리밍 영상이든 같은 버튼 하나로 처리한다.
    # 스트리밍 영상은 '등록 + 카테고리 지정'이 한 번에 일어나야 요약·가사 잠금이 풀린다
    # (두 기능은 영상별로 DB에 저장돼 안정적인 로컬 video_id가 필요하다).


    # ── Context menus ──────────────────────────────────────────────


    # ── Playlist handlers ──────────────────────────────────────────


    # ── 구독 피드 뷰 ─────────────────────────────────────────────────


    # ── 폴더 뷰 핸들러 ───────────────────────────────────────────────


    # ── 다중 선택 일괄 처리 ────────────────────────────────────────────


