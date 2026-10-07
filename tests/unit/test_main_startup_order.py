"""`main()` 시작 순서 가드 — 창을 먼저 보이고 스플래시를 닫는다 (성능 배치 1, A3-a).

Qt 없이 AST 만 본다. `QSplashScreen.finish(window)` 로 되돌아가면 창이 그려지기
전에 스플래시가 사라져 빈 화면이 난다.
"""
from __future__ import annotations

import ast
from pathlib import Path

_MAIN = Path(__file__).resolve().parents[2] / "main.py"


def _main_body(source: str) -> list[ast.stmt]:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node.body
    raise AssertionError("main() 을 찾지 못했다")


def _calls_in_order(body: list[ast.stmt]) -> list[tuple[int, str]]:
    """`main` 본문 전체의 호출을 소스 순서로 (줄, 점 표기 이름) 로 돌려준다."""
    found: list[tuple[int, int, str]] = []
    for stmt in body:
        for node in ast.walk(stmt):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
                name = f"{f.value.id}.{f.attr}"
            elif isinstance(f, ast.Name):
                name = f.id
            else:
                continue
            found.append((node.lineno, node.col_offset, name))
    found.sort()
    return [(ln, name) for ln, _c, name in found]


def _first(calls: list[tuple[int, str]], name: str) -> int | None:
    for ln, n in calls:
        if n == name:
            return ln
    return None


class TestSplashOrder:
    def test_수집기가_공허하지_않다(self):
        calls = _calls_in_order(_main_body(_MAIN.read_text(encoding="utf-8")))
        assert _first(calls, "window.show") is not None
        assert _first(calls, "show_splash") is not None

    def test_창을_먼저_보이고_스플래시를_닫는다(self):
        calls = _calls_in_order(_main_body(_MAIN.read_text(encoding="utf-8")))
        show = _first(calls, "window.show")
        finish = _first(calls, "finish_splash")
        assert finish is not None, "finish_splash(...) 호출이 main() 에 없다"
        assert show < finish

    def test_QSplashScreen_finish가_남아_있지_않다(self):
        calls = _calls_in_order(_main_body(_MAIN.read_text(encoding="utf-8")))
        assert _first(calls, "splash.finish") is None

    def test_가드_자가_검사_순서가_뒤집힌_소스를_잡는다(self):
        bad = (
            "def main():\n"
            "    show_splash(app)\n"
            "    finish_splash(splash, window)\n"
            "    window.show()\n"
        )
        calls = _calls_in_order(_main_body(bad))
        assert _first(calls, "window.show") > _first(calls, "finish_splash")
