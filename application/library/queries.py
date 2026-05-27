from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from application.library.dtos import (
    CategoryDTO,
    DownloadInfoDTO,
    TagDTO,
    VideoDTO,
    VideoDetailDTO,
)
from domain.download.repositories import IDownloadRepository
from domain.library.aggregates import VideoAggregate
from domain.library.repositories import IVideoRepository, SearchQuery


@dataclass
class GetVideosQuery:
    category_id: UUID | None = None
    category_ids: list[UUID] = field(default_factory=list)
    tag_ids: list[UUID] = field(default_factory=list)
    favorite_only: bool = False
    watched: bool | None = None
    limit: int = 50
    offset: int = 0


@dataclass
class SearchVideosQuery:
    text: str
    category_id: UUID | None = None
    category_ids: list[UUID] = field(default_factory=list)
    tag_ids: list[UUID] = field(default_factory=list)
    favorite_only: bool = False
    limit: int = 50
    offset: int = 0


@dataclass
class GetVideoByIdQuery:
    video_id: UUID


def _to_dto(agg: VideoAggregate, cats: dict | None = None) -> VideoDTO:
    v = agg.video
    cat_name = ""
    if cats and agg.category_id:
        cat_name = cats.get(agg.category_id, "")
    published = v.published_at.strftime("%Y-%m-%d") if v.published_at else None
    return VideoDTO(
        id=agg.id,
        url=v.url.value,
        title=v.title,
        channel_name=v.channel.name if v.channel else "",
        thumbnail_path=v.thumbnail_path,
        duration_sec=v.duration.seconds if v.duration else None,
        favorite=v.favorite,
        watched=v.watched,
        category_id=agg.category_id,
        category_name=cat_name,
        published_at=published,
        view_count=v.view_count,
    )


def _cats_dict(repo: IVideoRepository) -> dict:
    return {c.id: c.name for c in repo.list_categories()}


class GetVideosHandler:
    def __init__(self, repo: IVideoRepository) -> None:
        self._repo = repo

    def handle(self, query: GetVideosQuery) -> list[VideoDTO]:
        cats = _cats_dict(self._repo)
        return [
            _to_dto(agg, cats)
            for agg in self._repo.search(
                SearchQuery(
                    category_id=query.category_id,
                    category_ids=query.category_ids,
                    tag_ids=query.tag_ids,
                    favorite_only=query.favorite_only,
                    watched=query.watched,
                    limit=query.limit,
                    offset=query.offset,
                )
            )
        ]


class SearchVideosHandler:
    def __init__(self, repo: IVideoRepository) -> None:
        self._repo = repo

    def handle(self, query: SearchVideosQuery) -> list[VideoDTO]:
        cats = _cats_dict(self._repo)
        return [
            _to_dto(agg, cats)
            for agg in self._repo.search(
                SearchQuery(
                    text=query.text,
                    category_id=query.category_id,
                    category_ids=query.category_ids,
                    tag_ids=query.tag_ids,
                    favorite_only=query.favorite_only,
                    limit=query.limit,
                    offset=query.offset,
                )
            )
        ]


class GetVideoByIdHandler:
    def __init__(self, repo: IVideoRepository) -> None:
        self._repo = repo

    def handle(self, query: GetVideoByIdQuery) -> VideoDTO | None:
        agg = self._repo.get_by_id(query.video_id)
        if agg is None:
            return None
        cats = _cats_dict(self._repo)
        return _to_dto(agg, cats)


class GetVideoDetailHandler:
    """Returns rich VideoDetailDTO including description, tags, and download history."""

    def __init__(self, video_repo: IVideoRepository, dl_repo: IDownloadRepository) -> None:
        self._video_repo = video_repo
        self._dl_repo = dl_repo

    def handle(self, video_id: UUID) -> VideoDetailDTO | None:
        agg = self._video_repo.get_by_id(video_id)
        if agg is None:
            return None
        v = agg.video

        # Resolve tag names
        all_tags = {t.id: t for t in self._video_repo.list_tags()}
        tag_names = [all_tags[tid].name for tid in agg.tag_ids if tid in all_tags]

        # Download history for this URL
        completed = self._dl_repo.find_completed_by_url(v.url.value)
        downloads = []
        for j in completed:
            fp = Path(j.file_path) if j.file_path else None
            size = fp.stat().st_size if fp and fp.exists() else None
            downloads.append(DownloadInfoDTO(
                quality=j.settings.quality.value,
                fmt=j.settings.format.value,
                file_path=j.file_path,
                file_size_bytes=size,
            ))

        published = v.published_at.strftime("%Y-%m-%d") if v.published_at else None

        return VideoDetailDTO(
            id=agg.id,
            url=v.url.value,
            title=v.title,
            channel_name=v.channel.name if v.channel else "",
            channel_url=v.channel.url if v.channel else "",
            thumbnail_path=v.thumbnail_path,
            duration_sec=v.duration.seconds if v.duration else None,
            published_at=published,
            view_count=v.view_count,
            favorite=v.favorite,
            watched=v.watched,
            category_id=agg.category_id,
            notes=v.notes,
            description=v.description,
            tags=tag_names,
            downloads=downloads,
        )


class GetCategoriesHandler:
    def __init__(self, repo: IVideoRepository) -> None:
        self._repo = repo

    def handle(self) -> list[CategoryDTO]:
        return [
            CategoryDTO(id=c.id, name=c.name, parent_id=c.parent_id)
            for c in self._repo.list_categories()
        ]


class GetTagsHandler:
    def __init__(self, repo: IVideoRepository) -> None:
        self._repo = repo

    def handle(self) -> list[TagDTO]:
        return [TagDTO(id=t.id, name=t.name, count=c) for t, c in self._repo.list_tags_with_counts()]
