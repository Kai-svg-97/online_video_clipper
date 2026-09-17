"""자막 색인 조회 유스케이스 — 상세화면 자막 탭이 쓴다."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from domain.library.subtitle_repository import ISubtitleRepository


@dataclass(frozen=True)
class SubtitleLineDTO:
    start_ms: int
    end_ms: int
    text: str


@dataclass(frozen=True)
class SubtitleIndexDTO:
    lang: str
    label: str
    line_count: int


@dataclass
class GetSubtitleLinesQuery:
    video_id: UUID
    lang: str | None = None
    text: str = ""          # 비어 있으면 전체, 있으면 그 말이 든 줄만


class GetSubtitleLinesHandler:
    def __init__(self, repo: ISubtitleRepository) -> None:
        self._repo = repo

    def handle(self, query: GetSubtitleLinesQuery) -> list[SubtitleLineDTO]:
        if query.text:
            lines = self._repo.search_lines(query.video_id, query.text)
        else:
            lines = self._repo.list_lines(query.video_id, query.lang)
        return [SubtitleLineDTO(ln.start_ms, ln.end_ms, ln.text) for ln in lines]


@dataclass
class GetSubtitleIndexesQuery:
    video_id: UUID


class GetSubtitleIndexesHandler:
    """색인된 언어 목록 — 자막 탭이 "가져오기"를 보여줄지 목록을 보여줄지 정한다."""

    def __init__(self, repo: ISubtitleRepository) -> None:
        self._repo = repo

    def handle(self, query: GetSubtitleIndexesQuery) -> list[SubtitleIndexDTO]:
        return [
            SubtitleIndexDTO(i.lang, i.label, i.line_count)
            for i in self._repo.list_indexes(query.video_id)
        ]
