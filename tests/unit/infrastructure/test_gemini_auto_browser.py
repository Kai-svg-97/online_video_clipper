"""GeminiExtractor 쿠키 자동 감지 폴백.

사용자가 브라우저/프로필을 설정하지 않았거나, 설정한 브라우저에서 쿠키 내보내기가
실패해도(브라우저 실행 중 DB 잠금, Chrome App-Bound Encryption 등) 설치된 다른
로그인 브라우저를 자동으로 찾아 쿠키를 얻는다 — 매번 설정 화면에서 브라우저/프로필을
다시 선택해야 하는 수고를 없애기 위함이다.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yt_dlp

from infrastructure.auth.youtube_auth import BrowserProfile, YouTubeAuthService
from infrastructure.browser.gemini_extractor import (
    SUMMARY_REASON_NOT_SIGNED_IN,
    GeminiExtractor,
)


class _FakeYDL:
    """지정된 (browser, profile)이 성공 목록에 있을 때만 쿠키파일에 내용을 채운다."""

    SUCCESS: set[tuple[str, str]] = set()

    def __init__(self, opts):
        self._opts = opts

    def __enter__(self):
        browser, profile = self._opts["cookiesfrombrowser"]
        if (browser, profile) in self.SUCCESS:
            with open(self._opts["cookiefile"], "a", encoding="utf-8") as f:
                f.write(".youtube.com\tTRUE\t/\tTRUE\t0\tSID\tabc123\n" * 5)
        return self

    def __exit__(self, *exc_info):
        return False


@pytest.fixture(autouse=True)
def _fake_ydl(monkeypatch):
    _FakeYDL.SUCCESS = set()
    monkeypatch.setattr(yt_dlp, "YoutubeDL", _FakeYDL)
    yield
    _FakeYDL.SUCCESS = set()


@pytest.fixture
def no_persist(monkeypatch):
    """save_setting이 실사용 config.yaml을 건드리지 않도록 무력화한다."""
    import config.settings as s

    saved: dict[str, object] = {}
    monkeypatch.setattr(s, "save_setting", lambda k, v: saved.update({k: v}))
    return saved


def _cleanup(path: str | None) -> None:
    if path:
        Path(path).unlink(missing_ok=True)


class TestExplicitBrowserSucceeds:
    def test_명시적으로_설정한_브라우저가_성공하면_자동감지를_시도하지_않는다(
        self, monkeypatch, no_persist
    ):
        import config.settings as s

        monkeypatch.setattr(s, "YT_AUTH_BROWSER", "chrome", raising=False)
        monkeypatch.setattr(s, "YT_AUTH_PROFILE", "Default", raising=False)
        _FakeYDL.SUCCESS = {("chrome", "Default")}

        def _boom(self, browser):
            raise AssertionError("성공했는데 자동감지가 호출됨")

        monkeypatch.setattr(YouTubeAuthService, "detect_profiles", _boom)

        path = GeminiExtractor._export_browser_cookies()

        assert path is not None
        _cleanup(path)


class TestAutoDetectFallback:
    def test_설정이_없으면_설치된_다른_브라우저를_자동으로_찾아_시도한다(
        self, monkeypatch, no_persist
    ):
        import config.settings as s

        monkeypatch.setattr(s, "YT_AUTH_BROWSER", None, raising=False)
        monkeypatch.setattr(s, "YT_AUTH_PROFILE", None, raising=False)
        _FakeYDL.SUCCESS = {("edge", "Default")}

        def fake_detect(self, browser):
            if browser == "edge":
                return [BrowserProfile("Default", "Default", "Default")]
            return []

        monkeypatch.setattr(YouTubeAuthService, "detect_profiles", fake_detect)

        path = GeminiExtractor._export_browser_cookies()

        assert path is not None
        assert no_persist.get("yt_auth_browser") == "edge"
        assert no_persist.get("yt_auth_profile") == "Default"
        _cleanup(path)

    def test_명시적_브라우저가_실패하면_자동감지로_폴백한다(self, monkeypatch, no_persist):
        import config.settings as s

        monkeypatch.setattr(s, "YT_AUTH_BROWSER", "chrome", raising=False)
        monkeypatch.setattr(s, "YT_AUTH_PROFILE", "Default", raising=False)
        # chrome/Default는 실패(SUCCESS에 없음), firefox 자동감지가 성공한다.
        _FakeYDL.SUCCESS = {("firefox", "default-release")}

        def fake_detect(self, browser):
            if browser == "firefox":
                return [BrowserProfile(
                    "default-release", "default-release", "default-release"
                )]
            return []

        monkeypatch.setattr(YouTubeAuthService, "detect_profiles", fake_detect)

        path = GeminiExtractor._export_browser_cookies()

        assert path is not None
        _cleanup(path)

    def test_이미_시도한_조합은_자동감지에서_중복_시도하지_않는다(
        self, monkeypatch, no_persist
    ):
        import config.settings as s

        monkeypatch.setattr(s, "YT_AUTH_BROWSER", "chrome", raising=False)
        monkeypatch.setattr(s, "YT_AUTH_PROFILE", "Default", raising=False)
        # chrome/Default는 성공 목록에 없어 실패해야 정상인데, 자동감지가 같은
        # 조합을 다시 시도해 우연히 성공 처리되면 이 테스트가 놓친다 — 아래에서
        # 호출 횟수를 세어 중복 호출이 없었는지 직접 검증한다.
        calls: list[tuple[str, str]] = []
        real_init = _FakeYDL.__init__

        def counting_init(self, opts):
            calls.append(opts["cookiesfrombrowser"])
            real_init(self, opts)

        monkeypatch.setattr(_FakeYDL, "__init__", counting_init)

        def fake_detect(self, browser):
            if browser == "chrome":
                return [BrowserProfile("Default", "Default", "Default")]
            return []

        monkeypatch.setattr(YouTubeAuthService, "detect_profiles", fake_detect)

        path = GeminiExtractor._export_browser_cookies()

        assert path is None
        assert calls.count(("chrome", "Default")) == 1

    def test_모든_후보가_실패하면_None을_반환한다(self, monkeypatch, no_persist):
        import config.settings as s

        monkeypatch.setattr(s, "YT_AUTH_BROWSER", None, raising=False)
        monkeypatch.setattr(s, "YT_AUTH_PROFILE", None, raising=False)
        monkeypatch.setattr(YouTubeAuthService, "detect_profiles", lambda self, browser: [])

        path = GeminiExtractor._export_browser_cookies()

        assert path is None


class TestNoCookieFoundReason:
    """설정된 브라우저도 자동 감지도 모두 쿠키를 못 찾으면 실패 사유가 남아야 한다.

    과거엔 이 경로가 `out["reason"]`을 채우지 않아 `extract_with_reason`이 항상
    기본값인 SUMMARY_REASON_ERROR("잠시 후 다시 시도하세요")로 떨어졌다 — 실제로는
    로그인된 브라우저를 못 찾은 것인데도 원인을 알 수 없는 오류처럼 보여줬다.
    """

    def test_쿠키를_전혀_찾지_못하면_로그인_필요_사유를_반환한다(self, monkeypatch):
        monkeypatch.setattr(GeminiExtractor, "_get_cookie_path", staticmethod(lambda: None))
        monkeypatch.setattr(
            GeminiExtractor, "_export_browser_cookies", classmethod(lambda cls: None)
        )

        summary, reason = GeminiExtractor().extract_with_reason("https://youtu.be/x")

        assert summary is None
        assert reason == SUMMARY_REASON_NOT_SIGNED_IN
