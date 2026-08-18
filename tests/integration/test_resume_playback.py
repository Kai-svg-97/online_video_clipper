"""이어보기 — 재생 위치 저장·복원 규칙을 실제 SQLite로 고정한다.

이 기능이 없을 때는 보던 지점이 매번 날아갔다(DB에 `watched` 플래그만 있었다).
여기서 지키는 계약:
* 중간에 멈춘 영상만 이어보기 대상이다 — **잠깐 눌렀다 만 것**(15초 미만)과
  **거의 다 본 것**(97% 이상)은 위치를 남기지 않는다. 그러지 않으면 이어보기 목록이
  금세 쓰레기통이 되고, 끝나기 직전으로 되돌아가는 이상한 복귀가 생긴다.
* 끝까지 본 영상은 `watched`로 표시된다.
* 위치 저장은 **가벼운 전용 경로**를 쓴다(재생 중 반복 호출되므로).
"""
from __future__ import annotations

import pytest

from application.library.commands import (
    UpdatePlaybackPositionCommand,
    UpdatePlaybackPositionHandler,
)
from application.library.dtos import VideoDTO
from domain.library.aggregates import VideoAggregate
from domain.library.repositories import SearchQuery
from domain.library.value_objects import Duration, VideoUrl
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository


@pytest.fixture
def repo(tmp_path):
    db = Database(path=tmp_path / "resume.db")
    db.initialize()
    return SqliteVideoRepository(db)


def _add(repo, url="https://youtu.be/resume01", seconds=600) -> VideoAggregate:
    agg = VideoAggregate.create(VideoUrl(url), "영상", duration=Duration(seconds))
    repo.save(agg)
    return agg


class TestPositionRules:
    def test_중간에_멈추면_그_지점을_기억한다(self, repo):
        agg = _add(repo)
        handler = UpdatePlaybackPositionHandler(repo)

        handler.handle(UpdatePlaybackPositionCommand(video_id=agg.id, position_ms=120_000))

        again = repo.get_by_id(agg.id)
        assert again.video.last_position_ms == 120_000
        assert again.video.last_played_at is not None
        assert again.video.watched is False

    def test_잠깐_눌렀다_만_것은_기억하지_않는다(self, repo):
        agg = _add(repo)
        handler = UpdatePlaybackPositionHandler(repo)

        handler.handle(UpdatePlaybackPositionCommand(video_id=agg.id, position_ms=4_000))

        assert repo.get_by_id(agg.id).video.last_position_ms == 0

    def test_거의_다_보면_위치를_지우고_시청_표시한다(self, repo):
        agg = _add(repo, seconds=600)
        handler = UpdatePlaybackPositionHandler(repo)

        handler.handle(UpdatePlaybackPositionCommand(video_id=agg.id, position_ms=595_000))

        after = repo.get_by_id(agg.id).video
        assert after.last_position_ms == 0      # 끝 직전으로 되돌아가지 않는다
        assert after.watched is True

    def test_길이를_모르면_위치만_남긴다(self, repo):
        agg = VideoAggregate.create(VideoUrl("https://youtu.be/live0001"), "라이브")
        repo.save(agg)
        handler = UpdatePlaybackPositionHandler(repo)

        handler.handle(UpdatePlaybackPositionCommand(video_id=agg.id, position_ms=300_000))

        after = repo.get_by_id(agg.id).video
        assert after.last_position_ms == 300_000
        assert after.watched is False

    def test_없는_영상은_조용히_넘어간다(self, repo):
        from uuid import uuid4

        UpdatePlaybackPositionHandler(repo).handle(
            UpdatePlaybackPositionCommand(video_id=uuid4(), position_ms=1000)
        )   # 예외 없이 무시


class TestQueries:
    def test_이어보기만_추려_본다(self, repo):
        watched_half = _add(repo, "https://youtu.be/half0001")
        _add(repo, "https://youtu.be/fresh001")
        UpdatePlaybackPositionHandler(repo).handle(
            UpdatePlaybackPositionCommand(video_id=watched_half.id, position_ms=90_000)
        )

        found = repo.search(SearchQuery(in_progress_only=True))

        assert [a.id for a in found] == [watched_half.id]

    def test_최근_재생순으로_정렬된다(self, repo):
        first = _add(repo, "https://youtu.be/first001")
        second = _add(repo, "https://youtu.be/second01")
        handler = UpdatePlaybackPositionHandler(repo)
        handler.handle(UpdatePlaybackPositionCommand(video_id=first.id, position_ms=60_000))
        handler.handle(UpdatePlaybackPositionCommand(video_id=second.id, position_ms=60_000))

        found = repo.search(SearchQuery(in_progress_only=True, sort_by="last_played_at"))

        assert found[0].id == second.id   # 마지막에 본 것이 앞


class TestProgressRatio:
    def test_카드_진행률은_위치와_길이로_계산된다(self):
        dto = VideoDTO(
            id=None, url="u", title="t", channel_name="c", thumbnail_path="",
            duration_sec=600, favorite=False, watched=False, category_id=None,
            last_position_ms=150_000,
        )

        assert dto.progress_ratio == pytest.approx(0.25)

    def test_위치나_길이를_모르면_0이다(self):
        base = dict(
            id=None, url="u", title="t", channel_name="c", thumbnail_path="",
            favorite=False, watched=False, category_id=None,
        )

        assert VideoDTO(duration_sec=600, last_position_ms=0, **base).progress_ratio == 0.0
        assert VideoDTO(duration_sec=None, last_position_ms=1000, **base).progress_ratio == 0.0
