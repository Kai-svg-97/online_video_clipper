"""번역 카탈로그 — 원문(한국어) → 번역문.

## 왜 `.qm` 이 아니라 JSON 인가

Qt 의 표준은 `.ts` → `lrelease` → `.qm` 인데, **`lrelease` 가 PyQt6 wheel 에 들어
있지 않다**(`pylupdate6` 만 있다). 번역 하나 때문에 Qt 도구 전체를 빌드 의존성에
더하고 CI 에 설치 단계를 넣을 값어치가 없다.

JSON 은 덤도 있다 — **git diff 로 무엇이 바뀌었는지 보인다.** `.qm` 은 바이너리라
리뷰가 안 된다.

## 원문이 곧 키다

`_("설정")` 처럼 **한국어 원문을 그대로 키로 쓴다.** `_("settings.title")` 같은
인공 키를 쓰려면 1,100곳을 손으로 고쳐야 하는데, 그 과정에서 생기는 실수가 번역
누락보다 비싸다. 원문 키는 코드를 읽을 때 무슨 말이 나오는지 바로 보이는 이점도 있다.

## 없는 번역은 원문으로 남는다

실측으로 확인한 Qt 계약 — `QTranslator.translate()` 가

- `None` 을 돌려주면 → Qt 가 **원문으로 폴백**한다
- `""` 을 돌려주면 → **빈 문자열이 그대로 표시된다**(라벨이 사라진다)

그래서 번역이 없으면 반드시 `None` 이다. 이 성질 덕에 카탈로그를 **조금씩 채워도**
화면이 비지 않는다 — 안 채운 곳은 한국어로 남는다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 원문이 한국어이므로 `ko` 에는 카탈로그가 필요 없다.
SOURCE_LANGUAGE = "ko"

# 고를 수 있는 언어 — (코드, 그 언어로 쓴 이름).
#
# 이름을 **자국어로** 적는 것은 언어 선택기의 일반적인 관행이다. 지금 화면이 어떤
# 언어든 자기 언어는 알아볼 수 있어야 고를 수 있다.
AVAILABLE_LANGUAGES: tuple[tuple[str, str], ...] = (
    ("ko", "한국어"),
    ("en", "English"),
)

_LOCALE_DIR = "gui/text/locales"


def locale_path(code: str) -> Path:
    """카탈로그 파일 경로. 번들에서도 찾아야 하므로 리소스 경로를 거친다."""
    from utils.resources import get_resource_path  # noqa: PLC0415

    return get_resource_path(f"{_LOCALE_DIR}/{code}.json")


def load_catalog(code: str) -> dict[str, str]:
    """`{원문: 번역문}`. 파일이 없거나 깨졌으면 빈 표(= 전부 원문 유지).

    **번역을 못 읽었다고 앱이 뜨지 않으면 안 된다.** 최악이 한국어 화면이다.
    """
    if not code or code == SOURCE_LANGUAGE:
        return {}
    try:
        path = locale_path(code)
        if not path.exists():
            logger.info("번역 카탈로그가 없다(원문 유지): %s", code)
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("번역 카탈로그를 읽지 못했다(원문 유지): %s", code)
        return {}
    if not isinstance(data, dict):
        logger.warning("번역 카탈로그 형식이 아니다(원문 유지): %s", code)
        return {}
    # 빈 값은 "아직 번역하지 않음"이다 — 넣어 두면 라벨이 사라진다.
    return {k: v for k, v in data.items() if isinstance(v, str) and v.strip()}


def language_name(code: str) -> str:
    return dict(AVAILABLE_LANGUAGES).get(code, code)


def is_supported(code: str) -> bool:
    return code in dict(AVAILABLE_LANGUAGES)
