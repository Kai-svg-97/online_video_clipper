"""화면에 나가는 모든 말이 사는 곳 — 라벨·포맷·문장·번역.

## 규약 셋

1. **PyQt6를 임포트하지 않는다.** 이 패키지는 순수 파이썬이라 헤드리스로 단위
   테스트할 수 있고, 나중에 `presentation/` 계층으로 승격할 여지를 공짜로 남긴다.
   `tests/unit/gui/test_gui_text.py`가 강제한다 — 규약은 문서만으로 안 지켜진다.
2. **도메인·애플리케이션은 이 패키지를 임포트하지 않는다.** 의존 방향은
   `gui → application → domain` 그대로다. 도메인은 `Message`(키+파라미터)를 돌려주고
   여기서 문장이 된다.
3. **번역은 `tr()` 한 곳만 거친다.** 이름이 `_` 가 아닌 이유가 있다 — 이 코드베이스는
   `for _ in ...` 처럼 `_` 를 버리는 변수로 쓰는 곳이 19군데다. `_` 로 두면 그 반복문
   안에서 번역 함수가 **조용히 가려져** 라벨이 빈 채로 나온다(실제로 겪었다).

## `tr()` — 번역의 단일 지점

원문(한국어)이 곧 키다. 카탈로그에 없으면 **원문을 그대로 돌려준다** — 그래서
번역을 조금씩 채워도 화면이 비지 않는다(안 채운 곳은 한국어).

언어는 **시작할 때 한 번** 정해진다. 바꾸면 다시 시작해야 반영되는데, 그건 이 앱의
화면이 `setText()`로 생성 시점에 문자열을 박아 넣기 때문이다 — 즉시 전환을 하려면
214개 클래스에 `_retranslate()`를 신설해야 하고, 그 값어치가 지금은 없다.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# 지금 쓰는 카탈로그. `set_language()` 가 채운다.
_CATALOG: dict[str, str] = {}
_ACTIVE: str = "ko"


def set_language(code: str) -> None:
    """카탈로그를 갈아 끼운다. **시작할 때 한 번** 부르는 것을 전제로 한다."""
    global _CATALOG, _ACTIVE
    from gui.text.catalog import load_catalog  # noqa: PLC0415

    _ACTIVE = code or "ko"
    _CATALOG = load_catalog(_ACTIVE)
    if _CATALOG:
        logger.info("화면 언어: %s (번역 %d건)", _ACTIVE, len(_CATALOG))


def active_language() -> str:
    return _ACTIVE


def tr(text: str, context: str = "app") -> str:
    """번역 지점. 카탈로그에 없으면 **원문 그대로**.

    `context`는 같은 한국어가 자리마다 다른 번역이 되어야 할 때를 위해 받아 둔다
    (예: "열기"가 파일에서는 Open, 폴더에서는 Browse). 지금은 쓰지 않는다 —
    실제로 충돌하는 낱말이 나오면 그때 키를 `context`로 갈라 준다.

    **공백뿐인 번역도 미번역으로 친다.** 카탈로그를 채우다 만 항목이 그렇게 되기
    쉬운데, 그대로 두면 라벨이 사라져 화면에 빈 자리가 생긴다 — 한국어가 남는 편이
    언제나 낫다.
    """
    translated = _CATALOG.get(text)
    return translated if translated and translated.strip() else text


__all__ = ["active_language", "set_language", "tr"]
