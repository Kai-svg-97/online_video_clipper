"""게이트에 걸린 다운로드를 화면이 어떻게 말하는가 — 그리고 멈출 수 있는가.

예약 시간대나 동시 한도에 걸린 작업은 **진행률이 영원히 0**이다. 카드에 '0%'로
그리면 멈춘 것처럼 보이고, 사용자는 왜 안 받는지 알 길이 없다(CLAUDE.md — 상태를
말하지 않는 화면을 만들지 않는다).

그리고 여기 말고는 다운로드를 **멈출 길이 없었다**. 잘못 넣은 주소나 몇 시간짜리
녹화를 되돌리려면 앱을 끄는 수밖에 없었다.
"""

from __future__ import annotations

from datetime import time
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QMenu

from gui.panels.download_panel import DownloadPanel, _HistoryModel
from gui.view_models.download_vm import DownloadViewModel


class _Bridge:
    def add_progress_listener(self, cb): pass
    def add_completed_listener(self, cb): pass
    def add_failed_listener(self, cb): pass


def _job(job_id, title="영상", status="pending"):
    from application.download.dtos import DownloadJobDTO

    return DownloadJobDTO(
        id=job_id, url=f"https://youtu.be/{str(job_id)[:11]}",
        title=title, status=status,
    )


@pytest.fixture
def cfg(monkeypatch):
    from config import settings as c
    monkeypatch.setattr(c, "MAX_CONCURRENT_DOWNLOADS", 2, raising=False)
    monkeypatch.setattr(c, "DOWNLOAD_WINDOW_ENABLED", False, raising=False)
    monkeypatch.setattr(c, "DOWNLOAD_WINDOW_START", 23, raising=False)
    monkeypatch.setattr(c, "DOWNLOAD_WINDOW_END", 7, raising=False)
    return c


def _freeze_hour(monkeypatch, hour: int) -> None:
    frozen = type("T", (), {"time": lambda self=None: time(hour, 0)})()
    monkeypatch.setattr(
        "gui.view_models.download_vm.datetime",
        type("D", (), {"now": staticmethod(lambda: frozen)}),
    )


@pytest.fixture
def vm(qapp_instance, monkeypatch):
    start = MagicMock()
    start.handle.side_effect = lambda cmd: type("Job", (), {"id": uuid4()})()
    model = DownloadViewModel(
        start_handler=start,
        cancel_handler=MagicMock(),
        queue_handler=MagicMock(handle=MagicMock(return_value=[])),
        history_handler=MagicMock(handle=MagicMock(return_value=[])),
        event_bridge=_Bridge(),
    )

    class _FakeWorker:
        def isRunning(self): return False
        def terminate(self): pass
        def wait(self, _ms=0): return True

    monkeypatch.setattr(
        model, "_launch",
        lambda jid: model._workers.__setitem__(jid, _FakeWorker()),
    )
    return model


class TestWaitingReason:
    def test_기다리는_게_없으면_아무_말도_하지_않는다(self, vm, cfg):
        assert vm.waiting_reason() == ""

    def test_시간대_때문이면_시간대를_말한다(self, vm, cfg, monkeypatch):
        monkeypatch.setattr(cfg, "DOWNLOAD_WINDOW_ENABLED", True, raising=False)
        _freeze_hour(monkeypatch, 12)      # 23~7 밖
        vm.start_download("https://y/a", "가")

        reason = vm.waiting_reason()
        assert "23시~7시" in reason
        assert "1건" in reason

    def test_자리_때문이면_한도를_말한다(self, vm, cfg):
        """시간대는 열려 있는데 앞 작업이 자리를 잡고 있는 경우."""
        for i in range(4):
            vm.start_download(f"https://y/{i}", f"{i}")

        reason = vm.waiting_reason()
        assert "동시 다운로드 2개" in reason
        assert "시간대" not in reason

    def test_기다리는_작업_id를_알려준다(self, vm, cfg):
        for i in range(4):
            vm.start_download(f"https://y/{i}", f"{i}")
        assert len(vm.waiting_ids) == vm.waiting_count == 2


class TestModelWaitingRole:
    def test_대기_중인_작업만_표시한다(self):
        running, waiting = uuid4(), uuid4()
        model = _HistoryModel()
        model.set_all(
            [_job(running), _job(waiting)], [], waiting_ids={waiting}
        )

        rows = {
            model.data(model.index(r, 0), _HistoryModel.JobRole).id:
                model.data(model.index(r, 0), _HistoryModel.IsWaitingRole)
            for r in range(model.rowCount())
        }
        assert rows[waiting] is True
        assert rows[running] is False

    def test_대기가_풀리면_그_줄만_다시_그린다(self):
        """구조가 그대로일 때 전체 갱신 없이 상태만 바꿀 수 있어야 한다."""
        waiting = uuid4()
        model = _HistoryModel()
        model.set_all([_job(waiting)], [], waiting_ids={waiting})
        changed: list = []
        model.dataChanged.connect(lambda a, b, roles: changed.append(roles))

        model.set_waiting(set())

        assert changed and _HistoryModel.IsWaitingRole in changed[0]
        assert model.data(model.index(0, 0), _HistoryModel.IsWaitingRole) is False

    def test_바뀐_게_없으면_다시_그리지_않는다(self):
        waiting = uuid4()
        model = _HistoryModel()
        model.set_all([_job(waiting)], [], waiting_ids={waiting})
        changed: list = []
        model.dataChanged.connect(lambda *a: changed.append(a))

        model.set_waiting({waiting})

        assert changed == []


class TestPanelNotice:
    @pytest.fixture
    def panel(self, qtbot, vm, cfg):
        p = DownloadPanel(vm)
        qtbot.addWidget(p)
        return p

    def test_기다리는_게_없으면_안내가_숨어_있다(self, panel):
        panel.refresh()
        assert panel._waiting_lbl.isHidden() is True

    def test_기다리면_이유를_띄운다(self, panel, vm, cfg):
        for i in range(4):
            vm.start_download(f"https://y/{i}", f"{i}")
        vm._queue_q.handle.return_value = [_job(j) for j in vm._pending]

        panel.refresh()

        assert panel._waiting_lbl.isHidden() is False
        assert "동시 다운로드" in panel._waiting_lbl.text()


class TestCancel:
    @pytest.fixture
    def panel(self, qtbot, vm, cfg):
        p = DownloadPanel(vm)
        qtbot.addWidget(p)
        return p

    def _first_index(self, panel):
        return panel._list.model().index(0, 0)

    def test_우클릭_취소가_그_작업을_멈춘다(self, panel, vm, cfg, monkeypatch):
        for i in range(4):
            vm.start_download(f"https://y/{i}", f"{i}")
        vm._queue_q.handle.return_value = [_job(j) for j in list(vm._workers) + vm._pending]
        panel.refresh()

        target = panel._list.model().data(self._first_index(panel), _HistoryModel.JobRole)
        monkeypatch.setattr(panel._list, "indexAt", lambda _pos: self._first_index(panel))
        # exec()는 사용자 입력을 기다린다 — 메뉴의 첫 항목을 고른 셈 친다.
        monkeypatch.setattr(QMenu, "exec", lambda self, _pos=None: self.actions()[0])

        panel._show_card_menu(QPoint(1, 1))

        vm._cancel.handle.assert_called_once()
        assert vm._cancel.handle.call_args[0][0].job_id == target.id

    def test_끝난_카드에는_취소가_뜨지_않는다(self, panel, vm, cfg, monkeypatch):
        """이력 카드에 '취소'를 띄우면 누를 수는 있는데 아무 일도 없다."""
        done = _job(uuid4())
        vm._history_q.handle.return_value = [done]
        panel.refresh()

        monkeypatch.setattr(panel._list, "indexAt", lambda _pos: self._first_index(panel))
        called: list = []
        monkeypatch.setattr(QMenu, "exec", lambda self, _pos=None: called.append(1))

        panel._show_card_menu(QPoint(1, 1))

        assert called == []
