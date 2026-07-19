"""FetchSongInfoHandler 가사 출처 체인 단위 테스트.

핵심 회귀: yt-dlp가 주는 다중 아티스트 문자열(예: "NIKI, Phil Collins")로는
가사 제공자 검색이 실패한다. 체인은 주 아티스트(콤마/feat 등 분리)로도 재시도해야 한다.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from application.song.commands import FetchSongInfoHandler, _primary_artist
from domain.song.ports import LyricsResult


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
