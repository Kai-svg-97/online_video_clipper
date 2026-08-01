"""GitHub Releases 기반 업데이트 확인·다운로드 어댑터.

domain.shared.ports.IUpdateChecker 를 구조적 타이핑으로 만족한다.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

import requests

from application.updater.version_compare import is_newer
from domain.shared.ports import UpdateInfo

logger = logging.getLogger(__name__)

_API_URL = "https://api.github.com/repos/Kai-svg-97/online_video_clipper/releases/latest"
_TIMEOUT = 10
_CHUNK = 65_536  # 64 KB

# 인스톨러는 130MB가 넘어 API 조회용 타임아웃(10초)으로는 끊긴다.
# requests 의 read 타임아웃은 "청크 사이 정체 허용 시간"이므로 넉넉히 잡고,
# 그래도 끊기면 Range 로 이어받아 재시도한다.
_DL_TIMEOUT = (10, 60)      # (connect, read)
_DL_MAX_ATTEMPTS = 4
_DL_RETRY_BACKOFF_SEC = 3   # 시도마다 배수로 증가
_ALLOWED_HOSTS = frozenset({
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "codeload.github.com",
})
# 자산 이름 허용 패턴 — 경로 구분자·특수문자 차단
_ASSET_NAME_RE = re.compile(r"^[A-Za-z0-9._\-]+$")


def _validate_url(url: str) -> None:
    """다운로드 URL이 HTTPS이고 허용된 호스트임을 확인한다."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"허용되지 않은 URL 스킴: {parsed.scheme!r}")
    host = parsed.netloc.lower().split(":")[0]
    if host not in _ALLOWED_HOSTS:
        raise ValueError(f"허용되지 않은 다운로드 호스트: {host!r}")


def _sha256_of(path: Path) -> str:
    """파일 전체를 읽어 SHA-256 을 계산한다.

    이어받기(Range) 로 여러 응답에 걸쳐 받을 수 있으므로 스트리밍 중 누적하지 않고
    완료된 파일에서 한 번에 계산한다.
    """
    sha = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def _validate_asset_name(name: str) -> str:
    """자산 이름에서 경로 구성요소를 제거하고 안전한 파일명인지 확인한다."""
    bare = os.path.basename(name)
    if not _ASSET_NAME_RE.match(bare):
        raise ValueError(f"비정상 자산 이름: {name!r}")
    return bare


class GithubUpdateChecker:
    """IUpdateChecker 구현체 — GitHub Releases REST API 사용."""

    def __init__(
        self,
        current_version: str,
        *,
        session: requests.Session | None = None,
    ) -> None:
        self._current = current_version
        self._session = session or requests.Session()

    # ------------------------------------------------------------------
    def check_latest(self) -> UpdateInfo | None:
        """최신 릴리스를 조회한다. 새 버전이 없거나 네트워크 실패 시 None."""
        try:
            resp = self._session.get(
                _API_URL,
                headers={"Accept": "application/vnd.github+json"},
                timeout=_TIMEOUT,
                verify=True,
            )
            if resp.status_code == 403:
                logger.debug("GitHub API 할당량 초과 — 업데이트 확인 생략")
                return None
            resp.raise_for_status()
        except requests.RequestException:
            logger.exception("GitHub 릴리스 조회 실패")
            return None

        data = resp.json()
        tag: str = data.get("tag_name", "")
        latest_ver = tag.lstrip("v")

        if not is_newer(latest_ver, self._current):
            return None

        asset = self._select_asset(data.get("assets", []))
        if asset is None:
            logger.warning("현재 플랫폼에 맞는 릴리스 자산을 찾지 못했습니다")
            return None

        # 자산 이름·URL 유효성 확인
        try:
            asset_name = _validate_asset_name(asset["name"])
            download_url = asset["browser_download_url"]
            _validate_url(download_url)
        except (ValueError, KeyError):
            logger.exception("릴리스 자산 메타데이터 유효성 검사 실패")
            return None

        sha256 = self._extract_sha256(asset, data.get("assets", []))
        if sha256 is None:
            logger.warning("SHA-256 체크섬을 가져오지 못했습니다 — 업데이트 건너뜀")
            return None

        return UpdateInfo(
            version=latest_ver,
            asset_name=asset_name,
            download_url=download_url,
            size_bytes=asset.get("size", 0),
            sha256=sha256,
            release_notes=(data.get("body") or "")[:2000],
        )

    # ------------------------------------------------------------------
    def download_asset(
        self,
        info: UpdateInfo,
        dest_dir: Path,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> Path:
        """자산을 dest_dir 에 다운로드한다. SHA-256 검증 후 완료된 파일 경로를 반환한다."""
        # 다운로드 전 URL 재검증 (UpdateInfo가 외부에서 조작될 경우 대비)
        _validate_url(info.download_url)
        safe_name = _validate_asset_name(info.asset_name)

        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / safe_name
        part = dest.with_suffix(dest.suffix + ".part")

        try:
            self._download_with_resume(info, part, on_progress)
        except requests.RequestException:
            part.unlink(missing_ok=True)
            raise

        # SHA-256 검증 — 체크섬 없으면 fail-closed
        if not info.sha256:
            part.unlink(missing_ok=True)
            raise RuntimeError("SHA-256 체크섬이 없어 무결성을 검증할 수 없습니다 — 설치 중단")

        digest = _sha256_of(part)
        if not hmac.compare_digest(digest, info.sha256.lower()):
            part.unlink(missing_ok=True)
            raise RuntimeError(
                f"SHA-256 불일치: expected {info.sha256}, got {digest}"
            )

        dest.unlink(missing_ok=True)
        part.rename(dest)
        return dest

    # ------------------------------------------------------------------
    def _download_with_resume(
        self,
        info: UpdateInfo,
        part: Path,
        on_progress: Callable[[int, int], None] | None,
    ) -> None:
        """`.part` 에 내려받는다 — 끊기면 Range 로 이어받아 재시도한다.

        130MB 인스톨러는 네트워크가 잠깐만 정체돼도 read 타임아웃에 걸린다.
        예전에는 한 번 실패하면 그대로 포기해 업데이트가 영영 진행되지 않았다
        (사용자에게는 '빨간 점만 뜨고 설치는 안 됨'으로 보였다).
        """
        last_exc: Exception | None = None
        for attempt in range(1, _DL_MAX_ATTEMPTS + 1):
            have = part.stat().st_size if part.exists() else 0
            headers = {"Range": f"bytes={have}-"} if have else {}
            try:
                resp = self._session.get(
                    info.download_url,
                    stream=True,
                    timeout=_DL_TIMEOUT,
                    headers=headers,
                    verify=True,
                )
                if have and resp.status_code == 200:
                    # 서버가 Range 를 무시했다 — 처음부터 다시 받는다.
                    have = 0
                    part.unlink(missing_ok=True)
                resp.raise_for_status()

                remaining = int(resp.headers.get("content-length", 0) or 0)
                total = (have + remaining) or info.size_bytes or 0
                downloaded = have
                with part.open("ab" if have else "wb") as f:
                    for chunk in resp.iter_content(chunk_size=_CHUNK):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        if on_progress:
                            on_progress(downloaded, total)

                if total and downloaded < total:
                    raise requests.ConnectionError(
                        f"다운로드가 도중에 끊겼습니다({downloaded}/{total} bytes)"
                    )
                return
            except requests.RequestException as exc:
                last_exc = exc
                got = part.stat().st_size if part.exists() else 0
                logger.warning(
                    "업데이트 다운로드 %d/%d 실패(%s) — %d bytes 확보, 이어받기 재시도",
                    attempt, _DL_MAX_ATTEMPTS, exc, got,
                )
                if attempt == _DL_MAX_ATTEMPTS:
                    break
                time.sleep(_DL_RETRY_BACKOFF_SEC * attempt)

        raise last_exc if last_exc else RuntimeError("업데이트 다운로드 실패")

    # ------------------------------------------------------------------
    @staticmethod
    def _select_asset(assets: list[dict]) -> dict | None:
        if sys.platform == "win32":
            for a in assets:
                if a.get("name", "").endswith("setup.exe"):
                    return a
        else:
            for a in assets:
                if a.get("name", "").endswith(".AppImage"):
                    return a
        return None

    def _extract_sha256(self, asset: dict, all_assets: list[dict]) -> str | None:
        # GitHub API digest 필드 (신규 형식: "sha256:abcd...")
        digest = asset.get("digest", "")
        if digest.startswith("sha256:"):
            return digest[7:]

        # 별도 .sha256 자산 (이름: "<asset_name>.sha256") — session 사용
        sha_name = asset["name"] + ".sha256"
        for a in all_assets:
            if a.get("name") == sha_name:
                try:
                    _validate_url(a["browser_download_url"])
                    r = self._session.get(
                        a["browser_download_url"], timeout=_TIMEOUT, verify=True
                    )
                    r.raise_for_status()
                    # BOM 제거 후 첫 번째 토큰(해시)만 추출
                    text = r.content.decode("utf-8-sig").strip()
                    token = text.split()[0] if text else ""
                    return token or None
                except (requests.RequestException, ValueError):
                    logger.debug("SHA256 파일 다운로드 실패", exc_info=True)
                    return None
        return None
