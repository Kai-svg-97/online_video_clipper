"""라이브러리 정리 — 중복 영상·깨진 다운로드 파일 점검.

라이브러리가 커질수록 "같은 영상이 두 번 들어왔다", "다운로드 파일을 옮겼더니 재생이
안 된다" 같은 일이 쌓인다. 여기서는 **찾아서 보여 주기만** 하고, 지우는 것은 사용자가
고른 뒤 기존 삭제 유스케이스로 처리한다 — 자동으로 지우면 되돌릴 수 없다.

메모리 규칙에 따라 영상은 50건씩 끊어 읽는다(`_PAGE`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from application.library.dtos import VideoDTO
from domain.library.duplicates import group_duplicates
from domain.library.repositories import IVideoRepository, SearchQuery

logger = logging.getLogger(__name__)

_PAGE = 50
# 방어적 상한 — 이보다 큰 라이브러리는 정리 화면보다 검색이 맞다.
_MAX_SCAN = 5000


@dataclass
class FindDuplicatesQuery:
    """중복 영상 찾기(전체 라이브러리 대상)."""

    limit_groups: int = 100


@dataclass
class DuplicateGroupDTO:
    """중복 묶음 1건 — 화면이 바로 그릴 수 있는 형태."""

    kind: str                 # domain.library.duplicates.DUPLICATE_*
    key: str
    videos: list[VideoDTO] = field(default_factory=list)

    @property
    def extra_count(self) -> int:
        return max(0, len(self.videos) - 1)


@dataclass
class BrokenDownloadDTO:
    """파일이 사라진 다운로드 기록."""

    video_id: object | None
    title: str
    url: str
    file_path: str


class FindDuplicateVideosHandler:
    """라이브러리를 훑어 중복 묶음을 만든다(판정 규칙은 도메인 순수 함수)."""

    def __init__(self, video_repo: IVideoRepository, to_dto=None) -> None:
        self._repo = video_repo
        # DTO 변환기 주입(기본은 application.library.queries의 변환기를 쓴다).
        self._to_dto = to_dto

    def handle(self, query: FindDuplicatesQuery) -> list[DuplicateGroupDTO]:
        # **DTO로 먼저 바꾼 뒤 묶는다.** 판정 규칙은 url·title·channel_name을 평평한
        # 값으로 읽는데, 아그리게이트는 그 값들을 `.video.url`처럼 한 겹 안쪽에 둔다
        # (그대로 넘기면 아무것도 못 찾고 조용히 빈 결과가 된다).
        videos = [self._as_dto(agg) for agg in self._scan_all()]
        groups = group_duplicates(videos)[: query.limit_groups]
        result = [
            DuplicateGroupDTO(kind=g.kind, key=g.key, videos=list(g.items))
            for g in groups
        ]
        logger.info(
            "중복 점검: %d묶음 / 정리 가능 %d건 (영상 %d개 검사)",
            len(result), sum(g.extra_count for g in result), len(videos),
        )
        return result

    # ── 내부 ───────────────────────────────────────────────────────
    def _scan_all(self) -> list:
        out: list = []
        offset = 0
        while offset < _MAX_SCAN:
            page = self._repo.search(SearchQuery(limit=_PAGE, offset=offset))
            if not page:
                break
            out.extend(page)
            if len(page) < _PAGE:
                break
            offset += _PAGE
        return out

    def _as_dto(self, aggregate) -> VideoDTO:
        if self._to_dto is not None:
            return self._to_dto(aggregate)
        from application.library.queries import _to_dto  # noqa: PLC0415

        return _to_dto(aggregate, {}, {})


class FindBrokenDownloadsHandler:
    """완료된 다운로드 중 **파일이 실제로 없는** 기록을 찾는다.

    파일을 옮기거나 지운 뒤에도 목록에는 '다운로드됨'으로 남아 재생이 실패한다.
    경로는 리포지토리가 절대경로로 복원해 주므로 여기서는 존재 여부만 본다.
    """

    def __init__(self, download_repo, limit: int = 500) -> None:
        self._downloads = download_repo
        self._limit = limit

    def handle(self, _query=None) -> list[BrokenDownloadDTO]:
        broken: list[BrokenDownloadDTO] = []
        offset = 0
        while offset < self._limit:
            page = self._downloads.get_history(limit=_PAGE, offset=offset)
            if not page:
                break
            for job in page:
                path = getattr(job, "file_path", "") or ""
                if not path or Path(path).exists():
                    continue
                broken.append(
                    BrokenDownloadDTO(
                        video_id=getattr(job, "video_id", None),
                        title=getattr(job, "title", "") or path,
                        url=str(getattr(job, "url", "") or ""),
                        file_path=path,
                    )
                )
            if len(page) < _PAGE:
                break
            offset += _PAGE
        logger.info("다운로드 파일 점검: 사라진 파일 %d건", len(broken))
        return broken
