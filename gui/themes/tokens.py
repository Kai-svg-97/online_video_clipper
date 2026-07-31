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

    @property
    def is_light(self) -> bool:
        """밝은 테마인지 — 배경 휘도로 판정한다.

        의미 색(오류 빨강 등)은 테마 토큰에 없지만 밝은 배경과 어두운 배경에서
        읽히는 톤이 다르므로, 위젯이 이 값으로 톤을 고른다.
        """
        raw = self.bg_base.lstrip("#")
        r, g, b = (int(raw[i : i + 2], 16) for i in (0, 2, 4))
        return (0.299 * r + 0.587 * g + 0.114 * b) > 140


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
    text_secondary="#a7a7a7",
    text_muted="#7f7f7f",
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
    text_secondary="#a6b3c4",
    text_muted="#7587a1",
    accent="#7f86f6",
    accent_hover="#9ba1f9",
    selected_border="#7f86f6",
    progress_fg="#7f86f6",
    badge_bg="rgba(0, 0, 0, 0.75)",
    star_color="#f59e0b",
    text_on_accent="#0e1014",
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
    text_secondary="#b2acab",
    text_muted="#8e837c",
    accent="#d4a84b",
    accent_hover="#e8be65",
    selected_border="#d4a84b",
    progress_fg="#d4a84b",
    badge_bg="rgba(0, 0, 0, 0.75)",
    star_color="#d4a84b",
    text_on_accent="#1a1208",
)

FOREST = ThemeTokens(
    name="forest",
    display_name="Forest",
    bg_base="#0b1210",
    bg_surface="#0f1714",
    bg_elevated="#17211d",
    bg_overlay="#1f2c26",
    border="#1c2723",
    border_muted="#2a3830",
    text_primary="#e3ece7",
    text_secondary="#adbfb6",
    text_muted="#84988d",
    accent="#34d399",
    accent_hover="#6ee7b7",
    selected_border="#34d399",
    progress_fg="#34d399",
    badge_bg="rgba(0, 0, 0, 0.75)",
    star_color="#eab308",
    text_on_accent="#06120d",
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
    text_secondary="#394a63",
    text_muted="#536a86",
    accent="#1c5cea",
    accent_hover="#1d4ed8",
    selected_border="#1c5cea",
    progress_fg="#1c5cea",
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
    text_secondary="#733544",
    text_muted="#955963",
    accent="#cf1b42",
    accent_hover="#be123c",
    selected_border="#cf1b42",
    progress_fg="#cf1b42",
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
    text_secondary="#574633",
    text_muted="#7b674b",
    accent="#bd3f0c",
    accent_hover="#9a3412",
    selected_border="#bd3f0c",
    progress_fg="#bd3f0c",
    badge_bg="rgba(0, 0, 0, 0.55)",
    star_color="#d97706",
    text_on_accent="#ffffff",
)


MIST = ThemeTokens(
    name="mist",
    display_name="Mist",
    # 계층 간 휘도 차이를 12~18단위로 벌려 경계가 눈에 보이게 한다.
    # 순백 대신 #f8fafc를 카드에 써 장시간 사용 시 눈 부담을 줄인다.
    bg_base="#d9dee6",
    bg_surface="#e7ebf1",
    bg_elevated="#f8fafc",
    bg_overlay="#c9d2dd",
    border="#aab6c5",
    border_muted="#c4cdd9",
    text_primary="#121a25",
    text_secondary="#3c4858",
    text_muted="#556273",
    accent="#1555e2",
    accent_hover="#1d4ed8",
    selected_border="#1555e2",
    progress_fg="#1555e2",
    badge_bg="rgba(0, 0, 0, 0.55)",
    star_color="#b45309",
    text_on_accent="#ffffff",
)


SAGE = ThemeTokens(
    name="sage",
    display_name="Sage",
    bg_base="#e4eae1",
    bg_surface="#eef2ea",
    bg_elevated="#fbfdf9",
    bg_overlay="#d5ded0",
    border="#b2c0aa",
    border_muted="#ccd7c5",
    text_primary="#141c15",
    text_secondary="#3b4a39",
    text_muted="#55694f",
    accent="#2a7047",
    accent_hover="#1f5a38",
    selected_border="#2a7047",
    progress_fg="#2a7047",
    badge_bg="rgba(0, 0, 0, 0.55)",
    star_color="#b45309",
    text_on_accent="#ffffff",
)

LAVENDER = ThemeTokens(
    name="lavender",
    display_name="Lavender",
    bg_base="#eae6f4",
    bg_surface="#f3f0fa",
    bg_elevated="#fdfcff",
    bg_overlay="#ddd5ee",
    border="#bcb0d8",
    border_muted="#d6cee8",
    text_primary="#1b1430",
    text_secondary="#443a5e",
    text_muted="#5e5280",
    accent="#6d28d9",
    accent_hover="#5b21b6",
    selected_border="#6d28d9",
    progress_fg="#6d28d9",
    badge_bg="rgba(0, 0, 0, 0.55)",
    star_color="#b45309",
    text_on_accent="#ffffff",
)

GRAPHITE = ThemeTokens(
    name="graphite",
    display_name="Graphite",
    # 중간 밝기 회색 — 순백이 눈부신 사용자를 위한 저자극 밝은 테마.
    bg_base="#c9ccd1",
    bg_surface="#d8dbe0",
    bg_elevated="#eceef1",
    bg_overlay="#bcc0c7",
    border="#9ba1aa",
    border_muted="#b5bac1",
    text_primary="#14171c",
    text_secondary="#3a3f47",
    text_muted="#565c66",
    accent="#0b4b99",
    accent_hover="#083a78",
    selected_border="#0b4b99",
    progress_fg="#0b4b99",
    badge_bg="rgba(0, 0, 0, 0.55)",
    star_color="#9a5b00",
    text_on_accent="#ffffff",
)


PRESETS: dict[str, ThemeTokens] = {
    "slate": SLATE,
    "zinc": ZINC,
    "warm": WARM,
    "forest": FOREST,
    "cloud": CLOUD,
    "rose": ROSE,
    "sand": SAND,
    "mist": MIST,
    "sage": SAGE,
    "lavender": LAVENDER,
    "graphite": GRAPHITE,
}

DEFAULT_PRESET = "mist"
