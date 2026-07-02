"""YouTube Gemini AI 요약 추출기.

QThread 안에서만 호출해야 한다 (Playwright sync API는 메인 이벤트 루프가 없는
스레드에서 안전하게 동작한다).
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Gemini Ask 버튼 셀렉터 (다층 fallback — YouTube DOM 변경에 대응).
# 최신 YouTube는 좋아요/공유 옆 액션 행에 "질문하기"를 새 yt-button-view-model
# 구조로 렌더링해 ytd-button-renderer 기반 셀렉터가 매칭되지 않는다. 텍스트
# 기반 셀렉터는 감싸는 커스텀 엘리먼트 이름과 무관하게 동작해 더 견고하다.
_ASK_BUTTON_SELECTORS = [
    "button:has-text('질문하기')",
    "button:has-text('Ask')",
    # aria-label 기반 (접근성 속성은 변경 빈도가 낮다)
    "button[aria-label*='질문하기']",
    "button[aria-label*='Ask']",
    "button[aria-label*='Summarize']",
    "button[aria-label*='AI 요약']",
]

# "질문하기" 클릭 시 뜨는 패널의 요약 추천 칩 텍스트
_SUMMARIZE_CHIP_TEXT = "동영상을 요약해 줘"

_PAGE_LOAD_TIMEOUT_MS = 20_000
_BUTTON_SCAN_TIMEOUT_MS = 5_000
_RESPONSE_TIMEOUT_MS = 30_000
# 응답 스트리밍이 끝났다고 판단하기까지 텍스트가 변하지 않아야 하는 시간
_STABLE_POLL_INTERVAL_MS = 1_000
_STABLE_REQUIRED_COUNT = 3


class GeminiExtractor:
    """YouTube 영상 페이지에서 Gemini AI 요약 텍스트를 추출한다.

    인증은 반드시 쿠키 파일(Netscape 포맷)로만 이루어진다.

    쿠키 파일 확보 우선순위 (모두 설정 화면의 "구독 피드 — 브라우저 쿠키" 섹션에서 등록):
    1. "또는 쿠키 파일"에 등록한 Netscape 포맷 쿠키 파일 (`YT_AUTH_COOKIEFILE`)
    2. `data/auth/youtube_cookies.txt` — 별도 로그인 플로우가 앱에 연결되어 있지
       않아 현재는 수동으로 파일을 이 경로에 두었을 때만 사용된다.
    3. "브라우저"/"프로필" 드롭다운(`YT_AUTH_BROWSER`/`YT_AUTH_PROFILE`) 설정을
       yt-dlp `cookiesfrombrowser`로 임시 내보내기 — Firefox 등 대부분의 브라우저에서 동작한다.

    **Chrome v127+ 예외**: Chrome은 쿠키를 App-Bound Encryption으로 암호화해
    외부 프로세스가 복호화할 수 없다(DPAPI 오류). 프로필 직접 실행·프로필 파일
    복사·yt-dlp cookiesfrombrowser 세 가지 방식 모두 실패가 확인됐다. Chrome
    사용자는 방법 1(쿠키 파일 직접 등록)만 유효하다.
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
        temp_cookie_path: str | None = None
        if not cookie_path:
            temp_cookie_path = self._export_browser_cookies()
            cookie_path = temp_cookie_path

        if not cookie_path:
            logger.info(
                "YouTube 인증 쿠키 없음 — 설정 화면의 '구독 피드 — 브라우저 쿠키'에서 "
                "브라우저/프로필을 선택하거나 쿠키 파일을 등록하세요"
            )
            return None

        try:
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
                    page.goto(
                        url, wait_until="domcontentloaded", timeout=_PAGE_LOAD_TIMEOUT_MS
                    )

                    try:
                        page.wait_for_selector(
                            "ytd-watch-flexy", timeout=_PAGE_LOAD_TIMEOUT_MS
                        )
                    except Exception:
                        logger.debug("ytd-watch-flexy 미발견 — 계속 시도")

                    self._log_login_state(page)

                    return self._click_and_extract(page)
                finally:
                    try:
                        browser.close()
                    except Exception:
                        logger.debug("Playwright 브라우저 종료 실패")
        finally:
            if temp_cookie_path:
                Path(temp_cookie_path).unlink(missing_ok=True)

    @staticmethod
    def _log_login_state(page) -> None:
        """쿠키 주입 후 실제 로그인 상태인지 진단 로그를 남긴다."""
        try:
            signed_in = page.locator("ytd-topbar-menu-button-renderer #avatar-btn").first
            if signed_in.is_visible(timeout=3_000):
                logger.info("Gemini 추출: 로그인 상태로 페이지 로드됨")
                return
        except Exception:
            pass
        try:
            signed_out = page.locator("a[aria-label='로그인'], tp-yt-paper-button:has-text('로그인'), a:has-text('Sign in')").first
            if signed_out.is_visible(timeout=3_000):
                logger.info("Gemini 추출: 비로그인 상태로 페이지 로드됨 — 쿠키 미적용 또는 만료")
                return
        except Exception:
            pass
        logger.info("Gemini 추출: 로그인 상태 판별 불가 (셀렉터 미매칭)")

    @staticmethod
    def _save_debug_screenshot(page) -> None:
        """Ask 버튼 미발견 시 진단용 스크린샷을 로그 폴더에 저장한다."""
        try:
            import config.settings as _s  # noqa: PLC0415
            log_dir = Path(getattr(_s, "LOG_DIR", "."))
            log_dir.mkdir(parents=True, exist_ok=True)
            shot_path = log_dir / "gemini_debug.png"
            page.screenshot(path=str(shot_path))
            logger.info("Gemini 디버그 스크린샷 저장: %s", shot_path)
        except Exception:
            logger.debug("디버그 스크린샷 저장 실패")

    def _click_and_extract(self, page) -> str | None:
        """Ask 버튼 클릭 → 요약 칩 클릭 → 응답 안정화 대기 후 텍스트를 추출한다.

        "질문하기" 클릭은 채팅 패널을 열 뿐이며, 실제 요약은 추천 칩
        (예: "동영상을 요약해 줘")을 다시 클릭해야 생성된다.
        """
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
            logger.info("Gemini Ask 버튼 미발견 — 로그인 필요 또는 미지원 영상")
            self._save_debug_screenshot(page)
            return None

        ask_btn.click()

        try:
            chip = page.get_by_text(_SUMMARIZE_CHIP_TEXT, exact=False).first
            chip.wait_for(state="visible", timeout=_RESPONSE_TIMEOUT_MS)
        except Exception:
            logger.info("'%s' 추천 칩 미발견", _SUMMARIZE_CHIP_TEXT)
            self._save_debug_screenshot(page)
            self._save_debug_html(page)
            return None

        try:
            # 칩을 감싸는 패널 컨테이너를 폴링용으로 미리 확보해 둔다
            # (칩 자체는 클릭 후 대화 내용으로 대체되어 사라질 수 있다).
            panel_handle = chip.evaluate_handle(
                "el => { let p = el; for (let i = 0; i < 6 && p.parentElement; i++) "
                "p = p.parentElement; return p; }"
            )
        except Exception:
            logger.debug("패널 컨테이너 확보 실패 — 칩 자체로 폴백")
            panel_handle = None

        chip.click()

        text = self._wait_for_stable_text(page, panel_handle, chip)
        if text:
            logger.info("Gemini 요약 추출 성공 (%d자)", len(text))
            return text

        logger.info("Gemini 응답 텍스트 안정화 실패 (타임아웃)")
        self._save_debug_screenshot(page)
        self._save_debug_html(page)
        return None

    @staticmethod
    def _wait_for_stable_text(page, panel_handle, fallback_locator) -> str | None:
        """패널 텍스트가 일정 횟수 연속으로 변하지 않을 때까지 대기 후 반환한다.

        Gemini 응답은 스트리밍으로 채워지므로 고정 지연 대신 텍스트 안정화를
        기준으로 완료를 판단한다.
        """
        import time  # noqa: PLC0415

        last_text = ""
        stable_count = 0
        deadline = time.time() + _RESPONSE_TIMEOUT_MS / 1000

        while time.time() < deadline:
            page.wait_for_timeout(_STABLE_POLL_INTERVAL_MS)
            try:
                current = (
                    panel_handle.evaluate("el => el.innerText")
                    if panel_handle is not None
                    else fallback_locator.inner_text()
                ) or ""
            except Exception:
                current = ""
            current = current.strip()
            if current and current == last_text:
                stable_count += 1
                if stable_count >= _STABLE_REQUIRED_COUNT:
                    return current
            else:
                stable_count = 0
            last_text = current

        return last_text or None

    @staticmethod
    def _save_debug_html(page) -> None:
        """응답 추출 실패 시 진단용 페이지 HTML을 로그 폴더에 저장한다."""
        try:
            import config.settings as _s  # noqa: PLC0415
            log_dir = Path(getattr(_s, "LOG_DIR", "."))
            log_dir.mkdir(parents=True, exist_ok=True)
            html_path = log_dir / "gemini_debug.html"
            html_path.write_text(page.content(), encoding="utf-8")
            logger.info("Gemini 디버그 HTML 저장: %s", html_path)
        except Exception:
            logger.debug("디버그 HTML 저장 실패")

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
    def _export_browser_cookies() -> str | None:
        """`YT_AUTH_BROWSER`/`YT_AUTH_PROFILE` 설정으로 yt-dlp를 통해 쿠키를
        임시 Netscape 파일로 내보낸다.

        Firefox 등 대부분의 브라우저에서 동작한다. Chrome v127+는 App-Bound
        Encryption(DPAPI)으로 인해 실패하며, 이 경우 예외를 잡아 로그만 남기고
        None을 반환한다(호출자가 '로그인 필요' 상태로 처리).

        반환된 경로는 호출자가 사용 후 반드시 삭제해야 하는 임시 파일이다.
        """
        import os  # noqa: PLC0415
        import tempfile  # noqa: PLC0415

        import yt_dlp  # noqa: PLC0415
        import config.settings as _s  # noqa: PLC0415

        profile = getattr(_s, "YT_AUTH_PROFILE", None)
        if not profile:
            return None
        browser = getattr(_s, "YT_AUTH_BROWSER", None) or "firefox"

        fd, tmp_path = tempfile.mkstemp(prefix="ovc_gemini_cookies_", suffix=".txt")
        # yt-dlp는 cookiejar 속성 최초 접근 시(close() 시점) cookiefile을 먼저 읽으려
        # 시도한다 — mkstemp가 만든 빈 파일은 Netscape 헤더가 없어 LoadError가 나므로
        # 유효한 빈 쿠키 파일로 미리 초기화해 둔다.
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("# Netscape HTTP Cookie File\n\n")

        try:
            with yt_dlp.YoutubeDL({
                "cookiesfrombrowser": (browser, profile),
                "cookiefile": tmp_path,
                "quiet": True,
                "no_warnings": True,
            }):
                pass  # __exit__ 시 쿠키가 cookiefile에 플러시된다

            if Path(tmp_path).stat().st_size > 100:
                logger.info("브라우저(%s) 쿠키 임시 내보내기 성공: profile=%s", browser, profile)
                return tmp_path
            logger.debug("브라우저 쿠키 내보내기 결과 비어있음")
        except Exception:
            logger.warning(
                "브라우저 쿠키 내보내기 실패 (%s/%s)",
                browser, profile, exc_info=True,
            )
        Path(tmp_path).unlink(missing_ok=True)
        return None

    @staticmethod
    def _load_netscape_cookies(context, cookie_path: str) -> None:
        """Netscape 포맷 쿠키 파일을 Playwright 컨텍스트에 주입한다."""
        import time  # noqa: PLC0415

        cookies = []
        try:
            with open(cookie_path, encoding="utf-8") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line:
                        continue
                    # HttpOnly 쿠키는 "#HttpOnly_domain\t..." 형식으로 저장된다
                    # (SID/HSID/SSID 등 로그인 필수 쿠키 대부분이 여기 해당) —
                    # 진짜 주석("# ...")과 구분해 접두사만 제거하고 계속 처리한다.
                    http_only = False
                    if line.startswith("#HttpOnly_"):
                        http_only = True
                        line = line[len("#HttpOnly_"):]
                    elif line.startswith("#"):
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
                        "httpOnly": http_only,
                        "sameSite": "None",
                    })
            if cookies:
                context.add_cookies(cookies)
                logger.debug("YouTube 쿠키 %d개 주입 완료", len(cookies))
        except Exception:
            logger.exception("쿠키 파일 로드 실패 — 비로그인 상태로 계속")
