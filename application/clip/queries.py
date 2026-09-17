from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from application.clip.dtos import ChapterDTO, ClipDTO
from domain.clip.aggregates import ClipAggregate
from domain.clip.chapters import parse_chapters
from domain.clip.repositories import IClipRepository
from domain.library.repositories import IVideoRepository


@dataclass
class GetClipsQuery:
    source_video_id: UUID


@dataclass
class GetChaptersQuery:
    video_id: UUID


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


class GetChaptersHandler:
    """영상 설명에서 챕터 구간을 뽑는다.

    yt-dlp 의 `chapters` 메타데이터가 더 정확하지만 저장돼 있지 않아 다시 받아와야
    한다(영상마다 네트워크 왕복). 설명은 이미 DB에 있어 **즉시·오프라인**으로
    답할 수 있고, 상세화면이 이미 같은 타임스탬프를 seek 링크로 쓰고 있어 화면에
    보이는 것과 어긋나지 않는다.
    """

    def __init__(self, video_repo: IVideoRepository) -> None:
        self._videos = video_repo

    def handle(self, query: GetChaptersQuery) -> list[ChapterDTO]:
        agg = self._videos.get_by_id(query.video_id)
        if agg is None:
            return []
        video = agg.video
        duration = float(video.duration.seconds) if video.duration else 0.0
        chapters = parse_chapters(video.description or "", duration)
        return [ChapterDTO(c.title, c.start_sec, c.end_sec) for c in chapters]
