"""YouTube 브라우저 쿠키 기반 인증 서비스."""
from __future__ import annotations

import configparser
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from config.settings import DATA_DIR, save_setting

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BrowserProfile:
    name: str           # 화면 표시 이름
    display_name: str   # "이름 (email@gmail.com)" 형식
    profile_key: str    # yt-dlp에 전달할 프로필 디렉토리명


class YouTubeAuthService:
    """브라우저 프로필 감지 + yt-dlp 쿠키 옵션 관리."""

    def detect_profiles(self, browser: str) -> list[BrowserProfile]:
        """설치된 브라우저의 로그인 프로필 목록 반환."""
        try:
            if browser in ("chrome",):
                return self._chromium_profiles("Google", "Chrome")
            if browser == "edge":
                return self._chromium_profiles("Microsoft", "Edge")
            if browser == "chromium":
                return self._chromium_profiles("Chromium", "Chromium")
            if browser == "firefox":
                return self._firefox_profiles()
        except Exception:
            logger.exception("브라우저 프로필 감지 실패")
        return []

    def _chromium_profiles(self, vendor: str, app: str) -> list[BrowserProfile]:
        local_state = self._chromium_local_state(vendor, app)
        if local_state is None or not local_state.exists():
            return []
        with open(local_state, encoding="utf-8") as f:
            data = json.load(f)
        info_cache = data.get("profile", {}).get("info_cache", {})
        profiles: list[BrowserProfile] = []
        for profile_dir, info in info_cache.items():
            name = info.get("name") or profile_dir
            email = info.get("user_name") or ""
            display = f"{name}  ({email})" if email else name
            profiles.append(BrowserProfile(
                name=name,
                display_name=display,
                profile_key=profile_dir,
            ))
        return profiles

    @staticmethod
    def _chromium_local_state(vendor: str, app: str) -> Path | None:
        if sys.platform == "win32":
            base = os.environ.get("LOCALAPPDATA", "")
            return Path(base) / vendor / app / "User Data" / "Local State"
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / vendor / app / "Local State"
        # Linux
        return Path.home() / f".config/{app.lower()}" / "Local State"

    def _firefox_profiles(self) -> list[BrowserProfile]:
        if sys.platform == "win32":
            base = os.environ.get("APPDATA", "")
            profiles_dir = Path(base) / "Mozilla" / "Firefox"
        elif sys.platform == "darwin":
            profiles_dir = Path.home() / "Library" / "Application Support" / "Firefox"
        else:
            profiles_dir = Path.home() / ".mozilla" / "firefox"

        ini_path = profiles_dir / "profiles.ini"
        if not ini_path.exists():
            return []
        config = configparser.ConfigParser()
        config.read(str(ini_path), encoding="utf-8")
        profiles: list[BrowserProfile] = []
        for section in config.sections():
            if not section.startswith("Profile"):
                continue
            name = config.get(section, "Name", fallback=section)
            raw_path = config.get(section, "Path", fallback="")
            is_relative = config.getboolean(section, "IsRelative", fallback=True)

            if raw_path:
                # profiles.ini 경로는 슬래시 구분 → OS 구분자로 변환
                if is_relative:
                    profile_abs = profiles_dir / raw_path.replace("/", os.sep)
                else:
                    profile_abs = Path(raw_path)
                # yt-dlp 는 절대 경로면 그대로 사용, 이름이면 Profiles\{name} 으로 해석
                profile_key = str(profile_abs) if profile_abs.exists() else name
            else:
                profile_key = name

            profiles.append(BrowserProfile(
                name=name,
                display_name=name,
                profile_key=profile_key,
            ))
        return profiles

    def get_ytdlp_opts(self) -> dict:
        """저장된 인증 설정을 yt-dlp 옵션 dict로 반환.

        인증 미설정 시 빈 dict 반환 — 호출자는 빈 dict를 '비로그인'으로 처리해야 함.

        브라우저 쿠키는 프로필이 명시적으로 선택된 경우에만 사용한다.
        프로필 없이 브라우저만 지정되면 Chrome 실행 중 DB 잠금 문제가 발생하므로
        쿠키파일 또는 명시적 프로필이 없으면 빈 dict를 반환한다.
        """
        import config.settings as s  # noqa: PLC0415
        cookiefile = getattr(s, "YT_AUTH_COOKIEFILE", None)
        browser    = getattr(s, "YT_AUTH_BROWSER", None) or "firefox"
        profile    = getattr(s, "YT_AUTH_PROFILE", None)

        if cookiefile:
            return {"cookiefile": cookiefile}
        if profile:
            # 특정 프로필이 선택된 경우에만 브라우저 쿠키 사용
            return {"cookiesfrombrowser": (browser, profile)}
        # 프로필 미선택 + 쿠키파일 없음 → 비인증 (공개 콘텐츠만 접근 가능)
        return {}

    def _wl_ydl_opts(self, cookie_opts: dict) -> dict:
        """Watch Later 조회용 공통 yt-dlp 옵션."""
        return {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": True,
            "playlistend": 1,
            "extractor_args": {"youtubetab": {"skip": ["authcheck"]}},
            **cookie_opts,
        }

    def get_channel_info(self, cookie_opts: dict | None = None) -> dict | None:
        """현재 인증 계정의 YouTube 채널 정보 반환. 배경 스레드 전용.

        Watch Later(WL) 플레이리스트에서 uploader 필드로 채널명·URL을 추출한다.
        Returns: {"name": str, "channel_url": str} 또는 None
        """
        opts = cookie_opts if cookie_opts is not None else self.get_ytdlp_opts()
        if not opts:
            return None
        try:
            import yt_dlp  # noqa: PLC0415
            with yt_dlp.YoutubeDL(self._wl_ydl_opts(opts)) as ydl:
                info = ydl.extract_info(
                    "https://www.youtube.com/playlist?list=WL", download=False
                ) or {}
            name = info.get("uploader") or info.get("channel") or ""
            ch_url = (
                info.get("uploader_url")
                or info.get("channel_url")
                or ""
            )
            if name:
                return {"name": name, "channel_url": ch_url}
        except Exception:
            logger.exception("YouTube 채널 정보 조회 실패")
        return None

    def check_login_status(self) -> str | None:
        """현재 저장된 인증으로 YouTube 로그인 여부 확인. 배경 스레드 전용.

        Returns:
            YouTube 채널명 문자열 또는 None(로그인 안 됨)
        """
        import config.settings as _s  # noqa: PLC0415
        cookiefile = getattr(_s, "YT_AUTH_COOKIEFILE", None)
        profile    = getattr(_s, "YT_AUTH_PROFILE", None)
        if not cookiefile and not profile:
            return None  # 인증 미설정

        info = self.get_channel_info()
        return info["name"] if info else None

    def save_auth(
        self,
        browser: str,
        profile_key: str | None = None,
        cookiefile: str | None = None,
        account_name: str | None = None,
    ) -> None:
        """인증 설정을 config.yaml에 저장."""
        save_setting("yt_auth_browser", browser)
        save_setting("yt_auth_profile", profile_key)
        save_setting("yt_auth_cookiefile", cookiefile)
        save_setting("yt_auth_account_name", account_name)

    def clear_auth(self) -> None:
        """인증 정보를 초기화하고 저장된 쿠키 파일을 삭제한다."""
        import config.settings as s  # noqa: PLC0415
        cookiefile = getattr(s, "YT_AUTH_COOKIEFILE", None)
        if cookiefile:
            try:
                Path(cookiefile).unlink(missing_ok=True)
            except Exception:
                logger.exception("저장된 쿠키 파일 삭제 실패")
        # Playwright 로그인으로 생성된 쿠키 파일 삭제
        playwright_cookie = DATA_DIR / "auth" / "youtube_cookies.txt"
        playwright_cookie.unlink(missing_ok=True)

        save_setting("yt_auth_browser", "chrome")
        save_setting("yt_auth_profile", None)
        save_setting("yt_auth_cookiefile", None)
        save_setting("yt_auth_account_name", None)


def write_netscape_cookies(path: Path, cookies: list[dict]) -> None:
    """Playwright 쿠키 list를 yt-dlp가 읽을 수 있는 Netscape 포맷으로 저장."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Netscape HTTP Cookie File\n"]
    for c in cookies:
        domain = c.get("domain", "")
        include_sub = "TRUE" if domain.startswith(".") else "FALSE"
        path_val = c.get("path", "/")
        secure = "TRUE" if c.get("secure", False) else "FALSE"
        expiry = int(c.get("expires") or 0)
        if expiry <= 0:
            expiry = int(time.time()) + 86400 * 365
        name = c.get("name", "")
        value = c.get("value", "")
        lines.append(
            f"{domain}\t{include_sub}\t{path_val}\t{secure}\t{expiry}\t{name}\t{value}\n"
        )
    path.write_text("".join(lines), encoding="utf-8")
