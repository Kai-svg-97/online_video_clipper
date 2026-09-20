"""통계의 '완료 다운로드'는 **완료된 것만** 센다.

이력 전체를 세고 있어서 실패·대기 중인 건까지 "완료"로 집계됐다. 표본 자료(완료 2 +
실패 1)에서 "완료 다운로드 3개"로 나와 드러났다 — 라벨이 사실과 달랐다.

용량은 DB 값이 아니라 **디스크의 실제 파일**을 더한다(재시도로 이력이 여러 개인
경우를 정규화된 경로로 걸러내기 위해서다). 그래서 파일이 없으면 0이 맞다.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from application.library.queries import LibraryStatsHandler
from domain.download.entities import JobStatus


def _job(status: JobStatus, path: str = "") -> SimpleNamespace:
    return SimpleNamespace(status=status, file_path=path, url=SimpleNamespace(value="u"))


def _handler(history: list) -> LibraryStatsHandler:
    video_repo = MagicMock()
    video_repo.get_library_stats.return_value = {
        "total_videos": 0, "total_duration_sec": 0,
        "watched_count": 0, "favorite_count": 0, "category_stats": [],
    }
    dl_repo = MagicMock()
    dl_repo.get_history.return_value = history
    handler = LibraryStatsHandler(video_repo, dl_repo)
    handler._build_channel_stats = lambda: []      # 이 시험의 관심사가 아니다
    return handler


class TestCompletedCount:
    def test_실패한_건은_세지_않는다(self):
        stats = _handler([
            _job(JobStatus.COMPLETED),
            _job(JobStatus.COMPLETED),
            _job(JobStatus.FAILED),
        ]).handle()
        assert stats.total_downloads == 2

    def test_대기_중인_건도_세지_않는다(self):
        stats = _handler([_job(JobStatus.COMPLETED), _job(JobStatus.PENDING)]).handle()
        assert stats.total_downloads == 1

    def test_하나도_없으면_0(self):
        assert _handler([]).handle().total_downloads == 0


class TestBytes:
    def test_파일이_없으면_용량은_0이다(self):
        """DB 값이 아니라 디스크를 읽는다 — 지운 파일이 용량에 남으면 안 된다."""
        stats = _handler([_job(JobStatus.COMPLETED, "C:/없는/파일.mp4")]).handle()
        assert stats.total_download_bytes == 0
