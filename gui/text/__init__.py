"""화면에 나가는 모든 말이 사는 곳 — 라벨·포맷·문장.

## 규약 셋

1. **PyQt6를 임포트하지 않는다.** 이 패키지는 순수 파이썬이라 헤드리스로 단위
   테스트할 수 있고, 나중에 `presentation/` 계층으로 승격할 여지를 공짜로 남긴다.
   `tests/unit/gui/test_gui_text_purity.py`가 강제한다 — 규약은 문서만으로 안 지켜진다.
2. **도메인·애플리케이션은 이 패키지를 임포트하지 않는다.** 의존 방향은
   `gui → application → domain` 그대로다. 도메인은 `Message`(키+파라미터)를 돌려주고
   여기서 문장이 된다.
3. **번역은 `_()` 한 곳만 거친다.** 지금은 항등 함수다 — 2단계에서 이 함수 몸통만
   `QCoreApplication.translate`로 바꾸면 전체가 번역된다.

## 왜 `gui/panels/library/formatting.py`가 아닌가

그 모듈은 라이브러리 패널 안에서만 쓰이고(임포터 10곳 전부 그 패키지 내부),
PyQt6·ThemeManager를 끌어온다. 여기는 `gui/` 최상위의 공용 모듈 자리
(`anim.py`·`toast.py`·`workers.py`)와 같은 층위다.
"""

from __future__ import annotations


def _(text: str, context: str = "app") -> str:
    """번역 지점. **지금은 항등 함수다.**

    1단계에서는 아무것도 번역하지 않는다 — 이 단계의 성공 기준은 "화면이 지금과
    똑같다"이기 때문이다. 2단계에서 여기만 `QCoreApplication.translate(context, text)`
    로 바꾼다.

    `context`는 Qt 번역 문맥용으로 미리 받아 둔다. 같은 한국어가 자리마다 다른 영어가
    되어야 하는 경우(예: "열기"가 파일에서는 Open, 폴더에서는 Browse) 이 값으로 가른다.
    """
    return text


__all__ = ["_"]
