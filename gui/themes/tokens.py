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
    text_on_accent: str # 액센트 배경 위 텍스트 색상 (선택된 항목 등)


# ---------------------------------------------------------------------------
# 어두운 테마 프리셋
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
    text_on_accent="#0a0a0a",
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
    text_on_accent="#ffffff",
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
    text_on_accent="#1a1208",
)

# ---------------------------------------------------------------------------
# 밝은 테마 프리셋
# ---------------------------------------------------------------------------

CLOUD = ThemeTokens(
    name="cloud",
    display_name="Cloud",
    bg_base="#f0f4f8",
    bg_surface="#e4ecf4",
    bg_elevated="#ffffff",
    bg_overlay="#d8e4f0",
    border="#c0d0e0",
    border_muted="#d4e2ee",
    text_primary="#1a2840",
    text_secondary="#4a6080",
    text_muted="#8ca0b8",
    accent="#2563eb",
    accent_hover="#1d4ed8",
    selected_border="#2563eb",
    progress_fg="#2563eb",
    badge_bg="rgba(0, 0, 0, 0.55)",
    star_color="#d97706",
    text_on_accent="#ffffff",
)

ROSE = ThemeTokens(
    name="rose",
    display_name="Rose",
    bg_base="#fff5f7",
    bg_surface="#fce8ec",
    bg_elevated="#ffffff",
    bg_overlay="#f8d8de",
    border="#ecc0c8",
    border_muted="#f4d4da",
    text_primary="#2d1820",
    text_secondary="#7a3848",
    text_muted="#b88890",
    accent="#e11d48",
    accent_hover="#be123c",
    selected_border="#e11d48",
    progress_fg="#e11d48",
    badge_bg="rgba(0, 0, 0, 0.55)",
    star_color="#d97706",
    text_on_accent="#ffffff",
)

SAND = ThemeTokens(
    name="sand",
    display_name="Sand",
    bg_base="#faf7f2",
    bg_surface="#f0ebe0",
    bg_elevated="#ffffff",
    bg_overlay="#e8ddd0",
    border="#d4c4b0",
    border_muted="#e4d8c8",
    text_primary="#2c2218",
    text_secondary="#6e5840",
    text_muted="#a89070",
    accent="#c2410c",
    accent_hover="#9a3412",
    selected_border="#c2410c",
    progress_fg="#c2410c",
    badge_bg="rgba(0, 0, 0, 0.55)",
    star_color="#d97706",
    text_on_accent="#ffffff",
)


PRESETS: dict[str, ThemeTokens] = {
    "slate": SLATE,
    "zinc": ZINC,
    "warm": WARM,
    "cloud": CLOUD,
    "rose": ROSE,
    "sand": SAND,
}

DEFAULT_PRESET = "slate"
