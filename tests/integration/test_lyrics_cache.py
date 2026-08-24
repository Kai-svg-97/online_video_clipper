"""가사 JSON 파싱 캐시(`_lyrics_parse_cached`)의 적중률·불변성을 검증한다.

v1.22.0 체감 성능 개선 Phase 1 Step 2 — `infrastructure/persistence/
sqlite_song_repository.py`의 `_lyrics_from_json`은 내용 주소 지정(키=원본 JSON
문자열) `lru_cache`를 통해 파싱 결과를 재사용한다. video_id가 아니라 원본
문자열을 키로 쓰는 이유(무효화 로직 불필요 + MergeApplier의 리포지토리 우회
UPDATE 경로에서도 안전)는 CLAUDE.md·소스 주석에 기록돼 있다 — 여기서는 그
동작(적중률·수정 시 자동 갱신·반환값 불변성)을 못박는다.

`_lyrics_parse_cached`는 모듈 전역 `lru_cache`라 프로세스 내 다른 테스트와
캐시를 공유한다. 절대 히트/미스 개수 대신 **이 테스트 안에서의 델타**로
검증하고, 다른 테스트가 우연히 같은 내용을 캐시했을 가능성을 배제하려고
가사 원문에 매 테스트 전용 마커(고유 문자열)를 심는다.
"""
from __future__ import annotations

import uuid

import pytest

from domain.library.aggregates import VideoAggregate
from domain.library.value_objects import VideoUrl
from domain.song.aggregates import SongInfoAggregate
from domain.song.value_objects import LyricsLine
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_song_repository import (
    SqliteSongRepository,
    _lyrics_parse_cached,
)
from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository


@pytest.fixture
def db(tmp_path):
    database = Database(path=tmp_path / "lyrics_cache.db")
    database.initialize()
    return database


@pytest.fixture
def repo(db):
    return SqliteSongRepository(db)


@pytest.fixture
def video_id(db):
    videos = SqliteVideoRepository(db)
    agg = VideoAggregate.create(VideoUrl("https://youtu.be/lyrics-cache-1"), "가사 캐시 테스트 영상")
    videos.save(agg)
    return agg.id


def _marker() -> str:
    """다른 테스트가 우연히 같은 내용을 캐시했을 가능성을 배제하기 위한 고유 문자열."""
    return uuid.uuid4().hex


def _lines(marker: str) -> list[LyricsLine]:
    return [
        LyricsLine(original=f"line one {marker}", translation="첫 줄", start_ms=1000),
        LyricsLine(original=f"line two {marker}", translation="둘째 줄", start_ms=5500),
    ]


class TestLyricsParseCacheHitRate:
    def test_같은_가사를_반복_조회하면_두번째부터_캐시가_적중한다(self, repo, video_id):
        agg = SongInfoAggregate.create(video_id, is_song=True)
        agg.apply_fetched(lyrics_lines=_lines(_marker()), mark_song=True)
        repo.save(agg)

        hits_before = _lyrics_parse_cached.cache_info().hits
        for _ in range(3):
            loaded = repo.get(video_id)
            assert loaded is not None
        hits_after = _lyrics_parse_cached.cache_info().hits

        # 3회 조회 중 1회차는 최초 파싱(미스), 2·3회차는 캐시 적중이어야 한다.
        assert hits_after - hits_before == 2

    def test_가사를_수정하면_무효화_로직_없이_새_값이_반영된다(self, repo, video_id):
        marker = _marker()
        agg = SongInfoAggregate.create(video_id, is_song=True)
        agg.apply_fetched(lyrics_lines=_lines(marker), mark_song=True)
        repo.save(agg)

        first = repo.get(video_id)
        assert first is not None
        assert first.info.lyrics_lines[0].original == f"line one {marker}"

        new_marker = _marker()
        agg.edit_lyrics(_lines(new_marker))
        repo.save(agg)

        second = repo.get(video_id)
        assert second is not None
        # 내용이 바뀌었으니 JSON 문자열도 달라져 자동으로 새 캐시 키가 된다 —
        # video_id 키잉이었다면 필요했을 별도 무효화 호출이 전혀 없었다.
        assert second.info.lyrics_lines[0].original == f"line one {new_marker}"

    def test_반환된_리스트를_변형해도_캐시가_오염되지_않는다(self, repo, video_id):
        marker = _marker()
        agg = SongInfoAggregate.create(video_id, is_song=True)
        agg.apply_fetched(lyrics_lines=_lines(marker), mark_song=True)
        repo.save(agg)

        first = repo.get(video_id)
        assert first is not None
        mutable_copy = first.info.lyrics_lines
        # `_lyrics_from_json`이 매번 새 list를 돌려주므로, 호출자가 이 리스트를
        # 비워도 다음 조회 결과에는 영향이 없어야 한다(캐시된 tuple은 불변으로
        # 별도 보관되고, list()는 매번 새 사본이다).
        mutable_copy.clear()

        second = repo.get(video_id)
        assert second is not None
        assert len(second.info.lyrics_lines) == 2
        assert second.info.lyrics_lines[0].original == f"line one {marker}"
