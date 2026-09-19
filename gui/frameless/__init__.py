"""프레임리스 창 설치 — **걸 수 없으면 조용히 물러난다**.

여기서 예외가 밖으로 나가면 창이 만들어지지 않아 **앱이 아예 뜨지 않는다.** 그래서
설치는 전부 실패 가능한 일로 취급하고, 안 되면 `None`을 돌려줘 호출부가 네이티브
타이틀바로 되돌아가게 한다. 모양이 조금 다른 편이 앱이 안 켜지는 것보다 낫다.
"""

from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger(__name__)

# 사용자 환경에서 도저히 맞지 않을 때를 위한 탈출구. 지원 문의에서 "이걸로 한번
# 실행해 보세요"라고 말할 수 있어야 한다.
ESCAPE_HATCH_ENV = "OVC_NATIVE_TITLEBAR"


def can_install() -> bool:
    """이 환경에 프레임리스를 걸 수 있는가.

    `sys.platform`만 보면 부족하다 — 윈도우에서 `QT_QPA_PLATFORM=offscreen`으로
    돌 때 `winId()`가 HWND가 아니고, 그 값을 `SetWindowLongPtr`에 넘기면 엉뚱한
    핸들을 건드린다. 테스트가 바로 그 경로로 들어온다.
    """
    if sys.platform != "win32":
        return False
    if os.environ.get(ESCAPE_HATCH_ENV):
        logger.info("%s 가 설정돼 있어 네이티브 타이틀바를 쓴다", ESCAPE_HATCH_ENV)
        return False
    try:
        from PyQt6.QtGui import QGuiApplication  # noqa: PLC0415

        return QGuiApplication.platformName() == "windows"
    except Exception:
        logger.exception("플랫폼 플러그인을 확인하지 못했다")
        return False


def install_frameless(window, title_bar):
    """네이티브 프레임을 지운다. 걸지 못하면 `None`(호출부가 네이티브로 복귀)."""
    if not can_install():
        return None
    try:
        from gui.frameless.win32_hook import FramelessHook  # noqa: PLC0415

        hook = FramelessHook(window, title_bar)
        hook.install()
        return hook
    except Exception:
        logger.exception("프레임리스 설치 실패 — 네이티브 타이틀바로 진행한다")
        return None


def safe_dispatch(hook, event_type, message) -> tuple[bool, int, object]:
    """훅에 네이티브 메시지를 넘기되 **예외를 절대 밖으로 내지 않는다**.

    `nativeEvent`는 메시지 루프 안이다 — 거기서 예외가 새면 `paintEvent`와 같은
    부류로 진단 불가능하게 죽는다. 한 번이라도 터지면 훅을 버려서(세 번째 반환값이
    `None`) 그 뒤로는 네이티브 동작으로 떨어진다. 창이 조금 이상해지는 편이 앱이
    사라지는 것보다 낫다.

    반환: `(처리했는가, 반환값, 계속 쓸 훅 또는 None)`.

    이 판단을 `MainWindow.nativeEvent` 안에 두지 않는 이유는 **테스트하기 위해서**다
    — 거기 두면 창을 통째로 만들어야만 검증할 수 있다.
    """
    if hook is None:
        return False, 0, None
    try:
        handled, result = hook.handle(event_type, message)
    except Exception:
        logger.exception("네이티브 메시지 처리 실패 — 프레임리스를 끈다")
        return False, 0, None
    return bool(handled), int(result), hook
