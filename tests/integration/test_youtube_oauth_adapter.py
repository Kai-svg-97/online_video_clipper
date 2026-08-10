"""YouTubeOAuthAdapter — keyring 우선 토큰 저장 + 레거시 SQLite 마이그레이션 통합 테스트.

실제 임시 SQLite DB(Database)를 쓰고, keyring 대신 인메모리 FakeSecretStore를
주입한다. Google 네트워크/브라우저 플로우는 전부 monkeypatch로 대체한다.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest

from infrastructure.persistence.database import Database
from infrastructure.youtube.oauth_adapter import (
    SCOPES,
    _LEGACY_DB_TOKEN_KEY,
    _TOKEN_KEY,
    YouTubeOAuthAdapter,
)


SYNTHETIC_CREDENTIAL_DATA = {
    "token": "synthetic-access-token",
    "refresh_token": "synthetic-refresh-token",
    "token_uri": "https://oauth2.googleapis.com/token",
    "client_id": "synthetic.apps.googleusercontent.com",
    "client_secret": "synthetic-secret",
    "scopes": SCOPES,
    "expiry": "2099-01-01T00:00:00",
}


class FakeSecretStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


class FakeCredentials:
    """직렬화 대상 속성만 흉내내는 최소 자격증명 더블."""

    def __init__(
        self,
        token="synthetic-access-token",
        refresh_token="synthetic-refresh-token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="synthetic.apps.googleusercontent.com",
        client_secret="synthetic-secret",
        scopes=None,
        expiry=None,
        valid=True,
        expired=False,
    ) -> None:
        self.token = token
        self.refresh_token = refresh_token
        self.token_uri = token_uri
        self.client_id = client_id
        self.client_secret = client_secret
        self.scopes = scopes if scopes is not None else list(SCOPES)
        self.expiry = expiry
        self.valid = valid
        self.expired = expired
        self.refresh_calls: list = []

    def refresh(self, request) -> None:
        self.refresh_calls.append(request)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "library.db")
    database.initialize()
    return database


def _insert_legacy_row(db: Database, payload: dict) -> None:
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO yt_oauth_tokens(key, value) VALUES(?, ?)",
            (_LEGACY_DB_TOKEN_KEY, json.dumps(payload)),
        )


def _legacy_row_exists(db: Database) -> bool:
    with db.connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM yt_oauth_tokens WHERE key=?", (_LEGACY_DB_TOKEN_KEY,)
        ).fetchone()
    return row is not None


# ── 마이그레이션 ──────────────────────────────────────────────────────────────


def test_legacy_db_token_migrates_to_secret_store_and_is_deleted(db: Database) -> None:
    store = FakeSecretStore()
    _insert_legacy_row(db, SYNTHETIC_CREDENTIAL_DATA)

    adapter = YouTubeOAuthAdapter(db, store, client_config_path=None)
    assert adapter._load_token() == SYNTHETIC_CREDENTIAL_DATA
    assert json.loads(store.values[_TOKEN_KEY]) == SYNTHETIC_CREDENTIAL_DATA
    assert not _legacy_row_exists(db)


def test_secret_store_token_is_used_when_present_without_touching_legacy(db: Database) -> None:
    store = FakeSecretStore()
    store.values[_TOKEN_KEY] = json.dumps(SYNTHETIC_CREDENTIAL_DATA)
    other_legacy = {**SYNTHETIC_CREDENTIAL_DATA, "token": "stale-legacy-token"}
    _insert_legacy_row(db, other_legacy)

    adapter = YouTubeOAuthAdapter(db, store, client_config_path=None)
    assert adapter._load_token() == SYNTHETIC_CREDENTIAL_DATA
    assert _legacy_row_exists(db)  # 이미 secret store에 값이 있으면 legacy 행을 건드리지 않음


def test_no_token_anywhere_returns_none(db: Database) -> None:
    adapter = YouTubeOAuthAdapter(db, FakeSecretStore(), client_config_path=None)
    assert adapter._load_token() is None


def test_malformed_secret_store_json_returns_none_and_logs(
    db: Database, caplog: pytest.LogCaptureFixture
) -> None:
    store = FakeSecretStore()
    store.values[_TOKEN_KEY] = "not-json"
    adapter = YouTubeOAuthAdapter(db, store, client_config_path=None)
    with caplog.at_level(logging.ERROR):
        assert adapter._load_token() is None
    assert any("파싱" in rec.message for rec in caplog.records)


# ── save_credentials / clear ─────────────────────────────────────────────────


def test_save_credentials_writes_only_to_secret_store(db: Database) -> None:
    store = FakeSecretStore()
    adapter = YouTubeOAuthAdapter(db, store, client_config_path=None)
    creds = FakeCredentials(expiry=datetime(2099, 1, 1, tzinfo=timezone.utc))

    adapter.save_credentials(creds)

    assert json.loads(store.values[_TOKEN_KEY])["token"] == "synthetic-access-token"
    assert not _legacy_row_exists(db)


def test_clear_removes_secret_store_and_legacy_db_token(db: Database) -> None:
    store = FakeSecretStore()
    store.values[_TOKEN_KEY] = json.dumps(SYNTHETIC_CREDENTIAL_DATA)
    _insert_legacy_row(db, SYNTHETIC_CREDENTIAL_DATA)
    adapter = YouTubeOAuthAdapter(db, store, client_config_path=None)

    adapter.clear()

    assert _TOKEN_KEY not in store.values
    assert not _legacy_row_exists(db)


# ── has_client_config ────────────────────────────────────────────────────────


def test_has_client_config_reflects_injected_path(db: Database, tmp_path: Path) -> None:
    adapter_without = YouTubeOAuthAdapter(db, FakeSecretStore(), client_config_path=None)
    assert adapter_without.has_client_config() is False

    client_path = tmp_path / "OAuth2.json"
    client_path.write_text("{}", encoding="utf-8")
    adapter_with = YouTubeOAuthAdapter(db, FakeSecretStore(), client_config_path=client_path)
    assert adapter_with.has_client_config() is True


# ── run_auth_flow (브라우저 플로우, 전부 monkeypatch) ─────────────────────────


def test_run_auth_flow_uses_bundled_client_pkce_and_loopback(
    db: Database, tmp_path: Path, monkeypatch
) -> None:
    from unittest.mock import MagicMock

    client_path = tmp_path / "OAuth2.json"
    client_path.write_text("{}", encoding="utf-8")

    fake_creds = FakeCredentials()
    flow = MagicMock()
    flow.run_local_server.return_value = fake_creds
    factory = MagicMock(return_value=flow)
    monkeypatch.setattr(
        "google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file",
        factory,
    )

    store = FakeSecretStore()
    adapter = YouTubeOAuthAdapter(db, store, client_config_path=client_path)
    result = adapter.run_auth_flow()

    assert result is fake_creds
    factory.assert_called_once_with(
        str(client_path),
        SCOPES,
        autogenerate_code_verifier=True,
    )
    flow.run_local_server.assert_called_once_with(
        host="127.0.0.1",
        port=0,
        prompt="consent",
        access_type="offline",
        open_browser=True,
    )
    # 인증 성공 시 secret store에 저장됨
    assert json.loads(store.values[_TOKEN_KEY])["token"] == fake_creds.token


def test_run_auth_flow_without_client_config_raises_sanitized_error(db: Database) -> None:
    from infrastructure.youtube.oauth_client_config import OAuthClientConfigError

    adapter = YouTubeOAuthAdapter(db, FakeSecretStore(), client_config_path=None)
    with pytest.raises(OAuthClientConfigError):
        adapter.run_auth_flow()


# ── 보안 TLS 갱신 ────────────────────────────────────────────────────────────


def test_refresh_uses_normal_tls_verification_request(
    db: Database, monkeypatch
) -> None:
    import google.auth.transport.requests as greq
    from google.oauth2.credentials import Credentials

    captured: list = []

    def fake_refresh(self, request) -> None:
        captured.append(request)

    monkeypatch.setattr(Credentials, "refresh", fake_refresh)

    store = FakeSecretStore()
    # refresh_token 있고 expiry 없음 → needs_refresh 경로를 강제로 탄다
    data = {**SYNTHETIC_CREDENTIAL_DATA, "expiry": None}
    store.values[_TOKEN_KEY] = json.dumps(data)
    adapter = YouTubeOAuthAdapter(db, store, client_config_path=None)

    creds = adapter.get_credentials()

    assert len(captured) == 1
    request = captured[0]
    assert isinstance(request, greq.Request)
    # verify=False 세션을 주입하지 않았다면 기본 세션의 verify는 True
    assert request.session.verify is True
    assert creds is not None


def test_production_module_never_disables_tls_verification() -> None:
    source = Path("infrastructure/youtube/oauth_adapter.py").read_text(encoding="utf-8")
    normalized = source.replace(" ", "")
    assert "verify=False" not in normalized
    assert "disable_warnings" not in source
