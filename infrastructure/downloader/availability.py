"""원본 영상 생존 확인 어댑터 — YouTube oEmbed.

**왜 yt-dlp가 아닌가**: `extract_info`는 정확하지만 영상당 1초 안팎이 걸린다.
수백 건을 훑는 점검 화면에서는 몇 분이 되어 쓸 수 없다. oEmbed는 요청 하나로
살아 있는지만 알려 주고(200/404/401) 훨씬 가볍다.

**한계**: YouTube만 답한다. 다른 사이트는 '확인 불가'로 두는데, 확인하지 못한 것을
'사라졌다'고 보고하면 멀쩡한 영상을 지우게 만들기 때문이다.
"""

from __future__ import annotations

import logging

import requests

from domain.library.availability import (
    STATUS_UNKNOWN,
    AvailabilityResult,
    classify_http_status,
)
from domain.library.value_objects import extract_youtube_video_id

logger = logging.getLogger(__name__)

_OEMBED = "https://www.youtube.com/oembed"

# 한 건이라도 오래 붙들면 수백 건 점검이 끝나지 않는다.
_TIMEOUT = (4, 6)   # (connect, read)


class YouTubeAvailabilityChecker:
    """`IAvailabilitySource` 구현. 배경 QThread에서만 호출한다."""

    def __init__(self, session: requests.Session | None = None) -> None:
        # 세션을 재사용해 연결을 유지한다 — 수백 건을 연달아 물어보는 용도다.
        self._session = session or requests.Session()

    def check(self, url: str) -> AvailabilityResult:
        if not extract_youtube_video_id(url):
            return AvailabilityResult(STATUS_UNKNOWN, "YouTube 영상이 아닙니다")
        try:
            resp = self._session.get(
                _OEMBED,
                params={"url": url, "format": "json"},
                timeout=_TIMEOUT,
            )
        except requests.RequestException as exc:
            # 네트워크 실패는 흔하고 영상의 문제가 아니다 — 트레이스백 없이 한 줄만.
            logger.warning("원본 확인 실패(네트워크): %s", url)
            return AvailabilityResult(STATUS_UNKNOWN, str(exc)[:120])
        return classify_http_status(resp.status_code)
