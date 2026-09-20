"""`Message`(키+파라미터) → 사람이 읽는 문장.

도메인이 돌려준 `Message`를 여기서 문장으로 만든다. 템플릿 표 하나가 곧 번역 단위다.

## `render()`는 절대 예외를 내지 않는다

업데이트 배지가 이 결과를 **`paintEvent` 경로에서** 쓴다. 거기서 난 파이썬 예외는
PyQt가 **프로세스 종료**로 처리한다(Windows 0xC0000409) — 로그도 예외 메시지도 남지
않고 앱이 그냥 사라진다. `CLAUDE.md`의 "델리게이트 `paint()` 안에서 예외를 내지
않는다"와 같은 부류다.

그래서 템플릿이 없거나 파라미터가 모자라도 **예외 대신 읽을 수 있는 무언가**를
돌려준다. 빈 화면이 죽은 앱보다 낫다.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from domain.shared.messages import Message
from gui.text import _

logger = logging.getLogger(__name__)

# 키 → 문장. **키 하나가 완성된 문장 하나를 고른다** — 조각을 이어 붙이지 않는다.
# 덩어리 C3~C6에서 채워진다.
_TEMPLATES: dict[str, str] = {}

# 여러 조각을 한 줄로 이을 때 쓰는 구분자. 구분자도 언어 설정이라 여기 둔다.
JOIN_SEPARATOR = " · "


def render(msg: Message | None) -> str:
    """문장 하나를 만든다. 실패해도 예외를 내지 않는다(모듈 설명 참조)."""
    if msg is None:
        return ""
    template = _TEMPLATES.get(msg.key)
    if template is None:
        logger.warning("표시 문구 템플릿이 없다: %s", msg.key)
        return msg.key
    try:
        return _(template).format(**msg.as_dict())
    except (KeyError, IndexError, ValueError):
        # 파라미터가 모자라거나 형식이 안 맞는다. 채우지 못한 원문이라도 돌려준다.
        logger.exception("표시 문구를 채우지 못했다: %s", msg.key)
        return _(template)


def render_all(msgs: Sequence[Message], sep: str = JOIN_SEPARATOR) -> str:
    """여러 조각을 한 줄로 잇는다(필터 요약 등)."""
    return sep.join(render(m) for m in msgs)
