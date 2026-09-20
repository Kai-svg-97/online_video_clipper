"""`tr(...)` 로 감싼 원문을 모아 번역 카탈로그 뼈대를 만든다.

이미 번역해 둔 값은 **지우지 않는다** — 새로 생긴 원문만 빈 칸으로 더하고, 코드에서
사라진 원문은 빼낸다. 그래서 이 도구를 여러 번 돌려도 작업이 날아가지 않는다.

`gui/text/messages.py` 의 `_TEMPLATES` 값(도메인 `Message` 가 쓰는 문장)도 함께
모은다 — 그것도 화면에 나가는 말이고 `tr()` 을 거친다.

사용:
    python scripts/extract_catalog.py            # en.json 갱신
    python scripts/extract_catalog.py --report   # 무엇이 안 채워졌는지만 본다
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


def _tr_literals(root: Path) -> set[str]:
    """`tr("…")` 의 첫 인자가 문자열 리터럴인 것들."""
    out: set[str] = set()
    for path in root.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "tr"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                out.add(node.args[0].value)
    return out


def _message_templates() -> set[str]:
    from gui.text.messages import _TEMPLATES  # noqa: PLC0415

    return set(_TEMPLATES.values())


def collect() -> set[str]:
    return _tr_literals(_ROOT / "gui") | _message_templates()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="en")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    sources = collect()
    path = _ROOT / "gui" / "text" / "locales" / f"{args.lang}.json"
    existing: dict[str, str] = {}
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))

    kept = {k: v for k, v in existing.items() if k in sources}
    added = sorted(sources - set(kept))
    dropped = sorted(set(existing) - sources)
    merged = dict(kept)
    for key in added:
        merged.setdefault(key, "")

    done = sum(1 for v in merged.values() if v.strip())
    print(f"원문 {len(sources)}개 · 번역 완료 {done}개 ({done * 100 // max(1, len(sources))}%)")
    if added:
        print(f"  새로 생김 {len(added)}개")
    if dropped:
        print(f"  코드에서 사라져 뺌 {len(dropped)}개")
    if args.report:
        todo = [k for k, v in merged.items() if not v.strip()]
        for key in sorted(todo)[:40]:
            print(f"    - {key}")
        if len(todo) > 40:
            print(f"    … 외 {len(todo) - 40}개")
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    # 원문 기준 정렬 — diff 가 안정적이어야 리뷰가 된다.
    ordered = {k: merged[k] for k in sorted(merged)}
    io.open(path, "w", encoding="utf-8", newline="\n").write(
        json.dumps(ordered, ensure_ascii=False, indent=2) + "\n"
    )
    print(f"  → {path.relative_to(_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
