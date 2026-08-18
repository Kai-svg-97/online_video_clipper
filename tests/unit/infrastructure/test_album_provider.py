"""iTunes 앨범 제공자 — 가짜 세션으로 왕복을 검증한다(네트워크 없음).

검증 대상은 "무엇을 요청하고, 응답에서 무엇을 뽑아내며, 실패를 어떻게 삼키는가"다.
실패를 예외로 흘리면 앨범 화면 전체가 죽으므로 None 반환이 계약이다.
"""
from __future__ import annotations

import requests

from infrastructure.song.album_providers import ITunesAlbumProvider, upgrade_artwork_url

ALBUM_RESULT = {
    "resultCount": 1,
    "results": [
        {
            "wrapperType": "collection",
            "collectionId": 1234,
            "collectionName": "Palette",
            "artistName": "IU",
            "artworkUrl100": "https://is1.mzstatic.com/image/aaa/100x100bb.jpg",
            "releaseDate": "2017-04-21T07:00:00Z",
            "primaryGenreName": "K-Pop",
            "copyright": "℮ 2017 KAKAO",
            "trackCount": 2,
            "collectionViewUrl": "https://music.apple.com/kr/album/1234",
        }
    ],
}

LOOKUP_RESULT = {
    "resultCount": 3,
    "results": [
        ALBUM_RESULT["results"][0],
        {
            "wrapperType": "track", "trackNumber": 2, "trackName": "밤편지",
            "artistName": "IU", "trackTimeMillis": 254000,
        },
        {
            "wrapperType": "track", "trackNumber": 1, "trackName": "Palette",
            "artistName": "IU", "trackTimeMillis": 217000,
        },
    ],
}

SONG_SEARCH_RESULT = {
    "resultCount": 1,
    "results": [
        {
            "wrapperType": "track", "trackName": "밤편지", "artistName": "IU",
            "collectionId": 1234,
        }
    ],
}


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeSession:
    """요청 URL·파라미터를 기록하고 미리 정한 응답을 돌려주는 가짜 세션."""

    def __init__(self, router):
        self._router = router
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        payload = self._router(url, params or {})
        if isinstance(payload, Exception):
            raise payload
        return _Resp(payload)


def _router(url, params):
    if url.endswith("/lookup"):
        return LOOKUP_RESULT
    if params.get("entity") == "album":
        return ALBUM_RESULT
    return SONG_SEARCH_RESULT


class TestFetchAlbum:
    def test_자켓_발매일_장르_수록곡을_뽑는다(self):
        session = _FakeSession(_router)
        provider = ITunesAlbumProvider(session=session)

        meta = provider.fetch_album("IU", "Palette")

        assert meta is not None
        assert meta.album_title == "Palette"
        assert meta.artist == "IU"
        assert meta.release_date == "2017-04-21"
        assert meta.genre == "K-Pop"
        # 자켓은 큰 해상도로 바꿔 받는다 — 100x100은 카드에서 뭉갠다.
        assert meta.artwork_url.endswith("600x600bb.jpg")

    def test_수록곡을_트랙번호_순으로_정렬한다(self):
        provider = ITunesAlbumProvider(session=_FakeSession(_router))

        meta = provider.fetch_album("IU", "Palette")

        assert [t.track_no for t in meta.tracks] == [1, 2]
        assert [t.title for t in meta.tracks] == ["Palette", "밤편지"]
        assert meta.tracks[0].duration_sec == 217

    def test_수록곡_조회에는_국가를_붙이지_않는다(self):
        """iTunes lookup에 country를 붙이면 수록곡이 빠진 채 앨범만 돌아온다(실측).

        이걸 놓치면 14곡짜리 앨범이 '내 곡 1개'로만 보이고, 빠진 곡 자동 채우기도
        할 일이 없다고 판단해 조용히 아무것도 하지 않는다.
        """
        session = _FakeSession(_router)
        provider = ITunesAlbumProvider(session=session)

        provider.fetch_album("IU", "Palette")

        lookups = [params for url, params in session.calls if url.endswith("/lookup")]
        assert lookups, "lookup 호출이 없다"
        assert all("country" not in p for p in lookups)
        assert all(p.get("entity") == "song" for p in lookups)

    def test_앨범명이_없으면_요청하지_않는다(self):
        session = _FakeSession(_router)
        provider = ITunesAlbumProvider(session=session)

        assert provider.fetch_album("IU", "") is None
        assert session.calls == []

    def test_네트워크_실패는_None이다(self):
        def boom(url, params):
            return requests.exceptions.Timeout("timeout")

        provider = ITunesAlbumProvider(session=_FakeSession(boom))

        assert provider.fetch_album("IU", "Palette") is None

    def test_결과가_없으면_None이다(self):
        provider = ITunesAlbumProvider(session=_FakeSession(lambda u, p: {"results": []}))

        assert provider.fetch_album("IU", "없는앨범") is None


class TestFindAlbumOfTrack:
    def test_곡만_알아도_앨범을_찾는다(self):
        provider = ITunesAlbumProvider(session=_FakeSession(_router))

        meta = provider.find_album_of_track("IU", "밤편지")

        assert meta is not None
        assert meta.album_title == "Palette"

    def test_제목이_다르면_None이다(self):
        provider = ITunesAlbumProvider(session=_FakeSession(_router))

        assert provider.find_album_of_track("IU", "전혀 다른 곡") is None


def test_자켓_URL_패턴이_다르면_그대로_둔다():
    assert upgrade_artwork_url("https://x/y.jpg") == "https://x/y.jpg"
    assert upgrade_artwork_url("") == ""
