from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from domain.clip.aggregates import ClipAggregate
from domain.clip.repositories import IClipRepository


@dataclass
class GetClipsQuery:
    source_video_id: UUID


class GetClipsHandler:
    def __init__(self, repo: IClipRepository) -> None:
        self._repo = repo

    def handle(self, query: GetClipsQuery) -> list[ClipAggregate]:
        return self._repo.list_by_video(query.source_video_id)
