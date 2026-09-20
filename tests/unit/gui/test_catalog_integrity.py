"""번역 카탈로그가 원문과 **같은 약속**을 지키는가.

번역문이 어색한 것은 사람이 고치면 되지만, 자리표시자가 어긋난 것은 다르다 —
`{version}` 을 빠뜨리면 그 자리에 아무것도 안 나오고, 이름을 틀리면
`render()` 가 채우지 못해 원문이 그대로 나온다. 둘 다 **실행해 봐야 보이는** 고장이라
여기서 막는다.
"""

from __future__ import annotations

import json
import re

import pytest

from gui.text.catalog import AVAILABLE_LANGUAGES, SOURCE_LANGUAGE, locale_path

# `{name}` · `{start:02d}` 둘 다 잡되 `{{` 이스케이프는 제외한다.
_FIELD = re.compile(r"(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)(?::[^}]*)?\}")

_TRANSLATED = [code for code, _n in AVAILABLE_LANGUAGES if code != SOURCE_LANGUAGE]


def _catalog(code: str) -> dict[str, str]:
    return json.loads(locale_path(code).read_text(encoding="utf-8"))


@pytest.mark.parametrize("code", _TRANSLATED)
class TestCatalog:
    def test_자리표시자가_그대로다(self, code):
        """이름이 빠지거나 바뀌면 그 자리가 비거나 채우기가 실패한다."""
        bad = []
        for source, target in _catalog(code).items():
            if not target.strip():
                continue
            if set(_FIELD.findall(source)) != set(_FIELD.findall(target)):
                bad.append(f"{source!r} → {target!r}")
        assert not bad, "자리표시자가 어긋났다:\n  " + "\n  ".join(bad)

    def test_줄바꿈_수가_같다(self, code):
        """툴팁은 줄 수로 모양이 정해진다 — 한 줄로 합치면 배지 폭이 흔들린다."""
        bad = [
            f"{s!r} → {t!r}"
            for s, t in _catalog(code).items()
            if t.strip() and s.count("\n") != t.count("\n")
        ]
        assert not bad, "줄바꿈이 어긋났다:\n  " + "\n  ".join(bad)

    def test_번역문에_한글이_없다(self, code):
        """옮기다 만 항목을 잡는다 — 영어 화면에 한글이 섞이면 눈에 띄게 어색하다."""
        hangul = re.compile(r"[가-힣]")
        # 언어 이름은 자국어로 적는 것이 관행이라 예외다.
        allowed = {"한국어"}
        bad = [
            f"{s!r} → {t!r}"
            for s, t in _catalog(code).items()
            if t.strip() and hangul.search(t) and t not in allowed
        ]
        assert not bad, "번역문에 한글이 남았다:\n  " + "\n  ".join(bad)

    def test_빈_번역이_없다(self, code):
        todo = [s for s, t in _catalog(code).items() if not t.strip()]
        assert not todo, f"아직 번역하지 않은 항목 {len(todo)}개: {sorted(todo)[:5]}"

    def test_원문을_그대로_베끼지_않았다(self, code):
        """원문 복사는 '번역했다'고 착각하게 만든다.

        다만 `v{version} · {percent}%` 처럼 **자리표시자와 기호뿐인** 문자열은 옮길
        말이 없다 — 자리표시자를 걷어낸 뒤에 남는 낱말이 있는지로 판정한다.
        """
        meaningful = re.compile(r"[가-힣A-Za-z]{2,}")
        bad = [
            s for s, t in _catalog(code).items()
            if t.strip() and s == t and meaningful.search(_FIELD.sub("", s))
        ]
        assert not bad, f"원문과 같은 항목: {sorted(bad)[:5]}"


class TestSyncWithCode:
    """코드가 쓰는 원문과 카탈로그가 어긋나지 않는가."""

    def test_카탈로그에_없는_원문이_없다(self):
        """`tr()` 로 감쌌는데 카탈로그에 없으면 그 자리는 영영 한국어로 남는다."""
        import importlib.util
        from pathlib import Path

        root = Path(__file__).resolve().parents[3]
        spec = importlib.util.spec_from_file_location(
            "extract_catalog", root / "scripts" / "extract_catalog.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        for code in _TRANSLATED:
            missing = mod.collect() - set(_catalog(code))
            assert not missing, (
                f"{code} 카탈로그에 없는 원문 {len(missing)}개 — "
                f"`python scripts/extract_catalog.py` 를 돌려라: {sorted(missing)[:5]}"
            )
