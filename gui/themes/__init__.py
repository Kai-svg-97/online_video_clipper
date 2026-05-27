"""테마 시스템 패키지.

사용법:
    from gui.themes.manager import ThemeManager
    ThemeManager.instance().apply("slate")   # 즉시 전체 UI에 반영
    ThemeManager.instance().theme_changed.connect(my_slot)
"""
from gui.themes.tokens import PRESETS, ThemeTokens
from gui.themes.manager import ThemeManager

__all__ = ["ThemeTokens", "PRESETS", "ThemeManager"]
