"""`gui/`의 한국어 표시 문자열은 `tr()`을 거친다 — 새로 감싸지 않은 것을 막는다.

영어 화면이 생긴 뒤에도 `tr()` 밖에 한국어 문자열이 579건 남아 있었다(2026-09 정리).
빠뜨려도 화면이 비지는 않고 한국어로 남기 때문에, 영어 화면을 실제로 띄워 보기
전에는 아무도 모른다. 그래서 AST로 훑어 **새 위반**을 막는다.

세지 않는 것: `tr(...)` 인자, 로그 호출(`logger.*`), docstring. `gui/text/`는 번역이
사는 곳이라 대상에서 뺀다(언어별 구간표처럼 한국어 *데이터*가 거기 있다).

번역하면 안 되는 문자열은 `_ALLOWED`에 **이유와 함께** 적는다 — 저장되는 이름,
한국어 텍스트를 처리하기 위한 값, 글꼴 이름, QSS 주석.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_GUI = _ROOT / "gui"
_HANGUL = re.compile(r"[가-힣]")
_SKIP_CALLS = {"tr", "debug", "info", "warning", "error", "exception", "critical"}

# (gui/ 기준 경로, 문자열에 들어 있는 조각) — 이유
_ALLOWED: set[tuple[str, str]] = {
    # 로그에만 쓰이는 기본 인자(화면에 나가지 않는다).
    ("view_models/base.py", "백그라운드 작업 실패"),
    # 글꼴 이름.
    ("widgets/lyrics_overlay.py", "맑은 고딕"),
    # QSS 문자열 안의 주석.
    ("themes/stylesheet.py", "/* ====== 기반"),
    ("widgets/player/controls.py", "/* 슬라이더"),
}


def _docstring_ids(tree: ast.AST) -> set[int]:
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                out.add(id(body[0].value))
    return out


def _skipped_ids(tree: ast.AST) -> set[int]:
    out = _docstring_ids(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
        if name in _SKIP_CALLS:
            out.update(id(sub) for sub in ast.walk(node))
    return out


def _violations() -> list[str]:
    found: list[str] = []
    for path in sorted(_GUI.rglob("*.py")):
        rel = path.relative_to(_GUI).as_posix()
        if rel.startswith("text/") or "__pycache__" in rel:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = _skipped_ids(tree)
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            if id(node) in skip or not _HANGUL.search(node.value):
                continue
            if any(rel == f and frag in node.value for f, frag in _ALLOWED):
                continue
            found.append(f"gui/{rel}:{node.lineno}: {node.value[:50]!r}")
    return found


def test_tr_밖의_한국어_표시_문자열이_없다():
    found = _violations()
    assert not found, (
        "tr()로 감싸지 않은 한국어 문자열이 있다. 화면에 나가는 말이면 tr(\"…\")로 감싸고 "
        "`python scripts/extract_catalog.py`로 en.json에 번역을 채운다. 번역하면 안 되는 "
        "값이면 이 파일의 _ALLOWED에 이유와 함께 적는다.\n" + "\n".join(found)
    )


def test_허용_목록이_낡지_않았다():
    """고쳐진 예외가 목록에 남아 있으면 같은 자리의 새 위반을 가린다."""
    live: set[tuple[str, str]] = set()
    for path in sorted(_GUI.rglob("*.py")):
        rel = path.relative_to(_GUI).as_posix()
        if rel.startswith("text/") or "__pycache__" in rel:
            continue
        text = path.read_text(encoding="utf-8")
        live.update((f, frag) for f, frag in _ALLOWED if f == rel and frag in text)
    assert _ALLOWED - live == set(), sorted(_ALLOWED - live)
