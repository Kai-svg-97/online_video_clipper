import json
from pathlib import Path

import pytest

from infrastructure.youtube.oauth_client_config import (
    OAuthClientConfigError,
    find_youtube_oauth_config,
    validate_youtube_oauth_config,
)


VALID = """{
  "installed": {
    "client_id": "synthetic.apps.googleusercontent.com",
    "project_id": "synthetic-project",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "client_secret": "synthetic-secret",
    "redirect_uris": ["http://localhost"]
  }
}"""


def test_explicit_installed_client_is_selected(tmp_path: Path) -> None:
    path = tmp_path / "client.json"
    path.write_text(VALID, encoding="utf-8")
    assert find_youtube_oauth_config(path) == path.resolve()


def test_web_client_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "client.json"
    path.write_text('{"web":{"client_id":"x","client_secret":"y"}}', encoding="utf-8")
    with pytest.raises(OAuthClientConfigError, match="Desktop|installed"):
        validate_youtube_oauth_config(path)


def test_error_never_contains_secret(tmp_path: Path) -> None:
    secret = "must-not-appear"
    path = tmp_path / "client.json"
    path.write_text(f'{{"installed":{{"client_secret":"{secret}"}}}}', encoding="utf-8")
    with pytest.raises(OAuthClientConfigError) as exc:
        validate_youtube_oauth_config(path)
    assert secret not in str(exc.value)


def test_env_var_takes_precedence_over_bundled_and_dev_paths(tmp_path, monkeypatch) -> None:
    path = tmp_path / "client.json"
    path.write_text(VALID, encoding="utf-8")
    monkeypatch.setenv("OVC_YOUTUBE_OAUTH_CONFIG", str(path))
    assert find_youtube_oauth_config() == path.resolve()


def test_explicit_path_takes_precedence_over_env_var(tmp_path, monkeypatch) -> None:
    env_path = tmp_path / "env_client.json"
    env_path.write_text(VALID, encoding="utf-8")
    explicit_path = tmp_path / "explicit_client.json"
    explicit_path.write_text(VALID, encoding="utf-8")
    monkeypatch.setenv("OVC_YOUTUBE_OAUTH_CONFIG", str(env_path))
    assert find_youtube_oauth_config(explicit_path) == explicit_path.resolve()


def test_no_candidate_returns_none(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OVC_YOUTUBE_OAUTH_CONFIG", raising=False)
    monkeypatch.setattr(
        "infrastructure.youtube.oauth_client_config.get_resource_path",
        lambda rel: tmp_path / "missing" / rel,
    )
    monkeypatch.setattr(
        "infrastructure.youtube.oauth_client_config.settings.DATA_DIR",
        tmp_path / "missing_data",
    )
    assert find_youtube_oauth_config() is None


def test_missing_client_id_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "client.json"
    path.write_text(
        '{"installed":{"client_secret":"s","auth_uri":"https://accounts.google.com/o/oauth2/auth",'
        '"token_uri":"https://oauth2.googleapis.com/token","redirect_uris":["http://localhost"]}}',
        encoding="utf-8",
    )
    with pytest.raises(OAuthClientConfigError, match="client_id"):
        validate_youtube_oauth_config(path)


def test_missing_client_secret_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "client.json"
    path.write_text(
        '{"installed":{"client_id":"c","auth_uri":"https://accounts.google.com/o/oauth2/auth",'
        '"token_uri":"https://oauth2.googleapis.com/token","redirect_uris":["http://localhost"]}}',
        encoding="utf-8",
    )
    with pytest.raises(OAuthClientConfigError, match="client_secret"):
        validate_youtube_oauth_config(path)


def test_missing_loopback_redirect_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "client.json"
    path.write_text(
        '{"installed":{"client_id":"c","client_secret":"s",'
        '"auth_uri":"https://accounts.google.com/o/oauth2/auth",'
        '"token_uri":"https://oauth2.googleapis.com/token",'
        '"redirect_uris":["urn:ietf:wg:oauth:2.0:oob"]}}',
        encoding="utf-8",
    )
    with pytest.raises(OAuthClientConfigError, match="loopback|localhost"):
        validate_youtube_oauth_config(path)


def test_missing_file_raises_sanitized_error(tmp_path: Path) -> None:
    path = tmp_path / "nope.json"
    with pytest.raises(OAuthClientConfigError):
        validate_youtube_oauth_config(path)


# ── UTF-8 BOM 내구성 ──────────────────────────────────────────────────────
#
# CI가 시크릿을 파일로 복원할 때(또는 Notepad 등으로 재저장할 때) UTF-8 BOM이
# 붙는 사고가 실제로 있었다(v1.14.0 릴리즈에서 재현) — google_auth_oauthlib의
# InstalledAppFlow.from_client_secrets_file()은 open(path, "r")+json.load라
# BOM을 전혀 허용하지 않으므로, 검증만 통과시키고 파일에 BOM을 남겨두면
# "설정은 통과했는데 실제 연결 클릭은 여전히 깨지는" 상태가 된다. 그래서
# find_youtube_oauth_config()는 검증에 성공한 후보의 BOM을 파일에서 직접
# 제거해(self-heal) 이후 어떤 소비자가 읽어도 문제가 없게 한다.


def test_bom_prefixed_config_is_validated_successfully(tmp_path: Path) -> None:
    path = tmp_path / "client.json"
    path.write_bytes(b"\xef\xbb\xbf" + VALID.encode("utf-8"))
    validate_youtube_oauth_config(path)  # 예외 없이 통과해야 한다


def test_find_strips_bom_from_file_in_place(tmp_path: Path) -> None:
    path = tmp_path / "client.json"
    path.write_bytes(b"\xef\xbb\xbf" + VALID.encode("utf-8"))

    resolved = find_youtube_oauth_config(path)

    assert resolved == path.resolve()
    raw = path.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert json.loads(raw.decode("utf-8"))["installed"]["client_id"] == (
        "synthetic.apps.googleusercontent.com"
    )


def test_find_without_bom_leaves_file_byte_identical(tmp_path: Path) -> None:
    """BOM이 없는 정상 파일은 굳이 다시 쓰지 않는다(불필요한 파일 변경 방지)."""
    path = tmp_path / "client.json"
    original = VALID.encode("utf-8")
    path.write_bytes(original)
    mtime_before = path.stat().st_mtime_ns

    find_youtube_oauth_config(path)

    assert path.read_bytes() == original
    assert path.stat().st_mtime_ns == mtime_before


# ── main.py 컴포지션 루트 헬퍼 ───────────────────────────────────────────────


class _FakeAdapter:
    def __init__(self, db, secret_store, client_config_path) -> None:
        self.db = db
        self.secret_store = secret_store
        self.client_config_path = client_config_path

    def has_client_config(self) -> bool:
        return self.client_config_path is not None


class _FakeSecretStore:
    def __init__(self, service: str, fallback_path: Path) -> None:
        self.service = service
        self.fallback_path = fallback_path


def test_build_youtube_oauth_uses_expected_service_and_fallback_path(tmp_path, monkeypatch) -> None:
    import main as main_module

    monkeypatch.setattr(
        "infrastructure.youtube.oauth_client_config.find_youtube_oauth_config",
        lambda explicit_path=None: None,
    )
    monkeypatch.setattr(
        "infrastructure.sync.keyring_secret_store.KeyringSecretStore",
        _FakeSecretStore,
    )
    monkeypatch.setattr(
        "infrastructure.youtube.oauth_adapter.YouTubeOAuthAdapter",
        _FakeAdapter,
    )
    monkeypatch.setattr("config.settings.DATA_DIR", tmp_path)

    adapter = main_module._build_youtube_oauth(db=object())

    assert adapter.secret_store.service == "online-video-clipper.youtube-oauth"
    assert adapter.secret_store.fallback_path == tmp_path / "secrets" / "youtube_oauth.json"


def test_build_youtube_oauth_missing_client_config_does_not_stop_startup(tmp_path, monkeypatch) -> None:
    import main as main_module

    monkeypatch.setattr(
        "infrastructure.youtube.oauth_client_config.find_youtube_oauth_config",
        lambda explicit_path=None: None,
    )
    monkeypatch.setattr(
        "infrastructure.sync.keyring_secret_store.KeyringSecretStore",
        _FakeSecretStore,
    )
    monkeypatch.setattr(
        "infrastructure.youtube.oauth_adapter.YouTubeOAuthAdapter",
        _FakeAdapter,
    )
    monkeypatch.setattr("config.settings.DATA_DIR", tmp_path)

    adapter = main_module._build_youtube_oauth(db=object())

    assert adapter.has_client_config() is False


def test_build_youtube_oauth_passes_resolved_client_config_path(tmp_path, monkeypatch) -> None:
    import main as main_module

    client_path = tmp_path / "OAuth2.json"
    monkeypatch.setattr(
        "infrastructure.youtube.oauth_client_config.find_youtube_oauth_config",
        lambda explicit_path=None: client_path,
    )
    monkeypatch.setattr(
        "infrastructure.sync.keyring_secret_store.KeyringSecretStore",
        _FakeSecretStore,
    )
    monkeypatch.setattr(
        "infrastructure.youtube.oauth_adapter.YouTubeOAuthAdapter",
        _FakeAdapter,
    )
    monkeypatch.setattr("config.settings.DATA_DIR", tmp_path)

    adapter = main_module._build_youtube_oauth(db=object())

    assert adapter.client_config_path == client_path
    assert adapter.has_client_config() is True
