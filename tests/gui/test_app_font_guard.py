"""`QFont("")`(빈 패밀리)를 `gui/` 어디에도 쓰지 않는다 — AST 가드.

빈 패밀리 글꼴은 Windows에서 `MS Sans Serif`(비트맵 글꼴)로 풀려, 델리게이트가
글자를 그릴 때마다 느린 경로를 탄다. 앱 글꼴에서 파생하는 `gui.fonts.app_font`를
쓴다. 모듈 수준에서 `app_font(...)`를 부르면 앱·언어가 정해지기 전에 평가되므로
그것도 막는다(캐시 금지).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

GUI_DIR = Path(__file__).resolve().parents[2] / "gui"
GUI_FILES = sorted(p for p in GUI_DIR.rglob("*.py") if "__pycache__" not in p.parts)


def _is_qfont_call(call: ast.Call) -> bool:
    f = call.func
    return (isinstance(f, ast.Name) and f.id == "QFont") or (
        isinstance(f, ast.Attribute) and f.attr == "QFont"
    )


def _is_empty_const(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value == ""


def _empty_family_fonts(path: Path) -> list[int]:
    """`QFont("")`, `QFont("", n)`, `QFont(family="")`의 줄 번호."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    hits: list[int] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _is_qfont_call(node)):
            continue
        if node.args and _is_empty_const(node.args[0]):
            hits.append(node.lineno)
        elif any(k.arg == "family" and _is_empty_const(k.value) for k in node.keywords):
            hits.append(node.lineno)
    return sorted(hits)


def _contains_app_font_call(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            f = sub.func
            if (isinstance(f, ast.Name) and f.id == "app_font") or (
                isinstance(f, ast.Attribute) and f.attr == "app_font"
            ):
                return True
    return False


def _module_level_app_font(path: Path) -> list[int]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    hits: list[int] = []
    for stmt in tree.body:
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)) and stmt.value is not None:
            if _contains_app_font_call(stmt.value):
                hits.append(stmt.lineno)
    return hits


def _ids(p: Path) -> str:
    return p.relative_to(GUI_DIR).as_posix()


class TestScannerItself:
    def test_scanner_sees_the_gui_tree(self):
        assert len(GUI_FILES) > 50, f"gui/ 파일을 {len(GUI_FILES)}개만 찾았다"

    def test_scanner_detects_known_bad(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text(
            "from PyQt6.QtGui import QFont\n"
            "from PyQt6 import QtGui\n"
            "a = QFont('', 8)\n"
            "b = QtGui.QFont('')\n"
            "c = QFont(family='')\n",
            encoding="utf-8",
        )
        assert _empty_family_fonts(f) == [3, 4, 5]

    def test_scanner_allows_named_and_default(self, tmp_path):
        f = tmp_path / "ok.py"
        f.write_text(
            "from PyQt6.QtGui import QFont\n"
            "a = QFont()\n"
            "b = QFont('Segoe UI', 9)\n"
            "c = QFont(a)\n",
            encoding="utf-8",
        )
        assert _empty_family_fonts(f) == []

    def test_module_level_scanner_detects_constant(self, tmp_path):
        f = tmp_path / "const.py"
        f.write_text(
            "from gui.fonts import app_font\n"
            "_F8 = app_font(8)\n"
            "def g():\n"
            "    return app_font(9)\n",
            encoding="utf-8",
        )
        assert _module_level_app_font(f) == [2]


class TestNoEmptyFamilyFont:
    @pytest.mark.parametrize("path", GUI_FILES, ids=_ids)
    def test_no_empty_family_font(self, path):
        hits = _empty_family_fonts(path)
        assert not hits, (
            f'{_ids(path)}: QFont("") {len(hits)}곳(줄 {hits}) — '
            "gui.fonts.app_font(...)를 쓴다"
        )

    def test_helper_module_exists_outside_gui_text(self):
        assert (GUI_DIR / "fonts.py").is_file(), "gui/fonts.py가 없다"
        assert not (GUI_DIR / "text" / "fonts.py").exists()


class TestNoModuleLevelAppFont:
    @pytest.mark.parametrize("path", GUI_FILES, ids=_ids)
    def test_no_module_level_app_font(self, path):
        hits = _module_level_app_font(path)
        assert not hits, (
            f"{_ids(path)}: 모듈 수준 app_font() 대입(줄 {hits}) — "
            "함수 안에서 호출한다(앱 글꼴·언어 확정 전 평가 방지)"
        )
