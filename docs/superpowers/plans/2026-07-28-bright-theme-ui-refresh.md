# 밝은 테마 · 아이콘 제거 · 트리 재설계 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기본 테마를 밝은 중간 톤 `mist`로 바꿔 레이어가 구분되게 하고, 중복·불필요 아이콘 2개를 제거하고, 카테고리 트리의 그리기 계층만 교체해 세련된 외형을 만든다.

**Architecture:** 배경 계층은 이미 테마 토큰을 따르므로 새 팔레트 추가만으로 해결된다. 토큰을 우회해 `QPainter`로 직접 칠하는 칩 2종은 토큰 기반으로 바꾼다. 트리는 `_PlaylistTree`의 동작 코드 1,370줄을 건드리지 않고, 항목 팩토리에 데이터 롤을 심은 뒤 `QStyledItemDelegate`와 `drawBranches()` 오버라이드로 외형만 교체한다.

**Tech Stack:** Python 3.10+, PyQt6 (`QStyledItemDelegate`, `QTreeWidget.drawBranches`, `QPainter`), pytest / pytest-qt

**Spec:** `docs/superpowers/specs/2026-07-28-bright-theme-ui-refresh-design.md`

## Global Constraints

- 모든 문서·주석·커밋 메시지는 **한국어**로 작성한다. 코드 식별자·라이브러리명은 영어 유지.
- **`_PlaylistTree`의 시그널 28개·드래그&드롭·컨텍스트 메뉴·로딩 스피너·스냅샷 복원 코드는 수정하지 않는다.** 변경은 그리기 계층(델리게이트·`drawBranches`·항목 팩토리의 롤 추가)에만 한정한다.
- 항목 팩토리의 기존 `setText(0, ...)` 라벨은 **그대로 유지**한다 — 툴팁·스피너(`_ORIG_TEXT_ROLE`)·`find_item_by_*` 탐색이 계속 동작해야 한다.
- 기존 테마 6종(slate/zinc/warm/cloud/rose/sand)은 **삭제하지 않는다**. `mist`를 추가하고 기본값만 바꾼다.
- `_TAG_PALETTE`의 32색은 **항목 식별용 데이터 색상이므로 값을 바꾸지 않는다**. 배정 방식(해시)만 안정화한다.
- 모듈마다 `logger = logging.getLogger(__name__)`. 예외를 조용히 삼키지 말고 `logger.exception`/`logger.warning`으로 남긴다.
- GUI 파일을 수정했으므로 마지막에 `/verify`로 실앱 기동을 확인한다.
- `tests/gui/test_smoke.py`의 3건(`test_widget_has_expected_tabs`, `test_local_root_requests_categorized_only`, `test_playlist_view_not_categorized_only`)은 **작업 시작 전 main에서 이미 실패하던 기존 문제**다. 이번 작업으로 실패 건수가 3보다 늘지 않으면 통과로 본다.

## File Structure

| 파일 | 책임 | 변경 |
| --- | --- | --- |
| `gui/themes/tokens.py` | `MIST` 팔레트 추가, `DEFAULT_PRESET` 변경 | 수정 |
| `tests/unit/gui/test_theme_tokens.py` | 팔레트 계층 대비·기본값 검증 | 생성 |
| `gui/panels/library_panel.py` | 색상 배정 안정화, 칩 토큰화, 트리 롤 + 델리게이트 + `drawBranches` | 수정 |
| `tests/unit/gui/test_tag_color.py` | 색상 배정이 프로세스 간 안정적인지 검증 | 생성 |
| `tests/gui/test_tree_rows.py` | 항목 팩토리 롤·델리게이트 `sizeHint` 검증 | 생성 |
| `gui/main_window.py` | 로고·계정 버튼·죽은 메서드 제거 | 수정 |
| `tests/gui/test_sidebar_icons.py` | 제거 확인 | 생성 |
| `gui/themes/stylesheet.py` | 네이티브 branch 인디케이터 숨김 | 수정 |
| `CLAUDE.md` / `planning/youtube_content_manager_prd.md` | 규칙·요구사항 기록 | 수정 |

---

### Task 1: `mist` 팔레트 추가 및 기본값 지정

**Files:**
- Modify: `gui/themes/tokens.py` (밝은 테마 프리셋 구역, `SAND` 뒤 / `PRESETS` 딕셔너리 / `DEFAULT_PRESET`)
- Test: `tests/unit/gui/test_theme_tokens.py` (생성)

**Interfaces:**
- Consumes: `gui.themes.tokens.ThemeTokens` (기존 dataclass — 필드 17개)
- Produces:
  - `gui.themes.tokens.MIST: ThemeTokens` (`name="mist"`)
  - `PRESETS["mist"]`
  - `DEFAULT_PRESET == "mist"`

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`tests/unit/gui/__init__.py`를 빈 파일로 만들고(패키지 인식용), `tests/unit/gui/test_theme_tokens.py`를 생성한다:

```python
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
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/unit/gui/test_theme_tokens.py -v`
Expected: FAIL — `ImportError: cannot import name 'MIST' from 'gui.themes.tokens'`

- [ ] **Step 3: `MIST` 팔레트를 추가한다**

`gui/themes/tokens.py`의 `SAND` 정의 뒤, `PRESETS` 선언 앞에 추가한다:

```python
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
    text_secondary="#4d5c70",
    text_muted="#8290a2",
    accent="#2563eb",
    accent_hover="#1d4ed8",
    selected_border="#2563eb",
    progress_fg="#2563eb",
    badge_bg="rgba(0, 0, 0, 0.55)",
    star_color="#b45309",
    text_on_accent="#ffffff",
)
```

`PRESETS` 딕셔너리에 항목을 추가하고 `DEFAULT_PRESET`을 바꾼다:

```python
PRESETS: dict[str, ThemeTokens] = {
    "slate": SLATE,
    "zinc": ZINC,
    "warm": WARM,
    "cloud": CLOUD,
    "rose": ROSE,
    "sand": SAND,
    "mist": MIST,
}

DEFAULT_PRESET = "mist"
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/unit/gui/test_theme_tokens.py -v`
Expected: PASS — 6개 통과

- [ ] **Step 5: 설정 화면 테마 목록에 mist가 나오는지 확인한다**

`gui/panels/settings_panel.py:710`이 `for name, tokens in PRESETS.items():`로 순회하므로
**설정 패널은 수정할 필요가 없다**(사전 확인 완료). `mist`가 목록에 자동으로 나타난다.

Run: `python -c "from gui.themes.tokens import PRESETS; print([t.display_name for t in PRESETS.values()])"`
Expected: 목록 끝에 `'Mist'`가 포함된 7개

- [ ] **Step 6: 커밋한다**

```bash
python -m ruff check gui/themes/tokens.py tests/unit/gui/
git add gui/themes/tokens.py tests/unit/gui/
git commit -m "feat: 밝은 중간 톤 mist 테마 추가 및 기본값 지정

- bg_base #d9dee6 → surface #e7ebf1 → elevated #f8fafc 로 계층차 12~18단위 확보
- 기존 slate는 계층차가 3~7단위뿐이라 레이어 경계가 보이지 않았음
- 기존 테마 6종은 그대로 유지, DEFAULT_PRESET만 mist로 변경"
```

---

### Task 2: 태그·카테고리 색상 배정 안정화

`hash()`는 프로세스마다 무작위 시드를 쓰므로 **앱을 켤 때마다 색이 바뀐다**(실측: `music`이 3회 실행에서 인덱스 31 → 31 → 5). Task 5의 카테고리 색상 점이 의미를 가지려면 먼저 고쳐야 한다.

**Files:**
- Modify: `gui/panels/library_panel.py:1357`, `:2761` (`hash(...)` 호출부), `_TAG_PALETTE` 정의 뒤(`:147~` 구역)에 헬퍼 추가
- Test: `tests/unit/gui/test_tag_color.py` (생성)

**Interfaces:**
- Consumes: `gui.panels.library_panel._TAG_PALETTE` (기존 32색 tuple)
- Produces: `gui.panels.library_panel.tag_color(name: str) -> str` — `#rrggbb` 문자열 반환, 프로세스 간 안정

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`tests/unit/gui/test_tag_color.py` 생성:

```python
"""태그·카테고리 색상 배정이 실행 간 안정적인지 검증한다.

기존 구현은 `hash(name) % len(_TAG_PALETTE)`를 썼는데, 파이썬 str 해시는
PYTHONHASHSEED로 프로세스마다 무작위화되므로 앱을 다시 켤 때마다 색이 바뀌었다.
"""
from __future__ import annotations

import subprocess
import sys

from gui.panels.library_panel import _TAG_PALETTE, tag_color


class TestTagColor:
    def test_returns_palette_color(self):
        assert tag_color("music") in _TAG_PALETTE

    def test_deterministic_within_process(self):
        assert tag_color("music") == tag_color("music")

    def test_different_names_can_differ(self):
        """32색 팔레트이므로 몇 개 이름은 서로 다른 색을 받아야 한다."""
        names = ["music", "AI Coding", "Obsidian", "Redis", "Servers", "Movies"]
        assert len({tag_color(n) for n in names}) > 1

    def test_handles_korean_and_empty(self):
        assert tag_color("바이브코딩") in _TAG_PALETTE
        assert tag_color("") in _TAG_PALETTE

    def test_stable_across_processes(self):
        """핵심 회귀 — 별도 프로세스(다른 해시 시드)에서도 같은 색이어야 한다."""
        code = (
            "from gui.panels.library_panel import tag_color; "
            "print(','.join(tag_color(n) for n in ['music', 'AI Coding', '바이브코딩']))"
        )
        runs = set()
        for _ in range(3):
            out = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True, text=True, check=True,
            )
            runs.add(out.stdout.strip())
        assert len(runs) == 1, f"실행마다 색이 달라짐: {runs}"
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/unit/gui/test_tag_color.py -v`
Expected: FAIL — `ImportError: cannot import name 'tag_color'`

- [ ] **Step 3: 안정 해시 헬퍼를 구현한다**

`gui/panels/library_panel.py`의 `_TAG_PALETTE` 정의 바로 뒤에 추가한다:

```python
def tag_color(name: str) -> str:
    """태그·카테고리 이름에서 표시 색상을 결정한다.

    `hash()`는 파이썬 str 해시가 PYTHONHASHSEED로 프로세스마다 무작위화되어
    앱을 다시 켤 때마다 색이 바뀌었다. crc32는 시드에 의존하지 않아
    실행·플랫폼에 걸쳐 항상 같은 색을 준다.
    """
    digest = zlib.crc32(name.encode("utf-8"))
    return _TAG_PALETTE[digest % len(_TAG_PALETTE)]
```

파일 상단 import 구역에 `import zlib`을 추가한다(`import logging` 근처, 알파벳 순서 유지).

- [ ] **Step 4: 기존 호출부 2곳을 교체한다**

`library_panel.py:1357`:
```python
            color     = tag_color(name)
```

`library_panel.py:2761`:
```python
                color = tag_color(tname)
```

다른 `hash(` 사용처가 남았는지 확인한다:
```bash
grep -n "_TAG_PALETTE\[hash" gui/panels/library_panel.py
```
Expected: 결과 없음

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/unit/gui/test_tag_color.py -v`
Expected: PASS — 5개 통과 (`test_stable_across_processes` 포함)

- [ ] **Step 6: 커밋한다**

```bash
python -m ruff check gui/panels/library_panel.py tests/unit/gui/
git add gui/panels/library_panel.py tests/unit/gui/test_tag_color.py
git commit -m "fix: 태그·카테고리 색상이 앱 재시작마다 바뀌던 문제 수정

- hash()는 PYTHONHASHSEED로 프로세스마다 무작위화돼 색이 불안정했음
  (실측: 'music'이 3회 실행에서 팔레트 인덱스 31 → 31 → 5)
- zlib.crc32 기반 tag_color()로 교체해 실행·플랫폼 간 항상 동일
- 팔레트 32색 값 자체는 변경 없음"
```

---

### Task 3: 칩 색상 토큰화

토큰을 우회해 `QPainter`로 직접 칠하는 두 위젯을 테마에 반응하게 만든다. 밝은 테마에서 어두운 얼룩으로 남는 원인이다.

**Files:**
- Modify: `gui/panels/library_panel.py` — `_PopularTagButton.paintEvent`(`:1007~1042`), `_TagChipDelegate.paint`(`:1196~1237`), `_BreadcrumbBar` 배경(`:1302~1303`)
- Test: `tests/unit/gui/test_chip_colors.py` (생성)

**Interfaces:**
- Consumes: `gui.themes.manager.ThemeManager.instance().current() -> ThemeTokens`, `gui.themes.tokens.MIST`/`SLATE`
- Produces: `gui.panels.library_panel.chip_colors(tokens, selected: bool, data_color: str | None = None) -> dict[str, str]` — 키: `"bg"`, `"border"`, `"text"`, `"badge_bg"`, `"badge_text"`

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`tests/unit/gui/test_chip_colors.py` 생성:

```python
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
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/unit/gui/test_chip_colors.py -v`
Expected: FAIL — `ImportError: cannot import name 'chip_colors'`

- [ ] **Step 3: `chip_colors` 헬퍼를 구현한다**

`gui/panels/library_panel.py`의 `tag_color` 함수 바로 뒤에 추가한다:

```python
def chip_colors(tokens, selected: bool, data_color: str | None = None) -> dict[str, str]:
    """칩(인기 태그 버튼·태그 리스트 항목)의 색상을 테마 토큰에서 파생한다.

    미선택은 카드 표면(bg_elevated) + 약한 테두리로 배경에서 떠 보이게 하고,
    선택은 accent(또는 태그 고유 색)로 채운다.
    """
    if selected:
        return {
            "bg": data_color or tokens.accent,
            "border": data_color or tokens.accent,
            "text": tokens.text_on_accent,
            "badge_bg": tokens.bg_overlay,
            "badge_text": tokens.text_primary,
        }
    return {
        "bg": tokens.bg_elevated,
        "border": tokens.border_muted,
        "text": tokens.text_secondary,
        "badge_bg": tokens.bg_overlay,
        "badge_text": tokens.text_secondary,
    }
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/unit/gui/test_chip_colors.py -v`
Expected: PASS — 7개 통과

- [ ] **Step 5: `_PopularTagButton.paintEvent`을 교체한다**

`library_panel.py:1007~1042`의 본문을 다음으로 바꾼다(메서드 시그니처는 유지):

```python
    def paintEvent(self, _event) -> None:
        from gui.themes.manager import ThemeManager  # noqa: PLC0415

        tokens = ThemeManager.instance().current()
        c = chip_colors(tokens, selected=self._selected, data_color=self._color)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)

        painter.setBrush(QBrush(QColor(c["bg"])))
        painter.setPen(QPen(QColor(c["border"]), 1))
        painter.drawRoundedRect(rect, 10, 10)

        badge_text = str(self._count)
        painter.setFont(QFont("", 7))
        fm = painter.fontMetrics()
        badge_w = fm.horizontalAdvance(badge_text) + 12
        badge_h = rect.height() - 8
        badge_x = rect.right() - badge_w - 4
        badge_y = rect.center().y() - badge_h // 2
        badge_rect = QRect(badge_x, badge_y, badge_w, badge_h)

        painter.setBrush(QBrush(QColor(c["badge_bg"])))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(badge_rect, badge_h // 2, badge_h // 2)

        painter.setPen(QColor(c["badge_text"]))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)

        painter.setFont(QFont("", 9))
        painter.setPen(QColor(c["text"]))
        name_rect = QRect(rect.left() + 8, rect.top(), badge_x - rect.left() - 12, rect.height())
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine,
            self._tag_name,
        )
        painter.end()
```

`QPen`이 이 파일에 import되어 있는지 확인하고 없으면 추가한다:
```bash
grep -n "^from PyQt6.QtGui import" gui/panels/library_panel.py
```

- [ ] **Step 6: `_TagChipDelegate.paint`을 교체한다**

`library_panel.py:1196~1237`의 본문을 다음으로 바꾼다:

```python
    def paint(self, painter, option, index) -> None:
        from PyQt6.QtWidgets import QStyle  # noqa: PLC0415

        from gui.themes.manager import ThemeManager  # noqa: PLC0415

        text  = index.data(Qt.ItemDataRole.DisplayRole) or ""
        count = index.data(Qt.ItemDataRole.UserRole + 1) or 0
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        tokens = ThemeManager.instance().current()
        c = chip_colors(tokens, selected=selected)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        chip = option.rect.adjusted(3, 3, -3, -3)

        painter.setBrush(QBrush(QColor(c["bg"])))
        painter.setPen(QPen(QColor(c["border"]), 1))
        painter.drawRoundedRect(chip, 10, 10)

        # 카운트 배지(우측) — 클릭 시 삭제 히트 영역으로도 쓰인다
        badge_w = max(20, len(str(count)) * 7 + 10)
        badge_h = chip.height() - 6
        badge_x = chip.right() - badge_w - 4
        badge_y = chip.center().y() - badge_h // 2
        badge_rect = QRect(badge_x, badge_y, badge_w, badge_h)
        painter.setBrush(QBrush(QColor(c["badge_bg"])))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(badge_rect, badge_h // 2, badge_h // 2)

        painter.setFont(QFont("", 7))
        painter.setPen(QColor(c["badge_text"]))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, str(count))

        painter.setFont(QFont("", 8))
        painter.setPen(QColor(c["text"]))
        painter.drawText(
            QRect(chip.left() + 8, chip.top(), badge_x - chip.left() - 10, chip.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine,
            text,
        )

        painter.restore()
```

- [ ] **Step 7: 브레드크럼 배경을 토큰화한다**

`library_panel.py:1302~1303`의 하드코딩 배경을 테마 기반으로 바꾼다. 기존:

```python
        self.setStyleSheet(
            "background:#182430; border-radius:4px;"
```

이 위젯의 `__init__` 안에서 스타일을 적용하는 부분을 메서드로 빼고 `theme_changed`를 구독한다:

```python
        self._apply_theme(ThemeManager.instance().current())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)
```

그리고 클래스에 메서드를 추가한다(기존 스타일시트 문자열의 나머지 속성은 그대로 유지하고 색만 토큰으로 바꾼다):

```python
    def _apply_theme(self, tokens) -> None:
        self.setStyleSheet(
            f"background:{tokens.bg_surface}; border-radius:4px;"
        )
```

파일 상단에 `from gui.themes.manager import ThemeManager`가 이미 있는지 확인하고 없으면 추가한다.

- [ ] **Step 8: 남은 하드코딩 칩 색이 없는지 확인한다**

```bash
grep -n "#2a3a4a\|#1a4f82\|#204060\|#ddeeff\|#182430" gui/panels/library_panel.py
```
Expected: 결과 없음

- [ ] **Step 9: 테스트 실행 후 커밋한다**

```bash
python -m pytest tests/unit/gui/ tests/gui/ -q
python -m ruff check gui/panels/library_panel.py
git add gui/panels/library_panel.py tests/unit/gui/test_chip_colors.py
git commit -m "fix: 태그 칩·브레드크럼이 테마를 따르지 않던 문제 수정

- paintEvent에 하드코딩된 #2a3a4a·#1a4f82·#204060·#ddeeff를 chip_colors()로 대체
- 미선택 칩은 bg_elevated + border_muted로 배경에서 떠 보이게, 선택은 accent/태그색
- 브레드크럼 배경 #182430 → bg_surface + theme_changed 구독
- 밝은 테마에서 칩만 어두운 얼룩으로 남던 문제 해소"
```

---

### Task 4: 사이드바 아이콘 제거

**Files:**
- Modify: `gui/main_window.py:211~215`(로고), `:232~236`(계정 버튼), `:247~250`(죽은 메서드), `_SVG_ACCOUNT` 상수
- Test: `tests/gui/test_sidebar_icons.py` (생성)

**Interfaces:**
- Consumes: `gui.main_window._SideBar` (기존 클래스)
- Produces: `_SideBar`에 `_account_btn` 속성이 없고, `update_account_status` 메서드도 없다

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`tests/gui/test_sidebar_icons.py` 생성:

```python
"""사이드바에서 불필요한 아이콘이 제거됐는지 검증한다.

- 상단 ▶ 로고: 장식일 뿐 기능이 없었다.
- 계정 버튼: 클릭 동작이 바로 아래 기어 버튼과 완전히 동일한 중복이었다.
- update_account_status(): _account_btn만 참조하며 호출처가 없는 죽은 코드였다.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QStackedWidget

from gui.main_window import _SideBar


class TestSidebarIcons:
    def _bar(self, qapp_instance):
        return _SideBar(QStackedWidget())

    def test_no_play_logo_label(self, qapp_instance):
        bar = self._bar(qapp_instance)
        texts = [w.text() for w in bar.findChildren(QLabel)]
        assert "▶" not in texts

    def test_no_account_button(self, qapp_instance):
        bar = self._bar(qapp_instance)
        assert not hasattr(bar, "_account_btn")

    def test_dead_method_removed(self):
        assert not hasattr(_SideBar, "update_account_status")

    def test_nav_buttons_still_present(self, qapp_instance):
        """제거가 남은 내비게이션을 망가뜨리지 않았는지 — 주 4개 + 설정 1개."""
        bar = self._bar(qapp_instance)
        assert len(bar._buttons) == 5

    def test_settings_button_still_there(self, qapp_instance):
        bar = self._bar(qapp_instance)
        assert bar._settings_btn.toolTip() == "설정"
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/gui/test_sidebar_icons.py -v`
Expected: FAIL — `test_no_play_logo_label`, `test_no_account_button`, `test_dead_method_removed` 3건 실패

- [ ] **Step 3: 로고를 제거한다**

`gui/main_window.py`의 `_SideBar._build_ui`에서 다음 5줄을 삭제한다:

```python
        # 로고
        logo = QLabel("▶")
        logo.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        logo.setStyleSheet("font-size: 14px; font-weight: 700; margin-bottom: 10px;")
        layout.addWidget(logo)
```

- [ ] **Step 4: 계정 버튼과 죽은 메서드를 제거한다**

같은 파일에서 다음 5줄을 삭제한다:

```python
        # 계정 버튼 → 설정 페이지의 YouTube 연동 섹션으로 이동
        self._account_btn = _NavButton(_SVG_ACCOUNT, "YouTube 연동 설정")
        self._account_btn.setCheckable(False)
        self._account_btn.clicked.connect(lambda: self._navigate(_PAGE_SETTINGS))
        layout.addWidget(self._account_btn, alignment=Qt.AlignmentFlag.AlignHCenter)
```

그리고 `update_account_status` 메서드 전체(독스트링 포함 4줄)를 삭제한다:

```python
    def update_account_status(self, is_connected: bool) -> None:
        """YouTube 연동 상태에 따라 계정 버튼 tooltip을 갱신한다."""
        tip = "YouTube 연결됨 — 설정에서 관리" if is_connected else "YouTube 미연결 — 설정에서 연동"
        self._account_btn.setToolTip(tip)
```

- [ ] **Step 5: 남은 참조를 정리한다**

`_SVG_ACCOUNT`와 `QLabel`이 아직 쓰이는지 확인한다:
```bash
grep -n "_SVG_ACCOUNT\|QLabel" gui/main_window.py
```
`_SVG_ACCOUNT`가 더 이상 없으면 상수 정의를 삭제한다. `QLabel`이 더 이상 쓰이지 않으면 import에서 제거한다(`ruff check`가 F401로 잡아준다).

- [ ] **Step 6: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/gui/test_sidebar_icons.py -v`
Expected: PASS — 5개 통과

- [ ] **Step 7: 커밋한다**

```bash
python -m ruff check gui/main_window.py tests/gui/test_sidebar_icons.py
git add gui/main_window.py tests/gui/test_sidebar_icons.py
git commit -m "refactor: 사이드바에서 불필요한 아이콘 2개 제거

- 상단 ▶ 로고: 기능 없는 장식
- 계정 버튼: 클릭 동작이 바로 아래 기어 버튼과 완전히 동일한 중복
- update_account_status(): _account_btn만 참조하고 호출처가 없던 죽은 코드
- _SVG_ACCOUNT 상수도 함께 정리"
```

---

### Task 5: 트리 행 재설계 (데이터 롤 + 델리게이트 + `drawBranches`)

**Files:**
- Modify: `gui/panels/library_panel.py` — 롤 상수(`:1398` 뒤), `_make_folder`/`_make_unfiled`/`_make_category`/`_make_root` 팩토리(`:1754~1810`), 구독 노드(`:1645`), `_PlaylistTree.__init__`(`:1439~1460`)
- Create (같은 파일 내): `_TreeRowDelegate(QStyledItemDelegate)` — `_PlaylistTree` 클래스 정의 바로 앞
- Modify: `gui/themes/stylesheet.py:170~172` (`QTreeWidget::branch`)
- Test: `tests/gui/test_tree_rows.py` (생성)

**Interfaces:**
- Consumes: `chip_colors`(Task 3), `tag_color`(Task 2), `_ITEM_TYPE_ROLE`·`_ITYPE_CATEGORY`·`_ITYPE_FOLDER`·`_ITYPE_ROOT`(기존 상수)
- Produces:
  - `_NAME_ROLE = Qt.ItemDataRole.UserRole + 300`
  - `_COUNT_ROLE = Qt.ItemDataRole.UserRole + 301`
  - `_GLYPH_ROLE = Qt.ItemDataRole.UserRole + 302`
  - `_COLOR_ROLE = Qt.ItemDataRole.UserRole + 303`
  - `_TreeRowDelegate` — `sizeHint()` 높이 30, `paint()`가 롤을 읽어 행을 그린다
  - `_PlaylistTree.drawBranches(painter, rect, index)` 오버라이드

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`tests/gui/test_tree_rows.py` 생성:

```python
"""트리 항목의 데이터 롤과 델리게이트를 검증한다.

시각 정보가 한 문자열("🏷  이름  (3)")에 뭉쳐 있으면 델리게이트가 파싱해야 하는데,
로딩 스피너가 텍스트 뒤에 ⠋를 덧붙이고 카테고리 이름에 괄호가 들어갈 수도 있어
파싱은 깨진다. 그래서 팩토리가 롤을 따로 심고 델리게이트는 롤만 읽는다.
"""
from __future__ import annotations

from uuid import uuid4

from gui.panels.library_panel import (
    _COLOR_ROLE,
    _COUNT_ROLE,
    _GLYPH_ROLE,
    _ITEM_TYPE_ROLE,
    _ITYPE_CATEGORY,
    _NAME_ROLE,
    _STAR_ROLE,
    _PlaylistTree,
    _TreeRowDelegate,
)


class TestCategoryItemRoles:
    def test_name_and_count_stored_separately(self, qapp_instance):
        tree = _PlaylistTree(section="local")
        cid = uuid4()
        item = tree._make_category("AI Coding", cid, video_count=3)

        assert item.data(0, _NAME_ROLE) == "AI Coding"
        assert item.data(0, _COUNT_ROLE) == 3
        assert item.data(0, _GLYPH_ROLE) == "category"
        assert item.data(0, _ITEM_TYPE_ROLE) == _ITYPE_CATEGORY

    def test_zero_count_is_none(self, qapp_instance):
        tree = _PlaylistTree(section="local")
        item = tree._make_category("Servers", uuid4(), video_count=0)
        assert item.data(0, _COUNT_ROLE) is None

    def test_color_role_is_stable_palette_color(self, qapp_instance):
        """같은 이름은 항상 같은 색 — 색상 점이 의미를 가지려면 필수."""
        tree = _PlaylistTree(section="local")
        a = tree._make_category("Music", uuid4(), video_count=1)
        b = tree._make_category("Music", uuid4(), video_count=9)
        assert a.data(0, _COLOR_ROLE) == b.data(0, _COLOR_ROLE)
        assert a.data(0, _COLOR_ROLE).startswith("#")

    def test_name_role_excludes_parenthesis_in_name(self, qapp_instance):
        """이름에 괄호가 있어도 개수와 섞이지 않는다 — 문자열 파싱 방식이 깨지던 경우."""
        tree = _PlaylistTree(section="local")
        item = tree._make_category("Movies (2024)", uuid4(), video_count=5)
        assert item.data(0, _NAME_ROLE) == "Movies (2024)"
        assert item.data(0, _COUNT_ROLE) == 5

    def test_display_text_still_set(self, qapp_instance):
        """스피너·툴팁·find_item_by_* 가 계속 동작하려면 텍스트가 남아야 한다."""
        tree = _PlaylistTree(section="local")
        item = tree._make_category("Redis", uuid4(), video_count=1)
        assert "Redis" in item.text(0)


class TestFavoriteStar:
    def test_star_role_false_by_default(self, qapp_instance):
        tree = _PlaylistTree(section="local")
        item = tree._make_category("Redis", uuid4(), video_count=1)
        assert item.data(0, _STAR_ROLE) is False

    def test_star_role_true_when_favorited(self, qapp_instance):
        tree = _PlaylistTree(section="local")
        cid = uuid4()
        tree._favs.add(("category", str(cid)))
        item = tree._make_category("Music", cid, video_count=1)
        assert item.data(0, _STAR_ROLE) is True


class TestFolderItemRoles:
    def test_folder_roles(self, qapp_instance):
        tree = _PlaylistTree(section="local")
        item = tree._make_folder("보관함", uuid4(), "local")
        assert item.data(0, _NAME_ROLE) == "보관함"
        assert item.data(0, _GLYPH_ROLE) == "folder"

    def test_unfiled_roles(self, qapp_instance):
        tree = _PlaylistTree(section="local")
        item = tree._make_unfiled("local")
        assert item.data(0, _NAME_ROLE) == "미분류"
        assert item.data(0, _GLYPH_ROLE) == "folder"


class TestDelegate:
    def test_row_height_increased(self, qapp_instance):
        """행 높이 30px — 기존 약 22px보다 여유를 준다."""
        from PyQt6.QtWidgets import QStyleOptionViewItem

        tree = _PlaylistTree(section="local")
        item = tree._make_category("AI Coding", uuid4(), video_count=3)
        tree.addTopLevelItem(item)
        delegate = _TreeRowDelegate(tree)
        hint = delegate.sizeHint(QStyleOptionViewItem(), tree.indexFromItem(item, 0))
        assert hint.height() == 30

    def test_tree_installs_delegate(self, qapp_instance):
        tree = _PlaylistTree(section="local")
        assert isinstance(tree.itemDelegate(), _TreeRowDelegate)


class TestSpinnerStillWorks:
    def test_spinner_preserves_roles(self, qapp_instance):
        """스피너가 텍스트를 바꿔도 롤은 그대로여야 한다(델리게이트가 롤을 읽으므로)."""
        tree = _PlaylistTree(section="local")
        item = tree._make_category("AI Coding", uuid4(), video_count=3)
        tree.addTopLevelItem(item)

        tree.set_node_loading("k", item, True)
        assert item.data(0, _NAME_ROLE) == "AI Coding"
        assert item.data(0, _COUNT_ROLE) == 3

        tree.set_node_loading("k", None, False)
        assert item.data(0, _NAME_ROLE) == "AI Coding"
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/gui/test_tree_rows.py -v`
Expected: FAIL — `ImportError: cannot import name '_NAME_ROLE'`

- [ ] **Step 3: 롤 상수를 추가한다**

`gui/panels/library_panel.py`의 `_ORIG_TEXT_ROLE` 정의(`:1398`) 뒤에 추가한다:

```python
# 그리기 전용 롤 — _TreeRowDelegate가 읽는다. 항목 텍스트를 파싱하지 않기 위해
# 팩토리가 이름·개수·글리프·색을 따로 심는다(스피너가 텍스트를 변형하므로).
_NAME_ROLE  = Qt.ItemDataRole.UserRole + 300   # 아이콘·개수 없는 순수 이름
_COUNT_ROLE = Qt.ItemDataRole.UserRole + 301   # int | None
_GLYPH_ROLE = Qt.ItemDataRole.UserRole + 302   # "category" | "folder" | "playlist" | "channel" | "feed" | "group"
_COLOR_ROLE = Qt.ItemDataRole.UserRole + 303   # 카테고리 색상 점 (#rrggbb | None)
_STAR_ROLE  = Qt.ItemDataRole.UserRole + 304   # bool — 즐겨찾기
```

즐겨찾기는 델리게이트가 `_PlaylistTree._favs`를 직접 뒤지지 않도록 롤로 넘긴다.
팩토리가 이미 `starred` 값을 계산하고 있으므로 그 값을 그대로 심는다.

- [ ] **Step 4: 항목 팩토리에 롤을 심는다**

`_make_category`(`:1793~`)에서 기존 `label`·`setText` 로직은 그대로 두고 롤 4개를 추가한다:

```python
        item.setData(0, _NAME_ROLE, name)
        item.setData(0, _COUNT_ROLE, video_count if video_count > 0 else None)
        item.setData(0, _GLYPH_ROLE, "category")
        item.setData(0, _COLOR_ROLE, tag_color(name))
        item.setData(0, _STAR_ROLE, starred)
```

`starred`는 `_make_category`가 첫 줄에서 이미 계산한다
(`starred = ("category", str(cat_id)) in self._favs`) — 그 변수를 그대로 쓴다.

`_make_folder`(`:1765~`)에 추가한다:

```python
        item.setData(0, _NAME_ROLE, name)
        item.setData(0, _GLYPH_ROLE, "folder")
```

`_make_unfiled`(`:1778~`)에 추가한다:

```python
        item.setData(0, _NAME_ROLE, "미분류")
        item.setData(0, _GLYPH_ROLE, "folder")
```

`_make_root`(`:1754~`)에 추가한다:

```python
        item.setData(0, _NAME_ROLE, label)
        item.setData(0, _GLYPH_ROLE, "group")
```

구독 노드(`:1645` `sub_group`)에 추가한다:

```python
        sub_group.setData(0, _NAME_ROLE, "구독 채널")
        sub_group.setData(0, _GLYPH_ROLE, "group")
```

재생목록·채널·피드 항목 팩토리에도 같은 방식으로 `_NAME_ROLE`과 `_GLYPH_ROLE`(`"playlist"`, `"channel"`, `"feed"`)을 심는다. 각 팩토리를 찾으려면:
```bash
grep -n "_ITYPE_PLAYLIST\|_ITYPE_CHANNEL\|_ITYPE_FEED_ALL" gui/panels/library_panel.py | head
```
롤이 비어 있는 항목은 델리게이트가 `DisplayRole` 텍스트로 폴백하므로, 누락돼도 깨지지 않고 예전 모양으로 보인다.

- [ ] **Step 5: `_TreeRowDelegate`를 구현한다**

`class _PlaylistTree(QTreeWidget):` 정의 바로 앞에 추가한다:

```python
class _TreeRowDelegate(QStyledItemDelegate):
    """트리 행을 직접 그린다 — 둥근 pill 행 + 색상 점 + 우측 개수 뱃지 + ★.

    셰브론과 들여쓰기 가이드는 여기서 그리지 않는다. 아이템 영역에 그리면
    클릭이 확장으로 처리되지 않으므로 _PlaylistTree.drawBranches()가 담당한다.
    """

    _ROW_H = 30

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        size = super().sizeHint(option, index)
        return QSize(size.width(), self._ROW_H)

    def paint(self, painter, option, index) -> None:
        from PyQt6.QtWidgets import QStyle  # noqa: PLC0415

        from gui.themes.manager import ThemeManager  # noqa: PLC0415

        tokens = ThemeManager.instance().current()
        name = index.data(_NAME_ROLE) or index.data(Qt.ItemDataRole.DisplayRole) or ""
        count = index.data(_COUNT_ROLE)
        glyph = index.data(_GLYPH_ROLE) or ""
        color = index.data(_COLOR_ROLE)

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        is_group = glyph == "group"

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        row = option.rect.adjusted(3, 2, -3, -2)

        # 배경 — 그룹 행은 배경 없이 라벨처럼 보이게 한다
        if not is_group and (selected or hovered):
            if selected:
                tint = QColor(tokens.accent)
                tint.setAlpha(36)          # accent 약 14%
                bg = tint
            else:
                bg = QColor(tokens.bg_overlay)
            painter.setBrush(QBrush(bg))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(row, 6, 6)

        x = row.left() + 8

        # 카테고리 색상 점
        if glyph == "category" and color:
            dot = QRect(x, row.center().y() - 4, 8, 8)
            painter.setBrush(QBrush(QColor(color)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(dot)
            x += 16
        elif glyph:
            emoji = {"folder": "📂", "playlist": "≡", "channel": "📺", "feed": "📡"}.get(glyph, "")
            if emoji:
                painter.setPen(QColor(tokens.text_muted))
                painter.setFont(QFont("", 8))
                em_rect = QRect(x, row.top(), 16, row.height())
                painter.drawText(em_rect, Qt.AlignmentFlag.AlignVCenter, emoji)
                x += 20

        # 즐겨찾기 ★ (최우측)
        right = row.right() - 6
        if index.data(_STAR_ROLE):
            painter.setPen(QColor(tokens.star_color))
            painter.setFont(QFont("", 8))
            star_rect = QRect(right - 14, row.top(), 14, row.height())
            painter.drawText(star_rect, Qt.AlignmentFlag.AlignCenter, "★")
            right = star_rect.left() - 4

        # 우측 개수 뱃지
        if count:
            painter.setFont(QFont("", 7))
            fm = painter.fontMetrics()
            txt = str(count)
            bw = fm.horizontalAdvance(txt) + 12
            bh = 16
            badge = QRect(right - bw, row.center().y() - bh // 2, bw, bh)
            painter.setBrush(QBrush(QColor(tokens.bg_overlay)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(badge, bh // 2, bh // 2)
            painter.setPen(QColor(tokens.text_secondary))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, txt)
            right = badge.left() - 6

        # 이름 — 그룹 행은 자간을 넓힌 muted 라벨
        font = QFont(option.font)
        if is_group:
            font.setPointSize(9)
            font.setWeight(QFont.Weight.Bold)
            font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108)
            painter.setPen(QColor(tokens.text_muted))
        else:
            painter.setPen(QColor(tokens.accent if selected else tokens.text_primary))
        painter.setFont(font)

        name_rect = QRect(x, row.top(), max(10, right - x), row.height())
        elided = painter.fontMetrics().elidedText(
            name, Qt.TextElideMode.ElideRight, name_rect.width()
        )
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine,
            elided,
        )

        painter.restore()
```

`QStyledItemDelegate`·`QSize`·`QPen`·`QFont`가 import되어 있는지 확인한다(`_TagChipDelegate`가 같은 것들을 쓰므로 대부분 이미 있다).

- [ ] **Step 6: 델리게이트를 설치하고 `drawBranches`를 오버라이드한다**

`_PlaylistTree.__init__`의 `self.setIndentation(20)` 뒤에 추가한다:

```python
        self.setItemDelegate(_TreeRowDelegate(self))
        self.setMouseTracking(True)   # 호버 배경이 그려지도록 State_MouseOver 활성화
        self.setUniformRowHeights(True)
```

그리고 `_PlaylistTree`에 메서드를 추가한다(`_show_context_menu` 같은 기존 메서드 근처, 아무 곳이나 클래스 본문 안):

```python
    def drawBranches(self, painter, rect, index) -> None:  # noqa: N802
        """셰브론과 들여쓰기 가이드를 branch 영역에 직접 그린다.

        델리게이트(아이템 영역)에 그리면 클릭이 확장/축소로 처리되지 않는다 —
        QTreeView는 branch 영역의 클릭만 확장 히트로 본다. 여기서 그리면
        네이티브 히트테스트가 그대로 유지된다.
        """
        from gui.themes.manager import ThemeManager  # noqa: PLC0415

        tokens = ThemeManager.instance().current()
        painter.save()

        # 깊이별 세로 가이드선 — 화살표에 의존하지 않고 계층을 읽히게 한다
        indent = self.indentation()
        depth = 0
        walk = index.parent()
        while walk.isValid():
            depth += 1
            walk = walk.parent()

        painter.setPen(QPen(QColor(tokens.border_muted), 1))
        for level in range(depth):
            gx = rect.left() + indent * level + indent // 2
            painter.drawLine(gx, rect.top(), gx, rect.bottom())

        # 셰브론 — 자식이 있는 항목만
        item = self.itemFromIndex(index)
        if item is not None and item.childCount() > 0:
            cx = rect.left() + indent * depth + indent // 2
            painter.setPen(QColor(tokens.text_muted))
            painter.setFont(QFont("", 7))
            glyph = "▾" if item.isExpanded() else "▸"
            painter.drawText(
                QRect(cx - 6, rect.top(), 14, rect.height()),
                Qt.AlignmentFlag.AlignCenter,
                glyph,
            )

        painter.restore()
```

- [ ] **Step 7: 네이티브 branch 인디케이터를 숨긴다**

`gui/themes/stylesheet.py`의 `QTreeWidget::branch` 규칙(`:170~172`)을 바꾼다:

```
/* branch는 _PlaylistTree.drawBranches()가 직접 그린다 — 네이티브 화살표를 숨긴다 */
QTreeWidget::branch {{
    background: transparent;
    image: none;
}}
```

- [ ] **Step 8: 섹션 헤더 버튼의 톤을 새 트리에 맞춘다**

"로컬" / "YouTube" 헤더는 트리 행이 아니라 `_PlaylistPanel`의 `QPushButton`이다
(`local_hdr` `:2829`, `_yt_bar` 구역). 새 그룹 행과 같은 인상을 주도록 자간·색을 맞춘다.

먼저 현재 스타일을 확인한다:
```bash
grep -n "local_hdr\|_yt_toggle_btn\|_yt_bar" gui/panels/library_panel.py | head
```

두 버튼의 `setStyleSheet` 문자열에서 색을 토큰으로 바꾸고 자간을 넣는다. 델리게이트의
그룹 행과 동일한 값을 쓴다 — `text_muted`, 9pt, bold, letter-spacing 약 108%:

```python
        f"color:{tokens.text_muted}; font-size:9pt; font-weight:600;"
        f"letter-spacing:0.6px; background:transparent; border:none; text-align:left;"
```

이 버튼들이 이미 `theme_changed`를 구독하지 않으면, `_PlaylistPanel`에
`_apply_theme(tokens)` 메서드를 만들어 두 버튼 스타일을 갱신하고
`ThemeManager.instance().theme_changed.connect(self._apply_theme)`로 연결한다.
"YouTube" 헤더의 빨간 강조색은 브랜드 색이므로 유지한다.

- [ ] **Step 9: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/gui/test_tree_rows.py -v`
Expected: PASS — 13개 통과

- [ ] **Step 10: 트리 동작 회귀를 손으로 확인한다**

`/verify` 스킬로 실앱을 띄우고 다음을 하나씩 확인한다. 그리기 변경이 동작을 깨지 않았는지가 이 태스크의 핵심 위험이다.

1. 카테고리 노드의 **셰브론을 클릭**해 펼침/접힘이 동작하는가 (drawBranches 위치가 맞는지)
2. 카테고리를 클릭하면 우측 그리드가 그 카테고리로 바뀌는가
3. 재생목록을 **드래그해 폴더로** 옮길 수 있는가
4. 영상 카드를 **드래그해 카테고리로** 옮길 수 있는가
5. 노드 **우클릭 컨텍스트 메뉴**가 뜨는가
6. 즐겨찾기한 카테고리에 ★가 보이는가
7. YouTube 트리를 펼칠 때 **로딩 스피너**가 돌고, 끝나면 이름이 원래대로 돌아오는가
8. 뒤로가기(마우스 ‹)로 이전 화면이 복원되며 좌측 트리 강조가 따라오는가

- [ ] **Step 11: 커밋한다**

```bash
python -m pytest tests/ -q
python -m ruff check gui/panels/library_panel.py gui/themes/stylesheet.py
git add gui/panels/library_panel.py gui/themes/stylesheet.py tests/gui/test_tree_rows.py
git commit -m "feat: 카테고리 트리 행 재설계 (그리기 계층만 교체)

- 데이터 롤 4종(_NAME/_COUNT/_GLYPH/_COLOR)을 항목 팩토리에서 심어
  델리게이트가 텍스트를 파싱하지 않게 함(스피너가 텍스트를 변형하므로)
- _TreeRowDelegate: 둥근 pill 행·accent 틴트 선택·카테고리 색상 점·
  우측 개수 뱃지·행 높이 30px·그룹 행은 자간 넓힌 라벨
- 셰브론·들여쓰기 가이드는 drawBranches()에 그림 — 아이템 영역에 그리면
  펼침 클릭이 동작하지 않기 때문
- _PlaylistTree의 시그널·DnD·컨텍스트 메뉴·스피너 코드는 무수정"
```

---

### Task 6: 문서 갱신 및 before/after 시각 검증

**Files:**
- Modify: `CLAUDE.md` (`gui/` 파일 맵의 `tokens.py`·`library_panel.py`·`main_window.py` 항목)
- Modify: `planning/youtube_content_manager_prd.md` (UI/UX 개선 섹션)

**Interfaces:**
- Consumes: Task 1~5의 최종 결과
- Produces: 없음 (문서 + 검증 산출물)

- [ ] **Step 1: before/after 스크린샷을 찍어 비교한다**

스크래치패드의 미리보기 스크립트를 쓴다. `app.exec`를 가로채 `MainWindow`를 PNG로 캡처한다:

```bash
SP="C:/Users/kai/AppData/Local/Temp/claude/C--Users-kai-OneDrive-Documents-projects-online-video-clipper/825f481d-7ef5-4f78-b5fd-ad69c7303c60/scratchpad"
python "$SP/theme_preview.py" mist "$SP/after_mist.png"
python "$SP/theme_preview.py" slate "$SP/after_slate.png"
```

`after_mist.png`를 읽어 다음을 눈으로 확인한다:
- 좌측 패널·콘텐츠·카드의 세 계층이 구분되는가
- 태그 칩이 더 이상 어두운 얼룩이 아닌가
- 트리 행에 색상 점·개수 뱃지·pill 선택이 보이는가
- 사이드바 상단에 ▶가 없고 하단에 사람 아이콘이 없는가

`after_slate.png`로 **다크 테마에서도 새 트리·칩이 깨지지 않는지** 확인한다(토큰화가 제대로 됐다면 어두운 톤으로 잘 나와야 한다).

- [ ] **Step 2: `CLAUDE.md`의 gui 파일 맵을 갱신한다**

`gui/themes/tokens.py` 항목 설명에 추가한다:

```
. **기본 테마는 `mist`**(밝은 중간 톤) — `bg_base #d9dee6` → `bg_surface #e7ebf1` → `bg_elevated #f8fafc`로 계층차를 12~18단위 확보한다. 기존 slate는 계층차가 3~7단위뿐이라 레이어 경계가 보이지 않았다. 다크 6종은 그대로 유지돼 설정에서 선택 가능
```

`gui/panels/library_panel.py` 항목 설명에 추가한다:

```
. **트리 행은 `_TreeRowDelegate`가 그린다** — 둥근 pill 행·accent 14% 틴트 선택·카테고리 색상 점·우측 개수 뱃지·행 높이 30px. 항목 팩토리(`_make_category`/`_make_folder`/`_make_unfiled`/`_make_root`)가 `_NAME_ROLE`·`_COUNT_ROLE`·`_GLYPH_ROLE`·`_COLOR_ROLE`을 심고 델리게이트는 **롤만 읽는다**(로딩 스피너가 `setText`로 텍스트 뒤에 `⠋`를 덧붙이고 카테고리 이름에 괄호가 들어갈 수 있어 텍스트 파싱은 깨진다). **셰브론·들여쓰기 가이드선은 `drawBranches()` 오버라이드**에 그린다 — 델리게이트(아이템 영역)에 그리면 `QTreeView`가 branch 영역 클릭만 확장으로 처리하므로 펼침이 동작하지 않는다. 네이티브 화살표는 QSS `QTreeWidget::branch { image: none; }`로 숨긴다. **칩 색은 `chip_colors(tokens, selected, data_color)`로 토큰에서 파생**한다(과거 `paintEvent`에 `#2a3a4a` 등이 하드코딩돼 어떤 테마를 골라도 칩만 어두웠다). **태그·카테고리 색상은 `tag_color(name)`**(zlib.crc32 기반) — 이전 `hash(name)`은 PYTHONHASHSEED로 프로세스마다 무작위화돼 앱을 켤 때마다 색이 바뀌었다
```

`gui/main_window.py` 항목 설명에 추가한다:

```
. 사이드바에서 **상단 ▶ 로고와 계정(인증) 버튼을 제거**했다 — 로고는 기능 없는 장식이고, 계정 버튼은 클릭 동작이 바로 아래 기어 버튼과 완전히 동일한 중복이었다(`update_account_status()`도 호출처 없는 죽은 코드여서 함께 삭제)
```

- [ ] **Step 3: PRD에 UI 개선 항목을 추가한다**

`planning/youtube_content_manager_prd.md` 맨 끝에 로드맵 항목을 추가한다(직전 항목이 `### v1.8+`이므로 그 뒤):

```markdown
### v1.9+ — 밝은 테마 전환 & 트리 재설계

1. **기본 테마를 밝은 중간 톤으로**: 화면 전체가 너무 어둡고 창 배경·패널·카드가 서로 구분되지 않던 문제를 해결한다. 새 `mist` 팔레트를 기본값으로 하며, 계층 간 명도 차이를 눈에 보이는 수준으로 벌린다. 기존 어두운 테마 6종은 설정에서 계속 선택할 수 있다.
2. **칩·브레드크럼이 테마를 따르도록**: 태그 칩과 브레드크럼은 색이 코드에 고정돼 있어 어떤 테마를 골라도 어두운 색으로 남았다. 테마 색상에서 파생하도록 바꾼다.
3. **태그·카테고리 색상 고정**: 같은 태그가 앱을 켤 때마다 다른 색으로 표시되던 문제를 수정한다. 이제 이름이 같으면 항상 같은 색이다.
4. **카테고리 트리 외형 재설계**: 둥근 행 배경, 카테고리별 색상 점, 우측 정렬 개수 뱃지, 넉넉한 행 높이, 계층을 보여주는 들여쓰기 가이드선을 적용한다. 펼침·드래그&드롭·컨텍스트 메뉴 등 기존 동작은 그대로 유지된다.
5. **불필요한 아이콘 제거**: 사이드바 상단의 장식용 로고와, 설정 버튼과 기능이 겹치던 계정 아이콘을 없앤다.
```

- [ ] **Step 4: 커밋한다**

```bash
git add CLAUDE.md planning/youtube_content_manager_prd.md
git commit -m "docs: 밝은 테마·트리 재설계 규칙·요구사항 기록

- CLAUDE.md gui 파일 맵에 mist 기본값·_TreeRowDelegate·drawBranches 이유·
  chip_colors·tag_color(crc32) 기록
- main_window에서 로고·계정 버튼 제거 반영
- PRD에 v1.9+ 로드맵 추가"
```
