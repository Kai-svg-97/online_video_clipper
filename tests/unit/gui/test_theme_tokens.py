"""테마 토큰 검증 — 레이어 대비가 실제로 눈에 보이는 수준인지 확인한다.

기존 slate의 문제: bg_base #0a0a0a → bg_surface #0d0d0d → bg_elevated #141414 로
계층 간 차이가 3~7단위뿐이라 경계가 보이지 않았다.
"""
from __future__ import annotations

from gui.themes.tokens import DEFAULT_PRESET, MIST, PRESETS


def _lum(hex_color: str) -> float:
    """#rrggbb → 0~255 상대 휘도."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.299 * r + 0.587 * g + 0.114 * b


class TestMistPalette:
    def test_registered_and_default(self):
        assert PRESETS["mist"] is MIST
        assert DEFAULT_PRESET == "mist"

    def test_existing_presets_preserved(self):
        """기존 테마를 지우지 않았는지 확인한다."""
        for name in ("slate", "zinc", "warm", "cloud", "rose", "sand"):
            assert name in PRESETS

    def test_layers_are_distinguishable(self):
        """base < surface < elevated 순으로 밝아지고 각 단계가 8 이상 벌어져야 한다."""
        base, surface, elevated = _lum(MIST.bg_base), _lum(MIST.bg_surface), _lum(MIST.bg_elevated)
        assert base < surface < elevated
        assert surface - base >= 8, f"base→surface 차이 부족: {surface - base}"
        assert elevated - surface >= 8, f"surface→elevated 차이 부족: {elevated - surface}"

    def test_is_brighter_than_slate(self):
        """'너무 어둡다'는 요구를 실제로 해결했는지 — 밝은 쪽이어야 한다."""
        assert _lum(MIST.bg_base) > 180

    def test_text_has_contrast_on_base(self):
        """본문 텍스트가 배경과 충분히 대비되어야 한다."""
        assert abs(_lum(MIST.text_primary) - _lum(MIST.bg_base)) > 120

    def test_slate_layers_were_the_problem(self):
        """회귀 기준 기록 — slate는 계층차가 8 미만이었다(이 테스트는 slate를 고치지 않음)."""
        s = PRESETS["slate"]
        assert _lum(s.bg_surface) - _lum(s.bg_base) < 8
