# Bundled YouTube OAuth Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace user-entered Google OAuth Client ID/Client Secret fields with a single `Google 계정으로 연결` desktop OAuth flow that reuses the existing local `data/OAuth2.json` client configuration without distributing the developer's personal tokens.

**Architecture:** Treat the desktop OAuth client configuration and each user's OAuth token as different assets. Resolve the ignored local `data/OAuth2.json` during development/build, bundle only that client configuration into the packaged application, and store per-user tokens through the existing OS-keyring-backed secret store. Keep OAuth and Google network work in the existing `QThread`; keep dependency construction in `main.py`; retain SQLite only as a one-time legacy-token migration source.

**Tech Stack:** Python 3.12+, PyQt6, `google-auth-oauthlib`, `google-auth`, SQLite, `keyring`, PyInstaller, pytest/pytest-qt.

## Global Constraints

- Read the repository-root `AGENTS.md`, `CLAUDE.md`, and every nested `AGENTS.md` governing a touched file before editing.
- Reuse the existing `data/OAuth2.json` Desktop/Installed OAuth client. It is the client whose Client ID and Client Secret match the currently stored `yt_api_credentials` record.
- Do not use `data/OAuth.json`; it has the same Client ID but a different/older Client Secret.
- Never print, paste into source, paste into this plan, commit, log, or expose the actual Client ID, Client Secret, access token, or refresh token.
- Never package `data/library.db`, `data/library.db-wal`, `data/library.db-shm`, cookies, downloads, thumbnails, logs, `data/sync/secrets.json`, or the whole `data/` directory.
- Do not ask users for Google usernames/passwords or OAuth Client ID/Client Secret. Google credentials must be entered only in the system browser on Google's page.
- Use the Desktop Installed App OAuth flow, system browser, loopback callback, `state`, offline access, refresh token, and PKCE (`autogenerate_code_verifier=True`). Do not use an embedded web view or the deprecated OOB copy/paste flow.
- Preserve the current scope exactly: `https://www.googleapis.com/auth/youtube`. Scope reduction is a separate policy/product task.
- Use `google.auth.transport.requests.Request()` with normal TLS certificate verification. Do not create a `requests.Session(verify=False)` and do not disable `urllib3` warnings.
- Preserve DDD dependencies: `main.py` remains the composition root; GUI must not construct infrastructure; application must not import infrastructure.
- Preserve unauthenticated graceful behavior: the app must start when the OAuth client resource is absent, and YouTube API-dependent features must remain disabled/fallback rather than crashing.
- All OAuth/network work remains off the GUI thread using the existing `QThread` worker and Qt signals.
- Authentication takes effect for all handlers after the next app start. After successful first-time connection, clearly tell the user to restart; do not add a broad live dependency-rebinding refactor in this task.
- GUI changes require `pytest tests/gui/ -v` and the repository `/verify` skill with a real app launch.
- New feature documentation must update `planning/youtube_content_manager_prd.md`; packaging behavior must update `planning/packaging_plan.md`; architecture summary must update `CLAUDE.md`.
- Use TDD for each behavior and make small commits after each task. Do not commit the local credential JSON.

---

## File Map

**Create**

- `infrastructure/youtube/oauth_client_config.py` — resolves and validates a Desktop OAuth client JSON without exposing values.
- `tests/unit/infrastructure/test_youtube_oauth_config.py` — deterministic resolver/validation tests using synthetic credentials only.
- `tests/integration/test_youtube_oauth_adapter.py` — actual temporary SQLite DB plus fake secret-store tests for token persistence/migration and mocked Google flow.
- `tests/gui/test_youtube_oauth_settings.py` — settings-panel tests for the one-button UX and missing-client state.

**Modify**

- `infrastructure/youtube/oauth_adapter.py` — no-argument auth flow, PKCE client-file flow, keyring token persistence, legacy DB migration, secure TLS refresh.
- `main.py` — resolve the bundled client and inject `KeyringSecretStore` plus the optional config path.
- `gui/panels/settings_panel.py` — remove Client ID/Secret inputs and expose `Google 계정으로 연결`.
- `packaging/online_video_clipper.spec` — bundle exactly one build-supplied OAuth client JSON under `config/OAuth2.json`.
- `scripts/build_windows.ps1` — validate the local/build-supplied OAuth JSON before packaging without printing it.
- `scripts/build_linux.sh` — apply the same build-input contract on Linux.
- `planning/youtube_content_manager_prd.md` — document the small-audience Google account connection experience.
- `planning/packaging_plan.md` — document credential injection and artifact safety checks.
- `CLAUDE.md` — update OAuth adapter, token storage, and settings UX architecture notes.
- `README.md` — replace end-user BYO Client ID/Secret instructions with the Google connection flow, if such instructions exist.

**Local-only inputs (must remain ignored/uncommitted)**

- `data/OAuth2.json` — source Desktop client configuration used by local builds.
- `data/library.db*` — current developer data and legacy OAuth token source; never a build input.

---

### Task 1: Resolve and validate the bundled Desktop OAuth client

**Files:**

- Create: `infrastructure/youtube/oauth_client_config.py`
- Create: `tests/unit/infrastructure/test_youtube_oauth_config.py`
- Reference: `utils/resources.py:5-13`
- Reference: `config/settings.py:15`

**Interfaces:**

- Produces: `find_youtube_oauth_config(explicit_path: Path | None = None) -> Path | None`
- Produces: `validate_youtube_oauth_config(path: Path) -> None`
- Produces: `OAuthClientConfigError(RuntimeError)` with sanitized messages that contain a path/reason but no credential values.
- Resolution precedence: explicit path → `OVC_YOUTUBE_OAUTH_CONFIG` → bundled `config/OAuth2.json` via `get_resource_path()` → development `DATA_DIR/OAuth2.json`.
- Missing all candidates returns `None`; an existing malformed candidate raises `OAuthClientConfigError` instead of silently falling through.

- [x] **Step 1: Write resolver tests with synthetic values**

```python
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
```

Add tests for environment-variable precedence, missing-candidate `None`, missing `client_id`, missing `client_secret`, and absence of a localhost/loopback redirect.

- [x] **Step 2: Run the new tests and confirm they fail because the module does not exist**

Run: `pytest tests/unit/infrastructure/test_youtube_oauth_config.py -v`

Expected: collection failure with `ModuleNotFoundError: infrastructure.youtube.oauth_client_config`.

- [x] **Step 3: Implement the resolver and sanitized validator**

```python
import json
import os
from pathlib import Path

from config import settings
from utils.resources import get_resource_path


class OAuthClientConfigError(RuntimeError):
    pass


def validate_youtube_oauth_config(path: Path) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OAuthClientConfigError(f"OAuth 설정 JSON을 읽을 수 없습니다: {path}") from exc
    installed = data.get("installed") if isinstance(data, dict) else None
    if not isinstance(installed, dict):
        raise OAuthClientConfigError(f"Desktop installed OAuth 설정이 아닙니다: {path}")
    for field in ("client_id", "client_secret", "auth_uri", "token_uri"):
        if not isinstance(installed.get(field), str) or not installed[field].strip():
            raise OAuthClientConfigError(f"OAuth 설정 필드가 없습니다: {field} ({path})")
    redirects = installed.get("redirect_uris")
    if not isinstance(redirects, list) or not any(
        isinstance(uri, str)
        and uri.startswith(("http://localhost", "http://127.0.0.1"))
        for uri in redirects
    ):
        raise OAuthClientConfigError(f"localhost loopback redirect가 없습니다: {path}")


def find_youtube_oauth_config(explicit_path: Path | None = None) -> Path | None:
    env_path = os.environ.get("OVC_YOUTUBE_OAUTH_CONFIG")
    candidates = [
        explicit_path,
        Path(env_path) if env_path else None,
        get_resource_path("config/OAuth2.json"),
        Path(settings.DATA_DIR) / "OAuth2.json",
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        resolved = Path(candidate).expanduser().resolve()
        if resolved.is_file():
            validate_youtube_oauth_config(resolved)
            return resolved
    return None
```

Keep the implementation equivalent to the code above. Do not return or log the parsed credential object.

- [x] **Step 4: Run the focused tests**

Run: `pytest tests/unit/infrastructure/test_youtube_oauth_config.py -v`

Expected: all tests pass.

- [x] **Step 5: Lint the new files**

Run: `ruff check infrastructure/youtube/oauth_client_config.py tests/unit/infrastructure/test_youtube_oauth_config.py`

Expected: exit code 0.

- [x] **Step 6: Commit Task 1**

```bash
git add infrastructure/youtube/oauth_client_config.py tests/unit/infrastructure/test_youtube_oauth_config.py
git commit -m "feat: resolve bundled YouTube OAuth client"
```

---

### Task 2: Move user OAuth tokens to the OS-keyring store and migrate legacy SQLite data

**Files:**

- Modify: `infrastructure/youtube/oauth_adapter.py:1-139`
- Create: `tests/integration/test_youtube_oauth_adapter.py`
- Reference: `infrastructure/sync/keyring_secret_store.py:20-98`
- Reference: `db/schema.sql:183`

**Interfaces:**

- Change constructor to `YouTubeOAuthAdapter(db, secret_store, client_config_path: Path | None) -> None`.
- Change `run_auth_flow(self, client_id: str, client_secret: str)` to `run_auth_flow(self) -> Any`.
- Add `has_client_config(self) -> bool`.
- Keep `get_credentials()`, `save_credentials(creds)`, `clear()`, `is_authenticated()`, and `get_channel_name()` public behavior.
- Store serialized credentials under key `youtube.oauth.credentials.v1` via the injected structural `get/set/delete` secret-store methods.
- Treat SQLite key `yt_api_credentials` as legacy read/migration data only.

- [x] **Step 1: Write integration tests with a real temporary Database and a fake secret store**

```python
class FakeSecretStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        self.values[key] = value

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


def test_legacy_db_token_migrates_to_secret_store_and_is_deleted(tmp_path):
    db = Database(tmp_path / "library.db")
    db.initialize()
    store = FakeSecretStore()
    legacy = json.dumps(SYNTHETIC_CREDENTIAL_DATA)
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO yt_oauth_tokens(key, value) VALUES(?, ?)",
            ("yt_api_credentials", legacy),
        )

    adapter = YouTubeOAuthAdapter(db, store, client_config_path=None)
    assert adapter._load_token() == SYNTHETIC_CREDENTIAL_DATA
    assert json.loads(store.values["youtube.oauth.credentials.v1"]) == SYNTHETIC_CREDENTIAL_DATA
    with db.connection() as conn:
        assert conn.execute(
            "SELECT 1 FROM yt_oauth_tokens WHERE key=?", ("yt_api_credentials",)
        ).fetchone() is None
```

Also add tests that `save_credentials()` writes only to the secret store, `clear()` removes both new and legacy storage, and malformed secret-store JSON returns `None` with a logged error.

- [x] **Step 2: Write the OAuth-flow and secure-refresh tests**

Monkeypatch `google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file` and assert:

```python
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
```

Add a refresh test that monkeypatches `Credentials.refresh` and verifies it receives a normal `google.auth.transport.requests.Request` instance. Assert the production module contains neither `verify = False` nor `urllib3.disable_warnings`.

- [x] **Step 3: Run the focused integration tests and confirm the old adapter contract fails**

Run: `pytest tests/integration/test_youtube_oauth_adapter.py -v`

Expected: failures for the constructor and `run_auth_flow()` signature/storage expectations.

- [x] **Step 4: Refactor token serialization and migration**

Implement private helpers with these exact responsibilities:

```python
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

def _parse_token(raw: str) -> dict | None:
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        logger.exception("YouTube OAuth 토큰 JSON 파싱 실패")
        return None
    return data if isinstance(data, dict) else None

def _load_legacy_db_token(self) -> dict | None:
    with self._db.connection() as conn:
        row = conn.execute(
            "SELECT value FROM yt_oauth_tokens WHERE key=?",
            (_LEGACY_DB_TOKEN_KEY,),
        ).fetchone()
    return _parse_token(row["value"]) if row else None

def _delete_legacy_db_token(self) -> None:
    with self._db.connection() as conn:
        conn.execute(
            "DELETE FROM yt_oauth_tokens WHERE key=?",
            (_LEGACY_DB_TOKEN_KEY,),
        )
```

`_load_token()` must:

1. Read the secret store first.
2. If absent, read the legacy SQLite row.
3. Write the legacy raw JSON to the secret store.
4. Read it back and compare before deleting the SQLite row.
5. Return the parsed dict.

If secret-store persistence cannot be confirmed, leave the SQLite record intact so authentication is not lost.

- [x] **Step 5: Refactor browser OAuth and TLS refresh**

Use:

```python
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
```

If no config path is available, raise `OAuthClientConfigError("YouTube OAuth 클라이언트 설정이 포함되지 않았습니다.")`. Refresh with `_GReq()` and normal TLS verification. Keep `RefreshError` as a warning and return `None`; log unexpected errors with `logger.exception`.

- [x] **Step 6: Run adapter tests and adjacent YouTube tests**

Run: `pytest tests/integration/test_youtube_oauth_adapter.py tests/unit/application/test_enrich_video.py -v`

Expected: all pass.

- [x] **Step 7: Lint the adapter and tests**

Run: `ruff check infrastructure/youtube/oauth_adapter.py tests/integration/test_youtube_oauth_adapter.py`

Expected: exit code 0.

- [x] **Step 8: Commit Task 2**

```bash
git add infrastructure/youtube/oauth_adapter.py tests/integration/test_youtube_oauth_adapter.py
git commit -m "feat: secure YouTube OAuth token storage"
```

---

### Task 3: Wire OAuth configuration and token storage in the composition root

**Files:**

- Modify: `main.py:200-220`
- Modify: `main.py:270-281`
- Test: `tests/unit/infrastructure/test_youtube_oauth_config.py`

**Interfaces:**

- Consumes: `find_youtube_oauth_config() -> Path | None` from Task 1.
- Consumes: `KeyringSecretStore(service: str, fallback_path: Path)`.
- Produces: `_build_youtube_oauth(db) -> YouTubeOAuthAdapter`, a composition-root helper used by `main()` and the construction test.
- Produces one application-wide `YouTubeOAuthAdapter` injected into the existing settings/main-window path.

- [x] **Step 1: Add a construction test for the expected service/fallback contract**

Add `_build_youtube_oauth(db)` to `main.py` with imports kept inside the helper so splash/startup import behavior is preserved. Cover it by monkeypatching `infrastructure.youtube.oauth_client_config.find_youtube_oauth_config`, `infrastructure.sync.keyring_secret_store.KeyringSecretStore`, and `infrastructure.youtube.oauth_adapter.YouTubeOAuthAdapter` before calling the helper. The asserted values are:

```python
service = "online-video-clipper.youtube-oauth"
fallback_path = Path(DATA_DIR) / "secrets" / "youtube_oauth.json"
client_config_path = find_youtube_oauth_config()
```

The test must assert that a missing client config produces an adapter with `has_client_config() is False` and does not stop application startup.

- [x] **Step 2: Run the focused test and confirm the old constructor fails**

Run: `pytest tests/unit/infrastructure/test_youtube_oauth_config.py -v`

Expected: the newly added construction expectation fails until `main.py` is updated.

- [x] **Step 3: Update `main.py` dependency injection**

At the composition root, import the resolver and `KeyringSecretStore`, then construct:

```python
yt_secret_store = KeyringSecretStore(
    "online-video-clipper.youtube-oauth",
    Path(DATA_DIR) / "secrets" / "youtube_oauth.json",
)
yt_oauth = YouTubeOAuthAdapter(
    db,
    yt_secret_store,
    client_config_path=find_youtube_oauth_config(),
)
```

Do not read or parse credential values in `main.py`. Preserve `_yt_creds = yt_oauth.get_credentials()` and the current startup construction of `YouTubeApiAdapter`.

- [x] **Step 4: Run focused tests and startup import validation**

Run: `pytest tests/unit/infrastructure/test_youtube_oauth_config.py tests/gui/test_smoke.py -v`

Run: `python -m compileall main.py infrastructure/youtube`

Expected: both commands exit 0.

- [x] **Step 5: Commit Task 3**

```bash
git add main.py tests/unit/infrastructure/test_youtube_oauth_config.py
git commit -m "feat: inject bundled YouTube OAuth configuration"
```

---

### Task 4: Replace Client ID/Secret fields with one Google connection button

**Files:**

- Modify: `gui/panels/settings_panel.py:1004-1055`
- Modify: `gui/panels/settings_panel.py:1286-1359`
- Create: `tests/gui/test_youtube_oauth_settings.py`

**Interfaces:**

- Consumes: `YouTubeOAuthAdapter.has_client_config()` and no-argument `run_auth_flow()`.
- Keeps: `_yt_auth_btn`, `_yt_disconnect_btn`, `_yt_status_lbl`, and `_yt_auth_worker` lifecycle.
- Removes: `_yt_client_id_edit` and `_yt_client_secret_edit` completely.

- [x] **Step 1: Write GUI tests for the new controls**

```python
class FakeOAuth:
    def __init__(self, configured: bool = True, authenticated: bool = False) -> None:
        self.configured = configured
        self.authenticated = authenticated
        self.run_calls = 0

    def has_client_config(self) -> bool:
        return self.configured

    def is_authenticated(self) -> bool:
        return self.authenticated

    def get_channel_name(self) -> str | None:
        return "Synthetic Channel" if self.authenticated else None

    def run_auth_flow(self):
        self.run_calls += 1
        self.authenticated = True
        return object()

    def clear(self) -> None:
        self.authenticated = False


def test_youtube_oauth_uses_single_google_connect_button(qtbot):
    panel = SettingsPanel(get_tags_fn=lambda: [], yt_oauth=FakeOAuth())
    qtbot.addWidget(panel)
    assert panel._yt_auth_btn.text() == "Google 계정으로 연결"
    assert not hasattr(panel, "_yt_client_id_edit")
    assert not hasattr(panel, "_yt_client_secret_edit")


def test_missing_bundled_client_disables_connect(qtbot):
    panel = SettingsPanel(get_tags_fn=lambda: [], yt_oauth=FakeOAuth(configured=False))
    qtbot.addWidget(panel)
    assert not panel._yt_auth_btn.isEnabled()
    assert "배포자" in panel._yt_status_lbl.text()
```

Add a worker test using `qtbot.waitUntil` or `qtbot.waitSignal` that clicks the button, confirms `run_auth_flow()` was called with no credentials, and confirms the connected label includes the restart notice. Add a disconnect test.

- [x] **Step 2: Run GUI tests and confirm they fail against the current fields**

Run: `pytest tests/gui/test_youtube_oauth_settings.py -v`

Expected: failures because the current UI still renders and reads Client ID/Secret.

- [x] **Step 3: Replace the UI copy and controls**

Use this end-user copy:

```text
Google 계정을 연결하면 YouTube 재생목록 동기화(읽기·쓰기)와
구독 채널 가져오기를 사용할 수 있습니다.
로그인은 기본 브라우저의 Google 페이지에서 안전하게 진행됩니다.
```

Button labels:

- Disconnected: `Google 계정으로 연결`
- Working: `연결 중…`
- Connected: `Google 계정 다시 연결`
- Secondary: `연결 해제`

Remove all Client ID/Secret labels, placeholders, password echo mode, and empty-field validation.

- [x] **Step 4: Update the worker and status behavior**

The worker must call `self._oauth.run_auth_flow()` with no arguments. On success show:

```text
● 연결됨: {channel_name}
앱을 다시 시작하면 모든 YouTube 연동 기능이 활성화됩니다.
```

If `has_client_config()` is false, disable the connect button and show:

```text
YouTube OAuth 설정이 앱에 포함되지 않았습니다. 배포자에게 문의하세요.
```

Keep errors capped for display, but log the full exception in the worker boundary without credential/token content.

- [x] **Step 5: Run GUI tests**

Run: `pytest tests/gui/test_youtube_oauth_settings.py tests/gui/test_smoke.py -v`

Expected: all pass, no QThread-destroyed warnings.

- [x] **Step 6: Lint and compile the GUI module**

Run: `ruff check gui/panels/settings_panel.py tests/gui/test_youtube_oauth_settings.py`

Run: `python -m compileall gui/panels/settings_panel.py`

Expected: both exit 0.

- [x] **Step 7: Commit Task 4**

```bash
git add gui/panels/settings_panel.py tests/gui/test_youtube_oauth_settings.py
git commit -m "feat: add one-click Google account connection"
```

---

### Task 5: Inject the existing Desktop client at package-build time

**Files:**

- Modify: `packaging/online_video_clipper.spec:1-26`
- Modify: `scripts/build_windows.ps1:1-35`
- Modify: `scripts/build_linux.sh`
- Reference: `.gitignore:4-5`

**Interfaces:**

- Build input environment variable: `OVC_YOUTUBE_OAUTH_CONFIG`.
- Default local build input: `C:/projects/online_video_clipper/data/OAuth2.json` for this workspace; scripts must still derive it from their repository root rather than hard-code this absolute path.
- Packaged resource destination: `config/OAuth2.json`.
- Runtime resolution: `get_resource_path("config/OAuth2.json")` from Task 1.

- [x] **Step 1: Add non-secret build preflight validation to Windows**

Before invoking PyInstaller, resolve `$env:OVC_YOUTUBE_OAUTH_CONFIG` if supplied; otherwise use `Join-Path $Root "data\OAuth2.json"`. Parse it with `ConvertFrom-Json` and require non-empty `installed.client_id`, `installed.client_secret`, and localhost redirect. On failure, throw a message containing only the file path and missing field name.

Set `OVC_YOUTUBE_OAUTH_CONFIG` only for the PyInstaller process and restore/remove it in `finally`. Never echo the JSON or its values.

- [x] **Step 2: Add equivalent Linux validation**

Use a short Python JSON-validation command or existing Python runtime, then invoke PyInstaller with `OVC_YOUTUBE_OAUTH_CONFIG="$oauth_config"`. Print only the selected file path.

- [x] **Step 3: Update the shared PyInstaller spec**

At spec evaluation, require the environment variable and add exactly:

```python
_oauth_src = os.environ.get("OVC_YOUTUBE_OAUTH_CONFIG")
if not _oauth_src or not Path(_oauth_src).is_file():
    raise SystemExit("OVC_YOUTUBE_OAUTH_CONFIG must point to an installed-app JSON file")

datas=[
    ("../assets", "assets"),
    ("../db", "db"),
    (_oauth_src, "config"),
    *collect_data_files("yt_dlp"),
    *collect_data_files("PyQt6"),
]
```

Import `os` and `Path`. Do not add `../data`, the database, or a glob.

- [x] **Step 4: Validate the Windows build input without exposing it**

Run: `powershell -NoProfile -File scripts/build_windows.ps1`

Expected: PyInstaller succeeds using the local ignored `data/OAuth2.json`.

- [x] **Step 5: Audit the built artifact contents**

Run this read-only PowerShell audit:

```powershell
$bundle = Resolve-Path 'dist/windows/YouTubeContentManager'
$oauth = Get-ChildItem -LiteralPath $bundle -Recurse -File -Filter 'OAuth2.json'
$forbidden = Get-ChildItem -LiteralPath $bundle -Recurse -File |
  Where-Object { $_.Name -match 'library\.db|cookies|secrets\.json' }
[PSCustomObject]@{
  OAuthConfigCount = @($oauth).Count
  ForbiddenFileCount = @($forbidden).Count
}
```

Expected: `OAuthConfigCount = 1`, `ForbiddenFileCount = 0`. Do not output file contents.

- [x] **Step 6: Commit Task 5**

```bash
git add packaging/online_video_clipper.spec scripts/build_windows.ps1 scripts/build_linux.sh
git commit -m "build: bundle YouTube desktop OAuth client"
```

Do not stage `data/OAuth2.json`.

---

### Task 6: Update product, packaging, and architecture documentation

**Files:**

- Modify: `planning/youtube_content_manager_prd.md`
- Modify: `planning/packaging_plan.md`
- Modify: `CLAUDE.md`
- Modify: `README.md` only if it contains BYO OAuth setup instructions.

**Interfaces:** Documentation must match the implemented filenames, button labels, storage key, and restart behavior exactly.

- [x] **Step 1: Update the PRD**

Add acceptance criteria:

- User sees no Client ID/Secret inputs.
- User connects through the system browser and Google consent screen.
- App never handles a Google password.
- Small-audience/unverified warning is an operational Google Cloud setting, not an in-app error.
- Successful first-time connection instructs restart.
- Disconnect deletes the local user token.

- [x] **Step 2: Update the packaging plan**

Document `OVC_YOUTUBE_OAUTH_CONFIG`, default `data/OAuth2.json`, packaged `config/OAuth2.json`, and the artifact audit proving that no database/token/cookie files are included.

- [x] **Step 3: Update `CLAUDE.md` architecture notes**

Change the OAuth adapter description from SQLite persistence to keyring-first persistence with one-time SQLite migration. Change the settings-panel description from user-entered credentials to bundled-client Google connection. Mention normal TLS verification and PKCE.

- [x] **Step 4: Update README only where necessary** — README에는 BYO OAuth Client ID/Secret 안내가 존재하지 않아(사전 검색 확인) 변경 불필요, `git add`에서 제외

Remove instructions telling end users to create or paste Google Cloud OAuth credentials. Replace them with `설정 → YouTube API 연동 → Google 계정으로 연결` and the one-time unverified-app warning expected for the small acquaintance group.

- [x] **Step 5: Scan documentation for stale instructions and accidental secrets**

Run:

```powershell
rg -n -i "Client ID.*입력|Client Secret.*입력|OAuth 인증하기" README.md CLAUDE.md planning docs
rg -n "GOCSPX-|apps\.googleusercontent\.com" README.md CLAUDE.md planning docs infrastructure gui tests packaging scripts
```

Expected: no stale end-user input instructions; no real credential patterns. Synthetic test strings are allowed only in test files and must be visibly synthetic.

- [x] **Step 6: Commit Task 6**

```bash
git add planning/youtube_content_manager_prd.md planning/packaging_plan.md CLAUDE.md README.md
git commit -m "docs: describe bundled YouTube OAuth login"
```

If `README.md` required no change, omit it from `git add`.

---

### Task 7: Full verification and real-account acceptance check

**Files:** No production changes unless verification finds a defect.

**Acceptance flow:** New user data directory, packaged executable, system browser, acquaintance Google account, token persistence across restart, disconnect.

- [ ] **Step 1: Run targeted OAuth tests**

Run:

```bash
pytest tests/unit/infrastructure/test_youtube_oauth_config.py tests/integration/test_youtube_oauth_adapter.py tests/gui/test_youtube_oauth_settings.py -v
```

Expected: all pass.

- [ ] **Step 2: Run all unit tests**

Run: `pytest tests/unit/ -v`

Expected: all pass.

- [ ] **Step 3: Run all integration tests**

Run: `pytest tests/integration/ -v`

Expected: all pass; network-dependent pre-existing skips are documented, not silently converted to passes.

- [ ] **Step 4: Run all GUI tests**

Run: `pytest tests/gui/ -v`

Expected: all pass with no leaked/running QThreads.

- [ ] **Step 5: Run lint and compile checks**

Run: `ruff check .`

Run: `python -m compileall main.py application domain infrastructure gui config utils`

Expected: both exit 0.

- [ ] **Step 6: Invoke `/verify` and inspect the settings panel**

Required visual checks:

- No Client ID or Client Secret fields.
- `Google 계정으로 연결` is visible.
- Missing bundled config disables the button with the distributor message.
- Normal build opens the system browser, not an embedded window.
- Success shows channel name and restart instruction.
- Existing browser-cookie section remains unchanged and visually distinct from YouTube Data API OAuth.

- [ ] **Step 7: Perform a real packaged-build OAuth acceptance test without recording secrets**

Using a Google account listed/allowed for the small audience:

1. Start from a clean test user-data directory.
2. Click `Google 계정으로 연결`.
3. Complete Google's unverified-app warning and consent in the system browser.
4. Confirm the app shows the connected channel.
5. Restart the app.
6. Confirm YouTube playlist listing and subscription import work.
7. Confirm playlist create/add/remove actions work.
8. Restart again and confirm no second consent is required.
9. Click `연결 해제`, restart, and confirm YouTube API-dependent actions are disabled/fallback.

Do not capture screenshots containing account email, channel-private data, authorization codes, or tokens.

- [ ] **Step 8: Re-run the artifact safety audit**

Expected: exactly one bundled OAuth client JSON and zero databases, refresh-token files, cookies, or developer user data.

- [ ] **Step 9: Review the working tree before handoff**

Confirm `data/OAuth2.json`, `data/OAuth.json`, `data/library.db*`, and all other `data/` user files are untracked/unstaged. Confirm no generated `build/` or `dist/` files are staged.

- [ ] **Step 10: Final commit only if verification required fixes**

```bash
git add infrastructure/youtube/oauth_client_config.py infrastructure/youtube/oauth_adapter.py main.py gui/panels/settings_panel.py packaging/online_video_clipper.spec scripts/build_windows.ps1 scripts/build_linux.sh tests/unit/infrastructure/test_youtube_oauth_config.py tests/integration/test_youtube_oauth_adapter.py tests/gui/test_youtube_oauth_settings.py planning/youtube_content_manager_prd.md planning/packaging_plan.md CLAUDE.md README.md
git commit -m "fix: address YouTube OAuth verification findings"
```

---

## Definition of Done

- End users never enter Client ID, Client Secret, Google username, or Google password in the app.
- The existing `data/OAuth2.json` Desktop client is reused as a local build input and is bundled once.
- No developer access token, refresh token, database, cookie, or user data ships with the application.
- User tokens are keyring-first and legacy SQLite tokens migrate without loss.
- OAuth uses system browser + loopback + PKCE + normal TLS verification.
- App starts gracefully when the client configuration is missing.
- First-time connection clearly communicates the restart requirement.
- Focused, unit, integration, and GUI tests pass.
- `/verify` real app launch passes.
- Windows package build and content audit pass.
- PRD, packaging plan, CLAUDE.md, and relevant README instructions match the implementation.

## Out of Scope

- Google OAuth brand/sensitive-scope verification, domain registration, or an app website.
- Rotating or issuing a new OAuth Client ID/Client Secret.
- Removing Google's `unverified app` warning for the small acquaintance group.
- Reducing or splitting the current YouTube OAuth scope.
- Live rebinding of every already-constructed application handler after authentication; restart is the explicit activation boundary for this task.
- Replacing the separate browser-profile/cookie authentication used by yt-dlp/Gemini/subscription-feed scraping.
