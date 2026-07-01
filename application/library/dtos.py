from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class CategoryDTO:
    id: UUID
    name: str
    parent_id: UUID | None = None
    video_count: int = 0


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
class PlaylistFolderDTO:
    id: UUID
    name: str
    source: str    # "local" | "youtube"


@dataclass(frozen=True)
class PlaylistDTO:
    id: UUID
    title: str
    yt_playlist_id: str | None
    source: str       # "local" | "youtube"
    item_count: int
    folder_id: UUID | None = None
    updated_at: str | None = None   # ISO 8601 문자열


@dataclass(frozen=True)
class PlaylistItemDTO:
    playlist_id: UUID
    video_id: UUID
    position: int
    video_title: str = ""
    thumbnail_path: str = ""
    channel_name: str = ""
    duration_sec: int | None = None


@dataclass(frozen=True)
class FeedVideoDTO:
    url: str
    title: str
    channel_name: str
    channel_id: str
    thumbnail_url: str     # 원격 URL (미캐시)
    thumbnail_path: str    # 로컬 캐시 경로 ("" if not cached)
    published_at: str
    view_count: int | None
    duration_sec: int | None
    in_library: bool       # 이미 라이브러리에 등록된 영상이면 True
    yt_video_id: str = ""  # YouTube 영상 ID (썸네일 URL 생성용)


@dataclass(frozen=True)
class ChannelInfoDTO:
    """구독 채널 카드용 — 아바타 + 구독자수 + 영상수."""
    channel_id: str
    channel_name: str
    channel_url: str
    thumbnail_url: str           # 채널 아바타 원격 URL ("" if 없음)
    subscriber_count: int | None
    video_count: int | None
    latest_video_published_at: str | None = None  # 최신 업로드 영상 게시 시각(ISO)


@dataclass(frozen=True)
class FailedDownloadInfoDTO:
    error_msg: str
    created_at: datetime | None = None


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
    failed_downloads: list[FailedDownloadInfoDTO] = field(default_factory=list)
    gemini_summary: str = ""
