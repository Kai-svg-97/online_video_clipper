"""YouTube OAuth2 인증 어댑터.

google-auth-oauthlib InstalledAppFlow 기반.
토큰은 yt_oauth_tokens SQLite 테이블에 JSON으로 저장한다.
"""
from __future__ import annotations

import json
from typing import Any

SCOPES = ["https://www.googleapis.com/auth/youtube"]

_TOKEN_KEY = "yt_api_credentials"


class YouTubeOAuthAdapter:
    """YouTube Data API v3용 OAuth2 자격증명 관리."""

    def __init__(self, db) -> None:
        self._db = db  # infrastructure.persistence.database.Database

    # ── 공개 API ─────────────────────────────────────────────────────────────

    def get_credentials(self) -> Any | None:
        """DB에서 저장된 자격증명을 로드하고 필요 시 갱신한다."""
        from google.oauth2.credentials import Credentials  # noqa: PLC0415
        data = self._load_token()
        if not data:
            return None
        try:
            creds = Credentials(
                token=data.get("token"),
                refresh_token=data.get("refresh_token"),
                token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
                client_id=data.get("client_id"),
                client_secret=data.get("client_secret"),
                scopes=data.get("scopes", SCOPES),
            )
            # expiry 복원 — 없으면 만료 여부를 알 수 없으므로 강제 갱신
            expiry_str = data.get("expiry")
            if expiry_str:
                from datetime import datetime  # noqa: PLC0415
                creds.expiry = datetime.fromisoformat(expiry_str)

            needs_refresh = creds.refresh_token and (creds.expired or not expiry_str)
            if needs_refresh:
                import requests as _requests  # noqa: PLC0415
                import urllib3  # noqa: PLC0415
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                _sess = _requests.Session()
                _sess.verify = False
                from google.auth.transport.requests import Request as _GReq  # noqa: PLC0415
                creds.refresh(_GReq(session=_sess))
                self.save_credentials(creds)
            return creds
        except Exception:
            return None

    def run_auth_flow(self, client_id: str, client_secret: str) -> Any:
        """브라우저 OAuth 인증 플로우를 실행하고 자격증명을 반환한다."""
        from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: PLC0415
        client_config = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
            }
        }
        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
        self.save_credentials(creds)
        return creds

    def save_credentials(self, creds) -> None:
        """자격증명을 DB에 저장한다."""
        data = {
            "token": creds.token,
            "refresh_token": creds.refresh_token,
            "token_uri": creds.token_uri,
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "scopes": list(creds.scopes) if creds.scopes else SCOPES,
            "expiry": creds.expiry.isoformat() if creds.expiry else None,
        }
        with self._db.connection() as conn:
            conn.execute(
                "INSERT INTO yt_oauth_tokens(key, value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (_TOKEN_KEY, json.dumps(data)),
            )

    def clear(self) -> None:
        """저장된 자격증명을 삭제한다."""
        with self._db.connection() as conn:
            conn.execute(
                "DELETE FROM yt_oauth_tokens WHERE key=?", (_TOKEN_KEY,)
            )

    def is_authenticated(self) -> bool:
        """유효한 자격증명이 있으면 True."""
        creds = self.get_credentials()
        return creds is not None and creds.valid

    def get_channel_name(self) -> str | None:
        """현재 인증된 YouTube 채널명을 반환한다."""
        try:
            creds = self.get_credentials()
            if creds is None:
                return None
            from infrastructure.youtube.youtube_api_adapter import YouTubeApiAdapter  # noqa: PLC0415
            return YouTubeApiAdapter(creds).get_channel_name()
        except Exception:
            pass
        return None

    # ── 내부 헬퍼 ────────────────────────────────────────────────────────────

    def _load_token(self) -> dict | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT value FROM yt_oauth_tokens WHERE key=?", (_TOKEN_KEY,)
            ).fetchone()
        if row:
            try:
                return json.loads(row["value"])
            except Exception:
                pass
        return None
