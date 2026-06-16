from __future__ import annotations

import logging
from collections import OrderedDict
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
    GetTagsHandler,
    GetTagsQuery,
    GetVideoDetailHandler,
    GetVideosHandler,
    GetVideosQuery,
    SearchVideosHandler,
    SearchVideosQuery,
)
from config.settings import DEFAULT_PAGE_SIZE

logger = logging.getLogger(__name__)


class _AddVideoWorker(QThread):
    finished_ok = pyqtSignal()
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
            self._handler.handle(self._cmd)
            self.finished_ok.emit()
        except Exception as exc:
            self.finished_err.emit(str(exc))


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
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
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
        self._refresh_metadata_workers: list[_RefreshMetadataWorker] = []
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

    def shutdown(self) -> None:
        """앱 종료 시 호출 — 실행 중인 백그라운드 워커(메타데이터 갱신·YouTube
        가져오기·영상 추가)를 정리해 죽은 객체로의 시그널 방출을 막는다.

        finished 시그널이 리스트를 변형하므로 사본을 순회한다.
        """
        for worker in [
            *self._refresh_metadata_workers,
            *self._yt_import_workers,
            *self._add_workers,
            *self._thumb_workers,
            *self._list_workers,
        ]:
            if worker.isRunning():
                worker.terminate()
                worker.wait(3000)
        self._refresh_metadata_workers.clear()
        self._yt_import_workers.clear()
        self._add_workers.clear()
        self._thumb_workers.clear()
        self._list_workers.clear()

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
        self._search_text = text.strip()
        self._current_page = 0
        self._refresh_videos()

    def set_category_filter(self, category_id: UUID | None) -> None:
        self._filter_category_id = category_id
        # category_id 없음("로컬"/전체) → 카테고리 영상 전체만 표시
        self._filter_categorized_only = category_id is None
        self._filter_tag_ids = []
        self._filter_playlist_id = None
        self._filter_playlist_video_ids = []
        self._current_page = 0
        if category_id is not None:
            self._refresh_videos(on_done=lambda: self._apply_category_order(category_id))
        else:
            self._refresh_videos()

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

    def set_playlist_filter(self, playlist_id: UUID | None) -> None:
        """재생목록 필터 — None이면 필터 해제."""
        self._filter_playlist_id = playlist_id
        self._filter_playlist_video_ids = []
        self._filter_category_id = None
        # 재생목록 뷰는 video_ids로 필터 — 카테고리 미지정 영상도 보여야 하므로 해제
        self._filter_categorized_only = False
        # 태그 필터는 비우지 않는다 — 재생목록∩태그 교집합으로 함께 적용된다.
        self._current_page = 0
        if playlist_id is not None and self._get_playlist_items is not None:
            try:
                items = self._get_playlist_items.handle(
                    GetPlaylistItemsQuery(playlist_id=playlist_id, limit=500)
                )
                self._filter_playlist_video_ids = [item.video_id for item in items]
            except Exception as exc:
                self.error_occurred.emit(str(exc))
        self._refresh_videos()

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
        worker.finished_ok.connect(lambda: self._on_add_ok(url))
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
        """현재 필터 상태를 문자열 캐시 키로 직렬화한다."""
        cat = str(self._filter_category_id) if self._filter_category_id else ""
        tag = ",".join(sorted(str(t) for t in self._filter_tag_ids))
        pl  = ",".join(sorted(str(v) for v in self._filter_playlist_video_ids))
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
        self, append: bool = False, on_done=None, bust_cache: bool = False
    ) -> None:
        """영상 목록을 백그라운드 스레드에서 비동기로 갱신한다.

        on_done: 갱신 완료 후 메인 스레드에서 호출할 콜백(선택).
        bust_cache: True이면 캐시를 무효화하고 반드시 DB를 재쿼리한다(뮤테이션 호출 시).
        세대 토큰(_list_gen)으로 연속 빠른 전환 시 오래된 결과 UI 반영을 막지만,
        완료된 결과는 항상 캐시에 저장해 나중에 동일 노드 재방문 시 즉시 로드할 수 있다.
        """
        if bust_cache:
            self._video_cache.clear()

        ck = None if append else self._cache_key()
        if ck and ck in self._video_cache:
            self._videos = list(self._video_cache[ck])
            self.videos_changed.emit()
            if on_done:
                on_done()
            return

        self._list_gen += 1
        gen = self._list_gen

        offset = self._current_page * DEFAULT_PAGE_SIZE
        category_ids: list[UUID] = (
            self._resolve_category_ids(self._filter_category_id)
            if self._filter_category_id is not None
            else []
        )
        categorized_only = (
            self._filter_categorized_only
            and self._filter_category_id is None
            and not self._filter_playlist_video_ids
        )

        if self._search_text:
            query = SearchVideosQuery(
                text=self._search_text,
                category_ids=category_ids,
                tag_ids=self._filter_tag_ids,
                video_ids=self._filter_playlist_video_ids,
                categorized_only=categorized_only,
                favorite_only=self._filter_favorite_only,
                limit=DEFAULT_PAGE_SIZE,
                offset=offset,
                sort_by=self._sort_by,
                sort_asc=self._sort_asc,
                min_duration_sec=self._min_duration_sec,
                max_duration_sec=self._max_duration_sec,
            )
            fetch = lambda: self._search_videos.handle(query)
        else:
            query = GetVideosQuery(
                category_ids=category_ids,
                tag_ids=self._filter_tag_ids,
                video_ids=self._filter_playlist_video_ids,
                categorized_only=categorized_only,
                favorite_only=self._filter_favorite_only,
                limit=DEFAULT_PAGE_SIZE,
                offset=offset,
                sort_by=self._sort_by,
                sort_asc=self._sort_asc,
                min_duration_sec=self._min_duration_sec,
                max_duration_sec=self._max_duration_sec,
            )
            fetch = lambda: self._get_videos.handle(query)

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
        worker.finished.connect(lambda: self._list_workers.remove(worker) if worker in self._list_workers else None)
        self._list_workers.append(worker)
        worker.start()

    def _refresh_categories(self) -> None:
        self._video_cache.clear()  # 카테고리 트리 변경 시 캐시 무효화
        self._categories = self._get_categories.handle()
        self.categories_changed.emit()

    def _refresh_tags(self) -> None:
        self._tags = self._get_tags.handle()
        self.tags_changed.emit()

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

    def _on_add_ok(self, url: str) -> None:
        self._refresh_videos(bust_cache=True)
        self._refresh_tags()
        self.video_add_finished.emit(url)

    def _on_add_err(self, url: str, error: str) -> None:
        # Do NOT emit video_add_finished here — that signal implies success.
        # Emit a status-bar clear via a blank finished, then show the real error.
        self.video_add_finished.emit("")   # clears "영상 등록 중:" status message
        self.error_occurred.emit(error)

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
