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
            resp = self._session.get(
                info.download_url,
                stream=True,
                timeout=_TIMEOUT,
                verify=True,
            )
            resp.raise_for_status()

            total = int(resp.headers.get("content-length", info.size_bytes) or 0)
            downloaded = 0
            sha = hashlib.sha256()

            with part.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=_CHUNK):
                    if not chunk:
                        continue
                    f.write(chunk)
                    sha.update(chunk)
                    downloaded += len(chunk)
                    if on_progress:
                        on_progress(downloaded, total)

        except requests.RequestException:
            part.unlink(missing_ok=True)
            raise

        # SHA-256 검증 — 체크섬 없으면 fail-closed
        if not info.sha256:
            part.unlink(missing_ok=True)
            raise RuntimeError("SHA-256 체크섬이 없어 무결성을 검증할 수 없습니다 — 설치 중단")

        digest = sha.hexdigest()
        if not hmac.compare_digest(digest, info.sha256.lower()):
            part.unlink(missing_ok=True)
            raise RuntimeError(
                f"SHA-256 불일치: expected {info.sha256}, got {digest}"
            )

        part.rename(dest)
        return dest

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
