"""화질 강등 안내 판정(순수 함수) 시험."""

from __future__ import annotations

import pytest

from gui.widgets.player.quality_notice import (
    parse_height,
    requested_height,
    should_notify_downgrade,
)


class TestParseHeight:
    @pytest.mark.parametrize("label,expected", [
        ("360p", 360), ("1080p", 1080), ("720p60", 720), ("2160", 2160),
    ])
    def test_숫자를_읽는다(self, label, expected):
        assert parse_height(label) == expected

    @pytest.mark.parametrize("label", ["", "auto", "p", "원본"])
    def test_숫자가_없으면_None(self, label):
        assert parse_height(label) is None

    def test_None도_None(self):
        assert parse_height(None) is None  # type: ignore[arg-type]


class TestRequestedHeight:
    def test_알려진_키(self):
        assert requested_height("1080p") == 1080
        assert requested_height("360p") == 360

    @pytest.mark.parametrize("key", ["auto", "bogus", ""])
    def test_auto와_모르는_키는_None(self, key):
        assert requested_height(key) is None


class TestShouldNotifyDowngrade:
    @pytest.mark.parametrize("key,got,expected", [
        ("1080p", "360p", True),
        ("720p", "480p", True),
        ("360p", "360p", False),
        ("720p", "1080p", False),
        ("auto", "360p", False),
        ("auto", "1080p", False),
        ("bogus", "360p", False),
        ("1080p", "", False),
        ("1080p", "auto", False),
    ])
    def test_판정(self, key, got, expected):
        assert should_notify_downgrade(key, got) is expected
