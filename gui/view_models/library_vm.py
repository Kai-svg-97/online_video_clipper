from __future__ import annotations

from uuid import UUID

from PyQt6.QtCore import QObject, pyqtSignal

from application.library.commands import (
    AddVideoCommand,
    AddVideoHandler,
    DeleteVideoCommand,
    DeleteVideoHandler,
    MarkWatchedCommand,
    MarkWatchedHandler,
    UpdateVideoCommand,
    UpdateVideoHandler,
)
from application.library.queries import (
    GetCategoriesHandler,
    GetTagsHandler,
    GetVideosHandler,
    GetVideosQuery,
    SearchVideosHandler,
    SearchVideosQuery,
)
from config.settings import DEFAULT_PAGE_SIZE
from domain.library.aggregates import VideoAggregate
from domain.library.entities import Category, Tag


class LibraryViewModel(QObject):
    """Bridges the Library Application layer with the GUI.

    All handlers are called from the GUI thread; network-heavy operations
    (fetch_metadata) must be delegated to a QThread before calling the handler.
    """

    videos_changed = pyqtSignal()
    categories_changed = pyqtSignal()
    tags_changed = pyqtSignal()
    error_occurred = pyqtSignal(str)

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

        self._videos: list[VideoAggregate] = []
        self._categories: list[Category] = []
        self._tags: list[Tag] = []
        self._current_page: int = 0
        self._search_text: str = ""
        self._filter_category_id: UUID | None = None
        self._filter_tag_ids: list[UUID] = []
        self._filter_favorite_only: bool = False

    # ------------------------------------------------------------------
    # Public state accessors
    # ------------------------------------------------------------------

    @property
    def videos(self) -> list[VideoAggregate]:
        return self._videos

    @property
    def categories(self) -> list[Category]:
        return self._categories

    @property
    def tags(self) -> list[Tag]:
        return self._tags

    # ------------------------------------------------------------------
    # Commands (called from GUI thread)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Internal refresh helpers
    # ------------------------------------------------------------------

    def _refresh_videos(self, append: bool = False) -> None:
        offset = self._current_page * DEFAULT_PAGE_SIZE
        try:
            if self._search_text:
                results = self._search_videos.handle(
                    SearchVideosQuery(
                        text=self._search_text,
                        category_id=self._filter_category_id,
                        tag_ids=self._filter_tag_ids,
                        favorite_only=self._filter_favorite_only,
                        limit=DEFAULT_PAGE_SIZE,
                        offset=offset,
                    )
                )
            else:
                results = self._get_videos.handle(
                    GetVideosQuery(
                        category_id=self._filter_category_id,
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
