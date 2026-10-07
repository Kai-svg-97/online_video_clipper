"""`main()` 시작 순서 가드 — 창을 먼저 보이고 스플래시를 닫는다 (성능 배치 1, A3-a).

Qt 없이 AST 만 본다. `QSplashScreen.finish(window)` 로 되돌아가면 창이 그려지기
전에 스플래시가 사라져 빈 화면이 난다.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_MAIN = _ROOT / "main.py"


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


# ---------------------------------------------------------------------------
# 배치 2 (B3-a) — 스플래시 전에 실행되는 임포트는 가벼워야 한다 (조립 루트 규칙 1)
# ---------------------------------------------------------------------------

# 스플래시 전에 끌려오면 안 되는 모듈 접두. 조립 본체(handlers·services·...)와
# 그것이 끌고 오는 무거운 계층이다.
_FORBIDDEN_BEFORE_SPLASH = (
    "bootstrap.handlers",
    "bootstrap.services",
    "bootstrap.persistence",
    "bootstrap.view_models",
    "bootstrap.context",
    "requests",
    "infrastructure",
    "gui",
    "application",
)


def _imports_before_splash(source: str) -> list[str]:
    """`main()` 에서 첫 `show_splash(` 호출문 **앞**에 있는 임포트의 모듈 이름들."""
    body = _main_body(source)
    calls = _calls_in_order(body)
    splash_line = _first(calls, "show_splash")
    if splash_line is None:
        raise AssertionError("main() 에 show_splash 호출이 없다")
    mods: list[str] = []
    for stmt in body:
        for node in ast.walk(stmt):
            if getattr(node, "lineno", splash_line) >= splash_line:
                continue
            if isinstance(node, ast.Import):
                mods.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                mods.append(node.module)
    return mods


def _hits(loaded: list[str]) -> list[str]:
    return sorted(
        m for m in loaded
        if any(m == p or m.startswith(p + ".") for p in _FORBIDDEN_BEFORE_SPLASH)
    )


_SCRIPT = """
import json, sys
sys.path.insert(0, '.')
mods = json.loads(sys.argv[1])
for m in mods:
    __import__(m)
before = sorted(sys.modules)
import bootstrap
from bootstrap import build_app_graph
after = sorted(sys.modules)
names = [n for n in bootstrap.__all__]
resolved = [getattr(bootstrap, n) is not None for n in names]
print(json.dumps({"before": before, "after": after, "all_ok": all(resolved), "n": len(names)}))
"""


@pytest.fixture(scope="module")
def startup_probe(tmp_path_factory) -> dict:
    mods = _imports_before_splash(_MAIN.read_text(encoding="utf-8"))
    assert mods, "스플래시 전 임포트가 하나도 수집되지 않았다"
    data_dir = tmp_path_factory.mktemp("ovc_data")
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT, json.dumps(mods)],
        cwd=_ROOT,
        env={
            **os.environ, "OVC_DATA_DIR": str(data_dir),
            "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


class TestImportsBeforeSplash:
    def test_스플래시_전에_무거운_모듈이_로드되지_않는다(self, startup_probe):
        hit = _hits(startup_probe["before"])
        assert not hit, f"스플래시 전에 로드된 무거운 모듈: {hit}"

    def test_조립_본체는_나중에_실제로_로드된다(self, startup_probe):
        assert "bootstrap.handlers" not in startup_probe["before"]
        assert "bootstrap.handlers" in startup_probe["after"]

    def test_공개_이름이_모두_해석된다(self, startup_probe):
        assert startup_probe["n"] >= 4
        assert startup_probe["all_ok"]

    def test_수집기가_스플래시_전_임포트를_찾는다(self):
        mods = _imports_before_splash(_MAIN.read_text(encoding="utf-8"))
        assert any(m == "bootstrap.runtime" or m.startswith("bootstrap") for m in mods)

    def test_가드_자가_검사_가짜_main의_requests를_잡는다(self, tmp_path):
        fake = tmp_path / "main.py"
        fake.write_text(
            "def main():\n"
            "    import requests\n"
            "    from bootstrap.handlers import build_handlers\n"
            "    show_splash(app)\n"
            "    import json\n",
            encoding="utf-8",
        )
        mods = _imports_before_splash(fake.read_text(encoding="utf-8"))
        assert mods == ["requests", "bootstrap.handlers"]
        assert _hits(mods) == ["bootstrap.handlers", "requests"]
