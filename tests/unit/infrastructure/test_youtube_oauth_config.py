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
