"""오래 사는 신호원(`ThemeManager` 싱글턴)에 위젯 캡처 람다를 연결하지 않는다.

## 규칙

수신자가 QObject의 **바운드 메서드**면 그 객체가 파괴될 때 Qt가 연결을 끊어 주지만,
위젯을 캡처한 **람다**는 그 보호를 받지 못한다. `ThemeManager.instance()`처럼 앱
수명 내내 사는 싱글턴에 람다로 연결하면 위젯이 죽은 뒤에도 연결이 남아, 다음
테마 변경에서 죽은 객체를 건드린다:

```
RuntimeError: wrapped C/C++ object of type _PlaylistTree has been deleted
```

`CLAUDE.md`가 워커 신호에 대해 요구하는 것과 같은 규칙이고, 신호원이 싱글턴이면
더 강하게 적용된다. 이 파일은 `gui/` 전역을 AST로 훑어 **새 위반을 막는다.**

## 이 누수는 이미 알려져 있었다

`tests/gui/test_theme_transition.py`가 싱글턴 대신 `ThemeManager()`를 새로 만들어
쓰는 이유를 문서에 이렇게 적어 두었다 — "여러 패널이 앱 수명 동안 살아있다고
가정하고 연결한 뒤 해제하지 않는 기존 코드… 그 신호를 실제로 emit하면 이미 죽은
다른 테스트의 위젯을 건드려" 실패한다. 전수 조사 결과 싱글턴 신호에 남은 람다
연결은 `LibraryPanel` 한 곳뿐이었고(나머지 20여 곳은 전부 바운드 메서드), 지금은
그것도 바운드 메서드로 고쳤다.

한때 이 수정을 적용하면 패널 파괴 시 프로세스가 죽어서 되돌린 적이 있다. 원인은
바운드 메서드가 아니라 **별개 결함**이었다 — 실행 중인 `QVariantAnimation`이 패널의
자식이어서 소멸자가 그것을 함께 지우며 죽었다. 그 결함을 고치자
(`gui/anim.py:track_animation`) 이 수정도 성립했다. 조사 기록은
`tests/gui/test_panel_teardown.py` 문서에 있다.

## 왜 여기서는 소스를 검사하나

**런타임 검증은 `tests/gui/test_panel_teardown.py`가 자식 프로세스에서 한다** —
패널을 실제로 파괴한 뒤 싱글턴 `theme_changed`를 emit해 죽은 위젯을 건드리지 않는지
본다. 그걸 이 파일에서 하지 않는 이유는 두 가지다:

* `ThemeManager.apply()`는 **실사용 `data/config.yaml`에 저장한다**(테스트가 사용자
  설정을 건드리면 안 된다는 규칙).
* 싱글턴의 `theme_changed`를 이 프로세스에서 emit하면 다른 테스트 파일이 만든 위젯까지
  전부 발화해, 실패가 이 테스트와 무관한 곳에서 튀어나온다.

이 파일이 맡는 것은 **규칙 자체**다 — "싱글턴 신호에 위젯 캡처 람다를 연결하지
않는다"는 소스 수준의 성질이므로, `tests/gui/test_vm_worker_contract.py`와 같은
방식으로 AST로 훑어 **새로 추가되는 코드까지** 막는다(런타임 테스트는 이미 만들어진
`LibraryPanel` 한 경로만 본다).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

GUI_DIR = Path(__file__).resolve().parents[2] / "gui"

# 예외 없음. 한때 `LibraryPanel`의 좌측 트리 스타일 연결이 여기 있었는데, 바운드
# 메서드로 바꾸면 패널 파괴 시 프로세스가 죽어서(실제 원인은 **다른 결함**이었다 —
# 실행 중 애니메이션이 패널의 자식이었다) 예외로 두었다. 그 결함을 고친 뒤 예외가
# 필요 없어졌다. 배경은 `tests/gui/test_panel_teardown.py`와
# `docs/architecture/design-decisions.md` 참고.
_KNOWN_EXCEPTIONS: set[tuple[str, str]] = set()


def _singleton_signal_lambda_connections(path: Path) -> list[tuple[int, str]]:
    """`<무엇>.instance().<신호>.connect(lambda ...)` 꼴을 찾는다.

    `.instance()`가 붙어 있으면 프로세스 전역 싱글턴이고, 따라서 신호원이 구독하는
    위젯보다 오래 산다 — 람다로 연결하면 위젯이 죽어도 연결이 남는다.
    """
    hits: list[tuple[int, str]] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return hits

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "connect"):
            continue
        if not any(isinstance(a, ast.Lambda) for a in node.args):
            continue
        # connect 앞이 `<...>.instance().<신호>` 인지 — 싱글턴 신호원 판정
        signal = func.value
        if not isinstance(signal, ast.Attribute):
            continue
        owner = signal.value
        if (
            isinstance(owner, ast.Call)
            and isinstance(owner.func, ast.Attribute)
            and owner.func.attr == "instance"
        ):
            hits.append((node.lineno, signal.attr))
    return hits


GUI_FILES = sorted(p for p in GUI_DIR.rglob("*.py") if "__pycache__" not in p.parts)


class TestNoLambdaOnSingletonSignals:
    def test_scanner_sees_the_gui_tree(self):
        """스캐너가 실제로 파일을 읽는지 — 0개면 아래 테스트가 공허하게 통과한다."""
        assert len(GUI_FILES) > 50, f"gui/ 파일을 {len(GUI_FILES)}개만 찾았다"

    @pytest.mark.parametrize(
        "path", GUI_FILES, ids=lambda p: p.relative_to(GUI_DIR).as_posix()
    )
    def test_no_widget_capturing_lambda(self, path: Path):
        rel = path.relative_to(GUI_DIR).as_posix()
        hits = [
            (line, sig)
            for line, sig in _singleton_signal_lambda_connections(path)
            if (rel, sig) not in _KNOWN_EXCEPTIONS
        ]
        assert not hits, (
            f"{rel}에서 싱글턴 신호에 람다를 연결했다: {hits} — 싱글턴은 이 위젯보다 "
            "오래 살고, 람다는 Qt의 자동 연결 해제 보호를 받지 못한다. 위젯이 파괴된 뒤 "
            "그 신호가 발화하면 죽은 객체를 건드려 터진다. 인자를 받아 버리는 바운드 "
            "메서드를 두고 그것을 연결할 것."
        )

    def test_scanner_detects_a_known_bad_pattern(self, tmp_path):
        """스캐너가 실제로 잡아내는지 — 통과만 하는 검사가 되지 않게 확인한다."""
        bad = tmp_path / "bad.py"
        bad.write_text(
            "from gui.themes.manager import ThemeManager\n"
            "class W:\n"
            "    def wire(self):\n"
            "        ThemeManager.instance().theme_changed.connect(lambda _: self.f())\n",
            encoding="utf-8",
        )
        assert _singleton_signal_lambda_connections(bad) == [(4, "theme_changed")]

    def test_scanner_allows_bound_methods(self, tmp_path):
        good = tmp_path / "good.py"
        good.write_text(
            "from gui.themes.manager import ThemeManager\n"
            "class W:\n"
            "    def wire(self):\n"
            "        ThemeManager.instance().theme_changed.connect(self._on_theme_changed)\n",
            encoding="utf-8",
        )
        assert _singleton_signal_lambda_connections(good) == []

    def test_known_exceptions_are_still_real(self):
        """예외 목록이 낡지 않았는지 — 고쳐졌으면 목록에서 지워야 한다.

        예외를 적어 두고 방치하면 "왜 여기 있나"를 아무도 모르게 된다. 해당 위반이
        실제로 사라졌다면 이 테스트가 알려 준다.
        """
        stale: list[tuple[str, str]] = []
        for rel, sig in sorted(_KNOWN_EXCEPTIONS):
            path = GUI_DIR / rel
            if not path.exists():
                stale.append((rel, sig))
                continue
            found = {s for _, s in _singleton_signal_lambda_connections(path)}
            if sig not in found:
                stale.append((rel, sig))
        assert not stale, f"예외 목록이 낡았다 — 이미 고쳐진 항목을 지울 것: {stale}"


class TestSidebarStyleStillWired:
    """수명 논의와 별개로, 테마가 바뀌면 좌측 트리 스타일이 실제로 갱신되는지."""

    def test_panel_subscribes_to_theme_changed(
        self, library_vm, clip_vm, download_vm, qtbot
    ):
        from gui.panels.library_panel import LibraryPanel
        from gui.themes.manager import ThemeManager

        manager = ThemeManager.instance()
        before = manager.receivers(manager.theme_changed)

        panel = LibraryPanel(vm=library_vm, clip_vm=clip_vm, download_vm=download_vm)
        qtbot.addWidget(panel)

        assert manager.receivers(manager.theme_changed) > before, (
            "패널을 만들었는데 theme_changed 구독자가 늘지 않았다 — "
            "테마를 바꿔도 좌측 트리 스타일이 갱신되지 않는다"
        )

    def test_restyle_runs_without_error(self, library_vm, clip_vm, download_vm, qtbot):
        """스타일 적용 자체가 성립하는지(토큰 참조 오타 등)."""
        from gui.panels.library_panel import LibraryPanel

        panel = LibraryPanel(vm=library_vm, clip_vm=clip_vm, download_vm=download_vm)
        qtbot.addWidget(panel)
        panel._apply_sidebar_tree_style()   # 예외가 나면 실패
