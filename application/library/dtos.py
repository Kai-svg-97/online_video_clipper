from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True)
class CategoryDTO:
    id: UUID
    name: str
    parent_id: UUID | None = None


@dataclass(frozen=True)
class TagDTO:
    id: UUID
    name: str
    count: int = 0


@dataclass(frozen=True)
class VideoDTO:
    id: UUID
    url: str
    title: str
    channel_name: str
    thumbnail_path: str
    duration_sec: int | None
    favorite: bool
    watched: bool
    category_id: UUID | None
    category_name: str = ""
    published_at: str | None = None
    view_count: int | None = None
    tag_names: tuple[str, ...] = ()
    created_at: str | None = None


@dataclass(frozen=True)
class DownloadInfoDTO:
    quality: str
    fmt: str
    file_path: str
    file_size_bytes: int | None


@dataclass(frozen=True)
class CategoryStatDTO:
    name: str
    count: int


@dataclass(frozen=True)
class LibraryStatsDTO:
    total_videos: int
    total_duration_sec: int
    watched_count: int
    favorite_count: int
    category_stats: list[CategoryStatDTO]
    total_downloads: int
    total_download_bytes: int


@dataclass(frozen=True)
class VideoDetailDTO:
    id: UUID
    url: str
    title: str
    channel_name: str
    channel_url: str
    thumbnail_path: str
    duration_sec: int | None
    published_at: str | None        # ISO date string, e.g. "2024-03-15"
    view_count: int | None
    favorite: bool
    watched: bool
    category_id: UUID | None
    notes: str
    description: str
    tags: list[str] = field(default_factory=list)
    downloads: list[DownloadInfoDTO] = field(default_factory=list)
