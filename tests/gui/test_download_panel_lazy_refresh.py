"""DownloadPanel 지연 갱신 — 숨은 동안은 DB를 읽지 않는다 (성능 배치 1, A2).

시작 때 보이지도 않는 다운로드 화면이 이력 50건을 읽고 카드를 만들던 비용을 없앤다.
시간 수치가 아니라 **핸들러 호출 횟수**로 고정한다.
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import QCoreApplication

from gui.panels.download_panel import DownloadPanel


def _pump() -> None:
    # singleShot(0) 예약을 집행한다 — 두 번 돌려야 중첩 예약까지 끝난다.
    QCoreApplication.processEvents()
    QCoreApplication.processEvents()


@pytest.fixture
def panel(qtbot, download_vm):
    p = DownloadPanel(download_vm)
    qtbot.addWidget(p)
    return p


def _hist(vm) -> int:
    return vm._history_q.handle.call_count


def _queue(vm) -> int:
    return vm._queue_q.handle.call_count


class TestLazyRefresh:
    def test_숨은_채_생성하면_아무것도_읽지_않는다(self, panel, download_vm):
        _pump()
        assert _hist(download_vm) == 0
        assert _queue(download_vm) == 0

    def test_처음_보일_때_정확히_한_번_갱신한다(self, panel, download_vm, qtbot):
        panel.show()
        qtbot.waitExposed(panel)
        assert _hist(download_vm) == 1
        _pump()
        assert _hist(download_vm) == 1  # 중복 예약 없음

    def test_숨은_동안의_신호는_쌓아_두고_보일_때_한_번만_갱신한다(
        self, panel, download_vm, qtbot
    ):
        for _ in range(3):
            download_vm.history_changed.emit()
        for _ in range(5):
            download_vm.queue_changed.emit()
        _pump()
        assert _hist(download_vm) == 0
        assert _queue(download_vm) == 0

        panel.show()
        qtbot.waitExposed(panel)
        assert _hist(download_vm) == 1
        assert panel._refresh_dirty is False

    def test_바뀐_것_없이_다시_보여도_갱신하지_않는다(self, panel, download_vm, qtbot):
        panel.show()
        qtbot.waitExposed(panel)
        assert _hist(download_vm) == 1
        panel.hide()
        panel.show()
        _pump()
        assert _hist(download_vm) == 1

    def test_보이는_동안의_이력_신호는_즉시_반영한다(self, panel, download_vm, qtbot):
        panel.show()
        qtbot.waitExposed(panel)
        h0 = _hist(download_vm)

        download_vm.history_changed.emit()

        # 동기 — dirty 표시만 하고 끝나면 안 된다(보이는 패널의 회귀).
        assert _hist(download_vm) == h0 + 1

    def test_보이는_동안의_큐_신호는_경량_경로로_즉시_반영한다(
        self, panel, download_vm, qtbot
    ):
        panel.show()
        qtbot.waitExposed(panel)
        h0, q0 = _hist(download_vm), _queue(download_vm)

        download_vm.queue_changed.emit()

        assert _queue(download_vm) == q0 + 1
        assert _hist(download_vm) == h0  # 활성 작업이 그대로면 이력은 다시 읽지 않는다

    def test_명시_refresh는_숨어_있어도_실행한다(self, panel, download_vm):
        assert panel.isVisible() is False
        panel.refresh()
        assert _hist(download_vm) == 1

    def test_보이다_숨은_뒤의_신호는_다음_표시에서_반영한다(
        self, panel, download_vm, qtbot
    ):
        panel.show()
        qtbot.waitExposed(panel)
        base = _hist(download_vm)
        panel.hide()

        download_vm.history_changed.emit()
        assert _hist(download_vm) == base
        assert panel._refresh_dirty is True

        panel.show()
        assert _hist(download_vm) == base + 1
