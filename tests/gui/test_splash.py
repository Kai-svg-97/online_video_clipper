"""스플래시 — 프레임 없는 위젯, 창이 노출된 뒤에 닫힌다 (성능 배치 1, A3-a).

`QSplashScreen.finish(window)` 는 창이 **그려지기를 기다리지 않아** 이후의 무거운
첫 그리기 동안 빈 화면이 났다. `finish_splash` 가 노출을 확인한 뒤 닫는다.
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import QCoreApplication, Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QSplashScreen, QWidget

from bootstrap import runtime


def _pump() -> None:
    QCoreApplication.processEvents()
    QCoreApplication.processEvents()


@pytest.fixture
def splash(qtbot, qapp_instance):
    s = runtime.show_splash(qapp_instance)
    qtbot.addWidget(s)
    yield s
    s.close()


class TestShowSplash:
    def test_QSplashScreen이_아니고_프레임이_없다(self, splash):
        assert not isinstance(splash, QSplashScreen)
        assert splash.windowFlags() & Qt.WindowType.FramelessWindowHint

    def test_반환될_때_이미_보인다(self, splash):
        assert splash.isVisible()

    def test_그려도_죽지_않는다(self, splash):
        pix = splash.grab()
        assert isinstance(pix, QPixmap)
        assert not pix.isNull()


class TestFinishSplash:
    def test_창이_안_보이면_닫지_않는다(self, qtbot, splash):
        window = QWidget()
        qtbot.addWidget(window)
        runtime.finish_splash(splash, window)
        _pump()
        assert splash.isVisible()

        window.show()
        qtbot.waitExposed(window)
        qtbot.waitUntil(lambda: not splash.isVisible(), timeout=2000)

    def test_이미_노출된_창이면_바로_닫는다(self, qtbot, splash):
        window = QWidget()
        qtbot.addWidget(window)
        window.show()
        qtbot.waitExposed(window)
        runtime.finish_splash(splash, window)
        qtbot.waitUntil(lambda: not splash.isVisible(), timeout=1000)

    def test_창이_끝내_안_떠도_안전_타임아웃에_닫힌다(
        self, qtbot, splash, monkeypatch
    ):
        # 구현자 확인 필요: 상한 상수의 이름 — 계획에 이름이 없어 `SPLASH_TIMEOUT_MS` 로 추정했다.
        monkeypatch.setattr(runtime, "SPLASH_TIMEOUT_MS", 50)
        window = QWidget()
        qtbot.addWidget(window)
        runtime.finish_splash(splash, window)
        qtbot.waitUntil(lambda: not splash.isVisible(), timeout=2000)

    def test_안전_타임아웃의_기본값은_10초다(self):
        assert runtime.SPLASH_TIMEOUT_MS == 10_000
