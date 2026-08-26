"""모든 테마 프리셋이 읽을 수 있는 명도 대비를 갖는지 고정한다.

배경: 밝은 테마에서 글자가 배경에 묻혀 안 보인다는 문제가 있었다. 원인은 두 가지였다 —
(1) `text_muted`/`accent` 가 배경 대비 3:1도 안 되는 값이었고,
(2) 통계 패널 등이 테마와 무관한 어두운 색을 스타일시트에 직접 박아 두었다.
여기서는 (1)을 수치로 고정하고, (2)는 하드코딩이 되살아나지 않는지 확인한다.
"""
from __future__ import annotations

import ast
import io
import re
import tokenize
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


# gui/ 전체에서 색 리터럴이 허용되는 파일 — 각각 CLAUDE.md '색상 규칙'의 예외다.
# 여기 새 파일을 추가하려면 그 파일 안에 이유를 주석으로 남길 것.
_COLOR_LITERAL_ALLOWLIST = {
    # 색의 출처 자체
    "gui/themes/tokens.py": "테마 프리셋 정의 — 모든 색이 여기서 나온다",
    "gui/themes/colors.py": "_SEMANTIC(의미 색) 표",
    "gui/panels/library/constants.py": "_TAG_PALETTE(태그 식별용 고정 32색)·_BADGE_EMPTY_BG·_YT_BRAND_RED",
    # 영상 프레임 위 — 기준이 앱 테마가 아니라 '어떤 영상 위에서도 읽히는가'
    "gui/widgets/player/surfaces.py": "영상 레터박스 검정",
    "gui/widgets/player/controls.py": "컨트롤바 = 영상 위 스크림 + 흰 글자",
    "gui/widgets/lyrics_overlay.py": "자막 흰 글자 + 검은 외곽선",
    "gui/panels/library/delegates.py": "_PROGRESS_FG + 썸네일 위 배지 배경·흰 글자",
    "gui/panels/library/cards.py": "썸네일 위 개수 배지",
    "gui/panels/feed_panel.py": "썸네일 위 재생시간·채널명 배지",
    "gui/panels/download_panel.py": "썸네일 위 딤·진행률 스크림",
    # 태그 팔레트(고정색) 위의 흰 글자 — TestTagPaletteReadable이 대비를 보장한다
    "gui/panels/library/tag_widgets.py": "태그 칩 흰 글자",
    "gui/panels/library/tree.py": "태그 칩 흰 글자",
    # 밝기 어느 쪽 배경에도 섞이는 중립 회색 틴트(교대 음영)
    "gui/panels/detail/song_tab.py": "중립 회색 틴트",
}

_COLOR_LITERAL = re.compile(
    r"#[0-9a-fA-F]{3}\b|#[0-9a-fA-F]{6}\b"      # "#fff" / "#1a2b3c"
    r"|rgba?\(\s*\d+\s*,"                        # "rgb(1,..." / "rgba(1,..."
    r"|QColor\(\s*\d+\s*,\s*\d+\s*,\s*\d+"       # QColor(30, 30, 30)
)


def _code_literals(src: str) -> list[tuple[int, str]]:
    """주석·독스트링을 뺀 코드에서 찾은 색 리터럴을 (줄번호, 값)으로 돌려준다.

    **주석은 `tokenize`로 걷어낸다.** 줄을 `split("#")`으로 자르면 `"#dc2626"` 같은
    hex 색의 `#`을 주석 시작으로 오해해 색이 통째로 사라진다(이 검사를 처음 쓸 때
    실제로 그래서 hex 위반을 하나도 못 잡았다). 대신 COMMENT·독스트링 토큰이
    차지한 자리를 공백으로 덮고 남은 코드만 훑는다.

    주석 안의 색 언급("예전엔 #ddd가 박혀 있었다")은 위반이 아니라 설명이므로
    세지 않는 것이 맞다.
    """
    try:
        ast.parse(src)
    except SyntaxError:   # 문법 오류는 다른 테스트가 잡는다
        return []

    lines = src.splitlines()
    grid = [list(line) for line in lines]

    def blank(srow: int, scol: int, erow: int, ecol: int) -> None:
        for r in range(srow, erow + 1):
            if not (1 <= r <= len(grid)):
                continue
            row = grid[r - 1]
            lo = scol if r == srow else 0
            hi = ecol if r == erow else len(row)
            for c in range(lo, min(hi, len(row))):
                row[c] = " "

    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                blank(tok.start[0], tok.start[1], tok.end[0], tok.end[1])
    except (tokenize.TokenError, IndentationError):
        return []

    # 독스트링(모듈·클래스·함수의 첫 문자열)도 설명이므로 제외한다.
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                d = body[0].value
                blank(d.lineno, d.col_offset, d.end_lineno, d.end_col_offset)

    out: list[tuple[int, str]] = []
    for i, row in enumerate(grid, 1):
        for m in _COLOR_LITERAL.finditer("".join(row)):
            out.append((i, m.group(0)))
    return out


class TestNoHardcodedColors:
    """**gui/ 전체**에서 테마를 따르지 않는 색이 되살아나지 않는지 지킨다.

    예전에는 이 검사가 `stats_panel.py` 한 파일의 특정 금지 목록(`#1e1e2e` 등)만
    봤다. 그래서 라이브러리 화면 경로는 전혀 덮이지 않았고, 실제로 감사에서
    하드코딩 20건이 나왔다 — 썸네일 자리표시자 검정, 브레드크럼 링크 하늘색(밝은
    테마에서 약 2:1), 드롭 표시기 파랑, 상태 배지 Material 원색, 그리고 플레이어
    컨트롤바 글자(밝은 테마 7종에서 1.10~1.90:1) 등이다.

    이제 파일 단위 허용 목록만 예외로 두고 나머지는 전부 막는다.
    색이 필요하면 `gui/themes/colors.py`의 `tok()`·`sem()`을 쓴다.
    """

    _GUI = Path(__file__).resolve().parents[2] / "gui"

    def test_no_color_literals_outside_allowlist(self) -> None:
        violations: dict[str, list[tuple[int, str]]] = {}
        for path in sorted(self._GUI.rglob("*.py")):
            rel = path.relative_to(self._GUI.parent).as_posix()
            if "__pycache__" in rel or rel in _COLOR_LITERAL_ALLOWLIST:
                continue
            hits = _code_literals(path.read_text(encoding="utf-8"))
            if hits:
                violations[rel] = hits
        detail = "\n".join(f"  {f}: {h}" for f, h in violations.items())
        assert not violations, (
            "테마 토큰을 쓰지 않은 색 리터럴이 있다. tok()/sem()을 쓰거나, 정당한 "
            f"예외라면 이유 주석과 함께 _COLOR_LITERAL_ALLOWLIST에 등록할 것:\n{detail}"
        )

    def test_allowlist_entries_still_exist(self) -> None:
        """허용 목록이 낡지 않게 — 파일이 사라지거나 이름이 바뀌면 알려준다."""
        missing = [
            rel for rel in _COLOR_LITERAL_ALLOWLIST
            if not (self._GUI.parent / rel).exists()
        ]
        assert not missing, f"존재하지 않는 파일이 허용 목록에 등록돼 있다: {missing}"

    def test_allowlist_entries_actually_need_exception(self) -> None:
        """색 리터럴이 없어진 파일은 허용 목록에서 빼야 한다(예외가 굳는 것 방지)."""
        unnecessary = []
        for rel in _COLOR_LITERAL_ALLOWLIST:
            path = self._GUI.parent / rel
            if not path.exists():
                continue
            if not _code_literals(path.read_text(encoding="utf-8")):
                unnecessary.append(rel)
        assert not unnecessary, (
            f"색 리터럴이 없는데 허용 목록에 남아 있다(제거할 것): {unnecessary}"
        )


class TestTagPaletteReadable:
    """태그 칩은 흰 글자를 고정으로 쓰므로 팔레트 전 색이 그 대비를 만족해야 한다.

    칩 배경은 테마 토큰이 아니라 `_TAG_PALETTE`(식별용 고정 팔레트)에서 오고 글자는
    항상 흰색이다. 감사에서 "지금은 우연히 맞다"고 본 지점이 실제로는 2색(`#4a8a4a`
    4.18:1, `#1a8a8a` 4.16:1)이 AA 미달이었다 — 각 채널을 6 낮춰 4.5:1로 올렸다.
    칩 글자는 7pt(작은 텍스트)라 AA Large(3:1)가 아니라 본문 기준이 적용된다.
    """

    def test_white_text_on_every_tag_color(self) -> None:
        from gui.panels.library.constants import _TAG_PALETTE

        failures = [
            (color, round(contrast("#ffffff", color), 2))
            for color in _TAG_PALETTE
            if contrast("#ffffff", color) < _AA_NORMAL
        ]
        assert not failures, f"흰 글자 대비 미달 태그 색: {failures}"

    def test_palette_has_no_duplicates(self) -> None:
        """중복이 있으면 서로 다른 태그가 같은 색으로 보여 식별 목적이 깨진다."""
        from gui.panels.library.constants import _TAG_PALETTE

        dupes = {c for c in _TAG_PALETTE if _TAG_PALETTE.count(c) > 1}
        assert not dupes, f"팔레트에 중복 색: {sorted(dupes)}"


@pytest.mark.parametrize("preset", sorted(PRESETS))
def test_unselected_chip_has_visible_border(preset: str) -> None:
    """칩(인기 태그·태그 목록·즐겨찾기)은 클릭 대상이라 경계가 식별돼야 한다.

    칩 채움색(`bg_elevated`)은 배경 바(`bg_surface`) 대비가 11개 테마에서
    1.05~1.19:1뿐이므로 채움만으로는 절대 구분되지 않는다. 예전 테두리
    (`border_muted`)도 채움 대비 1.20~1.68:1이라 **전 테마가 3:1에 미달**했다 —
    다크 테마에서 칩이 사라지고 카운트 배지만 떠 보이는 원인이었다.
    """
    from gui.panels.library.formatting import chip_colors

    tokens = PRESETS[preset]
    c = chip_colors(tokens, selected=False)
    ratio = contrast(c["border"], c["bg"])
    assert ratio >= _AA_NON_TEXT, (
        f"{preset}: 칩 테두리({c['border']}) 대비 채움({c['bg']}) {ratio:.2f} "
        f"< {_AA_NON_TEXT} — 칩 경계가 보이지 않는다"
    )
