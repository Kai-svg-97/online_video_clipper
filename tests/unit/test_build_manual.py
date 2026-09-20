"""설명서 마크다운 → HTML 변환.

**왜 지키는가**: 이 렌더러는 설명서가 실제로 쓰는 문법만 다룬다. 다루지 못하는
문법을 설명서에 쓰면 조용히 **글자 그대로** 나온다("| 키 | 동작 |" 이 표가 아니라
문장으로 보이는 식). 그래서 문법별로 결과를 고정하고, 마지막에 실제 설명서를
렌더해 남은 마크다운이 없는지 훑는다.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "build_manual", _ROOT / "scripts" / "build_manual.py"
)
build_manual = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(build_manual)

render = build_manual.render
render_inline = build_manual.render_inline


class TestInline:
    def test_굵게(self):
        assert render_inline("**중요**") == "<strong>중요</strong>"

    def test_인라인_코드(self):
        assert render_inline("`F1` 키") == "<code>F1</code> 키"

    def test_링크(self):
        assert render_inline("[문서](a.md)") == '<a href="a.md">문서</a>'

    def test_이미지는_링크로_보지_않는다(self):
        out = render_inline("![설명](x.png)")
        assert out == '<img src="x.png" alt="설명">'
        assert "<a " not in out

    def test_html_특수문자를_이스케이프한다(self):
        """설명서에 `<`가 들어가도 태그로 해석되면 안 된다."""
        assert "&lt;script&gt;" in render_inline("<script>")


class TestBlocks:
    def test_제목에_앵커가_붙는다(self):
        """목차 링크(`#라이브러리`)가 걸리려면 id가 있어야 한다."""
        out = render("## 라이브러리")
        assert out == '<h2 id="라이브러리">라이브러리</h2>'

    def test_한글_제목의_공백은_하이픈이_된다(self):
        assert 'id="처음-시작하기"' in render("## 처음 시작하기")

    def test_표(self):
        out = render("| 키 | 동작 |\n| --- | --- |\n| `F1` | 도움말 |")
        assert "<table>" in out
        assert "<th>키</th>" in out
        assert "<td><code>F1</code></td>" in out
        assert "---" not in out, "구분선 줄이 칸으로 새어 나왔다"

    def test_순서없는_목록(self):
        out = render("- 하나\n- 둘")
        assert out == "<ul><li>하나</li><li>둘</li></ul>"

    def test_번호_목록(self):
        out = render("1. 하나\n2. 둘")
        assert out == "<ol><li>하나</li><li>둘</li></ol>"

    def test_인용(self):
        assert render("> 참고") == "<blockquote>참고</blockquote>"

    def test_수평선(self):
        assert render("---") == "<hr>"

    def test_문단의_줄바꿈은_유지된다(self):
        """'증상 / 해결'을 두 줄로 쓰는 곳이 있어 합쳐지면 읽기 어려워진다."""
        assert render("증상입니다\n해결입니다") == "<p>증상입니다<br>해결입니다</p>"


class TestImagePaths:
    def test_이미지_경로를_html_위치에_맞춰_줄인다(self):
        """마크다운은 docs/ 기준, HTML은 docs/manual/ 안에 놓인다."""
        out = render("![x](manual/images/library.png)")
        assert 'src="images/library.png"' in out


class TestRealManual:
    """실제 설명서를 렌더해 렌더되지 않고 남은 마크다운이 없는지 본다."""

    @pytest.fixture(scope="class")
    def rendered(self):
        src = _ROOT / "docs" / "manual.md"
        if not src.exists():
            pytest.skip("docs/manual.md 없음")
        return render(src.read_text(encoding="utf-8"))

    def test_표와_제목과_이미지가_모두_변환됐다(self, rendered):
        assert rendered.count("<table>") >= 5
        assert rendered.count("<h2") >= 8
        assert rendered.count("<img") >= 5

    def test_변환되지_않은_줄이_없다(self, rendered):
        leftovers = [
            line for line in rendered.splitlines()
            if re.match(r"^\s*(\||#{1,6}\s|-\s|>\s|\d+\.\s)", line)
        ]
        assert not leftovers, f"마크다운이 글자로 남았다: {leftovers[:3]}"

    def test_목차_링크가_실제_앵커를_가리킨다(self, rendered):
        anchors = set(re.findall(r'<h\d id="([^"]+)"', rendered))
        links = set(re.findall(r'<a href="#([^"]+)"', rendered))
        assert links, "목차 링크를 찾지 못했다"
        assert links <= anchors, f"가리키는 곳이 없는 링크: {links - anchors}"
