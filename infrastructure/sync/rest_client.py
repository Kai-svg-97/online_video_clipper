"""Bearer 토큰 REST 헬퍼 — Google Drive / OneDrive provider 공용.

`infrastructure/youtube/youtube_api_adapter.py`의 requests + verify=False + 401 강제
refresh 후 1회 재시도 패턴을 두 provider가 공유하도록 추출했다. VPN·보안 소프트웨어가
HTTPS를 인터셉트하는 환경에서 httplib2/googleapiclient는 TLS 핸드셰이크가 실패하므로
requests 로 직접 호출한다.

토큰 획득/갱신 방식은 provider마다 다르므로(google.oauth2 Credentials vs msal) 콜백으로
주입한다: `token_provider()` 는 현재 유효한 access token 문자열을, `force_refresh()` 는
401 시 강제 갱신을 담당한다. 세션은 테스트에서 주입 가능하다(가짜 세션).
"""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)


class RestClient:
    def __init__(
        self,
        token_provider: Callable[[], str],
        force_refresh: Callable[[], None] | None = None,
        session=None,
        verify: bool = False,
        timeout: int = 60,
    ) -> None:
        self._token_provider = token_provider
        self._force_refresh = force_refresh
        self._session = session
        self._verify = verify
        self._timeout = timeout

    def _sess(self):
        if self._session is None:
            import requests  # noqa: PLC0415
            import urllib3  # noqa: PLC0415

            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            s = requests.Session()
            s.verify = self._verify
            self._session = s
        return self._session

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict | None = None,
        params: dict | None = None,
        json: dict | None = None,
        data=None,
        stream: bool = False,
        timeout: int | None = None,
    ):
        """Bearer 인증을 붙여 요청하고, 401이면 토큰을 강제 갱신 후 1회 재시도한다."""

        def _do():
            h = dict(headers or {})
            h["Authorization"] = f"Bearer {self._token_provider()}"
            return self._sess().request(
                method,
                url,
                headers=h,
                params=params,
                json=json,
                data=data,
                stream=stream,
                timeout=timeout or self._timeout,
            )

        r = _do()
        if r.status_code == 401 and self._force_refresh is not None:
            logger.info("401 — 토큰 강제 갱신 후 재시도: %s %s", method, url)
            self._force_refresh()
            r = _do()
        return r
