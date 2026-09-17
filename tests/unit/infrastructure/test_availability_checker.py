"""원본 생존 확인 어댑터 — oEmbed 조회와 실패 내성.

`extract_info`가 아니라 oEmbed를 쓰는 이유는 속도다(영상당 1초 vs. 수십 ms).
수백 건을 훑는 화면에서는 그 차이가 '쓸 수 있다/없다'를 가른다.
"""

from __future__ import annotations

import pytest
import requests

from domain.library.availability import (
    STATUS_OK,
    STATUS_PRIVATE,
    STATUS_REMOVED,
    STATUS_UNKNOWN,
)
from infrastructure.downloader.availability import YouTubeAvailabilityChecker

URL = "https://www.youtube.com/watch?v=abcdefghijk"


class _Session:
    def __init__(self, status=200, raise_exc=None):
        self.status = status
        self.raise_exc = raise_exc
        self.calls: list[tuple] = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        if self.raise_exc:
            raise self.raise_exc
        return type("R", (), {"status_code": self.status})()


@pytest.mark.parametrize(
    "code,expected",
    [(200, STATUS_OK), (404, STATUS_REMOVED), (401, STATUS_PRIVATE), (500, STATUS_UNKNOWN)],
)
def test_응답_코드를_상태로_옮긴다(code, expected):
    checker = YouTubeAvailabilityChecker(_Session(code))
    assert checker.check(URL).status == expected


def test_oembed로_영상_주소를_보낸다():
    session = _Session()
    YouTubeAvailabilityChecker(session).check(URL)
    url, params = session.calls[0]
    assert url.endswith("/oembed")
    assert params["url"] == URL


def test_YouTube가_아니면_묻지_않고_확인_불가다():
    """확인할 방법이 없는 것을 '사라졌다'고 보고하면 멀쩡한 영상을 지우게 된다."""
    session = _Session()
    result = YouTubeAvailabilityChecker(session).check("https://vimeo.com/123")
    assert result.status == STATUS_UNKNOWN
    assert session.calls == []


def test_네트워크가_끊겨도_예외를_내지_않는다():
    checker = YouTubeAvailabilityChecker(_Session(raise_exc=requests.ConnectionError("끊김")))
    assert checker.check(URL).status == STATUS_UNKNOWN


def test_타임아웃도_확인_불가다():
    checker = YouTubeAvailabilityChecker(_Session(raise_exc=requests.Timeout("느림")))
    assert checker.check(URL).status == STATUS_UNKNOWN
