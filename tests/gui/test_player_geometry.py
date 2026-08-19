"""영상 영역 크기 — 컨트롤바가 언제나 보이는 자리에 있는지 고정한다.

컨트롤바는 영상 영역의 바닥에 얹힌다. 그래서 영역이 배정된 공간보다 커지면 바가 창
밖으로 밀려 **보이지도 눌리지도 않는다**. 예전에는 폭에서 계산한 16:9 높이를 그대로
고정 높이로 박아, 창이 가로로 길어질수록 실제로 그 일이 났다(실측: 2200×900 창에서
바 하단이 창 아래로 335px).

지금은 영역 높이를 창 높이의 일정 비율로 제한한다. 넘칠 때는 영상이 좌우로 레터박스
될 뿐이고, 바는 늘 영역 안 바닥에 있다. 자동 숨김(마우스가 멈추면 사라짐)은 그대로다.
"""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from gui.widgets.player.surfaces import _VideoArea
from gui.widgets.video_player import InlinePlayer


@pytest.fixture
def host(qtbot):
    """플레이어 + 그 아래 내용(탭 자리)을 담은 창 — 실제 상세 화면과 같은 구성."""
    widget = QWidget()
    qtbot.addWidget(widget)
    layout = QVBoxLayout(widget)
    player = InlinePlayer()
    layout.addWidget(player)
    tabs = QLabel("탭 영역")
    layout.addWidget(tabs, stretch=1)
    widget.player = player
    widget.tabs = tabs
    return widget


def _fix_size(host, width: int, height: int, qtbot) -> None:
    """창 크기를 **고정**한다 — 실제 창은 화면보다 커질 수 없다.

    `resize()`만 쓰면 Qt가 내용에 맞춰 창을 키워 버려, 정작 재현하려던 '넘침'이
    일어나지 않는다(이 테스트를 처음 쓸 때 실제로 그래서 통과해 버렸다).
    """
    host.setFixedSize(width, height)
    if not host.isVisible():
        host.show()
        qtbot.waitExposed(host)
    QApplication.processEvents()


def _bar_bottom_in_window(host) -> int:
    area = host.player._video_area
    return area.mapTo(host, host.player._bar.geometry().bottomLeft()).y()


class TestBarStaysVisible:
    @pytest.mark.parametrize(
        "size",
        [(2200, 900), (3400, 1000), (1600, 700), (1200, 900), (800, 1000)],
        ids=["아주 넓은 창", "울트라와이드", "낮고 넓은 창", "보통 창", "좁고 긴 창"],
    )
    def test_어떤_창_비율에서도_바가_창_안에_있다(self, host, qtbot, size):
        _fix_size(host, *size, qtbot)

        assert _bar_bottom_in_window(host) <= host.height()

    def test_바는_영역_바닥에_붙어_있다(self, host, qtbot):
        _fix_size(host, 2200, 900, qtbot)

        area, bar = host.player._video_area, host.player._bar
        assert bar.geometry().bottom() + 1 == area.height()
        assert bar.width() == area.width()

    def test_세로만_줄여도_따라온다(self, host, qtbot):
        """폭이 그대로면 이 위젯의 resizeEvent가 오지 않는다 — 창 크기도 지켜봐야 한다."""
        _fix_size(host, 2200, 1000, qtbot)

        _fix_size(host, 2200, 620, qtbot)

        assert _bar_bottom_in_window(host) <= host.height()

    def test_아래_내용도_자리를_잃지_않는다(self, host, qtbot):
        """영상이 창을 다 차지하면 바뿐 아니라 그 아래 탭도 함께 밀려난다."""
        _fix_size(host, 2200, 900, qtbot)

        assert host.tabs.height() > 100


class TestAreaHeightRule:
    def test_공간이_넉넉하면_16대9를_그대로_쓴다(self, qtbot):
        """평소 비율에서는 예전과 똑같아야 한다 — 제한은 넘칠 때만 개입한다."""
        window = QWidget()
        qtbot.addWidget(window)
        window.resize(1000, 1400)
        area = _VideoArea(QWidget(), parent=window)
        window.show()
        qtbot.waitExposed(window)

        assert area.heightForWidth(800) == 800 * 9 // 16

    def test_창을_넘으면_제한한다(self, qtbot):
        window = QWidget()
        qtbot.addWidget(window)
        window.resize(2400, 800)
        area = _VideoArea(QWidget(), parent=window)
        window.show()
        qtbot.waitExposed(window)

        capped = area.heightForWidth(2400)

        assert capped < 2400 * 9 // 16
        assert capped == int(800 * _VideoArea._MAX_WINDOW_RATIO)

    def test_배치_전_초기_크기에서는_제한하지_않는다(self, qtbot):
        """창 높이를 아직 모를 때 제한하면 영역이 찌부러진 채로 굳는다."""
        area = _VideoArea(QWidget())
        qtbot.addWidget(area)

        assert area.heightForWidth(1600) == 1600 * 9 // 16

    def test_최소_높이는_지킨다(self, qtbot):
        window = QWidget()
        qtbot.addWidget(window)
        window.resize(400, 240)
        area = _VideoArea(QWidget(), parent=window)
        window.show()
        qtbot.waitExposed(window)

        assert area.heightForWidth(100) >= _VideoArea._MIN_H
