from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from uuid import UUID

from domain.library.aggregates import VideoAggregate
from domain.library.entities import Category, Tag


@dataclass
class SearchQuery:
    text: str = ""
    category_id: UUID | None = None
    tag_ids: list[UUID] = field(default_factory=list)
    favorite_only: bool = False
    watched: bool | None = None        # None = both
    limit: int = 50
    offset: int = 0


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

    # Category management
    @abstractmethod
    def list_categories(self) -> list[Category]: ...

    @abstractmethod
    def save_category(self, category: Category) -> None: ...

    @abstractmethod
    def delete_category(self, category_id: UUID) -> None: ...

    # Tag management
    @abstractmethod
    def list_tags(self) -> list[Tag]: ...

    @abstractmethod
    def save_tag(self, tag: Tag) -> None: ...

    @abstractmethod
    def get_or_create_tag(self, name: str) -> Tag: ...
