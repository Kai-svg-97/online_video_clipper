"""LRCLIB 제공자가 syncedLyrics를 타이밍과 함께 채택하는지 검증한다.

과거에는 syncedLyrics의 타임스탬프를 버리고 텍스트만 썼다. 자막 기능은 이 타이밍이
있어야 하므로, synced가 있으면 그것을 우선 채택해야 한다. 네트워크 대신 세션을
가짜로 주입해 검증한다.
"""
from __future__ import annotations

from unittest.mock import patch

from infrastructure.song.lyrics_providers import LrclibProvider


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FakeSession:
    """/api/get 만 응답하는 최소 세션."""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self._status = status_code
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        if url.endswith("/api/get"):
            return _FakeResponse(self._payload, self._status)
        return _FakeResponse([], 200)   # 검색은 빈 결과


def _fetch(payload):
    with patch(
        "infrastructure.song.lyrics_providers._session",
        return_value=_FakeSession(payload),
    ):
        return LrclibProvider().fetch("Artist", "Title", 200)


class TestSyncedPreferred:
    def test_synced가_있으면_타이밍을_함께_반환한다(self):
        result = _fetch(
            {
                "plainLyrics": "one\ntwo",
                "syncedLyrics": "[00:01.00]one\n[00:05.50]two",
                "artistName": "Artist",
                "albumName": "Album",
                "trackName": "Title",
            }
        )
        assert result is not None
        assert result.lines == ["one", "two"]
        assert result.timings == [1000, 5500]

    def test_synced_텍스트가_plain보다_우선한다(self):
        result = _fetch(
            {
                "plainLyrics": "플레인",
                "syncedLyrics": "[00:02.00]싱크",
            }
        )
        assert result.lines == ["싱크"]
        assert result.timings == [2000]


class TestPlainFallback:
    def test_synced가_없으면_plain을_쓰고_타이밍은_빈_리스트(self):
        result = _fetch({"plainLyrics": "only plain\nsecond"})
        assert result.lines == ["only plain", "second"]
        assert result.timings == []

    def test_synced가_빈_문자열이면_plain으로_폴백(self):
        result = _fetch({"plainLyrics": "plain", "syncedLyrics": ""})
        assert result.lines == ["plain"]
        assert result.timings == []

    def test_synced가_파싱_불가면_plain으로_폴백(self):
        # 타임스탬프가 하나도 없는 문자열 → 타이밍을 얻을 수 없다
        result = _fetch({"plainLyrics": "plain", "syncedLyrics": "타임스탬프 없음"})
        assert result.lines == ["plain"]
        assert result.timings == []

    def test_가사가_전혀_없으면_None(self):
        assert _fetch({"plainLyrics": "", "syncedLyrics": ""}) is None


class TestLengthInvariant:
    def test_timings_길이는_lines와_같다(self):
        result = _fetch({"syncedLyrics": "[00:01.00]a\n[00:02.00]b\n[00:03.00]c"})
        assert len(result.timings) == len(result.lines)
