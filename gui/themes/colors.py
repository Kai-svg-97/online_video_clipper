"""인라인 스타일시트에서 쓰는 색 헬퍼.

위젯이 `setStyleSheet`에 색을 직접 박으면 테마를 바꿔도 그 색만 남아 밝은 테마에서
글자가 배경에 묻힌다. 색이 필요한 자리에서는 하드코딩 대신 여기를 거친다.

    lbl.setStyleSheet(f"font-size: 9pt; color: {tok().text_secondary};")
    err.setStyleSheet(f"color: {sem('danger')};")
"""
from __future__ import annotations

from gui.themes.manager import ThemeManager
from gui.themes.tokens import ThemeTokens

# 의미 색(성공·오류·경고) — 테마 토큰에는 없지만 배경 밝기에 따라 읽히는 톤이 다르다.
# 각 값은 해당 밝기의 표면 위에서 본문 대비 4.5:1 이상을 만족한다.
_SEMANTIC: dict[str, tuple[str, str]] = {
    # kind: (밝은 테마, 어두운 테마)
    "success": ("#15803d", "#4ade80"),
    "danger": ("#dc2626", "#f87171"),
    "warning": ("#b45309", "#fbbf24"),
}


def tok() -> ThemeTokens:
    """현재 테마 토큰."""
    return ThemeManager.instance().current()


def sem(kind: str) -> str:
    """의미 색을 현재 테마 밝기에 맞는 톤으로 반환한다."""
    light, dark = _SEMANTIC[kind]
    return light if tok().is_light else dark
