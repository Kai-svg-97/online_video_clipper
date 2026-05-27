from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ClipDTO:
    id: UUID
    source_video_id: UUID
    title: str
    file_path: str
    thumbnail_path: str
    start_sec: float
    end_sec: float
