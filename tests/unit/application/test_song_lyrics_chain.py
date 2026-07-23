"""FetchSongInfoHandler 가사 출처 체인 단위 테스트.

핵심 회귀: yt-dlp가 주는 다중 아티스트 문자열(예: "NIKI, Phil Collins")로는
가사 제공자 검색이 실패한다. 체인은 주 아티스트(콤마/feat 등 분리)로도 재시도해야 한다.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from application.song.commands import (
    FetchSongInfoHandler,
    TranslateSongLyricsCommand,
    TranslateSongLyricsHandler,
    _primary_artist,
)
from domain.song.aggregates import SongInfoAggregate
from domain.song.ports import LyricsResult
from domain.song.value_objects import LyricsLine


class _ArtistPickyProvider:
    """지정한 아티스트로 호출될 때만 가사를 반환하는 가짜 제공자."""

    key = "picky"

    def __init__(self, wanted_artist: str) -> None:
        self._wanted = wanted_artist
        self.calls: list[str] = []

    def fetch(self, artist, title, duration_sec=None):
        self.calls.append(artist)
        if artist == self._wanted:
            return LyricsResult(
                lines=["line 1", "line 2"],
                language="en",
                source_name="Picky",
                source_url="http://x",
            )
        return None


def _make_handler(provider):
    song_repo = MagicMock()
    song_repo.list_lyrics_sources.return_value = [
        SimpleNamespace(provider_key="picky", enabled=True, name="Picky")
    ]
    handler = FetchSongInfoHandler(
        song_repo=song_repo,
        video_repo=MagicMock(),
        event_bus=MagicMock(),
        lyrics_providers={"picky": provider},
        translator=None,
        media_source=None,
    )
    return handler


class TestPrimaryArtist:
    def test_comma_multi_artist(self):
        assert _primary_artist("NIKI, Phil Collins") == "NIKI"

    def test_feat(self):
        assert _primary_artist("아이유 feat. 이적") == "아이유"
        assert _primary_artist("Artist ft. Other") == "Artist"

    def test_ampersand(self):
        assert _primary_artist("Simon & Garfunkel") == "Simon"

    def test_single_artist_unchanged(self):
        assert _primary_artist("NIKI") == "NIKI"

    def test_empty(self):
        assert _primary_artist("") == ""


class TestRunChainArtistFallback:
    def test_falls_back_to_primary_artist(self):
        """전체 아티스트로 실패하면 주 아티스트로 재시도해 가사를 찾는다."""
        provider = _ArtistPickyProvider(wanted_artist="NIKI")
        handler = _make_handler(provider)

        lyrics, lang, source, artist, album, title, year = handler._run_chain(
            "NIKI, Phil Collins", "You'll Be in My Heart", "", "", None
        )

        assert lyrics == ["line 1", "line 2"]
        assert source is not None
        # 전체 아티스트를 먼저 시도한 뒤 주 아티스트로 재시도했어야 한다.
        assert "NIKI, Phil Collins" in provider.calls
        assert "NIKI" in provider.calls
        # 표시용 아티스트 값은 원본(전체)을 보존한다.
        assert artist == "NIKI, Phil Collins"

    def test_exact_artist_no_redundant_fallback(self):
        """전체 아티스트로 바로 성공하면 주 아티스트 재시도는 하지 않는다."""
        provider = _ArtistPickyProvider(wanted_artist="NIKI, Phil Collins")
        handler = _make_handler(provider)

        lyrics, *_ = handler._run_chain(
            "NIKI, Phil Collins", "You'll Be in My Heart", "", "", None
        )

        assert lyrics == ["line 1", "line 2"]
        assert provider.calls == ["NIKI, Phil Collins"]


class _TaggedProvider:
    """항상 자기 key를 태그한 가사를 반환하는 가짜 제공자."""

    def __init__(self, key: str) -> None:
        self.key = key

    def fetch(self, artist, title, duration_sec=None):
        return LyricsResult(
            lines=[f"{self.key}-lyric"], language="en",
            source_name="ignored", source_url=f"http://{self.key}",
        )


def _multi_handler():
    """출처 A(p1)·B(p2)·C(p3) 순서, 각자 가사를 반환하는 핸들러."""
    song_repo = MagicMock()
    song_repo.list_lyrics_sources.return_value = [
        SimpleNamespace(provider_key="p1", enabled=True, name="A"),
        SimpleNamespace(provider_key="p2", enabled=True, name="B"),
        SimpleNamespace(provider_key="p3", enabled=True, name="C"),
    ]
    return FetchSongInfoHandler(
        song_repo=song_repo, video_repo=MagicMock(), event_bus=MagicMock(),
        lyrics_providers={"p1": _TaggedProvider("p1"), "p2": _TaggedProvider("p2"),
                          "p3": _TaggedProvider("p3")},
        translator=None, media_source=None,
    )


class TestRunChainNextSource:
    def test_default_starts_from_first(self):
        lyrics, _l, source, *_ = _multi_handler()._run_chain("art", "t", "", "", None)
        assert lyrics == ["p1-lyric"] and source.name == "A"

    def test_start_after_picks_next(self):
        lyrics, _l, source, *_ = _multi_handler()._run_chain(
            "art", "t", "", "", None, start_after_name="A"
        )
        assert lyrics == ["p2-lyric"] and source.name == "B"

    def test_start_after_middle(self):
        lyrics, _l, source, *_ = _multi_handler()._run_chain(
            "art", "t", "", "", None, start_after_name="B"
        )
        assert lyrics == ["p3-lyric"] and source.name == "C"

    def test_wraps_around_at_end(self):
        # 마지막 출처(C) 다음 → 처음(A)으로 순환.
        lyrics, _l, source, *_ = _multi_handler()._run_chain(
            "art", "t", "", "", None, start_after_name="C"
        )
        assert lyrics == ["p1-lyric"] and source.name == "A"

    def test_unknown_source_starts_from_first(self):
        lyrics, _l, source, *_ = _multi_handler()._run_chain(
            "art", "t", "", "", None, start_after_name="없는출처"
        )
        assert lyrics == ["p1-lyric"] and source.name == "A"


class _FakeTranslator:
    def __init__(self, lang: str = "en") -> None:
        self._lang = lang

    def detect_language(self, text):
        return self._lang

    def translate(self, texts, target="ko", source="auto"):
        return [f"{t}(번역)" for t in texts]


class TestTranslateSongLyricsHandler:
    def _agg(self, lang="en"):
        agg = SongInfoAggregate.create(uuid4(), is_song=True)
        agg.apply_fetched(
            lyrics_lines=[LyricsLine("a", ""), LyricsLine("b", "")],
            lyrics_language=lang,
        )
        return agg

    def test_translates_non_korean(self):
        agg = self._agg("en")
        repo = MagicMock()
        repo.get.return_value = agg
        TranslateSongLyricsHandler(repo, _FakeTranslator("en"), MagicMock()).handle(
            TranslateSongLyricsCommand(agg.info.video_id)
        )
        assert [ln.translation for ln in agg.info.lyrics_lines] == ["a(번역)", "b(번역)"]
        repo.save.assert_called_once()

    def test_korean_is_noop(self):
        agg = self._agg("ko")
        repo = MagicMock()
        repo.get.return_value = agg
        TranslateSongLyricsHandler(repo, _FakeTranslator("ko"), MagicMock()).handle(
            TranslateSongLyricsCommand(agg.info.video_id)
        )
        assert all(ln.translation == "" for ln in agg.info.lyrics_lines)

    def test_no_translator_is_noop(self):
        agg = self._agg("en")
        repo = MagicMock()
        repo.get.return_value = agg
        TranslateSongLyricsHandler(repo, None, MagicMock()).handle(
            TranslateSongLyricsCommand(agg.info.video_id)
        )
        assert all(ln.translation == "" for ln in agg.info.lyrics_lines)
