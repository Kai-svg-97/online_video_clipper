"""`_start_thumb_preload`가 지켜야 할 QThread 규칙의 소스 가드(성능 배치 7, C2).

CLAUDE.md "QThread Lifecycle Management":

* 끝난 워커를 `deleteLater`로 지우지 않는다 — 아직 들고 있는 쪽이 나중에 접근하면
  `RuntimeError: wrapped C/C++ object ... has been deleted`가 난다.
* 결과 슬롯은 **QObject의 바운드 메서드**로 연결한다 — 위젯을 캡처한 람다는 위젯이
  죽어도 연결이 남는다.

범위는 이 함수(중첩 함수 포함)로 좁힌다. 같은 파일의 다른 람다(메뉴 액션 등)는
수명이 같은 자식 위젯에 걸려 있어 규칙 위반이 아니다.
"""

from __future__ import annotations

import ast
from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parents[2]
    / "gui" / "panels" / "library" / "mixins" / "video_list.py"
)


def _violations(source: str, func_name: str) -> list[str]:
    tree = ast.parse(source)
    found: list[str] = []
    for fn in ast.walk(tree):
        if not (isinstance(fn, ast.FunctionDef) and fn.name == func_name):
            continue
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr == "deleteLater":
                found.append(f"{node.lineno}: deleteLater 호출")
            if node.func.attr == "connect" and any(
                isinstance(arg, ast.Lambda) for arg in node.args
            ):
                found.append(f"{node.lineno}: 람다를 connect에 연결")
    return found


class TestScannerSelfCheck:
    def test_deleteLater와_람다_연결을_찾는다(self):
        src = (
            "def _start_thumb_preload(self):\n"
            "    def done(x):\n"
            "        x.deleteLater()\n"
            "    loader.batch_ready.connect(lambda b: self.f(b))\n"
        )
        assert len(_violations(src, "_start_thumb_preload")) == 2

    def test_다른_함수의_람다는_세지_않는다(self):
        src = "def other(self):\n    act.triggered.connect(lambda: 1)\n"
        assert _violations(src, "_start_thumb_preload") == []


class TestStartThumbPreloadGuard:
    def test_함수가_존재한다(self):
        assert "def _start_thumb_preload" in SOURCE.read_text(encoding="utf-8")

    def test_deleteLater도_람다_연결도_없다(self):
        found = _violations(SOURCE.read_text(encoding="utf-8"), "_start_thumb_preload")
        assert found == [], "video_list.py:_start_thumb_preload 위반 — " + "; ".join(found)
