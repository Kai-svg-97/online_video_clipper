"""자막 색인 조회 유스케이스 — 상세화면 자막 탭이 쓴다."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from domain.library.repositories import SearchQuery
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


@dataclass(frozen=True)
class SubtitleCoverageDTO:
    """라이브러리 전체의 자막 색인 현황 — 설정 화면이 한 줄로 보여준다."""

    indexed_videos: int
    total_videos: int

    @property
    def remaining(self) -> int:
        return max(0, self.total_videos - self.indexed_videos)


class GetSubtitleCoverageHandler:
    """몇 개 영상에 자막이 색인돼 있는지.

    전체 영상 수는 저장소가 세고, 색인 수는 자막 저장소가 센다 — 둘 다 개수만
    읽으므로 라이브러리가 커도 가볍다(영상을 메모리에 올리지 않는다).
    """

    def __init__(self, video_repo, subtitle_repo: ISubtitleRepository) -> None:
        self._videos = video_repo
        self._subtitles = subtitle_repo

    def handle(self, _query=None) -> SubtitleCoverageDTO:
        try:
            indexed = len(self._subtitles.indexed_video_ids())
        except Exception:
            indexed = 0
        try:
            total = int(self._videos.count(SearchQuery()))
        except Exception:
            total = 0
        return SubtitleCoverageDTO(indexed_videos=indexed, total_videos=total)
