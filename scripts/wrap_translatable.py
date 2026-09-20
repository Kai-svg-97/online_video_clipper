"""화면에 나가는 문자열을 `tr()` 로 감싼다 — **표시 API의 인자만**.

## 왜 "모든 한글 문자열"이 아닌가

문자열이 화면에 보인다고 전부 번역 대상은 아니다. dict 키·비교 대상·저장되는
이름으로 쓰이는 것도 있고, 그런 것을 감싸면 **언어를 바꾼 순간 조용히 어긋난다**
(1단계에서 실제로 그런 자리를 셋 찾아 고쳤다).

그래서 이 도구는 **`setText(...)`·`QLabel(...)` 처럼 "이건 화면에 그린다"가 분명한
호출의 인자**만 감싼다. 나머지는 사람이 판단한다.

## 감싸지 않는 것

- `logger.*(...)` — 로그는 번역하지 않는다(문제를 찾는 사람이 읽는다)
- `setStyleSheet`·`setObjectName` — 기계가 읽는 값이다
- f-string — 어순이 언어마다 달라 `tr()` 로 감싸는 것으로는 부족하다. 손으로
  `Message` 나 이름 있는 자리표시자로 바꿔야 한다
- 이미 `tr()` 로 감싼 것

사용:
    python scripts/wrap_translatable.py --dry-run     # 무엇이 바뀌는지만 본다
    python scripts/wrap_translatable.py
"""

from __future__ import annotations

import argparse
import ast
import io
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

_HANGUL = re.compile(r"[가-힣]")

# "이 인자는 화면에 그린다"가 분명한 호출들.
_DISPLAY_METHODS = {
    "setText", "setToolTip", "setPlaceholderText", "setWindowTitle",
    "setStatusTip", "setWhatsThis", "addItem", "addAction", "addTab",
    "addMenu", "showMessage", "setTitle", "setLabelText", "setInformativeText",
    "set_status", "show_toast", "setPrefix", "setSuffix", "setHtml",
}
_DISPLAY_CTORS = {
    "QLabel", "QPushButton", "QCheckBox", "QRadioButton", "QAction",
    "QGroupBox", "QToolButton", "QListWidgetItem", "QTreeWidgetItem",
}
# 첫 인자가 부모 위젯인 것들 — 두 번째부터가 문구다.
_MSGBOX = {"information", "warning", "critical", "question", "about"}


def _skip_ids(tree: ast.AST) -> set[int]:
    """감싸면 안 되는 문자열 노드 — 로그·스타일시트·이미 감싼 것."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        if name in {"debug", "info", "warning", "error", "exception", "critical", "log"} \
           or name in {"setStyleSheet", "setObjectName", "setProperty"} or name == "tr":
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant):
                    out.add(id(sub))
    return out


def _targets(tree: ast.AST) -> list[ast.Constant]:
    """감쌀 문자열 노드들."""
    skip = _skip_ids(tree)
    found: list[ast.Constant] = []

    def take(arg) -> None:
        if (
            isinstance(arg, ast.Constant)
            and isinstance(arg.value, str)
            and id(arg) not in skip
            and _HANGUL.search(arg.value)
        ):
            found.append(arg)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute):
            name = node.func.attr
            if name in _DISPLAY_METHODS:
                for arg in node.args:
                    take(arg)
            elif name in _MSGBOX:
                for arg in node.args[1:]:   # 첫 인자는 부모 위젯
                    take(arg)
        elif isinstance(node.func, ast.Name) and node.func.id in _DISPLAY_CTORS:
            for arg in node.args:
                take(arg)
    return found


def _rewrite(src: str, nodes: list[ast.Constant]) -> str:
    """뒤에서부터 고친다 — 앞에서 고치면 뒤 노드의 열 위치가 틀어진다.

    **`col_offset` 은 문자가 아니라 UTF-8 바이트 오프셋이다.** 한글이 섞인 줄에서
    문자 인덱스로 자르면 위치가 밀려 `QAction(_("창 열기", menu))` 처럼 괄호가 엉뚱한
    곳에 붙는다(실제로 11개 파일이 그렇게 깨졌다). 그래서 줄을 바이트로 다룬다.
    """
    lines = src.split("\n")
    spans = sorted(
        ((n.lineno, n.col_offset, n.end_lineno, n.end_col_offset) for n in nodes),
        reverse=True,
    )
    for lineno, col, end_lineno, end_col in spans:
        if lineno != end_lineno:
            continue                     # 여러 줄 문자열은 건드리지 않는다
        raw = lines[lineno - 1].encode("utf-8")
        lines[lineno - 1] = (
            raw[:col] + b"tr(" + raw[col:end_col] + b")" + raw[end_col:]
        ).decode("utf-8")
    return "\n".join(lines)


def _ensure_import(src: str, tree: ast.AST) -> str:
    """`tr` 임포트를 **맨 위 임포트 묶음 바로 뒤에** 넣는다.

    줄을 정규식으로 훑으면 여러 줄 임포트(`from x import (`) 안으로 들어가 파일이
    깨진다(실제로 16개 파일이 그랬다). AST 로 최상위 임포트의 **끝 줄**을 본다.

    파일 중간에 임포트가 또 있는 모듈이 몇 개 있는데(이미 E402 린트 기준선이다),
    거기에 한 줄을 더하면 기준선이 하나 늘어난다 — 그래서 **첫 코드 문장 앞까지만**
    본다.
    """
    if re.search(r"^from gui\.text import .*tr", src, re.M):
        return src
    last_end = 0
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            last_end = node.end_lineno or node.lineno
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue                     # 모듈 독스트링
        elif last_end:
            break                        # 코드가 시작됐다
    lines = src.split("\n")
    lines.insert(last_end, "from gui.text import tr")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--path", default="gui")
    args = ap.parse_args()

    total_files = total_strings = 0
    for path in sorted(Path(args.path).rglob("*.py")):
        if "__pycache__" in str(path) or "/text/" in path.as_posix():
            continue
        src = io.open(path, encoding="utf-8").read()
        try:
            nodes = _targets(ast.parse(src))
        except SyntaxError:
            print(f"  건너뜀(문법 오류): {path}")
            continue
        nodes = [n for n in nodes if n.lineno == n.end_lineno]
        if not nodes:
            continue
        total_files += 1
        total_strings += len(nodes)
        print(f"  {len(nodes):4}  {path}")
        if args.dry_run:
            continue
        io.open(path, "w", encoding="utf-8", newline="\n").write(
            _ensure_import(_rewrite(src, nodes), ast.parse(src))
        )
    verb = "감쌀 수 있다" if args.dry_run else "감쌌다"
    print(f"\n파일 {total_files}개 · 문자열 {total_strings}개를 {verb}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
