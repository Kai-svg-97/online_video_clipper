"""`docs/manual.md` → `docs/manual/index.html` — F1이 브라우저로 여는 설명서.

**설명서 원본은 하나다.** GitHub에서 읽히는 마크다운과 앱이 여는 HTML을 따로 쓰면
반드시 한쪽이 낡는다. 여기서 한쪽을 다른 쪽으로 만든다.

마크다운 라이브러리를 새로 들이지 않는다 — 설명서가 쓰는 문법(제목·문단·목록·표·
인용·수평선·이미지·링크·굵게·인라인 코드)만 다루면 충분하고, 그만큼은 의존성을
늘릴 값어치가 없다. 다루지 못하는 문법을 설명서에 쓰면 그대로 글자로 보이므로
`tests/unit/test_build_manual.py`가 렌더 결과를 지킨다.

사용:
    python scripts/build_manual.py
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
SRC = _ROOT / "docs" / "manual.md"
OUT = _ROOT / "docs" / "manual" / "index.html"

# 마크다운은 `docs/` 기준 경로를 쓰고(GitHub에서 읽힌다), HTML은 `docs/manual/`
# 안에 놓인다 — 이미지 경로를 그만큼 줄여 준다.
_IMG_PREFIX = re.compile(r"\]\(manual/images/")

_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_LINK = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")
_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def render_inline(text: str) -> str:
    """문단 안쪽 문법. **이스케이프를 먼저** 한다 — 순서가 바뀌면 우리가 만든
    태그까지 글자로 바뀐다."""
    out = html.escape(text, quote=False)
    out = _IMAGE.sub(
        lambda m: f'<img src="{html.escape(m.group(2), quote=True)}" '
                  f'alt="{html.escape(m.group(1), quote=True)}">',
        out,
    )
    out = _LINK.sub(
        lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>',
        out,
    )
    out = _INLINE_CODE.sub(lambda m: f"<code>{m.group(1)}</code>", out)
    out = _BOLD.sub(lambda m: f"<strong>{m.group(1)}</strong>", out)
    return out


def _slug(text: str) -> str:
    """제목 → 앵커. 목차 링크(`#라이브러리`)가 걸리도록 GitHub 방식에 맞춘다."""
    plain = re.sub(r"[`*]", "", text).strip().lower()
    plain = re.sub(r"[^\w가-힣\s-]", "", plain)
    return re.sub(r"\s+", "-", plain)


def _table(rows: list[str]) -> str:
    """`| a | b |` 묶음 → <table>. 두 번째 줄은 구분선이라 버린다."""
    def cells(line: str) -> list[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")]

    head = cells(rows[0])
    body = [cells(r) for r in rows[2:]]
    out = ["<table>", "<thead><tr>"]
    out += [f"<th>{render_inline(c)}</th>" for c in head]
    out += ["</tr></thead>", "<tbody>"]
    for row in body:
        out.append("<tr>" + "".join(f"<td>{render_inline(c)}</td>" for c in row) + "</tr>")
    out += ["</tbody>", "</table>"]
    return "\n".join(out)


def render(markdown: str) -> str:
    """설명서 마크다운을 본문 HTML로 바꾼다."""
    markdown = _IMG_PREFIX.sub("](images/", markdown)
    lines = markdown.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        if stripped.startswith("|"):            # 표
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            out.append(_table(block))
            continue

        if re.match(r"^-{3,}$", stripped):      # 수평선
            out.append("<hr>")
            i += 1
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            level = len(heading.group(1))
            text = heading.group(2)
            out.append(
                f'<h{level} id="{_slug(text)}">{render_inline(text)}</h{level}>'
            )
            i += 1
            continue

        if stripped.startswith("> "):           # 인용
            block = []
            while i < len(lines) and lines[i].strip().startswith("> "):
                block.append(lines[i].strip()[2:])
                i += 1
            out.append(f"<blockquote>{render_inline(' '.join(block))}</blockquote>")
            continue

        ordered = re.match(r"^\d+\.\s+(.*)$", stripped)
        if ordered or stripped.startswith("- "):
            tag = "ol" if ordered else "ul"
            items: list[str] = []
            while i < len(lines):
                s = lines[i].strip()
                m = re.match(r"^\d+\.\s+(.*)$", s) if ordered else None
                if m:
                    items.append(m.group(1))
                elif not ordered and s.startswith("- "):
                    items.append(s[2:])
                else:
                    break
                i += 1
            body = "".join(f"<li>{render_inline(it)}</li>" for it in items)
            out.append(f"<{tag}>{body}</{tag}>")
            continue

        # 문단 — 빈 줄까지 모은다. 줄바꿈 하나는 <br> 로 살린다(설명서에서
        # "증상 / 해결" 을 두 줄로 쓰는 곳이 있다).
        block = []
        while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith(
            ("#", "|", "- ", "> ")
        ):
            block.append(lines[i].strip())
            i += 1
        out.append("<p>" + "<br>".join(render_inline(b) for b in block) + "</p>")

    return "\n".join(out)


_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>YouTube Content Manager — 상세 설명서</title>
<style>
  :root {{
    --bg: #ffffff; --fg: #1f2328; --muted: #59636e; --border: #d1d9e0;
    --surface: #f6f8fa; --accent: #0969da;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #0d1117; --fg: #e6edf3; --muted: #9198a1; --border: #3d444d;
      --surface: #151b23; --accent: #4493f8;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--fg);
    font-family: "Segoe UI", "Malgun Gothic", system-ui, sans-serif;
    font-size: 16px; line-height: 1.7;
  }}
  main {{ max-width: 900px; margin: 0 auto; padding: 48px 16px 96px; }}
  h1 {{ font-size: 2em; border-bottom: 1px solid var(--border); padding-bottom: .3em; }}
  h2 {{ font-size: 1.5em; border-bottom: 1px solid var(--border);
       padding-bottom: .3em; margin-top: 2.2em; }}
  h3 {{ font-size: 1.2em; margin-top: 1.8em; }}
  hr {{ border: 0; border-top: 1px solid var(--border); margin: 2.5em 0; }}
  a {{ color: var(--accent); }}
  code {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 5px;
    padding: .15em .4em; font-size: .88em;
    font-family: "Cascadia Mono", Consolas, monospace;
  }}
  blockquote {{
    margin: 1em 0; padding: .6em 1em; color: var(--muted);
    border-left: 4px solid var(--border); background: var(--surface);
  }}
  table {{ border-collapse: collapse; width: 100%; margin: 1.2em 0; display: block;
          overflow-x: auto; }}
  th, td {{ border: 1px solid var(--border); padding: 8px 12px; text-align: left; }}
  th {{ background: var(--surface); }}
  tr:nth-child(2n) td {{ background: var(--surface); }}
  img {{ max-width: 100%; border: 1px solid var(--border); border-radius: 8px;
        margin: 1em 0; display: block; }}
  li {{ margin: .3em 0; }}
</style>
</head>
<body>
<main>
{body}
</main>
</body>
</html>
"""


def build() -> Path:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        _TEMPLATE.format(body=render(SRC.read_text(encoding="utf-8"))),
        encoding="utf-8",
    )
    return OUT


def main() -> int:
    if not SRC.exists():
        print(f"원본이 없습니다: {SRC}", file=sys.stderr)
        return 1
    out = build()
    print(f"만들었습니다: {out.relative_to(_ROOT)}  ({out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
