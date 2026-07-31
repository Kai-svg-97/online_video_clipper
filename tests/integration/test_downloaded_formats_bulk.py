"""목록 화면의 영상/음원 배지를 일괄 판정하는 경로를 검증한다.

회귀 배경: 표(상세) 뷰가 행마다 `GetVideoDetail`을 호출해 50행 × 여러 쿼리 +
파일 stat 이 메인 스레드에서 돌았고, 검색어를 한 글자 칠 때마다 이 작업이 반복돼
키 입력조차 어려울 만큼 UI가 멈췄다. 이제 URL 묶음 한 번의 쿼리로 대체한다.
"""
from __future__ import annotations

import pytest

from application.library.queries import (
    GetDownloadedFormatsHandler,
    GetDownloadedFormatsQuery,
)
from domain.download.entities import DownloadJob, JobStatus
from domain.download.value_objects import DownloadSettings, MediaFormat, Quality
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_download_repository import SqliteDownloadRepository


@pytest.fixture
def repo(tmp_path):
    db = Database(path=tmp_path / "dl.db")
    db.initialize()
    return SqliteDownloadRepository(db)


def _save(repo, url, fmt: MediaFormat, status=JobStatus.COMPLETED):
    job = DownloadJob.create(
        url, "제목", DownloadSettings(quality=Quality.BEST, fmt=fmt)
    )
    job.status = status
    repo.save(job)
    return job


class TestFindCompletedFormatsByUrls:
    def test_groups_formats_per_url(self, repo):
        _save(repo, "https://youtu.be/a", MediaFormat.MP4)
        _save(repo, "https://youtu.be/a", MediaFormat.MP3)
        _save(repo, "https://youtu.be/b", MediaFormat.MKV)

        result = repo.find_completed_formats_by_urls(
            ["https://youtu.be/a", "https://youtu.be/b", "https://youtu.be/none"]
        )
        assert result["https://youtu.be/a"] == {"mp4", "mp3"}
        assert result["https://youtu.be/b"] == {"mkv"}
        assert "https://youtu.be/none" not in result

    def test_ignores_non_completed(self, repo):
        _save(repo, "https://youtu.be/f", MediaFormat.MP4, status=JobStatus.FAILED)
        assert repo.find_completed_formats_by_urls(["https://youtu.be/f"]) == {}

    def test_empty_input(self, repo):
        assert repo.find_completed_formats_by_urls([]) == {}

    def test_matches_per_url_lookup(self, repo):
        """단건 조회(find_completed_by_url)와 결과가 일치해야 한다."""
        _save(repo, "https://youtu.be/x", MediaFormat.WEBM)
        _save(repo, "https://youtu.be/x", MediaFormat.M4A)
        bulk = repo.find_completed_formats_by_urls(["https://youtu.be/x"])
        one_by_one = {
            (j.settings.format.value or "").lower()
            for j in repo.find_completed_by_url("https://youtu.be/x")
        }
        assert bulk["https://youtu.be/x"] == one_by_one

    def test_chunks_beyond_sqlite_variable_limit(self, repo):
        """SQLite 바인딩 변수 상한(999)을 넘는 URL 묶음도 처리해야 한다."""
        urls = [f"https://youtu.be/v{i}" for i in range(1200)]
        _save(repo, urls[0], MediaFormat.MP4)
        _save(repo, urls[-1], MediaFormat.MP3)
        result = repo.find_completed_formats_by_urls(urls)
        assert result == {urls[0]: {"mp4"}, urls[-1]: {"mp3"}}


class TestGetDownloadedFormatsHandler:
    def test_flags_video_and_audio(self, repo):
        _save(repo, "https://youtu.be/v", MediaFormat.MP4)
        _save(repo, "https://youtu.be/s", MediaFormat.MP3)
        _save(repo, "https://youtu.be/both", MediaFormat.MKV)
        _save(repo, "https://youtu.be/both", MediaFormat.M4A)

        handler = GetDownloadedFormatsHandler(repo)
        flags = handler.handle(
            GetDownloadedFormatsQuery(
                urls=[
                    "https://youtu.be/v",
                    "https://youtu.be/s",
                    "https://youtu.be/both",
                    "https://youtu.be/nothing",
                ]
            )
        )
        assert flags["https://youtu.be/v"] == (True, False)
        assert flags["https://youtu.be/s"] == (False, True)
        assert flags["https://youtu.be/both"] == (True, True)
        assert "https://youtu.be/nothing" not in flags
