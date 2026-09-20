"""표시 포맷 — 흩어져 있던 20여 곳을 모으면서 **출력이 바뀌지 않았는지** 고정한다.

이 시험의 값어치는 특성화(characterization)에 있다. 같은 일을 하는 함수가 재생시간
11곳·용량 6곳·상대시간 3곳에 있었고 **서로 출력이 달랐다**. 하나로 뭉개면 화면이
조용히 바뀌는데, 그 변화를 나중에는 이 정리 탓이라고 짚을 수 없다.

그래서 통합 **전** 구현에서 뽑은 문자열을 여기 그대로 적었다.

**의도적으로 바꾼 것 하나**는 `TestBytesFixesTruncation`에 따로 모아 두었다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from gui.text.formats import (
    ByteUnit,
    RelativeStyle,
    format_bytes,
    format_count,
    format_duration,
    format_duration_ms,
    format_elapsed_span,
    format_recording_progress,
    format_long_duration,
    format_relative_time,
    format_view_count,
    views_label,
)


class TestDuration:
    """`Duration.formatted()` · `feed_panel._fmt_duration` 외 9곳이 같은 결과였다."""

    @pytest.mark.parametrize("sec, want", [
        (0, "0:00"), (5, "0:05"), (61, "1:01"), (599, "9:59"),
        (3600, "1:00:00"), (3661, "1:01:01"), (4812, "1:20:12"), (86399, "23:59:59"),
    ])
    def test_기존_출력과_같다(self, sec, want):
        assert format_duration(sec) == want

    def test_없으면_빈_문자열(self):
        assert format_duration(None) == ""

    def test_음수는_빈_문자열(self):
        """길이를 모르는 스트림이 -1 을 준다 — `-1:59:59` 를 보여 주면 안 된다."""
        assert format_duration(-1) == ""

    def test_시를_항상_적을_수도_있다(self):
        assert format_duration(61, always_hours=True) == "0:01:01"

    def test_밀리초_입구(self):
        assert format_duration_ms(4812_000) == "1:20:12"
        assert format_duration_ms(None) == ""


class TestLongDuration:
    """`stats_panel._fmt_dur` — 누적 시간."""

    @pytest.mark.parametrize("sec, want", [
        (0, "0시간 0분"), (3600 * 2 + 420, "2시간 7분"),
        (3600 * 24, "1일 0시간"), (3600 * 50, "2일 2시간"),
    ])
    def test_기존_출력과_같다(self, sec, want):
        assert format_long_duration(sec) == want


class TestElapsedSpan:
    """`domain/download/live.format_elapsed` — 라이브 녹화 경과."""

    @pytest.mark.parametrize("sec, want", [
        (0, "0초"), (3, "3초"), (63, "1분 3초"), (3900, "1시간 5분"),
    ])
    def test_기존_출력과_같다(self, sec, want):
        assert format_elapsed_span(sec) == want

    def test_음수는_0으로_본다(self):
        assert format_elapsed_span(-5) == "0초"


class TestRelativePrecise:
    """`formatting._fmt_elapsed` — 초 단위 잣대(방금/분/시간/일/개월/년)."""

    @pytest.mark.parametrize("delta, want", [
        (timedelta(seconds=10), "방금"),
        (timedelta(minutes=5), "5분 전"),
        (timedelta(hours=3), "3시간 전"),
        (timedelta(days=3), "3일 전"),
        (timedelta(days=60), "2개월 전"),
        (timedelta(days=400), "1년 전"),
    ])
    def test_기존_출력과_같다(self, delta, want):
        now = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
        iso = (now - delta).isoformat()
        assert format_relative_time(iso, style=RelativeStyle.PRECISE, now=now) == want

    def test_타임존이_없으면_UTC로_본다(self):
        now = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
        assert format_relative_time(
            "2026-09-20T09:00:00", style=RelativeStyle.PRECISE, now=now
        ) == "3시간 전"

    def test_못_읽으면_빈_문자열(self):
        assert format_relative_time("깨진 값", style=RelativeStyle.PRECISE) == ""


class TestRelativeCoarse:
    """`formatting._relative_time` · `feed_panel._relative_time` — 날짜 단위 잣대.

    **PRECISE 와 버킷이 다르다**(오늘/일/**주**/개월/년). 뭉개면 라이브러리 카드
    표시가 조용히 바뀐다 — 그래서 style 로 갈라 둔다.
    """

    @pytest.mark.parametrize("days, want", [
        (0, "오늘"), (1, "1일 전"), (6, "6일 전"),
        (7, "1주 전"), (29, "4주 전"), (30, "1개월 전"),
        (364, "12개월 전"), (365, "1년 전"),
    ])
    def test_기존_출력과_같다(self, days, want):
        now = datetime(2026, 9, 20, 12, 0)
        pub = (now - timedelta(days=days)).date().isoformat()
        assert format_relative_time(pub, now=now) == want

    def test_ytdlp_의_YYYYMMDD도_읽는다(self):
        now = datetime(2026, 9, 20, 12, 0)
        assert format_relative_time("20260917", now=now) == "3일 전"

    def test_미래_날짜는_빈_문자열(self):
        now = datetime(2026, 9, 20, 12, 0)
        assert format_relative_time("2026-09-25", now=now) == ""

    def test_두_잣대는_같은_입력에_다른_답을_낸다(self):
        """이 차이를 지키는 것이 이 파라미터의 존재 이유다."""
        now = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
        iso = (now - timedelta(days=10)).isoformat()
        assert format_relative_time(iso, style=RelativeStyle.PRECISE, now=now) == "10일 전"
        assert format_relative_time(iso, style=RelativeStyle.COARSE, now=now) == "1주 전"


class TestBytes:
    @pytest.mark.parametrize("n, want", [
        (0, "0 B"), (512, "512 B"), (1536, "1.5 KB"),
        (1024 * 1024, "1.0 MB"), (1572864, "1.5 MB"),
        (412_530_176, "393.4 MB"), (1024 ** 3 * 2, "2.0 GB"), (1024 ** 4 * 3, "3.0 TB"),
    ])
    def test_자동_단위(self, n, want):
        assert format_bytes(n) == want

    def test_배지는_항상_MB에_공백이_없다(self):
        """`badge_state._mb` 와 같아야 한다 — 배지 폭이 자릿수에 따라 흔들리면 안 된다."""
        assert format_bytes(188_153_588, unit=ByteUnit.MB) == "179.4MB"

    def test_없으면_부르는_쪽이_정한_글자(self):
        assert format_bytes(None) == ""
        assert format_bytes(None, none_text="—") == "—"

    def test_음수는_0으로_본다(self):
        assert format_bytes(-5) == "0 B"


class TestBytesFixesTruncation:
    """**의도적인 출력 변경** — 통계·상세 화면이 소수를 잘라 틀린 값을 보여 주고 있었다.

    `stats_panel._fmt_bytes` 와 `detail/widgets._fmt_size` 가 `b //= 1024`(정수
    나눗셈)를 써서 `393.4 MB` 를 `393.0 MB` 로, `1.5 MB` 를 `1.0 MB` 로 표시했다.
    통합하면서 실수로 옮기지 않고 고친다.
    """

    @pytest.mark.parametrize("n, old_wrong, new_right", [
        (1536, "1.0 KB", "1.5 KB"),
        (1572864, "1.0 MB", "1.5 MB"),
        (412_530_176, "393.0 MB", "393.4 MB"),
    ])
    def test_이제_소수가_살아_있다(self, n, old_wrong, new_right):
        got = format_bytes(n)
        assert got == new_right
        assert got != old_wrong


class TestViews:
    """`formatting._fmt_views` 와 `feed_panel._fmt_views` 는 글자까지 같았다."""

    @pytest.mark.parametrize("n, want", [
        (0, "조회수 0회"), (812, "조회수 812회"),
        (1_234, "조회수 1.2천 회"), (12_345, "조회수 1.2만 회"),
        (123_456_789, "조회수 1.2억 회"),
    ])
    def test_기존_출력과_같다(self, n, want):
        assert views_label(n) == want

    def test_없으면_빈_문자열(self):
        assert views_label(None) == ""

    def test_숫자만_따로_쓸_수도_있다(self):
        assert format_view_count(12_345) == "1.2만"


class TestCount:
    def test_천단위_구분(self):
        assert format_count(1234567) == "1,234,567"


class TestRecordingProgress:
    """`domain/download/live.format_recording_progress` 에서 옮겨 왔다."""

    def test_퍼센트를_쓰지_않는다(self):
        """라이브는 총 크기를 모른다 — 0%나 NaN이 뜨면 멈춘 것처럼 보인다."""
        line = format_recording_progress(5025, 2.4 * 1024 ** 3)
        assert "%" not in line
        assert "1시간 23분" in line
        assert "GB" in line


class TestUnifiedSizeGoesToTB:
    """**의도적인 차이** — 예전 녹화용 `live.format_size`는 GB에서 멈췄다.

    "녹화 하나가 그 크기면 다른 문제가 있다"는 판단이었는데, 이제 같은 함수를 통계
    화면도 쓰고 거기는 TB가 정상 범위다. 9,999 GB짜리 녹화는 현실에 없으므로 상한을
    없애는 쪽이 낫다.
    """

    def test_TB까지_올라간다(self):
        assert format_bytes(9999 * 1024 ** 3).endswith("TB")
