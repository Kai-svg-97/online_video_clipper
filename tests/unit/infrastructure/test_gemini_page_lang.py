"""Gemini 추출기의 언어별 프로필 — 화면 언어 고정·본문 자르기·언어 판정.

브라우저 없이 검증할 수 있는 순수 부분만 다룬다. 실제 YouTube 동작(로그인 상태에서
URL `hl=`·locale 이 무시되고 `PREF` 쿠키만 통한다, 영어 칩은 한국어 영상에 한국어로
답한다)은 2026-09 실측이며 설계 근거는 docs/architecture/design-decisions.md 에 있다.
"""
from __future__ import annotations

from infrastructure.browser.gemini_extractor import (
    GeminiExtractor,
    page_lang,
    supported_summary_languages,
)


class _FakeContext:
    def __init__(self, cookies):
        self._cookies = list(cookies)
        self.added = []

    def cookies(self):
        return list(self._cookies)

    def add_cookies(self, cookies):
        self.added.extend(cookies)


class TestPageLang:
    def test_known_languages(self):
        assert set(supported_summary_languages()) == {"ko", "en"}
        assert page_lang("en").locale == "en-US"
        assert page_lang("ko").locale == "ko-KR"

    def test_unknown_falls_back_to_korean(self):
        assert page_lang("ja").code == "ko"
        assert page_lang(None).code == "ko"

    def test_english_types_a_prompt_korean_clicks_chip(self):
        assert page_lang("en").prompt
        assert page_lang("ko").prompt is None


class TestForcePageLanguage:
    def test_replaces_hl_and_keeps_other_prefs(self):
        ctx = _FakeContext([{
            "name": "PREF", "value": "f6=40000080&hl=ko&tz=Asia.Manila",
            "domain": ".youtube.com", "path": "/",
        }])
        GeminiExtractor._force_page_language(ctx, "en")
        value = ctx.added[0]["value"]
        assert "hl=en" in value and "hl=ko" not in value
        assert "f6=40000080" in value and "tz=Asia.Manila" in value

    def test_reuses_original_cookie_domain_and_path(self):
        """다른 도메인으로 쓰면 쿠키가 둘이 되고 옛 것이 읽혀 언어 고정이 풀린다."""
        ctx = _FakeContext([{
            "name": "PREF", "value": "f6=1", "domain": "www.youtube.com", "path": "/",
        }])
        GeminiExtractor._force_page_language(ctx, "en")
        assert ctx.added[0]["domain"] == "www.youtube.com"

    def test_creates_pref_when_missing(self):
        ctx = _FakeContext([])
        GeminiExtractor._force_page_language(ctx, "ko")
        assert ctx.added[0]["value"] == "hl=ko"
        assert ctx.added[0]["domain"] == ".youtube.com"


class TestCleanSummary:
    def test_english_cuts_after_prompt_echo_and_before_disclaimer(self):
        en = page_lang("en")
        panel = (
            "Summarize the video\nRecommend related content\n"
            f"{en.prompt}\n\nThe body of the summary.\n"
            "AI can make mistakes, so double-check it. Learn more\nFollow-up?"
        )
        assert GeminiExtractor._clean_summary(panel, en) == "The body of the summary."

    def test_korean_unchanged(self):
        panel = "동영상을 요약해 줘\n요약 본문입니다.\nAI도 실수를 할 수 있으니 확인하세요"
        assert GeminiExtractor._clean_summary(panel) == "요약 본문입니다."


class TestLanguageCheck:
    def test_english_with_some_korean_names_is_accepted(self):
        text = "This video by 찐AI explains prompts for a 서울 tourist map in detail."
        assert GeminiExtractor._matches_language(text, page_lang("en"))

    def test_korean_answer_rejected_for_english(self):
        text = "이 영상은 프롬프트를 활용해 고품질 이미지를 만드는 방법을 설명합니다."
        assert not GeminiExtractor._matches_language(text, page_lang("en"))

    def test_korean_is_not_checked(self):
        assert GeminiExtractor._matches_language("Mostly English text", page_lang("ko"))

    def test_menu_filter_does_not_eat_words_like_asked(self):
        """짧은 메뉴 낱말로 본문을 깎으면 길이 판정이 흐려진다."""
        text = "Asked viewers " * 4
        assert GeminiExtractor._looks_like_summary(text, page_lang("en"))
