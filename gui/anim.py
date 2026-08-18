"""짧은 등장 연출 — 새로 나타나는 것이 '툭' 튀지 않게 한다.

두 가지만 다룬다.

* `fade_in(widget)` — 비동기로 도착한 것(썸네일·자켓)이 화면에 얹힐 때.
* `fade_switch(stack, index)` — 화면(목록↔상세)이 바뀔 때.

**영상이 있는 화면에는 걸지 않는다.** `QGraphicsOpacityEffect`는 위젯을 픽스맵으로
그려 합성하는데, 비디오 표시면(`QGraphicsView` + `QGraphicsVideoItem`)은 자기 서피스에
직접 그리므로 효과 아래에서 검게 비거나 깜빡일 수 있다. `fade_switch`는 대상 화면에
그런 위젯이 있으면 **연출 없이 즉시 전환**한다 — 부드러움보다 화면이 제대로 나오는 게 먼저다.

효과는 끝나면 반드시 떼어 낸다(`setGraphicsEffect(None)`). 남겨 두면 그 위젯은 계속
픽스맵 합성 경로를 타 스크롤·리페인트가 느려진다.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QGraphicsView, QStackedWidget, QWidget

logger = logging.getLogger(__name__)

_FADE_MS = 140


def _has_video_surface(widget: QWidget | None) -> bool:
    """이 화면에 영상 표시면이 있는지 — 있으면 투명도 효과를 걸지 않는다."""
    if widget is None:
        return False
    if isinstance(widget, QGraphicsView):
        return True
    return widget.findChild(QGraphicsView) is not None


def fade_in(widget: QWidget | None, duration_ms: int = _FADE_MS) -> bool:
    """위젯을 잠깐 사이에 나타나게 한다(적용했으면 True).

    비동기로 도착한 그림에 쓴다 — 이미 캐시에 있어 즉시 그려지는 경우에는 부르지 않는다
    (그때는 연출이 오히려 굼떠 보인다).
    """
    if widget is None or _has_video_surface(widget):
        return False
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(duration_ms)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _clear() -> None:
        try:
            widget.setGraphicsEffect(None)   # 남겨 두면 리페인트가 계속 느려진다
        except RuntimeError:
            logger.debug("페이드 대상 위젯이 이미 정리됨 — 무시")

    anim.finished.connect(_clear)
    anim.start()
    widget._fade_anim = anim   # GC 방지(애니메이션이 중간에 사라지면 반투명으로 굳는다)
    return True


def fade_switch(
    stack: QStackedWidget, index: int, duration_ms: int = _FADE_MS
) -> bool:
    """스택 화면을 바꾸며 새 화면을 살짝 띄운다(연출했으면 True).

    영상이 있는 화면으로 갈 때는 즉시 전환한다(위 모듈 설명 참고).
    """
    if stack.currentIndex() == index:
        return False
    target = stack.widget(index)
    stack.setCurrentIndex(index)
    if target is None or _has_video_surface(target):
        return False
    return fade_in(target, duration_ms)
