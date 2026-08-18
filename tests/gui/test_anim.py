"""등장 연출 — 영상 화면을 건드리지 않는다는 계약을 고정한다.

`QGraphicsOpacityEffect`는 위젯을 픽스맵으로 합성하는데, 비디오 표시면은 자기 서피스에
직접 그리므로 효과 아래에서 검게 비거나 깜빡일 수 있다. 그래서 영상이 있는 화면에는
연출을 걸지 않고 즉시 전환한다 — 부드러움보다 화면이 제대로 나오는 게 먼저다.

효과를 끝나고 떼어 내는 것도 계약이다(남으면 그 위젯은 계속 픽스맵 합성 경로를 타
스크롤·리페인트가 느려진다).
"""
from __future__ import annotations

from PyQt6.QtWidgets import QGraphicsView, QLabel, QStackedWidget, QVBoxLayout, QWidget

from gui.anim import fade_in, fade_switch


class TestFadeIn:
    def test_보통_위젯은_페이드된다(self, qtbot):
        label = QLabel("x")
        qtbot.addWidget(label)

        assert fade_in(label) is True
        assert label.graphicsEffect() is not None

    def test_끝나면_효과를_떼어_낸다(self, qtbot):
        label = QLabel("x")
        qtbot.addWidget(label)

        fade_in(label, duration_ms=40)

        qtbot.waitUntil(lambda: label.graphicsEffect() is None, timeout=2000)

    def test_영상_표시면에는_걸지_않는다(self, qtbot):
        view = QGraphicsView()
        qtbot.addWidget(view)

        assert fade_in(view) is False
        assert view.graphicsEffect() is None

    def test_영상을_품은_화면에도_걸지_않는다(self, qtbot):
        page = QWidget()
        qtbot.addWidget(page)
        layout = QVBoxLayout(page)
        layout.addWidget(QGraphicsView())

        assert fade_in(page) is False

    def test_None은_그냥_넘어간다(self):
        assert fade_in(None) is False


class TestFadeSwitch:
    def _stack(self, qtbot, with_video=False) -> QStackedWidget:
        stack = QStackedWidget()
        qtbot.addWidget(stack)
        stack.addWidget(QLabel("목록"))
        page = QWidget()
        if with_video:
            QVBoxLayout(page).addWidget(QGraphicsView())
        stack.addWidget(page)
        stack.show()
        qtbot.waitExposed(stack)
        return stack

    def test_화면을_바꾸고_새_화면을_띄운다(self, qtbot):
        stack = self._stack(qtbot)

        assert fade_switch(stack, 1) is True
        assert stack.currentIndex() == 1

    def test_영상_화면으로는_즉시_전환한다(self, qtbot):
        stack = self._stack(qtbot, with_video=True)

        faded = fade_switch(stack, 1)

        assert faded is False              # 연출 없이
        assert stack.currentIndex() == 1   # 전환은 됐다

    def test_같은_화면이면_아무_일도_하지_않는다(self, qtbot):
        stack = self._stack(qtbot)

        assert fade_switch(stack, 0) is False
