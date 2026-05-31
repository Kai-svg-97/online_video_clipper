from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from uuid import UUID

from domain.library.aggregates import VideoAggregate
from domain.library.entities import Category, Playlist, PlaylistFolder, Tag


_ALLOWED_SORT_COLUMNS = frozenset({"created_at", "title", "channel_name", "duration_sec"})


@dataclass
class SearchQuery:
    text: str = ""
    category_id: UUID | None = None
    category_ids: list[UUID] = field(default_factory=list)
    tag_ids: list[UUID] = field(default_factory=list)
    video_ids: list[UUID] = field(default_factory=list)  # 재생목록 필터 — 빈 리스트 = 필터 없음
    favorite_only: bool = False
    watched: bool | None = None        # None = both
    limit: int = 50
    offset: int = 0
    sort_by: str = "created_at"        # created_at | title | channel_name | duration_sec
    sort_asc: bool = False
    min_duration_sec: int | None = None
    max_duration_sec: int | None = None


class IVideoRepository(ABC):
    @abstractmethod
    def save(self, aggregate: VideoAggregate) -> None: ...

    @abstractmethod
    def get_by_id(self, video_id: UUID) -> VideoAggregate | None: ...

    @abstractmethod
    def search(self, query: SearchQuery) -> list[VideoAggregate]: ...

    @abstractmethod
    def count(self, query: SearchQuery) -> int: ...

    @abstractmethod
    def delete(self, video_id: UUID) -> None: ...

    @abstractmethod
    def exists_by_url(self, url: str) -> bool: ...

    @abstractmethod
    def get_by_url(self, url: str) -> VideoAggregate | None: ...

    # Category management
    @abstractmethod
    def list_categories(self) -> list[Category]: ...

    @abstractmethod
    def list_category_video_counts(self) -> dict[UUID, int]: ...

    @abstractmethod
    def save_category(self, category: Category) -> None: ...

    @abstractmethod
    def delete_category(self, category_id: UUID) -> None: ...

    # Tag management
    @abstractmethod
    def list_tags(self) -> list[Tag]: ...

    @abstractmethod
    def list_tags_with_counts(self) -> list[tuple[Tag, int]]: ...

    @abstractmethod
    def save_tag(self, tag: Tag) -> None: ...

    @abstractmethod
    def get_or_create_tag(self, name: str) -> Tag: ...

    @abstractmethod
    def delete_tag(self, tag_id: UUID) -> None: ...

    @abstractmethod
    def delete_zero_count_tags(self) -> int:
        """Delete tags not linked to any video. Returns count of deleted tags."""
        ...

    # Category video order
    @abstractmethod
    def get_category_video_order(self, category_id: UUID) -> list[UUID]:
        """카테고리 내 수동 영상 순서를 반환한다. 없으면 빈 리스트."""
        ...

    @abstractmethod
    def set_category_video_order(self, category_id: UUID, video_ids: list[UUID]) -> None:
        """카테고리 내 영상 순서를 전체 교체 저장한다."""
        ...


class IPlaylistRepository(ABC):
    @abstractmethod
    def save(self, playlist: Playlist) -> None: ...

    @abstractmethod
    def get_by_id(self, playlist_id: UUID) -> Playlist | None: ...

    @abstractmethod
    def list_all(self) -> list[Playlist]: ...

    @abstractmethod
    def delete(self, playlist_id: UUID) -> None: ...

    @abstractmethod
    def get_by_yt_id(self, yt_playlist_id: str) -> Playlist | None: ...

    @abstractmethod
    def get_items(self, playlist_id: UUID) -> list[tuple[UUID, int]]:
        """(video_id, position) 쌍 목록 반환 (position 오름차순)."""
        ...

    @abstractmethod
    def set_items(self, playlist_id: UUID, video_ids: list[UUID]) -> None:
        """전체 순서를 원자적으로 교체 (DELETE + INSERT). item_count도 갱신."""
        ...

    @abstractmethod
    def add_video(
        self,
        playlist_id: UUID,
        video_id: UUID,
        position: int | None = None,
    ) -> None:
        """재생목록에 영상 추가. position=None이면 맨 끝에 추가."""
        ...

    @abstractmethod
    def remove_video(self, playlist_id: UUID, video_id: UUID) -> None: ...

    @abstractmethod
    def update_folder(self, playlist_id: UUID, folder_id: UUID | None) -> None:
        """재생목록의 소속 폴더를 변경한다."""
        ...

    @abstractmethod
    def get_yt_item_id(self, playlist_id: UUID, video_id: UUID) -> str | None:
        """playlist_items.yt_item_id 조회 (YouTube API 삭제 시 사용)."""
        ...

    @abstractmethod
    def set_yt_item_id(self, playlist_id: UUID, video_id: UUID, yt_item_id: str) -> None:
        """playlist_items.yt_item_id 저장."""
        ...


class IPlaylistFolderRepository(ABC):
    @abstractmethod
    def save(self, folder: PlaylistFolder) -> None: ...

    @abstractmethod
    def get_by_id(self, folder_id: UUID) -> PlaylistFolder | None: ...

    @abstractmethod
    def list_by_source(self, source: str | None = None) -> list[PlaylistFolder]:
        """source=None이면 전체 반환."""
        ...

    @abstractmethod
    def delete(self, folder_id: UUID) -> None: ...
