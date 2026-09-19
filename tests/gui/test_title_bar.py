"""커스텀 타이틀바를 **실제로 그려 본다**.

`paintEvent` 안에서 난 파이썬 예외는 PyQt가 프로세스 종료로 처리한다(Windows에서
0xC0000409) — 예외 메시지도 로그도 없이 앱이 그냥 사라진다. 그래서 여기서는 '값을
잘 계산했나'가 아니라 **그리다가 죽지 않는가**를 본다(`test_download_card_paint.py`와
같은 이유).

드래그 가능 영역(`hit_test`)도 함께 지킨다. 제목 글자 위에서 창이 안 끌리는 것은
프레임리스 타이틀바에서 가장 흔한 실수인데, 화면을 봐서는 원인을 알 수 없다.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint, QSize
from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtWidgets import QLabel, QMainWindow

from gui.themes.manager import ThemeManager
from gui.themes.tokens import PRESETS
from gui.widgets.title_bar import (
    HTCAPTION,
    HTCLIENT,
    TITLE_BAR_HEIGHT,
    TitleBar,
)


@pytest.fixture
def bar(qtbot, qapp_instance):
    win = QMainWindow()
    win.setWindowTitle("YouTube Content Manager")
    qtbot.addWidget(win)
    tb = TitleBar(win)
    win.setMenuWidget(tb)
    tb.resize(900, TITLE_BAR_HEIGHT)
    return tb


def _paint(widget) -> None:
    """실제로 그린다 — 그리다 죽으면 테스트가 아니라 프로세스가 끝난다."""
    pm = QPixmap(QSize(max(widget.width(), 1), max(widget.height(), 1)))
    pm.fill()
    painter = QPainter(pm)
    try:
        widget.render(painter)
    finally:
        painter.end()


class TestPainting:
    @pytest.mark.parametrize("preset", sorted(PRESETS))
    def test_모든_테마에서_그려진다(self, bar, preset):
        """테마마다 토큰이 달라 어느 하나에서만 죽는 일이 실제로 있었다."""
        ThemeManager.instance().apply(preset)
        _paint(bar)

    def test_최대화_글리프도_그려진다(self, bar):
        bar.set_maximized(True)
        _paint(bar)
        bar.set_maximized(False)
        _paint(bar)

    def test_버튼_호버_상태도_그려진다(self, bar):
        """닫기 버튼만 고정색 경로를 타므로 따로 밟아 본다."""
        for btn in (bar._btn_min, bar._btn_max, bar._btn_close):
            btn._hover = True
            _paint(btn)
            btn._hover = False
            _paint(btn)

    def test_배지를_꽂아도_그려진다(self, bar, qtbot):
        badge = QLabel("v9.9.9")
        bar.set_leading_widget(badge)
        _paint(bar)


class TestTheme:
    def test_테마를_바꾸면_색이_따라온다(self, bar):
        """위젯 단위로 칠하는 화면은 전역 QSS 교체만으로 갱신되지 않는다."""
        ThemeManager.instance().apply("mist")
        before = bar._bg.name()
        ThemeManager.instance().apply("graphite")
        assert bar._bg.name() != before

    def test_버튼도_테마를_구독한다(self, bar):
        ThemeManager.instance().apply("mist")
        before = bar._btn_close._fg.name()
        ThemeManager.instance().apply("graphite")
        assert bar._btn_close._fg.name() != before


class TestTitle:
    def test_창_제목을_보여_준다(self, bar):
        assert bar._title.text() == "YouTube Content Manager"

    def test_제목이_바뀌면_따라간다(self, bar):
        bar._window.setWindowTitle("다른 제목")
        assert bar._title.text() == "다른 제목"


class TestHitTest:
    def test_빈_영역은_드래그_가능(self, bar):
        # 제목 오른쪽, 버튼 왼쪽의 빈 공간
        assert bar.hit_test(QPoint(500, TITLE_BAR_HEIGHT // 2)) == HTCAPTION

    def test_제목_글자_위에서도_드래그된다(self, bar):
        """라벨이 마우스를 먹으면 글자 위에서 창이 안 끌린다 — 흔한 실수다."""
        center = bar._title.geometry().center()
        assert bar.hit_test(center) == HTCAPTION

    def test_캡션_버튼_위는_드래그가_아니다(self, bar):
        for btn in (bar._btn_min, bar._btn_max, bar._btn_close):
            pos = btn.geometry().center()
            assert bar.hit_test(pos) == HTCLIENT, "버튼이 클릭을 받아야 한다"

    def test_배지_위는_드래그가_아니다(self, bar):
        badge = QLabel("v9.9.9")
        bar.set_leading_widget(badge)
        bar.resize(900, TITLE_BAR_HEIGHT)
        bar.activateWindow()
        # 레이아웃이 자리를 잡아야 geometry가 의미를 가진다
        bar.layout().activate()
        assert bar.hit_test(badge.geometry().center()) == HTCLIENT

    def test_띠_밖은_클라이언트(self, bar):
        assert bar.hit_test(QPoint(500, TITLE_BAR_HEIGHT + 200)) == HTCLIENT


class TestCaptionButtons:
    def test_최소화_버튼이_창을_내린다(self, bar):
        bar._btn_min._on_click()
        assert bar._window.isMinimized()

    def test_최대화_토글(self, bar):
        bar._btn_max._on_click()
        assert bar._window.isMaximized()
        bar._btn_max._on_click()
        assert not bar._window.isMaximized()

    def test_최대화_상태가_글리프에_반영된다(self, bar):
        bar.set_maximized(True)
        assert bar._btn_max._glyph == "restore"
        bar.set_maximized(False)
        assert bar._btn_max._glyph == "max"


class TestLeadingSlot:
    def test_비어_있으면_폭을_차지하지_않는다(self, bar):
        bar.layout().activate()
        assert bar._slot.width() <= 1

    def test_주입한_위젯이_슬롯의_자식이_된다(self, bar):
        badge = QLabel("v9.9.9")
        bar.set_leading_widget(badge)
        assert badge.parent() is bar._slot
