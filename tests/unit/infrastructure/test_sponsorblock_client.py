"""SponsorBlock API 어댑터 — 해시 접두 조회와 실패 처리.

두 가지가 핵심이다. **영상 ID를 그대로 보내지 않는 것**(보내면 서버가 시청 이력을
그대로 알게 된다), 그리고 **무슨 일이 나도 예외를 내지 않는 것**(건너뛰기는 부가
기능이라 여기서 터지면 재생이 막힌다).
"""

from __future__ import annotations

import hashlib
import json

import pytest
import requests

from infrastructure.sponsorblock.client import SponsorBlockClient

VIDEO_ID = "abcdefghijk"
PREFIX = hashlib.sha256(VIDEO_ID.encode()).hexdigest()[:4]


class _Resp:
    def __init__(self, payload=None, status=200, raise_json=False):
        self._payload = payload
        self.status_code = status
        self._raise_json = raise_json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        if self._raise_json:
            raise ValueError("not json")
        return self._payload


@pytest.fixture
def captured(monkeypatch):
    """requests.get 을 가로채 (url, params)를 기록하고 지정한 응답을 돌려준다."""
    box = {"url": None, "params": None, "resp": _Resp([])}

    def fake_get(url, params=None, timeout=None, headers=None):
        box["url"], box["params"] = url, params
        return box["resp"]

    monkeypatch.setattr(requests, "get", fake_get)
    return box


class TestPrivacy:
    def test_영상ID가_아니라_해시_앞자리를_보낸다(self, captured):
        SponsorBlockClient().fetch_segments(VIDEO_ID, ("sponsor",))
        assert captured["url"].endswith(f"/{PREFIX}")
        assert VIDEO_ID not in captured["url"]
        assert VIDEO_ID not in json.dumps(captured["params"])

    def test_카테고리는_JSON_배열로_보낸다(self, captured):
        SponsorBlockClient().fetch_segments(VIDEO_ID, ("sponsor", "intro"))
        assert json.loads(captured["params"]["categories"]) == ["sponsor", "intro"]


class TestParsing:
    def test_우리_영상의_구간만_골라낸다(self, captured):
        """해시 접두 응답에는 남의 영상이 잔뜩 섞여 온다."""
        captured["resp"] = _Resp([
            {"videoID": "zzzzzzzzzzz", "segments": [
                {"category": "sponsor", "segment": [0, 100]}]},
            {"videoID": VIDEO_ID, "segments": [
                {"category": "sponsor", "segment": [10.5, 20.5]}]},
        ])
        got = SponsorBlockClient().fetch_segments(VIDEO_ID, ("sponsor",))
        assert got == [("sponsor", 10.5, 20.5)]

    def test_형식이_이상한_구간만_건너뛴다(self, captured):
        """공개 API라 우리가 고칠 수 없다 — 한 항목 때문에 전체를 버리면 안 된다."""
        captured["resp"] = _Resp([{"videoID": VIDEO_ID, "segments": [
            {"category": "sponsor", "segment": ["없는값"]},
            {"segment": [1, 2]},
            {"category": "sponsor", "segment": [10, 20]},
        ]}])
        assert SponsorBlockClient().fetch_segments(VIDEO_ID, ("sponsor",)) == [
            ("sponsor", 10.0, 20.0)
        ]

    def test_응답이_리스트가_아니면_빈_목록(self, captured):
        captured["resp"] = _Resp({"error": "nope"})
        assert SponsorBlockClient().fetch_segments(VIDEO_ID, ("sponsor",)) == []


class TestFailure:
    def test_404는_등록된_구간이_없다는_뜻이다(self, captured):
        captured["resp"] = _Resp(None, status=404)
        assert SponsorBlockClient().fetch_segments(VIDEO_ID, ("sponsor",)) == []

    def test_서버_오류여도_예외를_내지_않는다(self, captured):
        captured["resp"] = _Resp(None, status=500)
        assert SponsorBlockClient().fetch_segments(VIDEO_ID, ("sponsor",)) == []

    def test_네트워크_실패여도_예외를_내지_않는다(self, monkeypatch):
        def boom(*a, **k):
            raise requests.ConnectionError("끊김")

        monkeypatch.setattr(requests, "get", boom)
        assert SponsorBlockClient().fetch_segments(VIDEO_ID, ("sponsor",)) == []

    def test_JSON이_아니어도_예외를_내지_않는다(self, captured):
        captured["resp"] = _Resp(None, raise_json=True)
        assert SponsorBlockClient().fetch_segments(VIDEO_ID, ("sponsor",)) == []


class TestGuards:
    def test_영상ID가_비면_묻지_않는다(self, captured):
        assert SponsorBlockClient().fetch_segments("", ("sponsor",)) == []
        assert captured["url"] is None

    def test_카테고리가_비면_묻지_않는다(self, captured):
        assert SponsorBlockClient().fetch_segments(VIDEO_ID, ()) == []
        assert captured["url"] is None
