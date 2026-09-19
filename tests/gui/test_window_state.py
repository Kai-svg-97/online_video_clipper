"""트레이·중복 실행에서 창을 되부를 때 **최대화가 풀리지 않는가**.

`showNormal()`은 최소화만 푸는 것이 아니라 최대화까지 해제한다. 최대화해 쓰다가
트레이로 내렸다가 되부르면 창이 작아진 채 돌아왔고, 사용자는 매번 크기를 다시
맞춰야 했다. 화면을 봐야만 알 수 있는 종류의 버그라 여기서 고정한다.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMainWindow

from gui.window_state import restore_from_tray


def _win(qtbot):
    w = QMainWindow()
    qtbot.addWidget(w)
    w.resize(900, 600)
    return w


class TestRestoreFromTray:
    def test_최소화를_푼다(self, qtbot, qapp_instance):
        w = _win(qtbot)
        w.showMinimized()
        restore_from_tray(w)
        assert not w.isMinimized()

    def test_최대화를_유지한다(self, qtbot, qapp_instance):
        """showNormal() 은 여기서 최대화까지 풀어 버린다."""
        w = _win(qtbot)
        w.showMaximized()
        w.showMinimized()
        restore_from_tray(w)
        assert w.isMaximized(), "트레이에서 되부르면 최대화가 풀렸다"

    def test_최대화가_아니면_그대로_보통_창(self, qtbot, qapp_instance):
        w = _win(qtbot)
        w.show()
        w.showMinimized()
        restore_from_tray(w)
        assert not w.isMaximized()
        assert not w.isMinimized()

    def test_숨겨진_창도_보이게_한다(self, qtbot, qapp_instance):
        """트레이로 내릴 때 hide() 를 쓰므로 show() 가 필요하다."""
        w = _win(qtbot)
        w.show()
        w.hide()
        restore_from_tray(w)
        assert w.isVisible()

    def test_최소화_비트만_건드린다(self, qtbot, qapp_instance):
        """다른 상태 비트(최대화 등)를 지우면 안 된다."""
        w = _win(qtbot)
        w.setWindowState(
            Qt.WindowState.WindowMaximized | Qt.WindowState.WindowMinimized
        )
        restore_from_tray(w)
        assert not (w.windowState() & Qt.WindowState.WindowMinimized)
        assert w.windowState() & Qt.WindowState.WindowMaximized
