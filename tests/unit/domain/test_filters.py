"""복합 필터의 사람 말 ↔ 값 변환.

여기 있는 규칙은 사소해 보이지만, 틀리면 **목록에서 영상이 조용히 사라진다** —
예외도 오류도 없이 "분명 있던 게 없다"가 된다. 그래서 경계와 열린 끝을 고정한다.
"""

from __future__ import annotations

from datetime import date

from domain.library.filters import (
    DATE_PRESETS,
    DOWNLOAD_PRESETS,
    DURATION_PRESETS,
    WATCHED_PRESETS,
    describe,
    resolve_date_preset,
    resolve_download_preset,
    resolve_duration_preset,
    resolve_watched_preset,
)

TODAY = date(2026, 9, 19)


class TestDatePreset:
    def test_전체_기간은_제한이_없다(self):
        assert resolve_date_preset("all", TODAY) == ("", "")

    def test_최근_1주는_이레_전부터(self):
        assert resolve_date_preset("7d", TODAY) == ("2026-09-12", "")

    def test_끝은_열어_둔다(self):
        """예약 공개 영상은 업로드 날짜가 내일일 수 있다 — 끝을 막으면 사라진다."""
        _start, end = resolve_date_preset("30d", TODAY)
        assert end == ""

    def test_월_경계를_넘는다(self):
        assert resolve_date_preset("7d", date(2026, 3, 3)) == ("2026-02-24", "")

    def test_모르는_키는_전체로_본다(self):
        """설정이 낡거나 손으로 고쳐져도 목록이 비지 않아야 한다."""
        assert resolve_date_preset("지난주쯤", TODAY) == ("", "")

    def test_표시_이름이_모두_있다(self):
        assert all(name for _k, name, _v in DATE_PRESETS)


class TestDurationPreset:
    def test_전체는_제한이_없다(self):
        assert resolve_duration_preset("all") == (None, None)

    def test_구간이_겹치지_않는다(self):
        """겹치면 같은 영상이 두 구간에 나오고, 벌어지면 어디에도 안 나온다."""
        _short_lo, short_hi = resolve_duration_preset("short")
        med_lo, med_hi = resolve_duration_preset("medium")
        long_lo, _long_hi = resolve_duration_preset("long")
        assert short_hi + 1 == med_lo
        assert med_hi + 1 == long_lo

    def test_짧은_것은_위만_막는다(self):
        assert resolve_duration_preset("short")[0] is None

    def test_긴_것은_아래만_막는다(self):
        assert resolve_duration_preset("long")[1] is None

    def test_4분과_20분이_경계다(self):
        assert resolve_duration_preset("medium") == (240, 1199)

    def test_모르는_키는_전체로_본다(self):
        assert resolve_duration_preset("적당한거") == (None, None)


class TestBooleanPresets:
    def test_다운로드_여부(self):
        assert resolve_download_preset("all") is None
        assert resolve_download_preset("yes") is True
        assert resolve_download_preset("no") is False

    def test_시청_여부(self):
        assert resolve_watched_preset("all") is None
        assert resolve_watched_preset("yes") is True
        assert resolve_watched_preset("no") is False

    def test_모르는_키는_전체로_본다(self):
        assert resolve_download_preset("몰라") is None
        assert resolve_watched_preset("몰라") is None

    def test_첫_항목이_전체다(self):
        """화면이 첫 항목을 기본 선택으로 두므로, 그게 '제한 없음'이어야 한다."""
        assert DOWNLOAD_PRESETS[0][2] is None
        assert WATCHED_PRESETS[0][2] is None
        assert DURATION_PRESETS[0][2] is None and DURATION_PRESETS[0][3] is None


class TestDescribe:
    def test_아무것도_안_걸면_빈_문자열(self):
        assert describe() == ""

    def test_걸린_것만_적는다(self):
        text = describe(date_key="7d", download_key="yes")
        assert "최근 1주" in text
        assert "받아 둔 것만" in text
        assert "전체" not in text

    def test_채널과_즐겨찾기도_적는다(self):
        text = describe(channel_name="  침착맨 ", favorite_only=True)
        assert "채널 '침착맨'" in text
        assert "즐겨찾기" in text

    def test_공백뿐인_채널은_세지_않는다(self):
        assert describe(channel_name="   ") == ""

    def test_여러_개는_가운뎃점으로_잇는다(self):
        assert " · " in describe(date_key="7d", duration_key="long")
