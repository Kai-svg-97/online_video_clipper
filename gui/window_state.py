"""창 상태 복원 — 트레이·중복 실행에서 창을 다시 불러올 때.

## `showNormal()`을 쓰지 않는 이유

`showNormal()`은 최소화만 푸는 것이 아니라 **최대화까지 해제한다**. 그래서 창을
최대화해 쓰다가 트레이로 내렸다가 되부르면 창이 작아진 채 돌아온다 — 사용자는
창 크기를 매번 다시 맞춰야 한다(두 번째 인스턴스를 실행할 때도 같았다).

최소화 비트만 지우면 최대화 상태가 그대로 살아 돌아온다.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt


def restore_from_tray(window) -> None:
    """최소화를 풀고 창을 앞으로 부른다(최대화 상태는 유지한다)."""
    window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMinimized)
    window.show()
    window.raise_()
    window.activateWindow()
