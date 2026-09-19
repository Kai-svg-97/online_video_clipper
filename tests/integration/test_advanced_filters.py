"""복합 필터 — 진짜 SQLite 로.

필터는 SQL 한 줄만 틀려도 **조용히 틀린다**: 예외 없이 목록에서 영상이 빠지거나,
안 걸러져야 할 것이 남는다. 그래서 값 변환이 아니라 **결과 집합**을 본다.

특히 날짜는 `published_at`이 `"2026-09-18T10:00:00"`처럼 시각까지 담고 있어,
문자열 그대로 `<=` 하면 **그 날 올라온 영상이 통째로 빠진다**.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from application.library.queries import (
    GetVideosHandler,
    GetVideosQuery,
    SearchVideosHandler,
    SearchVideosQuery,
)
from domain.library.aggregates import VideoAggregate
from domain.library.value_objects import ChannelInfo, Duration, VideoUrl
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository


@pytest.fixture
def repo(tmp_path):
    db = Database(path=tmp_path / "filters.db")
    db.initialize()
    return SqliteVideoRepository(db)


def _add(repo, *, title, channel="채널", duration=600, published="2026-09-10T00:00:00",
         favorite=False, watched=False, url=None):
    agg = VideoAggregate.create(
        url=VideoUrl(url or f"https://youtu.be/{abs(hash(title)) % 10**11:011d}"),
        title=title,
        channel=ChannelInfo(name=channel, url="", channel_id=f"ch-{channel}"),
        duration=Duration(duration),
        published_at=datetime.fromisoformat(published),
        favorite=favorite,
    )
    if watched:
        agg.mark_watched()
    repo.save(agg)
    return agg


def _titles(repo, **kwargs) -> set[str]:
    return {v.title for v in GetVideosHandler(repo).handle(GetVideosQuery(**kwargs))}


@pytest.fixture
def seeded(repo):
    _add(repo, title="짧은 최신", duration=100, published="2026-09-18T10:00:00")
    _add(repo, title="긴 옛날", duration=3600, published="2025-01-01T00:00:00")
    _add(repo, title="중간", duration=600, published="2026-09-01T00:00:00",
         channel="다른채널")
    _add(repo, title="즐겨찾기", duration=600, published="2026-09-15T00:00:00",
         favorite=True)
    return repo


class TestDateRange:
    def test_시작_이후만_남긴다(self, seeded):
        got = _titles(seeded, published_from="2026-09-10")
        assert got == {"짧은 최신", "즐겨찾기"}

    def test_그_날_올라온_영상이_빠지지_않는다(self, seeded):
        """`published_at`에 시각이 붙어 있어 문자열 비교로는 통째로 빠진다."""
        got = _titles(seeded, published_to="2026-09-18")
        assert "짧은 최신" in got

    def test_구간으로_좁힌다(self, seeded):
        got = _titles(seeded, published_from="2026-09-02", published_to="2026-09-16")
        assert got == {"즐겨찾기"}

    def test_비우면_거르지_않는다(self, seeded):
        assert len(_titles(seeded, published_from="", published_to="")) == 4


class TestDuration:
    def test_짧은_것만(self, seeded):
        assert _titles(seeded, max_duration_sec=239) == {"짧은 최신"}

    def test_긴_것만(self, seeded):
        assert _titles(seeded, min_duration_sec=1200) == {"긴 옛날"}


class TestChannel:
    def test_부분_일치로_좁힌다(self, seeded):
        assert _titles(seeded, channel_name="다른") == {"중간"}

    def test_와일드카드_문자를_글자로_다룬다(self, seeded):
        """`%`를 넣었을 때 전부가 걸리면 이스케이프가 빠진 것이다."""
        _add(seeded, title="퍼센트", channel="100%채널")
        assert _titles(seeded, channel_name="%") == {"퍼센트"}


class TestFavoriteAndWatched:
    def test_즐겨찾기만(self, seeded):
        assert _titles(seeded, favorite_only=True) == {"즐겨찾기"}

    def test_안_본_것만(self, repo):
        _add(repo, title="봄", watched=True)
        _add(repo, title="안봄", watched=False)
        assert _titles(repo, watched=False) == {"안봄"}


class TestDownloaded:
    @pytest.fixture
    def with_download(self, repo):
        target = _add(repo, title="받은 것", url="https://youtu.be/11111111111")
        _add(repo, title="안 받은 것", url="https://youtu.be/22222222222")
        with repo._db.connection() as conn:
            conn.execute(
                "INSERT INTO download_history "
                "(id, url, title, quality, format, status, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                ("dl-1", str(target.video.url), "받은 것", "best", "mp4",
                 "completed", "2026-09-18", "2026-09-18"),
            )
            conn.commit()
        return repo

    def test_받아_둔_것만(self, with_download):
        assert _titles(with_download, downloaded=True) == {"받은 것"}

    def test_안_받은_것만(self, with_download):
        assert _titles(with_download, downloaded=False) == {"안 받은 것"}

    def test_실패한_이력은_받은_것으로_치지_않는다(self, with_download):
        with with_download._db.connection() as conn:
            conn.execute(
                "INSERT INTO download_history "
                "(id, url, title, quality, format, status, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                ("dl-2", "https://youtu.be/22222222222", "안 받은 것", "best", "mp4",
                 "failed", "2026-09-18", "2026-09-18"),
            )
            conn.commit()
        assert _titles(with_download, downloaded=True) == {"받은 것"}


class TestWithSearch:
    def test_검색어와_함께_걸린다(self, seeded):
        """검색어를 넣는 순간 필터가 조용히 풀리면 안 된다."""
        got = {
            v.title
            for v in SearchVideosHandler(seeded).handle(
                SearchVideosQuery(text="", min_duration_sec=1200)
            )
        }
        assert got == {"긴 옛날"}

    def test_검색_경로에서도_시청_여부가_걸린다(self, repo):
        _add(repo, title="본 영상", watched=True)
        _add(repo, title="안 본 영상", watched=False)
        got = {
            v.title
            for v in SearchVideosHandler(repo).handle(
                SearchVideosQuery(text="영상", watched=True)
            )
        }
        assert got == {"본 영상"}
