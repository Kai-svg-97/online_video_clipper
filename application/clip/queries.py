from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from application.clip.dtos import ClipDTO
from domain.clip.aggregates import ClipAggregate
from domain.clip.repositories import IClipRepository


@dataclass
class GetClipsQuery:
    source_video_id: UUID


def _to_dto(agg: ClipAggregate) -> ClipDTO:
    c = agg.clip
    return ClipDTO(
        id=agg.id,
        source_video_id=c.source_video_id,
        title=c.title,
        file_path=c.file_path,
        thumbnail_path=c.thumbnail_path,
        start_sec=c.time_range.start_sec,
        end_sec=c.time_range.end_sec,
    )


class GetClipsHandler:
    def __init__(self, repo: IClipRepository) -> None:
        self._repo = repo

    def handle(self, query: GetClipsQuery) -> list[ClipDTO]:
        return [_to_dto(agg) for agg in self._repo.list_by_video(query.source_video_id)]
