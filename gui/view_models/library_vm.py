from __future__ import annotations

from uuid import UUID

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
    MarkWatchedCommand,
    MarkWatchedHandler,
    MoveCategoryCommand,
    MoveCategoryHandler,
    RefreshCategoryMetadataCommand,
    RefreshCategoryMetadataHandler,
    RenameCategoryCommand,
    RenameCategoryHandler,
    UpdateVideoCommand,
    UpdateVideoHandler,
)
from application.library.dtos import CategoryDTO, TagDTO, VideoDTO, VideoDetailDTO
from application.library.queries import (
    GetCategoriesHandler,
    GetTagsHandler,
    GetVideoDetailHandler,
    GetVideosHandler,
    GetVideosQuery,
    SearchVideosHandler,
    SearchVideosQuery,
)
from config.settings import DEFAULT_PAGE_SIZE


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
    error_occurred = pyqtSignal(str)
    video_add_started = pyqtSignal(str)
    video_add_finished = pyqtSignal(str)
    metadata_refresh_progress = pyqtSignal(int, int)  # current, total
    metadata_refresh_finished = pyqtSignal(int)        # count refreshed

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
        self._refresh_metadata_workers: list[_RefreshMetadataWorker] = []

        self._videos: list[VideoDTO] = []
        self._categories: list[CategoryDTO] = []
        self._tags: list[TagDTO] = []
        self._current_page: int = 0
        self._search_text: str = ""
        self._filter_category_id: UUID | None = None
        self._filter_tag_ids: list[UUID] = []
        self._filter_favorite_only: bool = False
        self._add_workers: list[_AddVideoWorker] = []

    @property
    def videos(self) -> list[VideoDTO]:
        return self._videos

    @property
    def categories(self) -> list[CategoryDTO]:
        return self._categories

    @property
    def tags(self) -> list[TagDTO]:
        return self._tags

    def load(self) -> None:
        self._current_page = 0
        self._refresh_videos()
        self._refresh_categories()
        self._refresh_tags()

    def load_next_page(self) -> None:
        self._current_page += 1
        self._refresh_videos(append=True)

    def set_search_text(self, text: str) -> None:
        self._search_text = text.strip()
        self._current_page = 0
        self._refresh_videos()

    def set_category_filter(self, category_id: UUID | None) -> None:
        self._filter_category_id = category_id
        self._filter_tag_ids = []
        self._current_page = 0
        self._refresh_videos()

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

    def delete_video(self, video_id: UUID) -> None:
        try:
            self._delete_video.handle(DeleteVideoCommand(video_id))
            self._refresh_videos()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def mark_watched(self, video_id: UUID) -> None:
        try:
            self._mark_watched.handle(MarkWatchedCommand(video_id))
            self._refresh_videos()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def assign_category(self, video_id: UUID, category_id: UUID | None) -> None:
        try:
            self._assign_category.handle(AssignCategoryCommand(video_id, category_id))
            self._refresh_videos()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def assign_category_bulk(self, video_ids: list[UUID], category_id: UUID | None) -> None:
        for vid_id in video_ids:
            try:
                self._assign_category.handle(AssignCategoryCommand(vid_id, category_id))
            except Exception as exc:
                self.error_occurred.emit(str(exc))
        self._refresh_videos()

    def delete_tag(self, tag_id: UUID) -> None:
        try:
            self._delete_tag.handle(DeleteTagCommand(tag_id))
            # Clear from active filter if it was being used
            if tag_id in self._filter_tag_ids:
                self._filter_tag_ids = [t for t in self._filter_tag_ids if t != tag_id]
            self._refresh_tags()
            self._refresh_videos()
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
            self._refresh_categories()
            self._refresh_videos()
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

    def _refresh_videos(self, append: bool = False) -> None:
        offset = self._current_page * DEFAULT_PAGE_SIZE
        category_ids: list[UUID] = (
            self._resolve_category_ids(self._filter_category_id)
            if self._filter_category_id is not None
            else []
        )
        try:
            if self._search_text:
                results = self._search_videos.handle(
                    SearchVideosQuery(
                        text=self._search_text,
                        category_ids=category_ids,
                        tag_ids=self._filter_tag_ids,
                        favorite_only=self._filter_favorite_only,
                        limit=DEFAULT_PAGE_SIZE,
                        offset=offset,
                    )
                )
            else:
                results = self._get_videos.handle(
                    GetVideosQuery(
                        category_ids=category_ids,
                        tag_ids=self._filter_tag_ids,
                        favorite_only=self._filter_favorite_only,
                        limit=DEFAULT_PAGE_SIZE,
                        offset=offset,
                    )
                )
            if append:
                self._videos.extend(results)
            else:
                self._videos = results
            self.videos_changed.emit()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def _refresh_categories(self) -> None:
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
            self._refresh_videos()
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
        self._refresh_videos()

    def refresh_category_metadata(self, category_id: UUID | None) -> None:
        category_ids = (
            self._resolve_category_ids(category_id)
            if category_id is not None
            else []
        )
        cmd = RefreshCategoryMetadataCommand(category_ids=category_ids)
        worker = _RefreshMetadataWorker(self._refresh_metadata, cmd, self)
        worker.progress.connect(self.metadata_refresh_progress)
        worker.finished_ok.connect(self._on_refresh_metadata_ok)
        worker.finished_err.connect(lambda err: self.error_occurred.emit(err))
        worker.finished.connect(lambda: self._refresh_metadata_workers.remove(worker))
        self._refresh_metadata_workers.append(worker)
        worker.start()

    def _on_refresh_metadata_ok(self, count: int) -> None:
        self._refresh_videos()
        self._refresh_tags()
        self.metadata_refresh_finished.emit(count)

    def _on_add_ok(self, url: str) -> None:
        self._refresh_videos()
        self._refresh_tags()
        self.video_add_finished.emit(url)

    def _on_add_err(self, url: str, error: str) -> None:
        # Do NOT emit video_add_finished here — that signal implies success.
        # Emit a status-bar clear via a blank finished, then show the real error.
        self.video_add_finished.emit("")   # clears "영상 등록 중:" status message
        self.error_occurred.emit(error)
