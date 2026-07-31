"""모든 테마 프리셋이 읽을 수 있는 명도 대비를 갖는지 고정한다.

배경: 밝은 테마에서 글자가 배경에 묻혀 안 보인다는 문제가 있었다. 원인은 두 가지였다 —
(1) `text_muted`/`accent` 가 배경 대비 3:1도 안 되는 값이었고,
(2) 통계 패널 등이 테마와 무관한 어두운 색을 스타일시트에 직접 박아 두었다.
여기서는 (1)을 수치로 고정하고, (2)는 하드코딩이 되살아나지 않는지 확인한다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from gui.themes.tokens import PRESETS

# WCAG 2.1 본문 텍스트 기준
_AA_NORMAL = 4.5


def _lin(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(hex_color: str) -> float:
    raw = hex_color.lstrip("#")
    r, g, b = (int(raw[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast(fg: str, bg: str) -> float:
    a, b = _luminance(fg), _luminance(bg)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


_TEXT_ON_BG = [
    ("text_primary", "bg_base"),
    ("text_primary", "bg_surface"),
    ("text_primary", "bg_elevated"),
    ("text_secondary", "bg_surface"),
    ("text_secondary", "bg_elevated"),
    ("text_muted", "bg_surface"),
    ("text_muted", "bg_elevated"),
    # accent 는 링크·강조 문구로도 쓰이므로 본문 기준을 적용한다.
    ("accent", "bg_surface"),
    ("accent", "bg_base"),
]


@pytest.mark.parametrize("preset", sorted(PRESETS))
@pytest.mark.parametrize(("fg", "bg"), _TEXT_ON_BG)
def test_text_meets_aa_contrast(preset: str, fg: str, bg: str) -> None:
    tokens = PRESETS[preset]
    ratio = contrast(getattr(tokens, fg), getattr(tokens, bg))
    assert ratio >= _AA_NORMAL, (
        f"{preset}: {fg}({getattr(tokens, fg)}) on {bg}({getattr(tokens, bg)}) "
        f"대비 {ratio:.2f} < {_AA_NORMAL}"
    )


@pytest.mark.parametrize("preset", sorted(PRESETS))
def test_text_on_accent_is_readable(preset: str) -> None:
    """선택된 항목·버튼처럼 accent 를 배경으로 쓰는 자리."""
    tokens = PRESETS[preset]
    ratio = contrast(tokens.text_on_accent, tokens.accent)
    assert ratio >= _AA_NORMAL, f"{preset}: text_on_accent 대비 {ratio:.2f}"


class TestPresetCatalog:
    def test_has_both_light_and_dark_choices(self) -> None:
        light = [n for n, t in PRESETS.items() if t.is_light]
        dark = [n for n, t in PRESETS.items() if not t.is_light]
        assert len(light) >= 3 and len(dark) >= 3

    def test_names_match_dict_keys(self) -> None:
        for key, tokens in PRESETS.items():
            assert tokens.name == key

    def test_is_light_classifies_known_presets(self) -> None:
        assert PRESETS["slate"].is_light is False
        assert PRESETS["forest"].is_light is False
        assert PRESETS["mist"].is_light is True
        assert PRESETS["graphite"].is_light is True


class TestNoHardcodedDarkColors:
    """테마를 따르지 않는 색이 통계 화면에 되살아나지 않는지 지킨다."""

    _PANEL = Path(__file__).resolve().parents[2] / "gui" / "panels" / "stats_panel.py"
    # 예전에 박혀 있던 값들: 카드 배경·본문 회색·링크 파랑
    _BANNED = re.compile(r"#(?:1e1e2e|2a2a3a|3a3a4a|34344a|8ab4ff|a9c6ff|cccccc|888)\b")

    def test_stats_panel_uses_theme_tokens(self) -> None:
        src = self._PANEL.read_text(encoding="utf-8")
        found = self._BANNED.findall(src)
        assert not found, f"테마와 무관한 색이 남아 있다: {found}"
