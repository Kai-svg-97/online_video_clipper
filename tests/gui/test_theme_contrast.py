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
    # bg_base 위 조합이 빠져 있어 graphite의 text_muted가 4.18:1로 미달인 채 통과했다.
    # 창 전체 배경이 bg_base이므로 그 위에 얹히는 글자가 오히려 가장 흔하다.
    ("text_secondary", "bg_base"),
    ("text_muted", "bg_base"),
    # accent 는 링크·강조 문구로도 쓰이므로 본문 기준을 적용한다.
    ("accent", "bg_surface"),
    ("accent", "bg_base"),
    ("accent", "bg_elevated"),
    # bg_overlay는 호버·선택 배경이다 — 그 위에서도 글자가 읽혀야 한다.
    ("text_primary", "bg_overlay"),
    ("text_secondary", "bg_overlay"),
]

# WCAG 2.1 1.4.11 — 텍스트가 아닌 UI 요소(조작 가능한 컨트롤)의 식별 기준
_AA_NON_TEXT = 3.0


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


@pytest.mark.parametrize("preset", sorted(PRESETS))
def test_scrollbar_handle_is_findable(preset: str) -> None:
    """스크롤바 손잡이는 '잡아야 하는' 컨트롤이라 트랙과 구분돼야 한다.

    예전에는 손잡이가 `bg_overlay`였는데 트랙(`bg_surface`) 대비가 11개 테마에서
    1.08~1.32:1이라 사실상 보이지 않았다(실측). 손잡이 색을 `text_muted`로 올려
    전 테마 3:1 이상(4.55~6.23)을 확보한다.
    """
    tokens = PRESETS[preset]
    ratio = contrast(tokens.text_muted, tokens.bg_surface)
    assert ratio >= _AA_NON_TEXT, (
        f"{preset}: 스크롤바 손잡이(text_muted) 대비 트랙(bg_surface) {ratio:.2f} "
        f"< {_AA_NON_TEXT} — 손잡이가 보이지 않는다"
    )


@pytest.mark.parametrize("preset", sorted(PRESETS))
def test_focus_ring_is_visible(preset: str) -> None:
    """키보드 포커스 표시(accent 테두리)가 입력 배경 위에서 식별돼야 한다.

    예전 QSS는 포커스 시 테두리를 `border_muted`로만 바꿨는데 기본 `border`와
    거의 같은 톤이라 지금 어디에 포커스가 있는지 알 수 없었다. accent 링으로 바꾸면
    전 테마 5.22:1 이상이 나온다(실측).
    """
    tokens = PRESETS[preset]
    for bg in ("bg_elevated", "bg_surface"):
        ratio = contrast(tokens.accent, getattr(tokens, bg))
        assert ratio >= _AA_NON_TEXT, (
            f"{preset}: 포커스 링(accent) 대비 {bg} {ratio:.2f} < {_AA_NON_TEXT}"
        )


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
