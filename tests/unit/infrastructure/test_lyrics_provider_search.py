"""제공자 다건 검색(`search`) 검증 — 같은 제목의 다른 가수 곡을 모두 돌려주는가.

예전에는 제공자가 `fetch`로 "가장 그럴듯한 한 곡"만 돌려줘, 검색 결과에 같은 제목의
다른 가수 곡이 나란히 있어도 항상 맨 위 한 곡만 걸렸다. 네트워크 대신 세션을 가짜로
주입해 검증한다.
"""
from __future__ import annotations

from unittest.mock import patch

from infrastructure.song.lyrics_providers import (
    GeniusProvider,
    LrclibProvider,
    _first_id,
)


class _FakeResponse:
    def __init__(self, payload=None, text="", status_code=200):
        self._payload = payload
        self.text = text
        self.status_code = status_code

    def json(self):
        return self._payload


class _LrclibSession:
    """/api/get(정확 조회) + /api/search(목록)를 흉내 내는 세션."""

    def __init__(self, exact=None, by_artist=None, by_title=None):
        self._exact = exact
        self._by_artist = by_artist or []
        self._by_title = by_title or []
        self.headers = {}
        self.search_params: list[dict] = []

    def get(self, url, params=None, timeout=None):
        if url.endswith("/api/get"):
            return _FakeResponse(self._exact, status_code=200 if self._exact else 404)
        self.search_params.append(dict(params or {}))
        if (params or {}).get("artist_name"):
            return _FakeResponse(self._by_artist)
        return _FakeResponse(self._by_title)


def _entry(artist, title="같은제목", lyrics="첫 줄\n둘째 줄", synced="", duration=None):
    return {
        "artistName": artist,
        "trackName": title,
        "albumName": "",
        "plainLyrics": lyrics,
        "syncedLyrics": synced,
        "duration": duration,
    }


def _search_lrclib(session, artist="가수1", title="같은제목", limit=10, duration=None):
    with patch(
        "infrastructure.song.lyrics_providers._session", return_value=session
    ):
        return LrclibProvider().search(artist, title, duration, limit)


class TestLrclibSearch:
    def test_같은_제목의_여러_가수_곡을_모두_돌려준다(self):
        session = _LrclibSession(
            by_artist=[_entry("가수1")],
            by_title=[_entry("가수1"), _entry("가수2"), _entry("가수3")],
        )
        results = _search_lrclib(session)
        assert [r.artist for r in results] == ["가수1", "가수2", "가수3"]

    def test_가수를_지정해도_제목만으로_한_번_더_검색한다(self):
        """가수 포함 검색만 하면 '다른 가수의 같은 제목'이 영영 안 나온다."""
        session = _LrclibSession(by_artist=[_entry("가수1")], by_title=[_entry("가수2")])
        _search_lrclib(session)
        assert [p.get("artist_name", "") for p in session.search_params] == ["가수1", ""]

    def test_정확_조회_결과가_맨_앞에_온다(self):
        session = _LrclibSession(
            exact=_entry("정확가수"),
            by_title=[_entry("다른가수")],
        )
        results = _search_lrclib(session)
        assert [r.artist for r in results] == ["정확가수", "다른가수"]

    def test_중복된_곡은_한_번만_담는다(self):
        session = _LrclibSession(
            exact=_entry("가수1"),
            by_artist=[_entry("가수1")],
            by_title=[_entry("가수1"), _entry("가수2")],
        )
        results = _search_lrclib(session)
        assert [r.artist for r in results] == ["가수1", "가수2"]

    def test_상한을_지키고_0이면_무제한이다(self):
        many = [_entry(f"가수{i}") for i in range(6)]
        assert len(_search_lrclib(_LrclibSession(by_title=many), limit=2)) == 2
        assert len(_search_lrclib(_LrclibSession(by_title=many), limit=0)) == 6

    def test_가사가_없는_항목은_후보에서_뺀다(self):
        session = _LrclibSession(
            by_title=[_entry("가수1", lyrics=""), _entry("가수2")]
        )
        assert [r.artist for r in _search_lrclib(session)] == ["가수2"]

    def test_영상_길이에_가까운_곡을_앞으로_올린다(self):
        """LRCLIB은 조회수를 주지 않아 곡 길이가 유일한 판별 신호다."""
        session = _LrclibSession(
            by_title=[
                _entry("먼가수", duration=300),
                _entry("가까운가수", duration=205),
                _entry("중간가수", duration=240),
            ]
        )
        results = _search_lrclib(session, duration=200)
        assert [r.artist for r in results] == ["가까운가수", "중간가수", "먼가수"]

    def test_길이_미상_후보는_뒤로_보내되_버리지_않는다(self):
        session = _LrclibSession(
            by_title=[_entry("길이없음"), _entry("길이있음", duration=201)]
        )
        results = _search_lrclib(session, duration=200)
        assert [r.artist for r in results] == ["길이있음", "길이없음"]

    def test_영상_길이를_모르면_출처_순서를_지킨다(self):
        session = _LrclibSession(
            by_title=[_entry("첫째", duration=300), _entry("둘째", duration=200)]
        )
        results = _search_lrclib(session, duration=None)
        assert [r.artist for r in results] == ["첫째", "둘째"]

    def test_정렬한_뒤에_상한을_적용한다(self):
        """먼저 자르면 뒤쪽에 있던 정답(길이가 맞는 곡)이 날아간다."""
        session = _LrclibSession(
            by_title=[
                _entry("먼가수1", duration=400),
                _entry("먼가수2", duration=500),
                _entry("정답", duration=200),
            ]
        )
        results = _search_lrclib(session, duration=200, limit=1)
        assert [r.artist for r in results] == ["정답"]

    def test_fetch는_여전히_한_건만_돌려준다(self):
        """체인 검색(등록 시 자동 보강·싱크 가사 찾기)이 쓰는 계약은 그대로다."""
        session = _LrclibSession(by_title=[_entry("가수1"), _entry("가수2")])
        with patch(
            "infrastructure.song.lyrics_providers._session", return_value=session
        ):
            one = LrclibProvider().fetch("가수1", "같은제목")
        assert one is not None and one.artist == "가수1"


_GENIUS_PAGE = """
<html><head><meta property="og:title" content="같은제목 by {artist}"></head>
<body><div data-lyrics-container="true">{artist}의 첫 줄<br>둘째 줄</div></body></html>
"""


class _GeniusSession:
    """``urls``는 URL 문자열 또는 (URL, 조회수) 튜플."""

    def __init__(self, urls, fail_urls=()):
        self._urls = [u if isinstance(u, tuple) else (u, 0) for u in urls]
        self._fail = set(fail_urls)
        self.headers = {}
        self.fetched: list[str] = []

    def get(self, url, params=None, timeout=None):
        if "api/search/multi" in url:
            return _FakeResponse(
                {
                    "response": {
                        "sections": [
                            {
                                "hits": [
                                    {
                                        "type": "song",
                                        "result": {"url": u, "stats": {"pageviews": v}},
                                    }
                                    for u, v in self._urls
                                ]
                            }
                        ]
                    }
                }
            )
        self.fetched.append(url)
        if url in self._fail:
            return _FakeResponse(text="", status_code=500)
        artist = url.rsplit("/", 1)[-1]
        return _FakeResponse(text=_GENIUS_PAGE.format(artist=artist))


def _search_genius(session, limit=10):
    with patch(
        "infrastructure.song.lyrics_providers._session", return_value=session
    ):
        return GeniusProvider().search("가수1", "같은제목", None, limit)


class TestGeniusSearch:
    def test_검색_히트_전부를_후보로_만든다(self):
        session = _GeniusSession(["https://g/가수1", "https://g/가수2", "https://g/가수3"])
        results = _search_genius(session)
        assert [r.artist for r in results] == ["가수1", "가수2", "가수3"]

    def test_상한만큼만_페이지를_긁는다(self):
        """limit이 곧 HTTP 요청 수라 상한이 지켜지지 않으면 검색이 매우 느려진다."""
        session = _GeniusSession([f"https://g/가수{i}" for i in range(6)])
        results = _search_genius(session, limit=2)
        assert len(results) == 2
        assert len(session.fetched) == 2

    def test_곡_하나가_실패해도_나머지는_모은다(self):
        session = _GeniusSession(
            ["https://g/가수1", "https://g/가수2"], fail_urls=["https://g/가수1"]
        )
        assert [r.artist for r in _search_genius(session)] == ["가수2"]

    def test_조회수_내림차순으로_정렬한다(self):
        session = _GeniusSession(
            [("https://g/보통", 5_000), ("https://g/인기", 900_000), ("https://g/비인기", 12)]
        )
        results = _search_genius(session)
        assert [r.artist for r in results] == ["인기", "보통", "비인기"]
        assert [r.popularity for r in results] == [900_000, 5_000, 12]

    def test_상한이_있어도_인기곡을_먼저_긁는다(self):
        """정렬을 페이지 요청 뒤에 하면 인기 곡이 상한 밖으로 밀려 조회조차 안 된다."""
        session = _GeniusSession(
            [("https://g/비인기", 1), ("https://g/보통", 100), ("https://g/인기", 999_999)]
        )
        results = _search_genius(session, limit=1)
        assert [r.artist for r in results] == ["인기"]
        assert session.fetched == ["https://g/인기"]

    def test_조회수가_없으면_원래_순서를_지킨다(self):
        session = _GeniusSession(["https://g/첫째", "https://g/둘째"])
        assert [r.artist for r in _search_genius(session)] == ["첫째", "둘째"]


class TestSearchIdExtraction:
    """국내 스크래퍼 공통 — 검색 페이지에서 곡 id를 **전부** 뽑아야 한다."""

    def test_등장_순서대로_모두_뽑고_중복은_제거한다(self):
        html = "goSongDetail('111') goSongDetail('222') goSongDetail('111')"
        assert _first_id(html, (r"goSongDetail\('(\d+)'\)",)) == ["111", "222"]

    def test_앞_패턴으로_잡히면_폴백_패턴은_쓰지_않는다(self):
        html = "goSongDetail('111') songId=999"
        assert _first_id(html, (r"goSongDetail\('(\d+)'\)", r"songId=(\d+)")) == ["111"]

    def test_앞_패턴이_비면_폴백_패턴을_쓴다(self):
        assert _first_id("songId=999", (r"goSongDetail\('(\d+)'\)", r"songId=(\d+)")) == ["999"]

    def test_아무것도_없으면_빈_목록(self):
        assert _first_id("결과 없음", (r"songId=(\d+)",)) == []
