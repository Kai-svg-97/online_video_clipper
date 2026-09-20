"""`gui/text/` 의 규약과 `render()` 의 안전성.

두 가지를 지킨다.

1. **`gui/text/` 는 PyQt6 를 임포트하지 않는다.** 규약은 문서만으로는 지켜지지 않아
   실행 가능한 형태로 고정한다. 이 규약이 있어야 헤드리스 단위 테스트가 되고,
   나중에 `presentation/` 계층으로 승격할 여지가 남는다.
2. **`render()` 는 어떤 경우에도 예외를 내지 않는다.** 업데이트 배지가 이 결과를
   `paintEvent` 경로에서 쓰는데, 거기서 난 파이썬 예외는 PyQt 가 **프로세스 종료**로
   처리한다(0xC0000409 — 로그도 메시지도 남지 않는다).
"""

from __future__ import annotations

import ast
from pathlib import Path

from domain.shared.messages import Message
from gui.text import _
from gui.text import messages as msg_mod
from gui.text.messages import render, render_all

_PKG = Path(__file__).resolve().parents[3] / "gui" / "text"


class TestPurity:
    def test_PyQt6를_임포트하지_않는다(self):
        offenders = []
        for path in _PKG.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                if any(n.split(".")[0] == "PyQt6" for n in names):
                    offenders.append(f"{path.name}:{node.lineno}")
        assert not offenders, f"gui/text/ 는 순수해야 한다: {offenders}"

    def test_도메인이_gui_text를_임포트하지_않는다(self):
        """의존 방향이 뒤집히면 도메인이 화면을 알게 된다."""
        root = _PKG.parents[1]
        offenders = []
        for layer in ("domain", "application"):
            for path in (root / layer).rglob("*.py"):
                if "__pycache__" in str(path):
                    continue
                src = path.read_text(encoding="utf-8")
                if "gui.text" in src or "from gui " in src:
                    offenders.append(str(path.relative_to(root)))
        assert not offenders, f"도메인/애플리케이션이 gui 를 임포트한다: {offenders}"


class TestTranslationHook:
    def test_지금은_원문_그대로다(self):
        """1단계의 성공 기준은 '화면이 지금과 똑같다'이다."""
        assert _("설정") == "설정"


class TestRenderNeverRaises:
    def test_None은_빈_문자열(self):
        assert render(None) == ""

    def test_모르는_키는_키를_돌려준다(self, caplog):
        """죽는 것보다 키가 보이는 편이 낫다 — 그리고 로그로 남는다."""
        assert render(Message.of("없는.키")) == "없는.키"
        assert "템플릿이 없다" in caplog.text

    def test_파라미터가_모자라도_터지지_않는다(self, monkeypatch, caplog):
        monkeypatch.setitem(msg_mod._TEMPLATES, "t.need", "{a} 와 {b}")
        out = render(Message.of("t.need", a=1))     # b 가 없다
        assert out == "{a} 와 {b}"                   # 채우지 못한 원문
        assert "채우지 못했다" in caplog.text

    def test_채워지면_채워진다(self, monkeypatch):
        monkeypatch.setitem(msg_mod._TEMPLATES, "t.ok", "새 영상 {total}개")
        assert render(Message.of("t.ok", total=3)) == "새 영상 3개"


class TestRenderAll:
    def test_가운뎃점으로_잇는다(self, monkeypatch):
        monkeypatch.setitem(msg_mod._TEMPLATES, "t.a", "가")
        monkeypatch.setitem(msg_mod._TEMPLATES, "t.b", "나")
        assert render_all([Message.of("t.a"), Message.of("t.b")]) == "가 · 나"

    def test_비어_있으면_빈_문자열(self):
        assert render_all([]) == ""


class TestTemplateCoverage:
    """도메인이 쓰는 키에 템플릿이 다 있는지 — 없으면 화면에 키가 그대로 뜬다."""

    def _keys_used_in_domain(self) -> set[str]:
        root = _PKG.parents[1]
        used: set[str] = set()
        for path in (root / "domain").rglob("*.py"):
            if "__pycache__" in str(path):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "of"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "Message"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    used.add(node.args[0].value)
        return used

    def test_도메인이_쓰는_키에_템플릿이_있다(self):
        missing = self._keys_used_in_domain() - set(msg_mod._TEMPLATES)
        assert not missing, f"템플릿 누락: {sorted(missing)}"
