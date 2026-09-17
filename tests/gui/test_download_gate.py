"""다운로드 큐 게이트 — 동시 실행 수와 예약 시간대.

**예전에는 게이트가 없었다.** 설정 화면의 "동시 다운로드 수"는 표시만 되고 아무 데서도
쓰이지 않아, 요청이 올 때마다 워커가 곧바로 떴다(사실상 무제한). 그 구멍을 막은
회귀 테스트다.
"""

from __future__ import annotations

from datetime import time
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from gui.view_models.download_vm import DownloadViewModel


class _Bridge:
    def add_progress_listener(self, cb): pass
    def add_completed_listener(self, cb): pass
    def add_failed_listener(self, cb): pass


@pytest.fixture
def vm(qapp_instance, monkeypatch):
    """워커를 실제로 띄우지 않는 뷰모델 — 게이트 판정만 본다."""
    start = MagicMock()
    start.handle.side_effect = lambda cmd: type("Job", (), {"id": uuid4()})()
    model = DownloadViewModel(
        start_handler=start,
        cancel_handler=MagicMock(),
        queue_handler=MagicMock(handle=MagicMock(return_value=[])),
        history_handler=MagicMock(handle=MagicMock(return_value=[])),
        event_bridge=_Bridge(),
    )
    launched: list = []

    class _FakeWorker:
        """실제 QThread 대신 — 게이트 판정만 보므로 수명 메서드만 흉내 낸다."""

        def isRunning(self):
            return False

        def terminate(self):
            pass

        def wait(self, _ms=0):
            return True

    monkeypatch.setattr(
        model,
        "_launch",
        lambda jid: (launched.append(jid), model._workers.__setitem__(jid, _FakeWorker())),
    )
    model.launched = launched          # type: ignore[attr-defined]
    return model


@pytest.fixture
def cfg(monkeypatch):
    from config import settings as c
    monkeypatch.setattr(c, "MAX_CONCURRENT_DOWNLOADS", 2, raising=False)
    monkeypatch.setattr(c, "DOWNLOAD_WINDOW_ENABLED", False, raising=False)
    monkeypatch.setattr(c, "DOWNLOAD_WINDOW_START", 23, raising=False)
    monkeypatch.setattr(c, "DOWNLOAD_WINDOW_END", 7, raising=False)
    return c


def _freeze_hour(monkeypatch, hour: int) -> None:
    """`datetime.now()`를 고정한다 — 실제 시각에 따라 결과가 흔들리면 안 된다."""
    frozen = type("T", (), {"time": lambda self=None: time(hour, 0)})()
    monkeypatch.setattr(
        "gui.view_models.download_vm.datetime",
        type("D", (), {"now": staticmethod(lambda: frozen)}),
    )


def _enqueue(vm, n):
    for i in range(n):
        vm.start_download(f"https://y/{i}", f"영상{i}")


class TestConcurrencyLimit:
    def test_한도만큼만_시작한다(self, vm, cfg):
        _enqueue(vm, 5)
        assert len(vm.launched) == 2
        assert vm.waiting_count == 3

    def test_하나가_끝나면_다음이_올라간다(self, vm, cfg):
        _enqueue(vm, 3)
        finished = vm.launched[0]
        vm._cleanup_worker(finished)
        assert len(vm.launched) == 3
        assert vm.waiting_count == 0

    def test_한도가_1이면_한_번에_하나다(self, vm, cfg, monkeypatch):
        monkeypatch.setattr(cfg, "MAX_CONCURRENT_DOWNLOADS", 1, raising=False)
        _enqueue(vm, 3)
        assert len(vm.launched) == 1

    def test_한도를_벗어난_설정값은_잘린다(self, vm, cfg, monkeypatch):
        monkeypatch.setattr(cfg, "MAX_CONCURRENT_DOWNLOADS", 99, raising=False)
        _enqueue(vm, 20)
        assert len(vm.launched) == 8      # MAX_CONCURRENT

    def test_먼저_넣은_것이_먼저_시작한다(self, vm, cfg):
        _enqueue(vm, 4)
        first_two = list(vm.launched)
        vm._cleanup_worker(first_two[0])
        vm._cleanup_worker(first_two[1])
        assert len(vm.launched) == 4      # FIFO 로 나머지 둘이 올라왔다


class TestScheduleWindow:
    def test_시간대_밖이면_시작하지_않는다(self, vm, cfg, monkeypatch):
        monkeypatch.setattr(cfg, "DOWNLOAD_WINDOW_ENABLED", True, raising=False)
        monkeypatch.setattr(cfg, "DOWNLOAD_WINDOW_START", 3, raising=False)
        monkeypatch.setattr(cfg, "DOWNLOAD_WINDOW_END", 4, raising=False)
        _freeze_hour(monkeypatch, 12)
        _enqueue(vm, 2)
        assert vm.launched == []
        assert vm.waiting_count == 2

    def test_기다리는_동안_타이머가_돈다(self, vm, cfg, monkeypatch):
        """창이 열리는 순간을 놓치지 않으려면 깨어 있어야 한다."""
        monkeypatch.setattr(cfg, "DOWNLOAD_WINDOW_ENABLED", True, raising=False)
        monkeypatch.setattr(cfg, "DOWNLOAD_WINDOW_START", 3, raising=False)
        monkeypatch.setattr(cfg, "DOWNLOAD_WINDOW_END", 4, raising=False)
        _freeze_hour(monkeypatch, 12)
        _enqueue(vm, 1)
        assert vm._window_timer.isActive()

    def test_시간대가_열리면_시작한다(self, vm, cfg, monkeypatch):
        monkeypatch.setattr(cfg, "DOWNLOAD_WINDOW_ENABLED", True, raising=False)
        monkeypatch.setattr(cfg, "DOWNLOAD_WINDOW_START", 9, raising=False)
        monkeypatch.setattr(cfg, "DOWNLOAD_WINDOW_END", 18, raising=False)
        _freeze_hour(monkeypatch, 10)
        _enqueue(vm, 1)
        assert len(vm.launched) == 1
        assert not vm._window_timer.isActive()

    def test_대기가_없으면_타이머를_멈춘다(self, vm, cfg):
        """유휴 상태에서 1분마다 깨어날 이유가 없다."""
        _enqueue(vm, 1)
        assert not vm._window_timer.isActive()


class TestCancel:
    def test_시작_전_취소는_대기줄에서_뺀다(self, vm, cfg):
        _enqueue(vm, 4)
        waiting = vm._pending[0]
        vm.cancel_download(waiting)
        assert waiting not in vm._pending
        assert vm.waiting_count == 1

    def test_종료하면_대기줄을_비운다(self, vm, cfg):
        _enqueue(vm, 5)
        vm.shutdown()
        assert vm.waiting_count == 0
        assert not vm._window_timer.isActive()
