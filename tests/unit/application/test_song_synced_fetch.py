"""싱크 전용 조회(synced_only)와 자막 오프셋 커맨드를 검증한다.

synced_only는 타이밍 없는 결과를 채택하지 않고 다음 출처로 넘어간다 — 실질적으로
LRCLIB만 통과하지만, 미래에 타이밍을 주는 출처가 생기면 자동 편입된다.
전 출처 실패 시 기존 가사를 지우지 않는 것이 핵심 계약이다.
"""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from application.song.commands import (
    FetchSongInfoCommand,
    FetchSongInfoHandler,
    SetLyricsOffsetCommand,
    SetLyricsOffsetHandler,
)
from domain.song.aggregates import SongInfoAggregate
from domain.song.entities import LyricsSource
from domain.song.ports import LyricsResult
from domain.song.value_objects import LyricsLine


class _Provider:
    def __init__(self, key, result):
        self.key = key
        self._result = result
        self.calls = 0

    def fetch(self, artist, title, duration_sec=None):
        self.calls += 1
        return self._result


@pytest.fixture
def video_id():
    return uuid4()


@pytest.fixture
def song_repo():
    repo = MagicMock()
    repo.list_lyrics_sources.return_value = [
        LyricsSource.create("플레인출처", "plain", priority=10),
        LyricsSource.create("싱크출처", "synced", priority=20),
    ]
    return repo


@pytest.fixture
def video_repo(video_id):
    repo = MagicMock()
    video = MagicMock()
    video.title = "Artist - Title"
    video.url = "https://youtu.be/x"
    video.channel = None
    video.duration = None
    agg = MagicMock()
    agg.video = video
    repo.get_by_id.return_value = agg
    return repo


def _handler(song_repo, video_repo, providers):
    return FetchSongInfoHandler(
        song_repo=song_repo,
        video_repo=video_repo,
        event_bus=MagicMock(),
        lyrics_providers=providers,
        translator=None,
        media_source=None,
    )


class TestSyncedOnlyFetch:
    def test_타이밍_없는_출처는_건너뛴다(self, song_repo, video_repo, video_id):
        song_repo.get.return_value = SongInfoAggregate.create(video_id, is_song=True)
        plain = _Provider("plain", LyricsResult(lines=["no timing"], timings=[]))
        synced = _Provider(
            "synced",
            LyricsResult(lines=["a", "b"], timings=[1000, 2000], source_url="u"),
        )
        handler = _handler(song_repo, video_repo, {"plain": plain, "synced": synced})

        agg = handler.handle(
            FetchSongInfoCommand(video_id=video_id, synced_only=True, force=True)
        )

        assert [ln.original for ln in agg.info.lyrics_lines] == ["a", "b"]
        assert [ln.start_ms for ln in agg.info.lyrics_lines] == [1000, 2000]
        assert agg.info.source.name == "싱크출처"

    def test_전_출처_실패면_기존_가사를_유지한다(self, song_repo, video_repo, video_id):
        existing = SongInfoAggregate.create(video_id, is_song=True)
        existing.apply_fetched(
            lyrics_lines=[LyricsLine(original="기존 가사")], mark_song=True
        )
        song_repo.get.return_value = existing
        plain = _Provider("plain", LyricsResult(lines=["x"], timings=[]))
        handler = _handler(song_repo, video_repo, {"plain": plain})

        agg = handler.handle(
            FetchSongInfoCommand(video_id=video_id, synced_only=True, force=True)
        )

        assert [ln.original for ln in agg.info.lyrics_lines] == ["기존 가사"]
        assert agg.info.is_synced is False

    def test_수동편집_가사도_싱크_가사로_교체된다(self, song_repo, video_repo, video_id):
        """사용자가 명시적으로 누른 버튼이므로 수동 편집 가드를 넘어선다."""
        existing = SongInfoAggregate.create(video_id, is_song=True)
        existing.edit_lyrics([LyricsLine(original="손으로 넣은 가사")])
        song_repo.get.return_value = existing
        synced = _Provider("synced", LyricsResult(lines=["새 가사"], timings=[500]))
        handler = _handler(song_repo, video_repo, {"synced": synced})

        agg = handler.handle(
            FetchSongInfoCommand(video_id=video_id, synced_only=True, force=True)
        )

        assert [ln.original for ln in agg.info.lyrics_lines] == ["새 가사"]
        assert agg.info.lyrics_lines[0].start_ms == 500


class TestNormalFetchUnaffected:
    def test_synced_only가_꺼져_있으면_타이밍_없는_가사도_채택(
        self, song_repo, video_repo, video_id
    ):
        song_repo.get.return_value = SongInfoAggregate.create(video_id, is_song=True)
        plain = _Provider("plain", LyricsResult(lines=["no timing"], timings=[]))
        handler = _handler(song_repo, video_repo, {"plain": plain})

        agg = handler.handle(
            FetchSongInfoCommand(video_id=video_id, force=True, fetch_lyrics=True)
        )

        assert [ln.original for ln in agg.info.lyrics_lines] == ["no timing"]

    def test_타이밍이_있으면_일반_조회에서도_보존된다(
        self, song_repo, video_repo, video_id
    ):
        song_repo.get.return_value = SongInfoAggregate.create(video_id, is_song=True)
        synced = _Provider("synced", LyricsResult(lines=["a"], timings=[700]))
        handler = _handler(song_repo, video_repo, {"synced": synced})

        agg = handler.handle(
            FetchSongInfoCommand(video_id=video_id, force=True, fetch_lyrics=True)
        )

        assert agg.info.lyrics_lines[0].start_ms == 700


class TestSetLyricsOffset:
    def test_오프셋을_저장한다(self, song_repo, video_id):
        agg = SongInfoAggregate.create(video_id, is_song=True)
        song_repo.get.return_value = agg
        bus = MagicMock()

        SetLyricsOffsetHandler(song_repo, bus).handle(
            SetLyricsOffsetCommand(video_id=video_id, offset_ms=1250)
        )

        assert agg.info.lyrics_offset_ms == 1250
        song_repo.save.assert_called_once_with(agg)

    def test_노래_정보가_없으면_새로_만든다(self, song_repo, video_id):
        song_repo.get.return_value = None
        SetLyricsOffsetHandler(song_repo, MagicMock()).handle(
            SetLyricsOffsetCommand(video_id=video_id, offset_ms=-500)
        )
        saved = song_repo.save.call_args[0][0]
        assert saved.info.lyrics_offset_ms == -500
