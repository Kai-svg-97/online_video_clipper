"""LibraryViewModel — 라이브러리 화면의 상태(영상 목록·카테고리·태그·필터).

**여기에는 조립부만 있다** — 시그널, 생성자(핸들러 주입·상태 초기화), `shutdown()`,
읽기 전용 속성. 동작은 `gui/view_models/library/` 패키지의 주제별 mixin에 있다:

| 모듈 | 책임 |
| --- | --- |
| `listing.py` | 목록 조회(캐시·페이지·동시 워커 상한·로딩 신호) |
| `filters.py` | 검색어·복합 필터·저장된 검색·카테고리/재생목록/태그 필터·정렬 |
| `categories.py` | 카테고리 트리 CRUD·경로·영상 배정 |
| `tags.py` | 태그 집계·삭제·영상 태그 편집 |
| `videos.py` | 영상 한 건 조회·저장(메인 스레드 동기 호출) |
| `registration.py` | 영상 등록 + 등록 직후 자동 보강(동시 1건) |
| `refresh.py` | 메타데이터·썸네일·YouTube 재생목록 가져오기(워커) |
| `workers.py` | 위가 띄우는 QThread 워커 7종 |

런타임 클래스는 그대로 `LibraryViewModel` 하나다(mixin 합성). 워커 이름은 이 모듈에서도
임포트할 수 있게 남겨 두지만, 테스트에서 **패치할 때는 쓰는 쪽 mixin 모듈**을 패치한다.
"""
from __future__ import annotations

import logging
from collections import OrderedDict, deque
from uuid import UUID

from PyQt6.QtCore import QObject, pyqtSignal

from gui.view_models.base import WorkerOwnerMixin
from gui.view_models.library.categories import CategoryMixin
from gui.view_models.library.filters import FilterMixin
from gui.view_models.library.listing import VideoListMixin
from gui.view_models.library.refresh import RefreshMixin
from gui.view_models.library.registration import RegistrationMixin
from gui.view_models.library.tags import TagMixin
from gui.view_models.library.videos import VideoQueryMixin
from gui.view_models.library.workers import (  # noqa: F401 — 재수출(기존 임포트 경로 유지)
    _AddVideoWorker,
    _EnrichWorker,
    _ImportYTToCatWorker,
    _ListVideosWorker,
    _RefreshMetadataWorker,
    _RefreshThumbnailWorker,
    _RefreshVideoMetaWorker,
)

from application.library.commands import (
    AddVideoHandler,
    AssignCategoryHandler,
    CreateCategoryHandler,
    DeleteCategoryHandler,
    DeleteTagHandler,
    DeleteVideoHandler,
    ImportYouTubePlaylistToCategoryHandler,
    MarkWatchedHandler,
    MoveCategoryHandler,
    RefreshCategoryMetadataHandler,
    RefreshVideoMetadataHandler,
    RefreshVideoThumbnailHandler,
    RenameCategoryHandler,
    SetCategoryVideoOrderHandler,
    UpdateVideoHandler,
)
from application.library.dtos import CategoryDTO, TagDTO, VideoDTO
from application.library.playlist_queries import GetPlaylistItemsHandler
from application.library.queries import (
    GetCategoriesHandler,
    GetCategoryVideoOrderHandler,
    GetTagsHandler,
    GetVideoDetailHandler,
    GetVideoIdByUrlHandler,
    GetVideosHandler,
    SearchVideosHandler,
)

logger = logging.getLogger(__name__)


class LibraryViewModel(
    WorkerOwnerMixin,
    VideoListMixin,
    FilterMixin,
    CategoryMixin,
    TagMixin,
    VideoQueryMixin,
    RegistrationMixin,
    RefreshMixin,
    QObject,
):
    videos_changed = pyqtSignal()
    categories_changed = pyqtSignal()
    tags_changed = pyqtSignal()
    scoped_tags_changed = pyqtSignal()  # 현재 트리 노드 스코프 인기 태그 갱신
    error_occurred = pyqtSignal(str)
    video_add_started = pyqtSignal(str)
    video_add_finished = pyqtSignal(str)
    metadata_refresh_progress = pyqtSignal(int, int)  # current, total
    metadata_refresh_finished = pyqtSignal(int)        # count refreshed
    yt_import_progress  = pyqtSignal(int, int)         # current, total
    yt_import_finished  = pyqtSignal(int)              # 처리된 영상 수
    thumbnail_refreshed = pyqtSignal(object, str)      # (video_id: UUID, new_path)
    # 단일 영상 상세 정보 갱신(⟳) 완료 — (video_id, ok). ok=True면 DB가 갱신됨.
    video_metadata_refreshed = pyqtSignal(object, bool)
    loading_key_changed = pyqtSignal(str, bool)        # (node_key, loading) — 트리 노드별 스피너
    # 목록 조회 진행 여부(노드 키 유무와 무관 — 검색 조회도 포함) — 목록 스켈레톤 전용.
    # 겹치는 조회를 깊이 카운터(_list_inflight)로 관리해, 먼저 끝난 조회가
    # 아직 진행 중인 다른 조회의 로딩 상태를 꺼버리지 않게 한다.
    loading_changed = pyqtSignal(bool)
    # 등록 직후 자동 보강 — (url, kind) / (url, kind, ok, detail)
    enrich_started  = pyqtSignal(str, str)
    enrich_finished = pyqtSignal(str, str, bool, str)

    def __init__(
        self,
        get_videos: GetVideosHandler,
        search_videos: SearchVideosHandler,
        get_categories: GetCategoriesHandler,
        get_tags: GetTagsHandler,
        add_video: AddVideoHandler,
        update_video: UpdateVideoHandler,
        delete_video: DeleteVideoHandler,
        mark_watched: MarkWatchedHandler,
        create_category: CreateCategoryHandler,
        rename_category: RenameCategoryHandler,
        delete_category: DeleteCategoryHandler,
        move_category: MoveCategoryHandler,
        delete_tag: DeleteTagHandler,
        assign_category: AssignCategoryHandler,
        get_video_detail: GetVideoDetailHandler,
        refresh_metadata: RefreshCategoryMetadataHandler,
        get_playlist_items: GetPlaylistItemsHandler | None = None,
        get_category_order: GetCategoryVideoOrderHandler | None = None,
        set_category_order: SetCategoryVideoOrderHandler | None = None,
        import_yt_to_category: ImportYouTubePlaylistToCategoryHandler | None = None,
        refresh_thumbnail: RefreshVideoThumbnailHandler | None = None,
        get_video_id_by_url: GetVideoIdByUrlHandler | None = None,
        refresh_video_metadata: RefreshVideoMetadataHandler | None = None,
        find_song_videos=None,   # FindSongVideoIdsHandler | None — 같은 가수/앨범 필터
        update_position=None,    # UpdatePlaybackPositionHandler | None — 이어보기
        enrich_video=None,       # EnrichVideoHandler | None — 등록 후 요약/가사 자동 보강
        list_saved_searches=None,   # ListSavedSearchesHandler | None
        save_search=None,           # SaveSearchHandler | None
        delete_saved_search=None,   # DeleteSavedSearchHandler | None
        rename_saved_search=None,   # RenameSavedSearchHandler | None
        get_downloaded_formats=None,  # GetDownloadedFormatsHandler | None — 목록 배지 일괄 판정
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._get_downloaded_formats = get_downloaded_formats
        self._get_video_id_by_url = get_video_id_by_url
        self._get_videos = get_videos
        self._search_videos = search_videos
        self._get_categories = get_categories
        self._get_tags = get_tags
        self._add_video = add_video
        self._update_video = update_video
        self._delete_video = delete_video
        self._mark_watched = mark_watched
        self._create_category = create_category
        self._rename_category = rename_category
        self._delete_category = delete_category
        self._move_category = move_category
        self._delete_tag = delete_tag
        self._assign_category = assign_category
        self._get_video_detail = get_video_detail
        self._refresh_metadata = refresh_metadata
        self._get_playlist_items = get_playlist_items
        self._get_category_order = get_category_order
        self._set_category_order = set_category_order
        self._import_yt_to_category = import_yt_to_category
        self._refresh_thumbnail_handler = refresh_thumbnail
        self._refresh_video_meta = refresh_video_metadata
        self._find_song_videos = find_song_videos
        # 이어보기 위치 저장(선택 주입) — 없으면 위치를 기록하지 않는다.
        self._update_position = update_position
        self._enrich_video = enrich_video
        # 없으면 저장된 검색 기능만 조용히 빠진다(화면이 메뉴를 만들지 않는다).
        self._list_saved = list_saved_searches
        self._save_search = save_search
        self._delete_saved = delete_saved_search
        self._rename_saved = rename_saved_search
        # 보강은 동시 1건만 — Gemini가 브라우저를 띄우므로 병렬 실행을 막는다.
        self._enrich_workers: list[_EnrichWorker] = []
        self._pending_enrich: deque = deque()   # (video_id, url)
        self._refresh_metadata_workers: list[_RefreshMetadataWorker] = []
        self._video_meta_workers: list[_RefreshVideoMetaWorker] = []
        self._yt_import_workers: list[_ImportYTToCatWorker] = []
        self._thumb_workers: list[_RefreshThumbnailWorker] = []
        self._list_workers: list[_ListVideosWorker] = []
        self._list_gen: int = 0
        self._list_inflight: int = 0  # loading_changed 깊이 카운터(겹치는 조회 안전)

        self._videos: list[VideoDTO] = []
        self._categories: list[CategoryDTO] = []
        self._tags: list[TagDTO] = []
        self._scoped_tags: list[TagDTO] = []
        self._current_page: int = 0
        # 다음 쪽이 더 있는가 — 마지막으로 받아 온 묶음이 한 쪽을 꽉 채웠는지로
        # 본다. 총 개수를 따로 세지 않는 이유는 COUNT(*) 한 번이 목록 조회와
        # 맞먹기 때문이다(필터·검색이 걸리면 특히).
        self._has_more: bool = False
        # ── 복합 필터 ─────────────────────────────────────────────
        # 엔진(SearchQuery·리포지토리 SQL)에는 처음부터 있었는데 **화면에서 넘기는
        # 곳이 없어** 쓸 수 없었다. 여기서 모아 두고 조회마다 함께 넘긴다.
        self._filter_published_from: str = ""
        self._filter_published_to: str = ""
        self._filter_channel: str = ""
        self._filter_downloaded: bool | None = None
        self._filter_favorite_only: bool = False
        self._filter_watched: bool | None = None
        self._filter_min_duration: int | None = None
        self._filter_max_duration: int | None = None
        self._search_text: str = ""
        self._filter_category_id: UUID | None = None
        # "로컬" 루트 뷰 — 카테고리에 속한 영상만 표시(미분류·재생목록 전용 제외). 기본 진입 뷰.
        self._filter_categorized_only: bool = True
        self._filter_tag_ids: list[UUID] = []
        self._filter_playlist_id: UUID | None = None
        self._filter_playlist_video_ids: list[UUID] = []
        self._add_workers: list[_AddVideoWorker] = []
        self._sort_by: str = "created_at"
        self._sort_asc: bool = False
        self._video_cache: OrderedDict[str, list[VideoDTO]] = OrderedDict()
        # 멀티워커 — 동시 로딩 워커 수를 제한하고 초과분은 큐에 보관(노드 연타 시 스레드 폭발 방지)
        self._pending_list: deque = deque()   # (fetch, append, gen, ck, on_done, node_key)
        try:
            import config.settings as _s  # noqa: PLC0415
            self._max_workers: int = getattr(_s, "MAX_CONCURRENT_FEED_WORKERS", 4)
        except Exception:
            self._max_workers = 4

    def set_max_workers(self, n: int) -> None:
        """동시 로딩 워커 최대 수를 변경한다 (메인 스레드에서만 호출)."""
        self._max_workers = max(1, min(n, 8))

    def shutdown(self) -> None:
        """앱 종료 시 호출 — 실행 중인 백그라운드 워커(메타데이터 갱신·YouTube
        가져오기·영상 추가)를 정리해 죽은 객체로의 시그널 방출을 막는다.

        finished 시그널이 리스트를 변형하므로 사본을 순회한다.
        """
        for worker in [
            *self._refresh_metadata_workers,
            *self._video_meta_workers,
            *self._yt_import_workers,
            *self._add_workers,
            *self._enrich_workers,
            *self._thumb_workers,
            *self._list_workers,
        ]:
            if worker.isRunning():
                worker.terminate()
                worker.wait(3000)
        self._refresh_metadata_workers.clear()
        self._video_meta_workers.clear()
        self._yt_import_workers.clear()
        self._add_workers.clear()
        self._enrich_workers.clear()
        self._pending_enrich.clear()
        self._thumb_workers.clear()
        self._list_workers.clear()
        self._pending_list.clear()
        self._list_inflight = 0
        super().shutdown()   # 공용 추적 목록 정리

    @property
    def videos(self) -> list[VideoDTO]:
        return self._videos

    @property
    def categories(self) -> list[CategoryDTO]:
        return self._categories

    @property
    def tags(self) -> list[TagDTO]:
        return self._tags

    @property
    def scoped_tags(self) -> list[TagDTO]:
        """현재 트리 노드(카테고리/재생목록) 스코프로 집계된 인기 태그."""
        return self._scoped_tags
