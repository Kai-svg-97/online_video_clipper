"""요약 실패 사유가 호출자에게 전달되는지 검증한다.

"질문하기 버튼이 없어서 실패"는 일반 오류와 원인이 달라 상세 화면 안내 문구도
달라야 한다. 그래서 추출기가 사유를 함께 반환한다.
"""
from __future__ import annotations

import pytest

from infrastructure.browser.gemini_extractor import (
    SUMMARY_REASON_ERROR,
    SUMMARY_REASON_NOT_SIGNED_IN,
    SUMMARY_REASON_NO_BUTTON,
    GeminiExtractor,
)


@pytest.fixture
def extractor():
    return GeminiExtractor()


class TestExtractWithReason:
    def test_success_returns_empty_reason(self, extractor, monkeypatch):
        monkeypatch.setattr(
            extractor, "_do_extract", lambda url, out=None: "요약 본문"
        )

        summary, reason = extractor.extract_with_reason("https://youtu.be/a")

        assert summary == "요약 본문"
        assert reason == ""

    def test_no_button_reason_is_propagated(self, extractor, monkeypatch):
        """핵심 — 버튼 미발견 사유가 그대로 올라와야 한다."""

        def fake(url, out=None):
            if out is not None:
                out["reason"] = SUMMARY_REASON_NO_BUTTON
            return None

        monkeypatch.setattr(extractor, "_do_extract", fake)

        summary, reason = extractor.extract_with_reason("https://youtu.be/a")

        assert summary is None
        assert reason == SUMMARY_REASON_NO_BUTTON

    def test_not_signed_in_reason_is_propagated(self, extractor, monkeypatch):
        def fake(url, out=None):
            if out is not None:
                out["reason"] = SUMMARY_REASON_NOT_SIGNED_IN
            return None

        monkeypatch.setattr(extractor, "_do_extract", fake)

        assert extractor.extract_with_reason("https://youtu.be/a")[1] == (
            SUMMARY_REASON_NOT_SIGNED_IN
        )

    def test_unknown_failure_defaults_to_error(self, extractor, monkeypatch):
        monkeypatch.setattr(extractor, "_do_extract", lambda url, out=None: None)

        assert extractor.extract_with_reason("https://youtu.be/a")[1] == (
            SUMMARY_REASON_ERROR
        )

    def test_exception_becomes_error_reason(self, extractor, monkeypatch):
        def boom(url, out=None):
            raise RuntimeError("브라우저 폭발")

        monkeypatch.setattr(extractor, "_do_extract", boom)

        summary, reason = extractor.extract_with_reason("https://youtu.be/a")

        assert summary is None
        assert reason == SUMMARY_REASON_ERROR

    def test_extract_still_returns_plain_summary(self, extractor, monkeypatch):
        """기존 extract() 계약(ISummarySource 포트)은 그대로 유지돼야 한다."""
        monkeypatch.setattr(extractor, "_do_extract", lambda url, out=None: "본문")

        assert extractor.extract("https://youtu.be/a") == "본문"

    def test_extract_returns_none_on_failure(self, extractor, monkeypatch):
        monkeypatch.setattr(extractor, "_do_extract", lambda url, out=None: None)

        assert extractor.extract("https://youtu.be/a") is None
