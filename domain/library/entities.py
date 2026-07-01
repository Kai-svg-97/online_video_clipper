from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4

from domain.library.value_objects import ChannelInfo, Duration, VideoUrl


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Video:
    id: UUID
    url: VideoUrl
    title: str
    channel: ChannelInfo | None
    duration: Duration | None
    published_at: datetime | None
    view_count: int | None
    favorite: bool
    watched: bool
    notes: str
    thumbnail_path: str       # relative path under THUMBNAIL_DIR; "" if not cached
    created_at: datetime
    updated_at: datetime
    # description is loaded on demand (GetVideoByIdQuery), not stored here
    description: str = field(default="", repr=False)
    gemini_summary: str = field(default="", repr=False)

    @classmethod
    def create(
        cls,
        url: VideoUrl,
        title: str,
        *,
        channel: ChannelInfo | None = None,
        duration: Duration | None = None,
        published_at: datetime | None = None,
        view_count: int | None = None,
        favorite: bool = False,
    ) -> Video:
        now = _now()
        return cls(
            id=uuid4(),
            url=url,
            title=title,
            channel=channel,
            duration=duration,
            published_at=published_at,
            view_count=view_count,
            favorite=favorite,
            watched=False,
            notes="",
            thumbnail_path="",
            created_at=now,
            updated_at=now,
        )


@dataclass
class Category:
    id: UUID
    name: str
    parent_id: UUID | None   # None = root category

    @classmethod
    def create(cls, name: str, parent_id: UUID | None = None) -> Category:
        return cls(id=uuid4(), name=name, parent_id=parent_id)


@dataclass
class Tag:
    id: UUID
    name: str

    @classmethod
    def create(cls, name: str) -> Tag:
        return cls(id=uuid4(), name=name.lower().strip())


@dataclass
class PlaylistFolder:
    """재생목록 폴더 (앱 내 조직 구조 — YouTube에는 반영되지 않음)."""
    id: UUID
    name: str
    source: str    # "local" | "youtube"
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(cls, name: str, source: str = "local") -> "PlaylistFolder":
        now = _now()
        return cls(id=uuid4(), name=name, source=source, created_at=now, updated_at=now)


@dataclass
class Playlist:
    id: UUID
    title: str
    yt_playlist_id: str | None   # None = 로컬 전용, "PLxxxxxxx" = YouTube 연동
    source: str                   # "local" | "youtube"
    item_count: int
    created_at: datetime
    updated_at: datetime
    folder_id: UUID | None = None  # 속한 폴더 (없으면 미분류)

    @classmethod
    def create(
        cls,
        title: str,
        yt_playlist_id: str | None = None,
        source: str = "local",
        folder_id: UUID | None = None,
    ) -> "Playlist":
        now = _now()
        return cls(
            id=uuid4(),
            title=title,
            yt_playlist_id=yt_playlist_id,
            source=source,
            item_count=0,
            created_at=now,
            updated_at=now,
            folder_id=folder_id,
        )
