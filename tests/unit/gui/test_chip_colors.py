"""칩 색상이 테마 토큰에서 파생되는지 검증한다.

기존에는 paintEvent에 #2a3a4a·#1a4f82·#204060·#ddeeff·#ccc가 하드코딩돼
어떤 테마를 골라도 칩만 어두운 색으로 남았다.
"""
from __future__ import annotations

from gui.panels.library_panel import chip_colors
from gui.themes.tokens import MIST, SLATE

_KEYS = {"bg", "border", "text", "badge_bg", "badge_text"}


class TestChipColors:
    def test_returns_all_keys(self):
        assert set(chip_colors(MIST, selected=False)) == _KEYS

    def test_follows_theme(self):
        """서로 다른 테마는 서로 다른 칩 색을 내야 한다 — 하드코딩이면 같아진다."""
        light = chip_colors(MIST, selected=False)
        dark = chip_colors(SLATE, selected=False)
        assert light["bg"] != dark["bg"]
        assert light["text"] != dark["text"]

    def test_unselected_uses_elevated_surface(self):
        c = chip_colors(MIST, selected=False)
        assert c["bg"] == MIST.bg_elevated
        assert c["border"] == MIST.border_muted
        assert c["text"] == MIST.text_secondary

    def test_selected_uses_accent(self):
        c = chip_colors(MIST, selected=True)
        assert c["bg"] == MIST.accent
        assert c["text"] == MIST.text_on_accent

    def test_data_color_overrides_selected_fill(self):
        """태그 고유 색이 주어지면 선택 시 그 색으로 채운다(식별성 유지)."""
        c = chip_colors(MIST, selected=True, data_color="#8b2252")
        assert c["bg"] == "#8b2252"
        assert c["text"] == MIST.text_on_accent

    def test_data_color_ignored_when_unselected(self):
        c = chip_colors(MIST, selected=False, data_color="#8b2252")
        assert c["bg"] == MIST.bg_elevated

    def test_no_hardcoded_legacy_colors(self):
        """회귀 방지 — 옛 하드코딩 값이 다시 새어나오지 않아야 한다."""
        legacy = {"#2a3a4a", "#1a4f82", "#204060", "#ddeeff"}
        for selected in (True, False):
            for tokens in (MIST, SLATE):
                assert not (set(chip_colors(tokens, selected=selected).values()) & legacy)
