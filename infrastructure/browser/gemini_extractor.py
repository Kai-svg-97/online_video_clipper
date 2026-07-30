"""YouTube Gemini AI 요약 추출기.

QThread 안에서만 호출해야 한다 (Playwright sync API는 메인 이벤트 루프가 없는
스레드에서 안전하게 동작한다).
"""
from __future__ import annotations

import logging
import re
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
# 칩 텍스트 공백 표기 흔들림("동영상을 요약해줘" 등)까지 잡는 공백 무시 패턴
_SUMMARIZE_CHIP_RE = re.compile(r"동영상을\s*요약해\s*줘")

# 칩 클릭 후 요약 대신 나타날 수 있는 추천 질문/메뉴 칩 라벨(비-요약).
# 이런 문구만으로 구성된 응답은 요약이 아니므로 성공으로 인정하지 않는다.
# 오검출(정상 요약을 메뉴로 오판)을 피하기 위해 보수적으로 시작한다.
_MENU_PHRASES = (
    "동영상을 요약해 줘",
    "동영상을 요약해줘",
    "타임라인을 만들어 줘",
    "타임라인을 만들어줘",
    "핵심 내용을 알려 줘",
    "핵심 내용을 알려줘",
    "이 동영상에 대해 질문하기",
    "질문하기",
    "다른 질문",
)
# 요약 본문으로 인정하기 위한 최소 길이(자). 이보다 짧으면 칩/메뉴 라벨로 간주.
_MIN_SUMMARY_LEN = 40

# 요약 본문 뒤에 붙는 면책/추천질문 블록의 시작 앵커 — 이 지점부터 잘라낸다.
_TRAILING_ANCHORS = (
    "AI도 실수를 할 수 있으니",
    "AI can make mistakes",
    "AI의 응답에는 실수가",
)

# Gemini 백엔드가 요청을 거부했을 때 패널에 표시되는 오류 문구
_ERROR_PHRASE = "문제가 발생했습니다"
_MAX_ERROR_RETRIES = 2

_PAGE_LOAD_TIMEOUT_MS = 20_000
# "질문하기" 버튼이 나타나기를 기다리는 **총** 예산.
# 유의: 예전에는 셀렉터마다 `is_visible(timeout=...)`로 확인했는데, Playwright 문서는
# 이 timeout 을 "Deprecated: This option is ignored. locator.is_visible() does not wait
# for the element to become visible and returns immediately." 라고 명시한다. 즉 대기가
# 전혀 없었고, 액션 행이 아직 스켈레톤인 영상에서는 0.2초 만에 미발견으로 포기했다.
# 이제 모든 셀렉터를 or_ 로 합쳐 `wait_for(state="visible")`로 한 번만 기다린다.
_ASK_BUTTON_TIMEOUT_MS = 20_000
_LOGIN_PROBE_TIMEOUT_MS = 8_000

# 요약 실패 사유 — 상세 화면이 원인별로 다른 안내 문구를 띄우는 데 쓴다.
# "질문하기 버튼이 없어서" 실패한 경우는 사용자가 손쓸 수 없는 YouTube 측 제약이므로
# 쿠키·네트워크 문제와 반드시 구분해 알려야 한다.
SUMMARY_REASON_NO_BUTTON = "no_button"
SUMMARY_REASON_NOT_SIGNED_IN = "not_signed_in"
SUMMARY_REASON_ERROR = "error"
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

        `ISummarySource` 포트 계약이며 다운로드 완료 캡처 경로가 이 형태를 쓴다.
        실패 사유까지 필요하면 `extract_with_reason()`을 쓸 것.

        반드시 QThread(백그라운드 스레드)에서 호출해야 한다.
        """
        return self.extract_with_reason(url)[0]

    def extract_with_reason(self, url: str) -> tuple[str | None, str]:
        """(요약, 실패사유)를 반환한다. 성공 시 사유는 빈 문자열.

        사유는 SUMMARY_REASON_* 중 하나다. 상세 화면이 "질문하기 버튼이 없어서"와
        쿠키·네트워크 문제를 구분해 안내하기 위해 필요하다.
        """
        out: dict[str, str] = {}
        try:
            summary = self._do_extract(url, out)
        except Exception:
            logger.exception("Gemini 요약 추출 실패 (무시하고 계속): %s", url)
            return None, SUMMARY_REASON_ERROR
        if summary:
            return summary, ""
        return None, out.get("reason", SUMMARY_REASON_ERROR)

    def _do_extract(self, url: str, out: dict | None = None) -> str | None:
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
                browser = self._launch_browser(p)
                if browser is None:
                    logger.warning(
                        "브라우저 실행 실패 — Chrome/Edge 미설치 및 번들 Chromium 없음. "
                        "Chrome 또는 Edge를 설치하세요"
                    )
                    return None
                try:
                    context = browser.new_context(
                        user_agent=(
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36"
                        ),
                        locale="ko-KR",
                        viewport={"width": 1366, "height": 900},
                    )
                    context.add_init_script(
                        "Object.defineProperty(navigator, 'webdriver', "
                        "{get: () => undefined});"
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

                    return self._click_and_extract(page, out)
                finally:
                    try:
                        browser.close()
                    except Exception:
                        logger.debug("Playwright 브라우저 종료 실패")
        finally:
            if temp_cookie_path:
                Path(temp_cookie_path).unlink(missing_ok=True)

    @staticmethod
    def _detect_login_state(page, timeout_ms: int = _LOGIN_PROBE_TIMEOUT_MS) -> str:
        """로그인 상태를 판정한다 — "signed_in" | "signed_out" | "unknown".

        `is_visible(timeout=...)`을 쓰지 않는다: Playwright 가 그 timeout 을 무시하고
        즉시 반환해, 아바타가 아직 렌더되지 않았으면 로그인 상태인데도 "판별 불가"로
        기록됐다. 그 오판이 실패 원인을 잘못 짚게 만들었다.
        """
        try:
            avatar = page.locator("ytd-topbar-menu-button-renderer #avatar-btn").first
            avatar.wait_for(state="visible", timeout=timeout_ms)
            return "signed_in"
        except Exception:
            pass
        try:
            signin = page.locator(
                "a[aria-label='로그인'], tp-yt-paper-button:has-text('로그인'), "
                "a:has-text('Sign in')"
            ).first
            signin.wait_for(state="visible", timeout=timeout_ms)
            return "signed_out"
        except Exception:
            pass
        return "unknown"

    @classmethod
    def _log_login_state(cls, page) -> None:
        """쿠키 주입 후 실제 로그인 상태인지 진단 로그를 남긴다."""
        state = cls._detect_login_state(page)
        if state == "signed_in":
            logger.info("Gemini 추출: 로그인 상태로 페이지 로드됨")
        elif state == "signed_out":
            logger.info("Gemini 추출: 비로그인 상태로 페이지 로드됨 — 쿠키 미적용 또는 만료")
        else:
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

    @staticmethod
    def _find_ask_button(page, timeout_ms: int = _ASK_BUTTON_TIMEOUT_MS):
        """"질문하기" 버튼이 보일 때까지 기다렸다가 반환한다(없으면 None).

        모든 fallback 셀렉터를 `or_`로 하나로 합쳐 **총 예산 한 번**만 소비한다.
        셀렉터마다 따로 기다리면 미지원 영상에서 대기 시간이 셀렉터 수만큼 늘어난다.

        `is_visible(timeout=...)`을 쓰지 않는 이유: Playwright 가 그 timeout 을 무시하고
        즉시 반환하므로 대기 수단이 되지 못한다(버튼이 늦게 렌더되면 놓친다).

        각 셀렉터에 `>> visible=true`를 붙이는 이유: 실측 결과 지원되는 영상에서
        `button[aria-label*='질문하기']`가 5개 매칭 중 **첫 번째가 숨은 요소**였다.
        필터 없이 or_ 로 합치면 `.first`가 그 숨은 요소를 가리켜 `wait_for(visible)`가
        영원히 실패한다(정상 영상까지 못 찾는 회귀).
        """
        combined = None
        for sel in _ASK_BUTTON_SELECTORS:
            loc = page.locator(f"{sel} >> visible=true")
            combined = loc if combined is None else combined.or_(loc)
        if combined is None:
            return None

        btn = combined.first
        try:
            btn.wait_for(state="visible", timeout=timeout_ms)
        except Exception:
            return None
        return btn

    def _click_and_extract(self, page, out: dict | None = None) -> str | None:
        """Ask 버튼 클릭 → 요약 칩 클릭 → 응답 안정화 대기 후 텍스트를 추출한다.

        "질문하기" 클릭은 채팅 패널을 열 뿐이며, 실제 요약은 추천 칩
        (예: "동영상을 요약해 줘")을 다시 클릭해야 생성된다.
        """
        ask_btn = self._find_ask_button(page)
        if ask_btn is None:
            # 원인을 구분해 기록한다. 예전에는 "로그인 필요 또는 미지원 영상"으로 뭉쳐
            # 있어, 로그인이 정상인데도 인증 문제로 오해하게 만들었다.
            state = self._detect_login_state(page)
            if out is not None:
                out["reason"] = (
                    SUMMARY_REASON_NOT_SIGNED_IN
                    if state == "signed_out"
                    else SUMMARY_REASON_NO_BUTTON
                )
            if state == "signed_out":
                logger.warning(
                    "Gemini '질문하기' 버튼 없음 — 비로그인 상태다. 설정에서 쿠키를 "
                    "다시 등록하세요: %s",
                    page.url,
                )
            else:
                logger.info(
                    "Gemini '질문하기' 버튼이 %d초 안에 나타나지 않음 — YouTube가 이 "
                    "영상에 요약 기능을 제공하지 않는 것으로 보인다(로그인 상태: %s). "
                    "조회수가 적거나 업로드가 최근인 영상은 기능이 제공되지 않는 사례가 "
                    "있다: %s",
                    _ASK_BUTTON_TIMEOUT_MS // 1000,
                    state,
                    page.url,
                )
            self._save_debug_screenshot(page)
            return None

        ask_btn.click()

        try:
            chip_text = page.get_by_text(_SUMMARIZE_CHIP_RE).first
            chip_text.wait_for(state="visible", timeout=_RESPONSE_TIMEOUT_MS)
        except Exception:
            logger.info("'%s' 추천 칩 미발견", _SUMMARIZE_CHIP_TEXT)
            self._save_debug_screenshot(page)
            self._save_debug_html(page)
            return None

        # get_by_text는 텍스트를 담은 가장 안쪽 노드(span/div)를 잡을 수 있어
        # 클릭 핸들러가 실제로 걸린 button 조상을 우선 사용한다. button 조상이
        # 없으면(텍스트 자체가 클릭 대상) 원래 요소로 폴백한다.
        try:
            btn_ancestor = chip_text.locator("xpath=ancestor-or-self::button[1]")
            btn_ancestor.wait_for(state="visible", timeout=2_000)
            chip = btn_ancestor
        except Exception:
            chip = chip_text

        try:
            # 칩을 감싸는 패널 컨테이너를 폴링용으로 미리 확보해 둔다
            # (칩 자체는 클릭 후 대화 내용으로 대체되어 사라질 수 있다).
            panel_handle = chip.evaluate_handle(
                "el => { let p = el; for (let i = 0; i < 8 && p.parentElement; i++) "
                "p = p.parentElement; return p; }"
            )
        except Exception:
            logger.debug("패널 컨테이너 확보 실패 — 칩 자체로 폴백")
            panel_handle = None

        self._robust_click(chip)
        summary = self._wait_for_summary(page, panel_handle, chip)

        retries = 0
        while (
            (not summary or _ERROR_PHRASE in summary or not self._looks_like_summary(summary))
            and retries < _MAX_ERROR_RETRIES
        ):
            retries += 1
            if summary and _ERROR_PHRASE in summary:
                reason = "오류 문구 감지"
            elif summary and not self._looks_like_summary(summary):
                reason = "요약 대신 메뉴/추천칩 감지"
            else:
                reason = "응답 없음"
            logger.info("Gemini 응답 재시도 %d/%d (%s)", retries, _MAX_ERROR_RETRIES, reason)
            try:
                self._robust_click(chip)
            except Exception:
                logger.debug("재시도 클릭 실패 — 칩이 더 이상 존재하지 않음")
                break
            summary = self._wait_for_summary(page, panel_handle, chip)

        if summary and _ERROR_PHRASE not in summary and self._looks_like_summary(summary):
            logger.info("Gemini 요약 추출 성공 (%d자)", len(summary))
            return summary

        logger.info("Gemini 요약 추출 실패 — 응답이 없거나 오류/메뉴 상태")
        self._save_debug_screenshot(page)
        self._save_debug_html(page)
        return None

    @staticmethod
    def _launch_browser(p):
        """Chromium 계열 브라우저를 실행한다.

        패키징된 앱에는 Playwright의 Chromium 바이너리가 번들되지 않으므로
        시스템에 설치된 Chrome/Edge(channel)를 우선 사용하고, 둘 다 없으면
        번들 Chromium(dev 환경)으로 폴백한다. 자동화 감지를 완화하는 인자를 공통 적용.
        """
        launch_args = {
            "headless": True,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        # 1) 시스템 Chrome → 2) 시스템 Edge → 3) 번들 Chromium(dev)
        for channel in ("chrome", "msedge"):
            try:
                browser = p.chromium.launch(channel=channel, **launch_args)
                logger.info("Gemini 추출: 시스템 브라우저 실행 (channel=%s)", channel)
                return browser
            except Exception:
                logger.debug("channel=%s 실행 실패 — 다음 후보 시도", channel)
        try:
            browser = p.chromium.launch(**launch_args)
            logger.info("Gemini 추출: 번들 Chromium 실행")
            return browser
        except Exception:
            logger.debug("번들 Chromium 실행도 실패")
            return None

    @staticmethod
    def _robust_click(locator) -> None:
        """칩을 뷰에 스크롤한 뒤 클릭한다. 일반 클릭 실패 시 강제 클릭으로 폴백."""
        try:
            locator.scroll_into_view_if_needed(timeout=2_000)
        except Exception:
            pass
        try:
            locator.click(timeout=5_000)
        except Exception:
            locator.click(timeout=5_000, force=True)

    @staticmethod
    def _read_panel_text(panel_handle, fallback_locator) -> str:
        """패널(또는 폴백 요소)의 현재 텍스트를 읽는다. 실패 시 빈 문자열."""
        try:
            current = (
                panel_handle.evaluate("el => el.innerText")
                if panel_handle is not None
                else fallback_locator.inner_text()
            ) or ""
        except Exception:
            current = ""
        return current.strip()

    @staticmethod
    def _clean_summary(full_text: str) -> str:
        """전체 패널 텍스트에서 순수 요약 본문만 잘라낸다.

        패널에는 인사말·추천 질문·요약 본문·면책 문구·추천 질문이 모두 담긴다.
        요약 본문은 마지막 "동영상을 요약해 줘"(클릭된 질문의 에코) 이후부터
        면책 문구("AI도 실수를 할 수 있으니…") 직전까지의 구간이다.
        """
        if not full_text:
            return ""
        idx = full_text.rfind(_SUMMARIZE_CHIP_TEXT)
        body = (
            full_text[idx + len(_SUMMARIZE_CHIP_TEXT):]
            if idx >= 0
            else full_text
        )
        for anchor in _TRAILING_ANCHORS:
            pos = body.find(anchor)
            if pos >= 0:
                body = body[:pos]
                break
        return body.strip()

    @staticmethod
    def _looks_like_summary(text: str) -> bool:
        """추출된 텍스트가 실제 요약 본문인지(추천칩/메뉴가 아닌지) 판정한다.

        칩 클릭 후 요약이 생성되지 않고 추천 질문/메뉴만 다시 뜨는 경우, 그
        정적 라벨 텍스트가 안정화 조건을 즉시 만족해 요약으로 오인될 수 있다.
        이를 걸러내기 위해 (1) 메뉴 문구를 제거한 뒤 (2) 남은 본문의 길이로
        판정한다. 보수적으로 판단해 정상 요약을 메뉴로 오판하지 않도록 한다.
        """
        if not text:
            return False
        residual = text
        for phrase in _MENU_PHRASES:
            residual = residual.replace(phrase, " ")
        # 메뉴 라벨을 제거하고 공백을 정리한 뒤에도 충분한 본문이 남아야 요약.
        residual = re.sub(r"\s+", " ", residual).strip()
        return len(residual) >= _MIN_SUMMARY_LEN

    @classmethod
    def _wait_for_summary(cls, page, panel_handle, fallback_locator) -> str | None:
        """정제된 요약 본문이 비어있지 않고 안정될 때까지 폴링 후 반환한다.

        전체 패널이 아닌 '정제된 요약 영역'만 기준으로 판단하므로, 인사말/추천
        질문만 있는 상태(요약 미생성)를 성공으로 오인하지 않는다. 응답은 스트리밍
        으로 채워지므로 본문이 `_STABLE_REQUIRED_COUNT`회 연속 동일할 때 완료로 본다.
        오류 문구가 감지되면 즉시 반환해 상위 재시도 루프가 처리하게 한다.
        """
        import time  # noqa: PLC0415

        last_summary = ""
        stable_count = 0
        deadline = time.time() + _RESPONSE_TIMEOUT_MS / 1000

        while time.time() < deadline:
            page.wait_for_timeout(_STABLE_POLL_INTERVAL_MS)
            full = cls._read_panel_text(panel_handle, fallback_locator)
            if _ERROR_PHRASE in full:
                return cls._clean_summary(full) or _ERROR_PHRASE
            summary = cls._clean_summary(full)
            if summary and summary == last_summary:
                stable_count += 1
                if stable_count >= _STABLE_REQUIRED_COUNT:
                    return summary
            else:
                stable_count = 0
            last_summary = summary

        return last_summary or None

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
