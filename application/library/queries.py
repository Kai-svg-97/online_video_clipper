from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from domain.library.aggregates import VideoAggregate
from domain.library.entities import Category, Tag
from domain.library.repositories import IVideoRepository, SearchQuery


@dataclass
class GetVideosQuery:
    category_id: UUID | None = None
    tag_ids: list[UUID] = field(default_factory=list)
    favorite_only: bool = False
    watched: bool | None = None
    limit: int = 50
    offset: int = 0


@dataclass
class SearchVideosQuery:
    text: str
    category_id: UUID | None = None
    tag_ids: list[UUID] = field(default_factory=list)
    favorite_only: bool = False
    limit: int = 50
    offset: int = 0


@dataclass
class GetVideoByIdQuery:
    video_id: UUID


# ------------------------------------------------------------------
# Handlers
# ------------------------------------------------------------------

class GetVideosHandler:
    def __init__(self, repo: IVideoRepository) -> None:
        self._repo = repo

    def handle(self, query: GetVideosQuery) -> list[VideoAggregate]:
        return self._repo.search(
            SearchQuery(
                category_id=query.category_id,
                tag_ids=query.tag_ids,
                favorite_only=query.favorite_only,
                watched=query.watched,
                limit=query.limit,
                offset=query.offset,
            )
        )


class SearchVideosHandler:
    def __init__(self, repo: IVideoRepository) -> None:
        self._repo = repo

    def handle(self, query: SearchVideosQuery) -> list[VideoAggregate]:
        return self._repo.search(
            SearchQuery(
                text=query.text,
                category_id=query.category_id,
                tag_ids=query.tag_ids,
                favorite_only=query.favorite_only,
                limit=query.limit,
                offset=query.offset,
            )
        )


class GetVideoByIdHandler:
    def __init__(self, repo: IVideoRepository) -> None:
        self._repo = repo

    def handle(self, query: GetVideoByIdQuery) -> VideoAggregate | None:
        return self._repo.get_by_id(query.video_id)


class GetCategoriesHandler:
    def __init__(self, repo: IVideoRepository) -> None:
        self._repo = repo

    def handle(self) -> list[Category]:
        return self._repo.list_categories()


class GetTagsHandler:
    def __init__(self, repo: IVideoRepository) -> None:
        self._repo = repo

    def handle(self) -> list[Tag]:
        return self._repo.list_tags()
