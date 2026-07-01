"""YouTube Gemini AI 요약 추출기.

QThread 안에서만 호출해야 한다 (Playwright sync API는 메인 이벤트 루프가 없는
스레드에서 안전하게 동작한다).
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Gemini Ask 버튼 셀렉터 (다층 fallback — YouTube DOM 변경에 대응)
_ASK_BUTTON_SELECTORS = [
    # aria-label 기반 (접근성 속성은 변경 빈도가 낮다)
    "button[aria-label*='Ask']",
    "button[aria-label*='질문하기']",
    "button[aria-label*='Summarize']",
    "button[aria-label*='AI 요약']",
    # YouTube custom element 내부 버튼
    "ytd-button-renderer:has-text('Ask') button",
    "ytd-button-renderer:has-text('질문하기') button",
    # chip 형태
    "yt-chip-cloud-chip-renderer:has-text('Ask')",
    "yt-chip-cloud-chip-renderer:has-text('질문하기')",
]

# 요약 결과 컨테이너 셀렉터
_SUMMARY_CONTAINER_SELECTORS = [
    "ytd-engagement-panel-section-list-renderer[target-id*='gemini']",
    "ytd-engagement-panel-section-list-renderer[target-id*='ai']",
    "ytd-engagement-panel-section-list-renderer[target-id*='searchable-transcript']",
    "#engagement-panel-searchable-transcript",
]

_PAGE_LOAD_TIMEOUT_MS = 20_000
_BUTTON_SCAN_TIMEOUT_MS = 5_000
_RESPONSE_TIMEOUT_MS = 30_000


class GeminiExtractor:
    """YouTube 영상 페이지에서 Gemini AI 요약 텍스트를 추출한다.

    인증은 반드시 쿠키 파일(Netscape 포맷)로만 이루어진다. Chrome v127+는
    쿠키를 App-Bound Encryption으로 암호화해 프로필 직접 접근·복사·yt-dlp
    cookiesfrombrowser 어떤 방식으로도 외부에서 복호화할 수 없으므로(DPAPI
    오류), 설정 > YouTube 계정의 "새 계정으로 로그인…"(Playwright 로그인)
    플로우로 저장된 data/auth/youtube_cookies.txt에 의존한다.
    """

    def extract(self, url: str) -> str | None:
        """Gemini 요약 텍스트를 반환한다. 실패·미지원 시 None.

        반드시 QThread(백그라운드 스레드)에서 호출해야 한다.
        """
        try:
            return self._do_extract(url)
        except Exception:
            logger.exception("Gemini 요약 추출 실패 (무시하고 계속): %s", url)
            return None

    def _do_extract(self, url: str) -> str | None:
        try:
            from playwright.sync_api import sync_playwright  # noqa: PLC0415
        except ImportError:
            logger.warning("playwright 미설치 — Gemini 추출 생략")
            return None

        cookie_path = self._get_cookie_path()
        if not cookie_path:
            logger.info(
                "YouTube 인증 쿠키 없음 — 설정 > YouTube 계정에서 "
                "'새 계정으로 로그인…'을 먼저 실행하세요"
            )
            return None

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    locale="ko-KR",
                )
                self._load_netscape_cookies(context, cookie_path)

                page = context.new_page()
                page.route(
                    "**/*.{png,jpg,jpeg,gif,svg,ico,woff,woff2,ttf,otf}",
                    lambda r: r.abort(),
                )

                logger.info("Gemini 추출: 페이지 로드 중 %s", url)
                page.goto(url, wait_until="domcontentloaded", timeout=_PAGE_LOAD_TIMEOUT_MS)

                try:
                    page.wait_for_selector("ytd-watch-flexy", timeout=_PAGE_LOAD_TIMEOUT_MS)
                except Exception:
                    logger.debug("ytd-watch-flexy 미발견 — 계속 시도")

                return self._click_and_extract(page)
            finally:
                try:
                    browser.close()
                except Exception:
                    logger.debug("Playwright 브라우저 종료 실패")

    def _click_and_extract(self, page) -> str | None:
        """Ask 버튼 클릭 후 응답 텍스트를 추출한다."""
        ask_btn = None
        for sel in _ASK_BUTTON_SELECTORS:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=_BUTTON_SCAN_TIMEOUT_MS):
                    ask_btn = btn
                    logger.debug("Gemini Ask 버튼 발견: %s", sel)
                    break
            except Exception:
                continue

        if ask_btn is None:
            logger.debug("Gemini Ask 버튼 미발견 — 로그인 필요 또는 미지원 영상")
            return None

        ask_btn.click()

        for sel in _SUMMARY_CONTAINER_SELECTORS:
            try:
                container = page.locator(sel).first
                container.wait_for(state="visible", timeout=_RESPONSE_TIMEOUT_MS)
                text = container.inner_text()
                if text and text.strip():
                    logger.info("Gemini 요약 추출 성공 (%d자)", len(text))
                    return text.strip()
            except Exception:
                continue

        logger.debug("Gemini 응답 컨테이너 미발견")
        return None

    @staticmethod
    def _get_cookie_path() -> str | None:
        """YouTube 인증 쿠키 파일 경로를 반환한다.

        우선순위:
        1. YT_AUTH_COOKIEFILE 설정에 파일이 있으면 그대로 사용
        2. Playwright 로그인으로 저장된 data/auth/youtube_cookies.txt
        """
        try:
            import config.settings as _s  # noqa: PLC0415
            cookiefile = getattr(_s, "YT_AUTH_COOKIEFILE", None)
            if cookiefile and Path(cookiefile).exists():
                return cookiefile

            data_dir = getattr(_s, "DATA_DIR", None)
            if data_dir:
                playwright_cookie = Path(data_dir) / "auth" / "youtube_cookies.txt"
                if playwright_cookie.exists() and playwright_cookie.stat().st_size > 0:
                    logger.debug("Playwright 저장 쿠키 사용: %s", playwright_cookie)
                    return str(playwright_cookie)
        except Exception:
            logger.debug("쿠키 경로 확인 실패")
        return None

    @staticmethod
    def _load_netscape_cookies(context, cookie_path: str) -> None:
        """Netscape 포맷 쿠키 파일을 Playwright 컨텍스트에 주입한다."""
        import time  # noqa: PLC0415

        cookies = []
        try:
            with open(cookie_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) < 7:
                        continue
                    domain, _, path, secure, expiry, name, value = parts[:7]
                    expires = (
                        int(expiry)
                        if expiry.lstrip("-").isdigit()
                        else int(time.time()) + 86400
                    )
                    cookies.append({
                        "name": name,
                        "value": value,
                        "domain": domain,
                        "path": path,
                        "expires": expires,
                        "secure": secure.upper() == "TRUE",
                        "httpOnly": False,
                        "sameSite": "None",
                    })
            if cookies:
                context.add_cookies(cookies)
                logger.debug("YouTube 쿠키 %d개 주입 완료", len(cookies))
        except Exception:
            logger.exception("쿠키 파일 로드 실패 — 비로그인 상태로 계속")
