"""싱크 가사(줄별 시각)·자막 오프셋의 저장/로드 왕복을 검증한다.

lyrics_json은 [{"o":원문,"t":번역,"s":시작ms}] 형태로 확장됐다. "s"가 없는 기존
데이터가 그대로 로드되어야 한다(하위호환) — 이 회귀가 나면 기존 사용자의 가사가
깨진다.
"""
from __future__ import annotations

import json

import pytest

from domain.library.aggregates import VideoAggregate
from domain.library.value_objects import VideoUrl
from domain.song.aggregates import SongInfoAggregate
from domain.song.value_objects import LyricsLine
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_song_repository import SqliteSongRepository
from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository


@pytest.fixture
def db(tmp_path):
    database = Database(path=tmp_path / "song.db")
    database.initialize()
    return database


@pytest.fixture
def repo(db):
    return SqliteSongRepository(db)


@pytest.fixture
def video_id(db):
    videos = SqliteVideoRepository(db)
    agg = VideoAggregate.create(VideoUrl("https://youtu.be/sync1"), "노래 영상")
    videos.save(agg)
    return agg.id


def _lines() -> list[LyricsLine]:
    return [
        LyricsLine(original="first line", translation="첫 줄", start_ms=1000),
        LyricsLine(original="second line", translation="둘째 줄", start_ms=5500),
        LyricsLine(original="untimed", translation="", start_ms=None),
    ]


class TestSyncedLyricsRoundTrip:
    def test_start_ms가_저장되고_로드된다(self, repo, video_id):
        agg = SongInfoAggregate.create(video_id, is_song=True)
        agg.apply_fetched(lyrics_lines=_lines(), mark_song=True)
        repo.save(agg)

        loaded = repo.get(video_id)
        assert loaded is not None
        assert [ln.start_ms for ln in loaded.info.lyrics_lines] == [1000, 5500, None]
        assert loaded.info.is_synced is True

    def test_타이밍_없는_가사는_is_synced_False(self, repo, video_id):
        agg = SongInfoAggregate.create(video_id, is_song=True)
        agg.apply_fetched(
            lyrics_lines=[LyricsLine(original="no timing")], mark_song=True
        )
        repo.save(agg)
        assert repo.get(video_id).info.is_synced is False


class TestBackwardCompatibility:
    def test_s_키_없는_기존_JSON도_로드된다(self, db, repo, video_id):
        """기존 설치본의 lyrics_json에는 "s" 키가 없다."""
        legacy = json.dumps(
            [{"o": "old line", "t": "옛 줄"}], ensure_ascii=False
        )
        with db.connection() as conn:
            conn.execute(
                "INSERT INTO song_info (video_id, is_song, lyrics_json, updated_at) "
                "VALUES (?, 1, ?, datetime('now'))",
                (str(video_id), legacy),
            )
        loaded = repo.get(video_id)
        assert loaded.info.lyrics_lines[0].original == "old line"
        assert loaded.info.lyrics_lines[0].start_ms is None
        assert loaded.info.is_synced is False

    def test_s_키가_비정수여도_None으로_취급(self, db, repo, video_id):
        broken = json.dumps([{"o": "line", "t": "", "s": "이상한값"}], ensure_ascii=False)
        with db.connection() as conn:
            conn.execute(
                "INSERT INTO song_info (video_id, is_song, lyrics_json, updated_at) "
                "VALUES (?, 1, ?, datetime('now'))",
                (str(video_id), broken),
            )
        assert repo.get(video_id).info.lyrics_lines[0].start_ms is None

    def test_타이밍_없는_줄은_s_키를_쓰지_않는다(self, db, repo, video_id):
        agg = SongInfoAggregate.create(video_id, is_song=True)
        agg.apply_fetched(lyrics_lines=[LyricsLine(original="a")], mark_song=True)
        repo.save(agg)
        with db.connection() as conn:
            raw = conn.execute(
                "SELECT lyrics_json FROM song_info WHERE video_id=?", (str(video_id),)
            ).fetchone()[0]
        assert "s" not in json.loads(raw)[0]


class TestLyricsOffset:
    def test_기본값은_0(self, repo, video_id):
        agg = SongInfoAggregate.create(video_id, is_song=True)
        repo.save(agg)
        assert repo.get(video_id).info.lyrics_offset_ms == 0

    def test_저장되고_로드된다(self, repo, video_id):
        agg = SongInfoAggregate.create(video_id, is_song=True)
        agg.set_lyrics_offset(1500)
        repo.save(agg)
        assert repo.get(video_id).info.lyrics_offset_ms == 1500

    def test_음수도_저장된다(self, repo, video_id):
        agg = SongInfoAggregate.create(video_id, is_song=True)
        agg.set_lyrics_offset(-750)
        repo.save(agg)
        assert repo.get(video_id).info.lyrics_offset_ms == -750

    def test_범위를_벗어나면_clamp된다(self, repo, video_id):
        agg = SongInfoAggregate.create(video_id, is_song=True)
        agg.set_lyrics_offset(999_999)
        assert agg.info.lyrics_offset_ms == 30_000
        agg.set_lyrics_offset(-999_999)
        assert agg.info.lyrics_offset_ms == -30_000

    def test_같은_값이면_이벤트를_내지_않는다(self, video_id):
        agg = SongInfoAggregate.create(video_id, is_song=True)
        agg.set_lyrics_offset(0)
        assert agg.pull_events() == []


class TestEditLyricsTimingPreservation:
    def test_줄_수가_같으면_타이밍을_유지한다(self, video_id):
        """오탈자 수정으로 싱크가 날아가면 안 된다."""
        agg = SongInfoAggregate.create(video_id, is_song=True)
        agg.apply_fetched(lyrics_lines=_lines(), mark_song=True)
        edited = [
            LyricsLine(original="FIRST LINE", translation="첫 줄"),
            LyricsLine(original="second line", translation="둘째 줄"),
            LyricsLine(original="untimed", translation=""),
        ]
        agg.edit_lyrics(edited)
        assert [ln.start_ms for ln in agg.info.lyrics_lines] == [1000, 5500, None]
        assert agg.info.lyrics_lines[0].original == "FIRST LINE"

    def test_줄_수가_다르면_타이밍을_폐기한다(self, video_id):
        agg = SongInfoAggregate.create(video_id, is_song=True)
        agg.apply_fetched(lyrics_lines=_lines(), mark_song=True)
        agg.edit_lyrics([LyricsLine(original="한 줄로 줄임")])
        assert agg.info.lyrics_lines[0].start_ms is None
        assert agg.info.is_synced is False


class TestTranslationPreservesTiming:
    def test_번역_교체_후에도_start_ms가_남는다(self, video_id):
        agg = SongInfoAggregate.create(video_id, is_song=True)
        agg.apply_fetched(lyrics_lines=_lines(), mark_song=True)
        translated = [
            LyricsLine(original=ln.original, translation="새 번역", start_ms=ln.start_ms)
            for ln in agg.info.lyrics_lines
        ]
        agg.set_lyrics_translations(translated)
        assert [ln.start_ms for ln in agg.info.lyrics_lines] == [1000, 5500, None]
