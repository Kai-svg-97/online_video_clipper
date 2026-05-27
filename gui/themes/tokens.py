"""디자인 토큰 — 모든 색상 값의 단일 출처.

각 ThemeTokens 인스턴스가 하나의 완전한 색상 팔레트를 정의한다.
DESIGN.md의 색상 토큰 표와 1:1 대응.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeTokens:
    """하나의 테마를 구성하는 모든 색상 토큰."""

    # 테마 식별자
    name: str
    display_name: str

    # 배경 계층
    bg_base: str        # 최하단 배경 (창 전체)
    bg_surface: str     # 패널/사이드바 배경
    bg_elevated: str    # 카드/입력 배경
    bg_overlay: str     # 호버·활성 상태

    # 테두리
    border: str         # 기본 테두리
    border_muted: str   # 약한 테두리 (카드 등)

    # 텍스트
    text_primary: str   # 주 텍스트
    text_secondary: str # 부 텍스트 (메타데이터)
    text_muted: str     # 3차 텍스트 (비활성)

    # 액센트 (버튼, 선택 상태, 진행바)
    accent: str
    accent_hover: str
    selected_border: str
    progress_fg: str

    # 기타
    badge_bg: str       # 뱃지/오버레이 배경 (rgba 문자열)
    star_color: str     # 즐겨찾기 별 색상


# ---------------------------------------------------------------------------
# 프리셋 정의
# ---------------------------------------------------------------------------

SLATE = ThemeTokens(
    name="slate",
    display_name="Slate",
    bg_base="#0a0a0a",
    bg_surface="#0d0d0d",
    bg_elevated="#141414",
    bg_overlay="#1e1e1e",
    border="#1a1a1a",
    border_muted="#252525",
    text_primary="#e0e0e0",
    text_secondary="#888888",
    text_muted="#444444",
    accent="#e0e0e0",
    accent_hover="#ffffff",
    selected_border="#e0e0e0",
    progress_fg="#e0e0e0",
    badge_bg="rgba(0, 0, 0, 0.75)",
    star_color="#d4a84b",
)

ZINC = ThemeTokens(
    name="zinc",
    display_name="Zinc",
    bg_base="#0e1014",
    bg_surface="#111318",
    bg_elevated="#1c1f26",
    bg_overlay="#252832",
    border="#1e2230",
    border_muted="#2d3142",
    text_primary="#e2e8f0",
    text_secondary="#94a3b8",
    text_muted="#475569",
    accent="#6366f1",
    accent_hover="#818cf8",
    selected_border="#6366f1",
    progress_fg="#6366f1",
    badge_bg="rgba(0, 0, 0, 0.75)",
    star_color="#f59e0b",
)

WARM = ThemeTokens(
    name="warm",
    display_name="Warm",
    bg_base="#0f0e0d",
    bg_surface="#131211",
    bg_elevated="#1e1c1b",
    bg_overlay="#2a2624",
    border="#252220",
    border_muted="#302c28",
    text_primary="#e8e4e0",
    text_secondary="#9a9290",
    text_muted="#4a4440",
    accent="#d4a84b",
    accent_hover="#e8be65",
    selected_border="#d4a84b",
    progress_fg="#d4a84b",
    badge_bg="rgba(0, 0, 0, 0.75)",
    star_color="#d4a84b",
)

PRESETS: dict[str, ThemeTokens] = {
    "slate": SLATE,
    "zinc": ZINC,
    "warm": WARM,
}

DEFAULT_PRESET = "slate"
