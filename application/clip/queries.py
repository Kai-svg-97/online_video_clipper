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


@dataclass
class GetHighlightsQuery:
    video_id: UUID
    limit: int = 5


class GetHighlightsHandler:
    """자막(+챕터)에서 '볼 만한 구간'을 제안한다.

    **자막 색인 위에서만 성립한다.** 색인이 없으면 빈 목록이고, 화면은 "자막을 먼저
    만들어 주세요"로 안내한다 — 빈 목록만 보여 주면 기능이 고장 난 것처럼 보인다.

    네트워크도 모델 호출도 없다(`domain.clip.highlights` 의 순수 규칙). 그래서 동기로
    충분하고, 오프라인에서도 동작한다.
    """

    def __init__(self, subtitle_repo, video_repo: IVideoRepository) -> None:
        self._subtitles = subtitle_repo
        self._videos = video_repo

    def handle(self, query: GetHighlightsQuery) -> list[ChapterDTO]:
        """제안 구간 — 화면이 챕터와 **같은 방식으로** 다룰 수 있게 ChapterDTO로 준다.

        클립 탭은 이미 챕터를 체크박스로 고르고 한 번에 추출하는 흐름을 갖고 있다.
        같은 형태로 돌려주면 그 흐름을 그대로 재사용한다.
        """
        from domain.clip.highlights import suggest_highlights  # noqa: PLC0415

        lines = self._subtitles.list_lines(query.video_id)
        if not lines:
            return []
        agg = self._videos.get_by_id(query.video_id)
        if agg is None:
            return []
        video = agg.video
        duration = float(video.duration.seconds) if video.duration else 0.0
        chapters = [
            (c.title, c.start_sec, c.end_sec)
            for c in parse_chapters(video.description or "", duration)
        ]
        cues = [(ln.start_ms, ln.end_ms, ln.text) for ln in lines]
        return [
            ChapterDTO(
                title=h.title or f"제안 구간 {i}",
                start_sec=h.start_sec,
                end_sec=h.end_sec,
            )
            for i, h in enumerate(
                suggest_highlights(cues, duration, chapters, limit=query.limit), start=1
            )
        ]
