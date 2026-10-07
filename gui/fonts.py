"""앱 글꼴에서 파생하는 글꼴 헬퍼.

`QFont("", N)`(빈 패밀리)은 Windows에서 비트맵 글꼴 'MS Sans Serif'로 풀려, 화면 배율이
1이 아니면 글자 그리기가 앱 글꼴보다 50배 느리다. 델리게이트·카드는 `app_font()`로
앱 글꼴(`create_qt_app`이 정한 것)에서 파생한 글꼴을 쓴다.

캐시하지 않는다 — 앱 글꼴이 정해지기 전에 평가되면 같은 결함이 돌아온다. 페인트 경로나
함수 안에서 호출하고, 모듈 수준 상수로 만들지 않는다(`tests/gui/test_app_font_guard.py`).
이 모듈은 PyQt6를 임포트하므로 `gui/text/`가 아니라 여기에 둔다.
"""

from __future__ import annotations

import logging

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

_FALLBACK_POINT_SIZE = 9


def app_font(point_size: int, weight: QFont.Weight | None = None) -> QFont:
    """앱 글꼴을 복사해 크기(와 굵기)를 지정한 글꼴을 돌려준다. 예외를 내지 않는다."""
    try:
        font = QFont(QApplication.font())
    except Exception:
        logger.debug("앱 글꼴을 읽지 못해 기본 QFont로 폴백", exc_info=True)
        font = QFont()
    size = point_size
    if size <= 0:
        base = font.pointSize()
        size = base if base > 0 else _FALLBACK_POINT_SIZE
    font.setPointSize(size)
    if weight is not None:
        font.setWeight(weight)
    return font
