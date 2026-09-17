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


@dataclass(frozen=True)
class ChapterDTO:
    """설명에서 뽑은 챕터 한 구간 — 화면 표시와 클립 추출에 그대로 쓴다."""

    title: str
    start_sec: float
    end_sec: float

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec
