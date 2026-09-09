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

from PyQt6.QtCore import QAbstractAnimation, QEasingCurve, QPropertyAnimation
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QGraphicsView, QStackedWidget, QWidget

logger = logging.getLogger(__name__)

_FADE_MS = 140

# 실행 중인 애니메이션의 강한 참조. 멈추면 스스로 빠진다.
_RUNNING: set[QAbstractAnimation] = set()


def track_animation(anim: QAbstractAnimation) -> QAbstractAnimation:
    """애니메이션이 끝날 때까지 붙든다 — **부모를 떼어 낸다.**

    `gui/workers.py:track_thread()`와 같은 이유, 같은 방식이다. 거기 적힌 함정이
    애니메이션에도 그대로 있다:

    **실행 중인 애니메이션을 위젯의 자식으로 두면, 그 위젯이 파괴될 때 C++ 소멸자가
    자식 애니메이션까지 지우면서 프로세스가 죽는다**(access violation). `~QAbstractAnimation`
    이 암묵적으로 `stop()`을 부르고, 그것이 `finished`/`stateChanged`를 발화하는데 그
    시점의 수신 슬롯(보통 위젯을 캡처한 클로저)은 이미 파괴 중이라 해제된 메모리를
    건드린다.

    실측으로 좁힌 결과:

    * 애니메이션을 만들고 `start()`하지 않으면 — 클로저를 연결해 두어도 — 안전하다.
    * **실행 중**에 부모 위젯이 파괴되면 죽는다.
    * `destroyed`에서 `stop()`을 부르거나 신호를 `disconnect()`해도 **여전히 죽는다**
      (그 시점엔 이미 늦다).
    * **부모 없이** 만들면 안전하다 — 애니메이션의 수명이 위젯 소멸자와 분리되기 때문.

    그래서 부모를 떼고 레지스트리가 붙든다. 소유 위젯이 먼저 사라져도 애니메이션은
    자기 일을 마치고(또는 멈추고) 조용히 정리된다.

    `finished` 대신 **`stateChanged`**로 놓아 준다 — `finished`는 끝까지 재생됐을 때만
    나오므로, 중간에 `stop()`으로 멈춘 애니메이션은 레지스트리에 영원히 남는다.
    """
    if anim in _RUNNING:
        return anim
    try:
        if anim.parent() is not None:
            anim.setParent(None)
    except RuntimeError:
        return anim   # 이미 정리된 애니메이션
    _RUNNING.add(anim)
    anim.stateChanged.connect(lambda new, _old, a=anim: _release_if_stopped(a, new))
    return anim


def _release_if_stopped(anim: QAbstractAnimation, state) -> None:
    """멈췄으면 레지스트리에서 놓는다 — **`deleteLater`는 부르지 않는다.**

    끝난 애니메이션을 지우면, 아직 그것을 들고 있는 쪽(예: 패널의 `_recommend_anim`)이
    나중에 접근할 때 ``RuntimeError: wrapped C/C++ object ... has been deleted``가 난다
    (`gui/workers.py`가 워커에 대해 같은 판단을 한다). 참조만 놓으면 마지막 참조가
    사라질 때 파이썬이 정리하며, 그때는 이미 멈춰 있어 안전하다.
    """
    if state == QAbstractAnimation.State.Stopped:
        _RUNNING.discard(anim)


def running_animation_count() -> int:
    """레지스트리에 남은 애니메이션 수(테스트·진단용)."""
    return len(_RUNNING)


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
    # 부모를 떼고 레지스트리가 붙든다 — 위젯 속성 하나로만 붙들면 위젯이 사라질 때
    # 실행 중 애니메이션이 함께 파괴된다(track_animation 문서 참고). 예전에는
    # `widget._fade_anim = anim`으로 GC만 막았는데, 그것은 위젯→애니메이션→클로저→
    # 위젯 참조 순환을 만들어 파괴 순서를 GC에 맡기는 형태였다.
    track_animation(anim)
    anim.start()
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
