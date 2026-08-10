"""YouTube OAuth2 인증 어댑터.

google-auth-oauthlib InstalledAppFlow(Desktop, PKCE) 기반. 사용자 토큰은
**keyring 우선**(주입된 secret_store) 저장소에 JSON으로 둔다. 과거 SQLite
`yt_oauth_tokens` 테이블에 있던 토큰은 최초 조회 시 1회 자동 마이그레이션되고
(secret store 기록·검증 후) 원본 행은 삭제된다 — secret store 기록이 확인되지
않으면 인증 유실을 막기 위해 SQLite 레코드를 그대로 둔다.

Desktop OAuth 클라이언트 설정(Client ID/Secret) 자체는 `client_config_path`로
주입받는다 — 이 모듈은 그 파일의 내용을 읽어 인증 플로우에 넘기기만 하고
값을 저장하거나 로그로 남기지 않는다.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube"]

_TOKEN_KEY = "youtube.oauth.credentials.v1"
_LEGACY_DB_TOKEN_KEY = "yt_api_credentials"


def _serialize_credentials(creds) -> str:
    payload = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else SCOPES,
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }
    return json.dumps(payload)


def _parse_token(raw: str | None) -> dict | None:
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        logger.exception("YouTube OAuth 토큰 JSON 파싱 실패")
        return None
    return data if isinstance(data, dict) else None


class YouTubeOAuthAdapter:
    """YouTube Data API v3용 OAuth2 자격증명 관리."""

    def __init__(self, db, secret_store, client_config_path: Path | None) -> None:
        self._db = db  # infrastructure.persistence.database.Database
        self._secret_store = secret_store  # ISecretStore 구조적 타입(get/set/delete)
        self._client_config_path = client_config_path

    # ── 공개 API ─────────────────────────────────────────────────────────────

    def has_client_config(self) -> bool:
        """번들된(또는 로컬 개발용) Desktop OAuth 클라이언트 설정이 있는지."""
        return self._client_config_path is not None

    def get_credentials(self) -> Any | None:
        """저장된 자격증명을 로드하고 필요 시 갱신한다."""
        from google.auth.exceptions import RefreshError  # noqa: PLC0415
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
                from google.auth.transport.requests import Request as _GReq  # noqa: PLC0415
                creds.refresh(_GReq())
                self.save_credentials(creds)
            return creds
        except RefreshError as exc:
            # 토큰 만료/취소는 재인증으로 해소되는 예상 상황 — 스택트레이스 없이 경고만 남긴다.
            logger.warning("OAuth 토큰 만료/취소됨 — 재인증이 필요합니다: %s", exc)
            return None
        except Exception:
            logger.exception("OAuth 자격증명 로드/갱신 실패")
            return None

    def run_auth_flow(self) -> Any:
        """시스템 브라우저 OAuth(Desktop/PKCE/loopback) 플로우를 실행한다."""
        from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: PLC0415
        from infrastructure.youtube.oauth_client_config import (  # noqa: PLC0415
            OAuthClientConfigError,
        )
        if self._client_config_path is None:
            raise OAuthClientConfigError("YouTube OAuth 클라이언트 설정이 포함되지 않았습니다.")
        flow = InstalledAppFlow.from_client_secrets_file(
            str(self._client_config_path),
            SCOPES,
            autogenerate_code_verifier=True,
        )
        creds = flow.run_local_server(
            host="127.0.0.1",
            port=0,
            prompt="consent",
            access_type="offline",
            open_browser=True,
        )
        self.save_credentials(creds)
        return creds

    def save_credentials(self, creds) -> None:
        """자격증명을 secret store에 저장한다."""
        self._secret_store.set(_TOKEN_KEY, _serialize_credentials(creds))

    def clear(self) -> None:
        """저장된 자격증명을 secret store와 레거시 DB 양쪽에서 삭제한다."""
        self._secret_store.delete(_TOKEN_KEY)
        self._delete_legacy_db_token()

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
            logger.exception("YouTube 채널명 조회 실패")
        return None

    # ── 내부 헬퍼 ────────────────────────────────────────────────────────────

    def _load_token(self) -> dict | None:
        raw = self._secret_store.get(_TOKEN_KEY)
        data = _parse_token(raw)
        if data is not None:
            return data
        if raw is not None:
            # secret store에 값은 있지만 파싱이 실패한 경우 — legacy로 폴백하지 않는다.
            return None
        return self._migrate_legacy_db_token()

    def _migrate_legacy_db_token(self) -> dict | None:
        legacy_raw = self._read_legacy_db_token_raw()
        if legacy_raw is None:
            return None
        data = _parse_token(legacy_raw)
        if data is None:
            return None
        self._secret_store.set(_TOKEN_KEY, legacy_raw)
        confirmed = self._secret_store.get(_TOKEN_KEY)
        if confirmed != legacy_raw:
            # 저장이 확인되지 않으면 인증 유실을 막기 위해 SQLite 레코드를 남겨둔다.
            logger.warning("YouTube OAuth 토큰 마이그레이션 확인 실패 — 레거시 레코드 보존")
            return data
        self._delete_legacy_db_token()
        return data

    def _read_legacy_db_token_raw(self) -> str | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT value FROM yt_oauth_tokens WHERE key=?",
                (_LEGACY_DB_TOKEN_KEY,),
            ).fetchone()
        return row["value"] if row else None

    def _delete_legacy_db_token(self) -> None:
        with self._db.connection() as conn:
            conn.execute(
                "DELETE FROM yt_oauth_tokens WHERE key=?",
                (_LEGACY_DB_TOKEN_KEY,),
            )
