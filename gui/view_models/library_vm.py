from __future__ import annotations

import logging
from collections import OrderedDict, deque
from uuid import UUID

_VIDEO_CACHE_MAX = 20  # 최대 20개 쿼리 결과를 LRU 캐시에 보관

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from application.library.commands import (
    AddVideoCommand,
    AddVideoHandler,
    AssignCategoryCommand,
    AssignCategoryHandler,
    CreateCategoryCommand,
    CreateCategoryHandler,
    DeleteCategoryCommand,
    DeleteCategoryHandler,
    DeleteTagCommand,
    DeleteTagHandler,
    DeleteVideoCommand,
    DeleteVideoHandler,
    ImportYouTubePlaylistToCategoryCommand,
    ImportYouTubePlaylistToCategoryHandler,
    MarkWatchedCommand,
    MarkWatchedHandler,
    MoveCategoryCommand,
    MoveCategoryHandler,
    RefreshCategoryMetadataCommand,
    RefreshCategoryMetadataHandler,
    RefreshVideoMetadataCommand,
    RefreshVideoMetadataHandler,
    RefreshVideoThumbnailCommand,
    RefreshVideoThumbnailHandler,
    RenameCategoryCommand,
    RenameCategoryHandler,
    SetCategoryVideoOrderCommand,
    SetCategoryVideoOrderHandler,
    UpdateVideoCommand,
    UpdateVideoHandler,
)
from application.library.dtos import CategoryDTO, TagDTO, VideoDTO, VideoDetailDTO
from application.library.playlist_queries import GetPlaylistItemsHandler, GetPlaylistItemsQuery
from application.library.queries import (
    GetCategoriesHandler,
    GetCategoryVideoOrderHandler,
    GetCategoryVideoOrderQuery,
    GetDownloadedFormatsQuery,
    GetTagsHandler,
    GetTagsQuery,
    GetVideoDetailHandler,
    GetVideoIdByUrlHandler,
    GetVideosHandler,
    GetVideosQuery,
    SearchVideosHandler,
    SearchVideosQuery,
)
from config.settings import DEFAULT_PAGE_SIZE

logger = logging.getLogger(__name__)


class _AddVideoWorker(QThread):
    finished_ok = pyqtSignal(object)   # video_id: UUID — 등록 후 보강에 사용
    finished_err = pyqtSignal(str)

    def __init__(
        self,
        handler: AddVideoHandler,
        cmd: AddVideoCommand,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._handler = handler
        self._cmd = cmd

    def run(self) -> None:
        try:
            agg = self._handler.handle(self._cmd)
            self.finished_ok.emit(agg.id)
        except Exception as exc:
            self.finished_err.emit(str(exc))


class _EnrichWorker(QThread):
    """등록 직후 요약/가사 자동 보강을 백그라운드에서 실행한다.

    Gemini 요약 추출은 Playwright 브라우저를 띄워 수십 초가 걸리므로
    ViewModel이 동시 1건으로 직렬화한다.
    """
    finished_result = pyqtSignal(str, str, bool, str)   # url, kind, ok, detail

    def __init__(self, handler, cmd, url: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._handler = handler
        self._cmd = cmd
        self._url = url

    def run(self) -> None:
        try:
            result = self._handler.handle(self._cmd)
            self.finished_result.emit(self._url, result.kind, result.ok, result.detail)
        except Exception as exc:
            logger.exception("영상 보강 워커 실패: %s", self._url)
            self.finished_result.emit(self._url, "skipped", False, str(exc))


class _ImportYTToCatWorker(QThread):
    progress    = pyqtSignal(int, int)  # current, total
    finished_ok = pyqtSignal(int)       # 처리된 영상 수
    finished_err = pyqtSignal(str)

    def __init__(
        self,
        handler: ImportYouTubePlaylistToCategoryHandler,
        cmd: ImportYouTubePlaylistToCategoryCommand,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._handler = handler
        self._cmd = cmd

    def run(self) -> None:
        try:
            self._cmd.on_progress = lambda cur, tot: self.progress.emit(cur, tot)
            count = self._handler.handle(self._cmd)
            self.finished_ok.emit(count)
        except Exception as exc:
            self.finished_err.emit(str(exc))


class _ListVideosWorker(QThread):
    """_refresh_videos()를 백그라운드 스레드에서 실행한다."""
    finished_ok  = pyqtSignal(list, bool)   # (videos, append)
    finished_err = pyqtSignal(str)

    def __init__(self, fetch_fn, append: bool, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fetch = fetch_fn
        self._append = append

    def run(self) -> None:
        try:
            results = self._fetch()
            self.finished_ok.emit(results, self._append)
        except Exception as exc:
            self.finished_err.emit(str(exc))


class _RefreshThumbnailWorker(QThread):
    """단일 영상의 썸네일을 백그라운드에서 갱신한다."""
    finished_ok  = pyqtSignal(object, str)   # (video_id: UUID, new_path: str)
    finished_err = pyqtSignal(str)

    def __init__(
        self,
        handler: RefreshVideoThumbnailHandler,
        cmd: RefreshVideoThumbnailCommand,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._handler = handler
        self._cmd = cmd

    def run(self) -> None:
        try:
            new_path = self._handler.handle(self._cmd)
            if new_path:
                self.finished_ok.emit(self._cmd.video_id, new_path)
        except Exception as exc:
            self.finished_err.emit(str(exc))


class _RefreshMetadataWorker(QThread):
    progress = pyqtSignal(int, int)   # current, total
    finished_ok = pyqtSignal(int)     # count of refreshed videos
    finished_err = pyqtSignal(str)

    def __init__(
        self,
        handler: RefreshCategoryMetadataHandler,
        cmd: RefreshCategoryMetadataCommand,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._handler = handler
        self._cmd = cmd

    def run(self) -> None:
        try:
            count = self._handler.handle(
                self._cmd,
                on_progress=lambda cur, total: self.progress.emit(cur, total),
            )
            self.finished_ok.emit(count)
        except Exception as exc:
            self.finished_err.emit(str(exc))


class _RefreshVideoMetaWorker(QThread):
    """단일 영상 메타데이터를 YouTube(yt-dlp)에서 재수집한다(상세화면 ⟳)."""
    finished_ok  = pyqtSignal(object, bool)   # (video_id: UUID, updated: bool)
    finished_err = pyqtSignal(object, str)    # (video_id: UUID, error)

    def __init__(
        self,
        handler: RefreshVideoMetadataHandler,
        cmd: RefreshVideoMetadataCommand,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._handler = handler
        self._cmd = cmd

    def run(self) -> None:
        try:
            updated = self._handler.handle(self._cmd)
            self.finished_ok.emit(self._cmd.video_id, bool(updated))
        except Exception as exc:
            logger.exception("영상 메타데이터 갱신 실패: %s", self._cmd.video_id)
            self.finished_err.emit(self._cmd.video_id, str(exc))


class LibraryViewModel(QObject):
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
        # 보강은 동시 1건만 — Gemini가 브라우저를 띄우므로 병렬 실행을 막는다.
        self._enrich_workers: list[_EnrichWorker] = []
        self._pending_enrich: deque = deque()   # (video_id, url)
        self._refresh_metadata_workers: list[_RefreshMetadataWorker] = []
        self._video_meta_workers: list[_RefreshVideoMetaWorker] = []
        self._yt_import_workers: list[_ImportYTToCatWorker] = []
        self._thumb_workers: list[_RefreshThumbnailWorker] = []
        self._list_workers: list[_ListVideosWorker] = []
        self._list_gen: int = 0

        self._videos: list[VideoDTO] = []
        self._categories: list[CategoryDTO] = []
        self._tags: list[TagDTO] = []
        self._scoped_tags: list[TagDTO] = []
        self._current_page: int = 0
        self._search_text: str = ""
        self._filter_category_id: UUID | None = None
        # "로컬" 루트 뷰 — 카테고리에 속한 영상만 표시(미분류·재생목록 전용 제외). 기본 진입 뷰.
        self._filter_categorized_only: bool = True
        self._filter_tag_ids: list[UUID] = []
        self._filter_favorite_only: bool = False
        self._filter_playlist_id: UUID | None = None
        self._filter_playlist_video_ids: list[UUID] = []
        self._add_workers: list[_AddVideoWorker] = []
        self._sort_by: str = "created_at"
        self._sort_asc: bool = False
        self._min_duration_sec: int | None = None
        self._max_duration_sec: int | None = None
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

    def refresh_scoped_tags(self) -> None:
        """현재 활성 필터(카테고리 서브트리 또는 재생목록 영상)에 맞춘 인기 태그를
        집계한다. 카테고리·재생목록 모두 없으면(로컬 루트) 라이브러리 전체.

        피드/채널 등 로컬 태그가 없는 뷰에서는 패널이 이 메서드를 호출하지 않고
        인기 태그 패널 자체를 숨긴다.
        """
        category_ids = (
            self._resolve_category_ids(self._filter_category_id)
            if self._filter_category_id is not None
            else []
        )
        video_ids = list(self._filter_playlist_video_ids)
        try:
            self._scoped_tags = self._get_tags.handle(
                GetTagsQuery(category_ids=category_ids, video_ids=video_ids)
            )
        except Exception as exc:
            logger.exception("스코프 태그 집계 실패")
            self._scoped_tags = []
            self.error_occurred.emit(str(exc))
            return
        self.scoped_tags_changed.emit()

    def load(self) -> None:
        self._current_page = 0
        self._refresh_videos()
        self._refresh_categories()
        self._refresh_tags()
        self.refresh_scoped_tags()

    def load_next_page(self) -> None:
        self._current_page += 1
        self._refresh_videos(append=True)

    def set_search_text(self, text: str) -> None:
        """검색어를 적용한다. 실제로 바뀐 경우에만 재조회한다.

        IME 조합·공백 입력처럼 strip 결과가 같은 입력이 반복될 때 워커를 새로
        띄우지 않도록 막는다(호출 측은 별도로 디바운스한다).
        """
        text = text.strip()
        if text == self._search_text:
            return
        self._search_text = text
        self._current_page = 0
        self._refresh_videos()

    def set_category_filter(self, category_id: UUID | None, node_key: str | None = None) -> None:
        self._filter_category_id = category_id
        # category_id 없음("로컬"/전체) → 카테고리 영상 전체만 표시
        self._filter_categorized_only = category_id is None
        self._filter_tag_ids = []
        self._filter_playlist_id = None
        self._filter_playlist_video_ids = []
        self._current_page = 0
        if category_id is not None:
            self._refresh_videos(
                on_done=lambda: self._apply_category_order(category_id),
                node_key=node_key,
            )
        else:
            self._refresh_videos(node_key=node_key)

    def _apply_category_order(self, category_id: UUID) -> None:
        """저장된 카테고리 순서가 있으면 영상 목록을 그 순서로 재정렬한다."""
        if self._get_category_order is None or not self._videos:
            return
        try:
            ordered_ids = self._get_category_order.handle(
                GetCategoryVideoOrderQuery(category_id=category_id)
            )
            if not ordered_ids:
                return
            order_map = {vid: pos for pos, vid in enumerate(ordered_ids)}
            unordered_fallback = len(ordered_ids)
            self._videos = sorted(
                self._videos,
                key=lambda dto: order_map.get(dto.id, unordered_fallback),
            )
            self.videos_changed.emit()
        except Exception:
            logger.exception("카테고리 영상 순서 적용 실패")

    def reorder_category_videos(self, category_id: UUID, video_ids: list[UUID]) -> None:
        """카테고리 내 영상 순서를 저장하고 현재 목록에 즉시 반영한다."""
        if self._set_category_order is None:
            return
        try:
            self._set_category_order.handle(
                SetCategoryVideoOrderCommand(category_id=category_id, video_ids=video_ids)
            )
            self._apply_category_order(category_id)
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    @property
    def active_playlist_id(self) -> "UUID | None":
        return self._filter_playlist_id

    def set_playlist_filter(self, playlist_id: UUID | None, node_key: str | None = None) -> None:
        """재생목록 필터 — None이면 필터 해제.

        재생목록 영상 id 조회(GetPlaylistItemsQuery)는 _refresh_videos의 워커 스레드 안에서
        수행해 메인 스레드(클릭)를 막지 않는다.
        """
        self._filter_playlist_id = playlist_id
        self._filter_playlist_video_ids = []
        self._filter_category_id = None
        # 재생목록 뷰는 video_ids로 필터 — 카테고리 미지정 영상도 보여야 하므로 해제
        self._filter_categorized_only = False
        # 태그 필터는 비우지 않는다 — 재생목록∩태그 교집합으로 함께 적용된다.
        self._current_page = 0
        self._refresh_videos(node_key=node_key)

    def get_playlist_video_ids(self, playlist_id: UUID) -> list[UUID]:
        """재생목록에 속한 영상 ID 목록을 반환한다."""
        if self._get_playlist_items is None:
            return []
        try:
            items = self._get_playlist_items.handle(
                GetPlaylistItemsQuery(playlist_id=playlist_id, limit=500)
            )
            return [item.video_id for item in items]
        except Exception:
            logger.exception("재생목록 영상 ID 조회 실패")
            return []

    def set_tag_filter(self, tag_ids: list[UUID]) -> None:
        self._filter_tag_ids = tag_ids
        self._current_page = 0
        self._refresh_videos()

    def set_favorite_filter(self, only: bool) -> None:
        self._filter_favorite_only = only
        self._current_page = 0
        self._refresh_videos()

    def add_video(self, url: str, category_id: UUID | None = None) -> None:
        cmd = AddVideoCommand(url=url, category_id=category_id)
        worker = _AddVideoWorker(self._add_video, cmd, self)
        worker.finished_ok.connect(lambda vid: self._on_add_ok(url, vid))
        worker.finished_err.connect(lambda err: self._on_add_err(url, err))
        worker.finished.connect(lambda: self._add_workers.remove(worker))
        self._add_workers.append(worker)
        worker.start()
        self.video_add_started.emit(url)

    def get_playlist_first_item(self, playlist_id: "UUID"):
        """재생목록의 첫 번째 영상 아이템을 반환한다 (폴더 카드 썸네일용)."""
        if self._get_playlist_items is None:
            return None
        try:
            from application.library.playlist_queries import GetPlaylistItemsQuery  # noqa: PLC0415
            items = self._get_playlist_items.handle(
                GetPlaylistItemsQuery(playlist_id=playlist_id, limit=1, offset=0)
            )
            return items[0] if items else None
        except Exception:
            logger.exception("재생목록 첫 영상 조회 실패")
            return None

    def quick_search_videos(self, text: str, limit: int = 12) -> list:
        """빠른 이동(Ctrl+K)용 영상 검색 — 현재 필터를 무시하고 라이브러리 전체에서 찾는다.

        메인 스레드에서 바로 부른다: 결과 수가 작고(기본 12건) 조회가 짧아, 워커를
        띄우는 비용이 더 크다. 검색어가 없으면 최근에 보던 것부터 보여 준다.
        """
        if self._search_videos is None or self._get_videos is None:
            return []
        try:
            from application.library.queries import (  # noqa: PLC0415
                GetVideosQuery,
                SearchVideosQuery,
            )

            if text.strip():
                return self._search_videos.handle(
                    SearchVideosQuery(text=text.strip(), limit=limit, offset=0)
                )
            return self._get_videos.handle(
                GetVideosQuery(
                    limit=limit, offset=0,
                    sort_by="last_played_at", sort_asc=False, in_progress_only=True,
                )
            )
        except Exception:
            logger.exception("빠른 이동 검색 실패: %r", text)
            return []

    def save_playback_position(self, video_id: UUID, position_ms: int) -> None:
        """이어보기 위치를 기록한다(가벼운 UPDATE라 메인 스레드에서 바로 쓴다).

        재생 중 몇 초 간격으로 불리므로 워커를 새로 띄우지 않는다 — 스레드 생성 비용이
        쿼리보다 크다.
        """
        if self._update_position is None:
            return
        try:
            from application.library.commands import (  # noqa: PLC0415
                UpdatePlaybackPositionCommand,
            )

            self._update_position.handle(
                UpdatePlaybackPositionCommand(video_id=video_id, position_ms=position_ms)
            )
        except Exception:
            logger.exception("이어보기 위치 저장 실패: %s", video_id)

    def get_video_id_by_url(self, url: str) -> "UUID | None":
        """URL로 라이브러리 영상 ID를 조회한다(없으면 None)."""
        if self._get_video_id_by_url is None:
            return None
        try:
            return self._get_video_id_by_url.handle(url)
        except Exception:
            logger.exception("URL로 영상 ID 조회 실패: %s", url)
            return None

    def delete_video(self, video_id: UUID) -> None:
        try:
            self._delete_video.handle(DeleteVideoCommand(video_id))
            self._refresh_videos(bust_cache=True)
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def mark_watched(self, video_id: UUID) -> None:
        try:
            self._mark_watched.handle(MarkWatchedCommand(video_id))
            self._refresh_videos(bust_cache=True)
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def assign_category(self, video_id: UUID, category_id: UUID | None) -> None:
        try:
            self._assign_category.handle(AssignCategoryCommand(video_id, category_id))
            self._refresh_videos(bust_cache=True)
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def assign_category_bulk(self, video_ids: list[UUID], category_id: UUID | None) -> None:
        for vid_id in video_ids:
            try:
                self._assign_category.handle(AssignCategoryCommand(vid_id, category_id))
            except Exception as exc:
                self.error_occurred.emit(str(exc))
        self._refresh_videos(bust_cache=True)

    def delete_tag(self, tag_id: UUID) -> None:
        try:
            self._delete_tag.handle(DeleteTagCommand(tag_id))
            # Clear from active filter if it was being used
            if tag_id in self._filter_tag_ids:
                self._filter_tag_ids = [t for t in self._filter_tag_ids if t != tag_id]
            self._refresh_tags()
            self._refresh_videos(bust_cache=True)
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def get_video_detail(self, video_id: UUID) -> VideoDetailDTO | None:
        try:
            return self._get_video_detail.handle(video_id)
        except Exception as exc:
            self.error_occurred.emit(str(exc))
            return None

    def get_downloaded_flags(self, urls: list[str]) -> dict[str, tuple[bool, bool]]:
        """URL별 (영상 받음, 음원 받음)을 한 번의 쿼리로 조회한다(표 뷰 배지용)."""
        if self._get_downloaded_formats is None or not urls:
            return {}
        try:
            return self._get_downloaded_formats.handle(
                GetDownloadedFormatsQuery(urls=list(urls))
            )
        except Exception:
            logger.exception("다운로드 포맷 일괄 조회 실패")
            return {}

    def find_video_id_by_url(self, url: str) -> UUID | None:
        if self._get_video_id_by_url is None:
            return None
        try:
            return self._get_video_id_by_url.handle(url)
        except Exception:
            logger.exception("URL로 영상 ID 조회 실패: %s", url)
            return None

    def find_thumbnail_by_url(self, url: str) -> str | None:
        """URL로 라이브러리 영상의 로컬 썸네일 절대 경로 반환. 없으면 None."""
        try:
            vid = self.find_video_id_by_url(url)
            if vid is None:
                return None
            detail = self._get_video_detail.handle(vid)
            if not detail or not detail.thumbnail_path:
                return None
            from config.settings import THUMBNAIL_DIR  # noqa: PLC0415
            from pathlib import Path  # noqa: PLC0415
            p = Path(THUMBNAIL_DIR) / detail.thumbnail_path
            return str(p) if p.exists() else None
        except Exception:
            logger.debug("URL로 썸네일 경로 조회 실패: %s", url)
            return None

    def find_title_by_url(self, url: str) -> str | None:
        """URL로 라이브러리 영상의 제목 반환. 없으면 None."""
        try:
            vid = self.find_video_id_by_url(url)
            if vid is None:
                return None
            detail = self._get_video_detail.handle(vid)
            if not detail or not detail.title or detail.title == url:
                return None
            return detail.title
        except Exception:
            logger.debug("URL로 제목 조회 실패: %s", url)
            return None

    def get_category_videos(self, category_id: UUID, limit: int = 30) -> list:
        """카테고리 소속 영상 목록 반환 (연관 영상 구성용)."""
        try:
            return self._get_videos.handle(
                GetVideosQuery(category_id=category_id, limit=limit)
            )
        except Exception:
            logger.exception("카테고리 영상 조회 실패: %s", category_id)
            return []

    def get_videos_by_song(self, field: str, value: str, limit: int = 100) -> list:
        """같은 가수/앨범(field='artist'|'album')의 영상 목록 반환 (상세화면 필터용).

        song_info에서 매칭 video_id를 구해 기존 라이브러리 쿼리로 VideoDTO를 조회한다.
        """
        if self._find_song_videos is None:
            return []
        try:
            ids = self._find_song_videos.handle(field, value)
            if not ids:
                return []
            return self._get_videos.handle(GetVideosQuery(video_ids=ids, limit=limit))
        except Exception:
            logger.exception("같은 %s 영상 조회 실패: %s", field, value)
            return []

    def get_category_path(self, category_id: UUID) -> list[str]:
        """카테고리 계층 경로 반환 (브레드크럼용). 루트→리프 순서."""
        try:
            if not self._categories:
                self._categories = self._get_categories.handle()
            cats = {c.id: c for c in self._categories}
            path: list[str] = []
            current = category_id
            seen: set = set()
            while current and current in cats and current not in seen:
                seen.add(current)
                cat = cats[current]
                path.insert(0, cat.name)
                current = cat.parent_id
            return path
        except Exception:
            logger.debug("카테고리 경로 조회 실패: %s", category_id)

    def get_category_path_with_ids(self, category_id: UUID) -> list[tuple]:
        """카테고리 계층 경로 반환 (이름, ID) 쌍 리스트. 루트→리프 순서. 브레드크럼 클릭용."""
        try:
            if not self._categories:
                self._categories = self._get_categories.handle()
            cats = {c.id: c for c in self._categories}
            path: list[tuple] = []
            current = category_id
            seen: set = set()
            while current and current in cats and current not in seen:
                seen.add(current)
                cat = cats[current]
                path.insert(0, (cat.name, cat.id))
                current = cat.parent_id
            return path
        except Exception:
            logger.debug("카테고리 경로(ID) 조회 실패: %s", category_id)
            return []

    def create_category(self, name: str, parent_id: UUID | None = None) -> None:
        try:
            self._create_category.handle(CreateCategoryCommand(name=name, parent_id=parent_id))
            self._refresh_categories()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def rename_category(self, category_id: UUID, new_name: str) -> None:
        try:
            self._rename_category.handle(RenameCategoryCommand(category_id=category_id, new_name=new_name))
            self._refresh_categories()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def delete_category(self, category_id: UUID) -> None:
        try:
            self._delete_category.handle(DeleteCategoryCommand(category_id=category_id))
            self._refresh_categories()  # _refresh_categories()가 캐시 무효화 포함
            self._refresh_videos(bust_cache=True)
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def reparent_category(self, category_id: UUID, new_parent_id: UUID | None) -> None:
        if new_parent_id is not None:
            # Prevent circular reference (can't make a parent a child of its descendant)
            if new_parent_id in set(self._resolve_category_ids(category_id)):
                self.error_occurred.emit("상위 카테고리를 하위 카테고리의 자식으로 설정할 수 없습니다.")
                return
        try:
            self._move_category.handle(MoveCategoryCommand(category_id, new_parent_id))
            self._refresh_categories()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def _resolve_category_ids(self, cat_id: UUID) -> list[UUID]:
        """Return cat_id plus all descendant IDs via BFS.

        Uses a `seen` set to terminate safely even if the DB contains a
        circular parent→child reference (which would otherwise loop forever).
        """
        result = [cat_id]
        seen: set = {cat_id}
        queue = [cat_id]
        while queue:
            parent = queue.pop(0)
            for c in self._categories:
                if c.parent_id == parent and c.id not in seen:
                    seen.add(c.id)
                    result.append(c.id)
                    queue.append(c.id)
        return result

    def _cache_key(self) -> str:
        """현재 필터 상태를 문자열 캐시 키로 직렬화한다.

        재생목록은 video_ids가 아니라 재생목록 UUID(_filter_playlist_id)로 식별한다.
        (video_ids 조회를 워커 스레드로 옮겼기 때문에 캐시 키 계산 시점엔 아직 비어 있을 수 있음.)
        """
        cat = str(self._filter_category_id) if self._filter_category_id else ""
        tag = ",".join(sorted(str(t) for t in self._filter_tag_ids))
        pl  = str(self._filter_playlist_id) if self._filter_playlist_id else ""
        return (
            f"cat={cat}|tag={tag}|pl={pl}"
            f"|sort={self._sort_by}:{self._sort_asc}"
            f"|q={self._search_text}|fav={self._filter_favorite_only}"
            f"|cat_only={self._filter_categorized_only}"
            f"|dur={self._min_duration_sec}-{self._max_duration_sec}"
        )

    def set_sort(self, sort_by: str, sort_asc: bool) -> None:
        """정렬 기준을 변경하고 영상 목록을 갱신한다."""
        self._sort_by = sort_by
        self._sort_asc = sort_asc
        self._current_page = 0
        self._refresh_videos()

    def set_duration_filter(self, min_sec: int | None, max_sec: int | None) -> None:
        """재생시간 필터를 변경하고 영상 목록을 갱신한다."""
        self._min_duration_sec = min_sec
        self._max_duration_sec = max_sec
        self._current_page = 0
        self._refresh_videos()

    def _refresh_videos(
        self, append: bool = False, on_done=None, bust_cache: bool = False,
        node_key: str | None = None,
    ) -> None:
        """영상 목록을 백그라운드 스레드에서 비동기로 갱신한다.

        on_done: 갱신 완료 후 메인 스레드에서 호출할 콜백(선택).
        bust_cache: True이면 캐시를 무효화하고 반드시 DB를 재쿼리한다(뮤테이션 호출 시).
        node_key: 트리 노드별 스피너용 키(선택) — 워커 시작/종료 시 loading_key_changed 방출.
        세대 토큰(_list_gen)으로 연속 빠른 전환 시 오래된 결과 UI 반영을 막지만,
        완료된 결과는 항상 캐시에 저장해 나중에 동일 노드 재방문 시 즉시 로드할 수 있다.
        동시 실행 워커는 _max_workers로 제한하고 초과분은 _pending_list 큐에 보관한다.
        """
        if bust_cache:
            self._video_cache.clear()

        ck = None if append else self._cache_key()
        if ck and ck in self._video_cache:
            # 캐시 히트 — 스피너 없이 즉시 표시
            self._videos = list(self._video_cache[ck])
            self.videos_changed.emit()
            if on_done:
                on_done()
            return

        self._list_gen += 1
        gen = self._list_gen

        offset = self._current_page * DEFAULT_PAGE_SIZE
        # 필터 상태를 호출 시점에 캡처 — fetch는 워커 스레드에서 실행된다.
        search_text = self._search_text
        filter_category_id = self._filter_category_id
        filter_playlist_id = self._filter_playlist_id
        explicit_video_ids = list(self._filter_playlist_video_ids)
        tag_ids = list(self._filter_tag_ids)
        favorite_only = self._filter_favorite_only
        categorized_only_base = self._filter_categorized_only
        sort_by, sort_asc = self._sort_by, self._sort_asc
        min_dur, max_dur = self._min_duration_sec, self._max_duration_sec

        def fetch() -> list:
            category_ids: list[UUID] = (
                self._resolve_category_ids(filter_category_id)
                if filter_category_id is not None
                else []
            )
            # 재생목록 영상 id 조회를 워커 안에서 수행(메인 스레드 차단 방지)
            video_ids = explicit_video_ids
            if (
                filter_playlist_id is not None
                and not video_ids
                and self._get_playlist_items is not None
            ):
                items = self._get_playlist_items.handle(
                    GetPlaylistItemsQuery(playlist_id=filter_playlist_id, limit=500)
                )
                video_ids = [item.video_id for item in items]
            categorized_only = (
                categorized_only_base
                and filter_category_id is None
                and filter_playlist_id is None
            )
            common = dict(
                category_ids=category_ids,
                tag_ids=tag_ids,
                video_ids=video_ids,
                categorized_only=categorized_only,
                favorite_only=favorite_only,
                limit=DEFAULT_PAGE_SIZE,
                offset=offset,
                sort_by=sort_by,
                sort_asc=sort_asc,
                min_duration_sec=min_dur,
                max_duration_sec=max_dur,
            )
            if search_text:
                return self._search_videos.handle(SearchVideosQuery(text=search_text, **common))
            return self._get_videos.handle(GetVideosQuery(**common))

        self._enqueue_list(fetch, append, gen, ck, on_done, node_key)

    def _enqueue_list(self, fetch, append, gen, ck, on_done, node_key) -> None:
        """워커 슬롯이 있으면 즉시 실행, 아니면 큐에 보관(상한 32)."""
        if len(self._list_workers) < self._max_workers:
            self._run_list(fetch, append, gen, ck, on_done, node_key)
        else:
            if len(self._pending_list) >= 32:
                self._pending_list.popleft()
            self._pending_list.append((fetch, append, gen, ck, on_done, node_key))

    def _run_list(self, fetch, append, gen, ck, on_done, node_key) -> None:
        if node_key:
            self.loading_key_changed.emit(node_key, True)
        worker = _ListVideosWorker(fetch, append, self)

        def _on_ok(videos: list, app: bool) -> None:
            # 항상 캐시에 저장 — gen 불일치(구 노드 로딩)여도 결과는 보관해
            # 나중에 동일 노드 재방문 시 즉시 로드할 수 있도록 한다.
            if ck and not app:
                self._video_cache[ck] = list(videos)
                while len(self._video_cache) > _VIDEO_CACHE_MAX:
                    self._video_cache.popitem(last=False)
            if gen != self._list_gen:
                return  # UI 반영은 현재 gen만
            if app:
                self._videos.extend(videos)
            else:
                self._videos = videos
            self.videos_changed.emit()
            if on_done:
                on_done()

        worker.finished_ok.connect(_on_ok)
        worker.finished_err.connect(self.error_occurred)
        worker.finished.connect(lambda w=worker, k=node_key: self._drain_list(w, k))
        self._list_workers.append(worker)
        worker.start()

    def _drain_list(self, worker, node_key) -> None:
        if worker in self._list_workers:
            self._list_workers.remove(worker)
        if node_key:
            self.loading_key_changed.emit(node_key, False)
        while len(self._list_workers) < self._max_workers and self._pending_list:
            fetch, append, gen, ck, on_done, nk = self._pending_list.popleft()
            self._run_list(fetch, append, gen, ck, on_done, nk)

    def _refresh_categories(self) -> None:
        self._video_cache.clear()  # 카테고리 트리 변경 시 캐시 무효화
        self._categories = self._get_categories.handle()
        self.categories_changed.emit()

    def _refresh_tags(self) -> None:
        self._tags = self._get_tags.handle()
        self.tags_changed.emit()

    def save_notes(self, video_id: UUID, notes: str) -> None:
        """영상 메모 저장."""
        try:
            self._update_video.handle(UpdateVideoCommand(video_id=video_id, notes=notes))
        except Exception:
            logger.exception("메모 저장 실패: %s", video_id)

    def save_gemini_summary(self, video_id: UUID, summary: str) -> None:
        """Gemini AI 요약 저장."""
        try:
            self._update_video.handle(UpdateVideoCommand(video_id=video_id, gemini_summary=summary))
        except Exception:
            logger.exception("Gemini 요약 저장 실패: %s", video_id)

    def save_summary_status(self, video_id: UUID, status: str) -> None:
        """요약 실패 사유 저장(빈 문자열이면 삭제).

        상세 화면이 다음에 열릴 때도 "질문하기 버튼이 없어 실패" 같은 정확한 안내를
        띄우기 위한 진단 상태다. 저장 실패는 기능에 영향이 없어 로그만 남긴다.
        """
        try:
            self._update_video.handle(
                UpdateVideoCommand(video_id=video_id, summary_status=status)
            )
        except Exception:
            logger.exception("요약 상태 저장 실패: %s", video_id)

    def update_video_tags(self, video_id: UUID, tag_names: list[str]) -> None:
        """Replace the tag list for a single video (used from detail panel)."""
        try:
            self._update_video.handle(UpdateVideoCommand(video_id=video_id, tags=tag_names))
            self._refresh_tags()
            self._refresh_videos(bust_cache=True)
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def add_tags_bulk(self, video_ids: list[UUID], tag_names: list[str]) -> None:
        """Append *tag_names* to each video in *video_ids*, preserving existing tags."""
        for vid_id in video_ids:
            try:
                detail = self._get_video_detail.handle(vid_id)
                if detail is None:
                    continue
                merged = list(dict.fromkeys(list(detail.tags) + tag_names))
                self._update_video.handle(UpdateVideoCommand(video_id=vid_id, tags=merged))
            except Exception as exc:
                self.error_occurred.emit(str(exc))
        self._refresh_tags()
        self._refresh_videos(bust_cache=True)

    def refresh_category_metadata(self, category_id: UUID | None) -> None:
        if self._refresh_metadata_workers:  # already running
            return
        category_ids = (
            self._resolve_category_ids(category_id)
            if category_id is not None
            else []
        )
        cmd = RefreshCategoryMetadataCommand(category_ids=category_ids)
        worker = _RefreshMetadataWorker(self._refresh_metadata, cmd, self)
        worker.progress.connect(self.metadata_refresh_progress)
        worker.finished_ok.connect(self._on_refresh_metadata_ok)
        worker.finished_err.connect(self._on_refresh_metadata_err)
        worker.finished.connect(lambda: self._refresh_metadata_workers.remove(worker))
        self._refresh_metadata_workers.append(worker)
        worker.start()

    def _on_refresh_metadata_ok(self, count: int) -> None:
        self._refresh_videos(bust_cache=True)
        self._refresh_tags()
        self.metadata_refresh_finished.emit(count)

    def _on_refresh_metadata_err(self, err: str) -> None:
        self.error_occurred.emit(err)
        self.metadata_refresh_finished.emit(0)

    def import_youtube_to_category(
        self,
        yt_playlist_id: str,
        category_id: UUID | None,
        cookie_opts: dict,
    ) -> None:
        """YouTube 재생목록의 영상들을 지정 카테고리로 가져온다 (비동기)."""
        if self._import_yt_to_category is None:
            self.error_occurred.emit("ImportYouTubePlaylistToCategoryHandler가 초기화되지 않았습니다.")
            return
        cmd = ImportYouTubePlaylistToCategoryCommand(
            yt_playlist_id=yt_playlist_id,
            category_id=category_id,
            cookie_opts=cookie_opts,
        )
        worker = _ImportYTToCatWorker(self._import_yt_to_category, cmd, self)
        worker.progress.connect(self.yt_import_progress)
        worker.finished_ok.connect(self._on_yt_import_ok)
        worker.finished_err.connect(self._on_yt_import_err)
        worker.finished.connect(lambda: self._yt_import_workers.remove(worker))
        self._yt_import_workers.append(worker)
        worker.start()

    def _on_yt_import_ok(self, count: int) -> None:
        self._refresh_videos(bust_cache=True)
        self._refresh_categories()  # _refresh_categories()가 캐시 무효화 포함
        self._refresh_tags()
        self.yt_import_finished.emit(count)

    def _on_yt_import_err(self, err: str) -> None:
        self.error_occurred.emit(err)
        self.yt_import_finished.emit(0)

    def _on_add_ok(self, url: str, video_id: object = None) -> None:
        self._refresh_videos(bust_cache=True)
        self._refresh_tags()
        self.video_add_finished.emit(url)
        if isinstance(video_id, UUID):
            self._maybe_enrich(video_id, url)

    def _on_add_err(self, url: str, error: str) -> None:
        # Do NOT emit video_add_finished here — that signal implies success.
        # Emit a status-bar clear via a blank finished, then show the real error.
        self.video_add_finished.emit("")   # clears "영상 등록 중:" status message
        self.error_occurred.emit(error)

    # ── 등록 후 자동 보강 (요약/가사) ──────────────────────────────────
    def _maybe_enrich(self, video_id: UUID, url: str) -> None:
        """설정이 켜져 있으면 보강을 큐에 넣는다(동시 1건)."""
        if self._enrich_video is None:
            return
        try:
            import config.settings as _s  # noqa: PLC0415
            if not getattr(_s, "AUTO_ENRICH_ON_ADD", True):
                return
        except Exception:
            logger.exception("자동 보강 설정 조회 실패")
            return
        self._pending_enrich.append((video_id, url))
        self._drain_enrich()

    def _drain_enrich(self) -> None:
        """대기 중인 보강 작업을 하나 꺼내 실행한다(이미 실행 중이면 대기)."""
        if self._enrich_workers or not self._pending_enrich:
            return
        video_id, url = self._pending_enrich.popleft()
        from application.library.commands import EnrichVideoCommand  # noqa: PLC0415

        # kind는 상태바 라벨용 사전 판정 — 실제 분기는 핸들러가 결정한다.
        try:
            kind = "song" if self._enrich_video.is_song_video(video_id) else "summary"
        except Exception:
            logger.exception("보강 종류 판정 실패: %s", video_id)
            kind = "summary"

        worker = _EnrichWorker(
            self._enrich_video, EnrichVideoCommand(video_id=video_id), url, self
        )
        worker.finished_result.connect(self._on_enrich_done)
        worker.finished.connect(lambda: self._release_enrich(worker))
        self._enrich_workers.append(worker)
        worker.start()
        self.enrich_started.emit(url, kind)

    def _release_enrich(self, worker) -> None:
        if worker in self._enrich_workers:
            self._enrich_workers.remove(worker)
        self._drain_enrich()

    def _on_enrich_done(self, url: str, kind: str, ok: bool, detail: str) -> None:
        self.enrich_finished.emit(url, kind, ok, detail)

    def request_thumbnail_refresh(self, video_id: UUID, video_url: str) -> None:
        """상세화면 진입 시 1주일 경과 썸네일을 백그라운드에서 갱신한다.

        YouTube 영상이 아니거나 handler가 미설정이면 무시한다.
        """
        if self._refresh_thumbnail_handler is None:
            return
        cmd = RefreshVideoThumbnailCommand(video_id=video_id, video_url=video_url)
        worker = _RefreshThumbnailWorker(self._refresh_thumbnail_handler, cmd, self)

        def _on_ok(vid_id: object, new_path: str) -> None:
            self.thumbnail_refreshed.emit(vid_id, new_path)
            self._refresh_videos(bust_cache=True)  # 그리드 썸네일 갱신

        worker.finished_ok.connect(_on_ok)
        worker.finished_err.connect(lambda err: logger.debug("썸네일 갱신 실패(무시): %s", err))
        worker.finished.connect(lambda: self._thumb_workers.remove(worker) if worker in self._thumb_workers else None)
        self._thumb_workers.append(worker)
        worker.start()

    def refresh_video_metadata(self, video_id: UUID) -> None:
        """상세화면 ⟳ — 단일 영상 메타데이터를 YouTube에서 재수집해 DB를 갱신한다.

        네트워크 I/O이므로 백그라운드 워커에서 실행하고, 완료 시
        `video_metadata_refreshed(video_id, ok)`를 방출한다(ok=True면 갱신됨).
        handler 미설정이면 무시한다.
        """
        if self._refresh_video_meta is None:
            self.video_metadata_refreshed.emit(video_id, False)
            return
        cmd = RefreshVideoMetadataCommand(video_id=video_id)
        worker = _RefreshVideoMetaWorker(self._refresh_video_meta, cmd, self)

        def _on_ok(vid_id: object, updated: bool) -> None:
            if updated:
                self._refresh_videos(bust_cache=True)  # 그리드/목록도 갱신
            self.video_metadata_refreshed.emit(vid_id, updated)

        def _on_err(vid_id: object, err: str) -> None:
            self.error_occurred.emit(err)
            self.video_metadata_refreshed.emit(vid_id, False)

        worker.finished_ok.connect(_on_ok)
        worker.finished_err.connect(_on_err)
        worker.finished.connect(
            lambda: self._video_meta_workers.remove(worker)
            if worker in self._video_meta_workers else None
        )
        self._video_meta_workers.append(worker)
        worker.start()
