"""도메인에 화면 문구가 다시 들어오는 것을 막는다.

다국어화 1단계로 `domain/` 의 한국어 표시 문자열을 전부 걷어냈다. 이 시험이 없으면
다음에 기능을 더하는 사람이 자연스럽게 `return "하루 종일 받습니다"` 를 쓰고, 그
문장은 **번역할 방법이 없는 채로** 화면까지 흘러간다.

## 주석과 독스트링은 보지 않는다

이 프로젝트는 **주석·독스트링을 한국어로 쓰는 것이 규약**이고, 거기 담긴 설계 근거는
자산이다. "한글 제거"로 오해해 그것까지 밀어버리는 일을 막기 위해, 이 시험은 AST의
문자열 상수만 훑고 독스트링은 명시적으로 제외한다.

## 허용 목록 — 화면 문구가 아니라 언어 데이터

불용어·잡음어 같은 것은 한국어 텍스트를 처리하기 위한 **데이터**다. 번역 대상이
아니고, 지우면 검색·앨범 매칭이 조용히 망가진다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_HANGUL = re.compile(r"[가-힣]")

# 화면 문구가 아니라 **언어 데이터**다 — 도메인에 있는 것이 맞다.
_ALLOWED: dict[str, set[str]] = {
    # 한국어 텍스트를 **처리하기 위한** 데이터·정규식. 지우면 검색·앨범 매칭이
    # 조용히 망가진다.
    "domain/library/recommendation.py": {"_STOPWORDS", "_TOKEN_SPLIT"},
    "domain/song/album.py": {
        "_NOISE_WORDS", "_REJECT_KEYWORDS", "_PLACEHOLDER_VALUES",
        "_NON_WORD_RE", "NO_ALBUM_TITLE",
    },
    "domain/library/repositories.py": {"MUSIC_ROOT_CATEGORY_NAMES"},
    "domain/library/duplicates.py": set(),
    "domain/song/aggregates.py": set(),     # 개발자용 예외 메시지
    # 디스크의 **실제 폴더 이름**이다. 번역하면 이미 만들어진 폴더를 잃는다.
    "domain/library/watch_folder.py": {"DONE_DIR_NAME"},
}


def _docstring_ids(tree: ast.AST) -> set[int]:
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                out.add(id(body[0].value))
    return out


def _enclosing_names(tree: ast.AST) -> dict[int, str]:
    """문자열 노드 → 그것이 담긴 최상위 이름(허용 목록 판정용)."""
    out: dict[int, str] = {}
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        for name in names:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    out[id(sub)] = name
    return out


def _offenders(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = _docstring_ids(tree)
    owners = _enclosing_names(tree)
    rel = path.relative_to(_ROOT).as_posix()
    allowed = _ALLOWED.get(rel)
    found: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in docs or not _HANGUL.search(node.value):
            continue
        if allowed is not None and owners.get(id(node), "") in allowed:
            continue
        if allowed == set():          # 파일 전체를 허용한 경우
            continue
        found.append(f"{rel}:{node.lineno}  {node.value[:40]!r}")
    return found


_DOMAIN_FILES = sorted(
    p for p in (_ROOT / "domain").rglob("*.py") if "__pycache__" not in str(p)
)


@pytest.mark.parametrize("path", _DOMAIN_FILES, ids=lambda p: p.stem)
def test_도메인에_화면_문구가_없다(path: Path):
    offenders = _offenders(path)
    assert not offenders, (
        "도메인에 한국어 표시 문자열이 있다 — `gui/text/` 로 옮기거나 "
        f"Message 를 돌려주게 하라:\n  " + "\n  ".join(offenders)
    )


def test_허용_목록이_낡지_않았다():
    """허용 목록에 적힌 파일이 사라졌는데 항목만 남는 것을 막는다."""
    missing = [rel for rel in _ALLOWED if not (_ROOT / rel).exists()]
    assert not missing, f"허용 목록에 없는 파일이 적혀 있다: {missing}"
