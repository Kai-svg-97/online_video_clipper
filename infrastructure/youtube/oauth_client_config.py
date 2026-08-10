"""Desktop OAuth 클라이언트 설정(JSON) 파일 탐색 및 검증.

값을 반환/로그/직렬화하지 않는다 — 오직 경로만 다룬다. `data/OAuth2.json`
(devloper의 로컬 Desktop client 설정)을 개발/빌드 시 재사용하고, 패키징 시엔
`config/OAuth2.json`으로 번들된 동일 파일을 그대로 쓴다.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from config import settings
from utils.resources import get_resource_path

logger = logging.getLogger(__name__)

_UTF8_BOM = b"\xef\xbb\xbf"


class OAuthClientConfigError(RuntimeError):
    """OAuth 클라이언트 설정 JSON이 없거나 형식이 올바르지 않을 때."""


def validate_youtube_oauth_config(path: Path) -> None:
    """Desktop installed OAuth 클라이언트 JSON인지 검증한다.

    `encoding="utf-8-sig"`로 읽어 UTF-8 BOM이 있어도 통과시킨다 — CI가 시크릿을
    파일로 복원하거나 Notepad 등으로 재저장하면 BOM이 붙는 사고가 실제로 있었다
    (v1.14.0 릴리즈에서 재현). 에러 메시지에는 경로/필드명만 담고, client_id·
    client_secret 등의 값은 절대 포함하지 않는다.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
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
    """유효한 Desktop OAuth 클라이언트 JSON 경로를 우선순위대로 탐색한다.

    우선순위: explicit_path → OVC_YOUTUBE_OAUTH_CONFIG 환경변수 →
    번들된 config/OAuth2.json → 개발용 DATA_DIR/OAuth2.json.
    모든 후보가 없으면 None. 존재하지만 형식이 틀린 후보는 조용히 건너뛰지
    않고 OAuthClientConfigError를 즉시 발생시킨다.
    """
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
            _strip_bom_if_present(resolved)
            return resolved
    return None


def _strip_bom_if_present(path: Path) -> None:
    """파일에 남은 UTF-8 BOM을 제거한다(self-heal).

    `validate_youtube_oauth_config`는 BOM이 있어도 통과시키지만, 이 경로는 이후
    `google_auth_oauthlib.InstalledAppFlow.from_client_secrets_file()`에도 그대로
    넘어간다 — 그 함수는 `open(path, "r")` + `json.load`로 BOM을 전혀 허용하지
    않으므로, 검증만 통과하고 실제 "Google 계정으로 연결" 클릭 시 다시 깨지는
    상태를 막기 위해 파일 자체를 정규화한다.
    """
    try:
        raw = path.read_bytes()
    except OSError:
        logger.warning("BOM 확인을 위한 OAuth 설정 파일 읽기 실패: %s", path)
        return
    if not raw.startswith(_UTF8_BOM):
        return
    try:
        path.write_bytes(raw[len(_UTF8_BOM):])
    except OSError:
        logger.warning("OAuth 설정 파일의 BOM 제거 실패(읽기 전용 위치일 수 있음): %s", path)
