"""라이브 판정·표기 규칙.

녹화의 위험은 **조용히 엉뚱한 것을 받는 것**이다. 예정 방송을 '녹화 가능'으로 보면
워커가 몇 시간 잡힌 채 '녹화 중'으로 보이고, 끝난 방송을 라이브로 보면 진행률이
영영 뜨지 않는다. 그 경계를 고정한다.
"""

from __future__ import annotations

import pytest

from domain.download.live import (
    LIVE_ENDED,
    LIVE_NOW,
    LIVE_UPCOMING,
    MAX_CONCURRENT_RECORDINGS,
    NOT_LIVE,
    classify_live_status,
    is_recordable,
)


class TestClassify:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("is_live", LIVE_NOW),
            ("is_upcoming", LIVE_UPCOMING),
            ("was_live", LIVE_ENDED),
            ("post_live", LIVE_ENDED),
            ("not_live", NOT_LIVE),
        ],
    )
    def test_live_status를_그대로_읽는다(self, raw, expected):
        assert classify_live_status({"live_status": raw}) == expected

    def test_오래된_추출기의_is_live_불리언도_받는다(self):
        assert classify_live_status({"is_live": True}) == LIVE_NOW

    def test_was_live_불리언도_받는다(self):
        assert classify_live_status({"was_live": True}) == LIVE_ENDED

    def test_live_status가_우선한다(self):
        """둘 다 오면 명시적인 쪽을 믿는다."""
        assert classify_live_status({"live_status": "was_live", "is_live": False}) == LIVE_ENDED

    def test_아무것도_없으면_라이브가_아니다(self):
        assert classify_live_status({}) == NOT_LIVE

    def test_None이어도_터지지_않는다(self):
        assert classify_live_status(None) == NOT_LIVE

    def test_모르는_값은_라이브가_아니다(self):
        """yt-dlp가 새 값을 추가해도 조용히 지나간다."""
        assert classify_live_status({"live_status": "무언가새로운값"}) == NOT_LIVE


class TestRecordable:
    def test_방송_중만_녹화할_수_있다(self):
        assert is_recordable(LIVE_NOW)

    def test_예정_방송은_녹화하지_않는다(self):
        """대기시키면 워커가 몇 시간 잡힌 채 '녹화 중'으로 보인다."""
        assert not is_recordable(LIVE_UPCOMING)

    @pytest.mark.parametrize("status", [LIVE_ENDED, NOT_LIVE])
    def test_그_외는_녹화_대상이_아니다(self, status):
        assert not is_recordable(status)


# 경과 시간·용량·진행 한 줄의 포맷 시험은 표시 계층으로 옮겼다
# (`tests/unit/gui/test_text_formats.py`) — 도메인은 이제 그 문자열을 만들지 않는다.


class TestLimits:
    def test_동시_녹화_상한이_일반_다운로드보다_작다(self):
        """녹화는 몇 시간씩 이어져 쌓아 두면 디스크가 먼저 찬다."""
        from domain.download.schedule import MAX_CONCURRENT

        assert 1 <= MAX_CONCURRENT_RECORDINGS < MAX_CONCURRENT
