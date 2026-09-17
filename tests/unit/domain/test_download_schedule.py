"""다운로드 예약 시간대·동시 실행 수 규칙.

자정을 넘기는 시간대(23시~07시)가 오히려 흔한 설정이라, 단순 비교로 짜면 밤 시간대가
통째로 막힌다. 그 경계를 촘촘히 고정한다.
"""

from __future__ import annotations

from datetime import time

import pytest

from domain.download.schedule import (
    MAX_CONCURRENT,
    MIN_CONCURRENT,
    DownloadWindow,
    clamp_concurrent,
    slots_available,
)


class TestDisabled:
    def test_꺼져_있으면_언제든_허용한다(self):
        window = DownloadWindow(enabled=False, start_hour=1, end_hour=2)
        assert all(window.allows(time(h, 0)) for h in range(24))


class TestSameDay:
    WINDOW = DownloadWindow(enabled=True, start_hour=9, end_hour=18)

    @pytest.mark.parametrize("hour", [9, 12, 17])
    def test_시간대_안이면_허용(self, hour):
        assert self.WINDOW.allows(time(hour, 30))

    @pytest.mark.parametrize("hour", [8, 18, 23, 0])
    def test_시간대_밖이면_거부(self, hour):
        assert not self.WINDOW.allows(time(hour, 30))

    def test_시작_시각은_포함이다(self):
        assert self.WINDOW.allows(time(9, 0))

    def test_끝_시각은_포함하지_않는다(self):
        """18시까지로 정했으면 18시 정각엔 이미 끝난 것이다."""
        assert not self.WINDOW.allows(time(18, 0))


class TestCrossingMidnight:
    """23시~07시 — 이 경우를 놓치면 '밤에만 받기'가 통째로 막힌다."""

    WINDOW = DownloadWindow(enabled=True, start_hour=23, end_hour=7)

    @pytest.mark.parametrize("hour", [23, 0, 3, 6])
    def test_자정을_넘어도_허용(self, hour):
        assert self.WINDOW.allows(time(hour, 30))

    @pytest.mark.parametrize("hour", [7, 12, 22])
    def test_시간대_밖이면_거부(self, hour):
        assert not self.WINDOW.allows(time(hour, 30))


class TestFullDay:
    def test_시작과_끝이_같으면_하루_종일이다(self):
        """폭 0으로 읽으면 아무것도 못 받는데, 원인을 찾기가 매우 어렵다."""
        window = DownloadWindow(enabled=True, start_hour=3, end_hour=3)
        assert all(window.allows(time(h, 0)) for h in range(24))

    def test_24시를_0시로_본다(self):
        window = DownloadWindow(enabled=True, start_hour=22, end_hour=24)
        assert window.allows(time(23, 0))
        assert not window.allows(time(1, 0))


class TestDescribe:
    def test_꺼짐(self):
        assert "언제든" in DownloadWindow().describe()

    def test_같은_날(self):
        assert DownloadWindow(True, 9, 18).describe().startswith("09:00 ~ 18:00")

    def test_자정을_넘기면_그렇게_알린다(self):
        assert "다음 날" in DownloadWindow(True, 23, 7).describe()

    def test_하루_종일(self):
        assert "하루 종일" in DownloadWindow(True, 5, 5).describe()


class TestConcurrency:
    def test_범위를_벗어나면_자른다(self):
        assert clamp_concurrent(0) == MIN_CONCURRENT
        assert clamp_concurrent(99) == MAX_CONCURRENT
        assert clamp_concurrent(3) == 3

    def test_남은_자리를_센다(self):
        assert slots_available(running=1, limit=3) == 2

    def test_이미_다_차면_0(self):
        assert slots_available(running=3, limit=3) == 0

    def test_넘치게_돌고_있어도_음수가_되지_않는다(self):
        """설정을 실행 중에 낮추면 running > limit 인 순간이 생긴다."""
        assert slots_available(running=5, limit=3) == 0
