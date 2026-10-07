"""진행률 신호 합치기 (성능 배치 4, B2 축소).

yt-dlp 의 진행 콜백은 초당 수십 번 오고, 그때마다 `queue_changed` 가 나가면 다운로드
화면이 `vm.queue` 조회(DB)와 모델 갱신을 그 횟수만큼 한다. VM 에서 작업당 4~10Hz 로
합친다. **완료·실패·취소는 합치지 않고 즉시** 보낸다 — 사용자가 기다리는 순간이다.

메인 세션 결정(고정): 진행률 합치기 주기는 `PROGRESS_MIN_INTERVAL_MS`(100~250ms),
시계는 모듈 수준 `_now`(= `time.monotonic`)다.

시계는 가짜로 바꾸고, 타이머 기반 trailing 은 이벤트 루프를 돌려서 집행한다
(`qtbot.wait` — 시간 맞추기용 sleep 이 아니라 Qt 타이머를 돌리는 방법이다).
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QThread, Qt

from gui.view_models.download_vm import DownloadViewModel

_CLOCK = "gui.view_models.download_vm._now"
_INTERVAL = getattr(DownloadViewModel, "PROGRESS_MIN_INTERVAL_MS", 250)


class _Bridge:
    """리스너를 **저장**한다 — 시험이 콜백을 직접 부른다."""

    def __init__(self) -> None:
        self.progress_cb = None
        self.completed_cb = None
        self.failed_cb = None

    def add_progress_listener(self, cb):
        self.progress_cb = cb

    def add_completed_listener(self, cb):
        self.completed_cb = cb

    def add_failed_listener(self, cb):
        self.failed_cb = cb


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    # 시계 시드가 아직 없어도(구현 전) 동작 시험이 '속성 없음'이 아니라 실제 횟수로 실패하게 한다.
    monkeypatch.setattr(_CLOCK, c, raising=False)
    return c


@pytest.fixture
def bridge():
    return _Bridge()


@pytest.fixture
def vm(qapp_instance, bridge, clock):
    model = DownloadViewModel(
        start_handler=MagicMock(),
        cancel_handler=MagicMock(),
        queue_handler=MagicMock(handle=MagicMock(return_value=[])),
        history_handler=MagicMock(handle=MagicMock(return_value=[])),
        event_bridge=bridge,
    )
    model._last_finished_title = lambda: "t"
    yield model
    model.shutdown()


class _Probe:
    """신호를 **직접 연결**로 받아 순서와 스레드를 기록한다(큐잉 없이 방출 시점이 보인다)."""

    def __init__(self, vm, *, direct: bool = True) -> None:
        self.seq: list[str] = []
        self.queue = 0
        self.history = 0
        self.finished: list[tuple] = []
        self.errors: list[str] = []
        self.threads_ok: list[bool] = []
        # direct=False 는 앱이 쓰는 기본(Auto) 연결 — 워커 스레드에서 방출돼도 수신은 GUI 스레드다.
        kind = (
            Qt.ConnectionType.DirectConnection if direct else Qt.ConnectionType.AutoConnection
        )
        vm.queue_changed.connect(self._queue, kind)
        vm.history_changed.connect(self._history, kind)
        vm.job_finished.connect(self._finished, kind)
        vm.error_occurred.connect(self._error, kind)

    def _queue(self):
        self.queue += 1
        self.seq.append("emit")
        self.threads_ok.append(QThread.currentThread() is _gui_thread())

    def _history(self):
        self.history += 1

    def _finished(self, ok, text):
        self.finished.append((ok, text))

    def _error(self, msg):
        self.errors.append(msg)

    def call(self):
        self.seq.append("call")


def _gui_thread():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance().thread()


class TestProgressThrottle:
    def test_시계_시드와_주기_상수가_있다(self):
        import gui.view_models.download_vm as mod

        assert hasattr(mod, "_now")
        assert 100 <= DownloadViewModel.PROGRESS_MIN_INTERVAL_MS <= 250

    def test_같은_스레드_폭주는_합치고_마지막_상태는_뒤에_반드시_전달된다(
        self, vm, bridge, clock, qtbot
    ):
        probe = _Probe(vm)
        clock.t = 0.0

        for _ in range(200):
            probe.call()
            bridge.progress_cb()

        # 폭주 직후: 앞 1회(+ 즉시 뒤따른 1회까지 허용). 현행은 200회다.
        assert 1 <= probe.queue <= 2, f"queue_changed {probe.queue}회 — 합쳐지지 않았다"

        # 시간이 흐르면 trailing 이 한 번 나가 **마지막 상태**를 전달한다.
        clock.t += 1.0
        qtbot.wait(_INTERVAL * 3)

        assert probe.queue <= 3
        # 마지막 호출 뒤에 방출이 한 번 이상 있었다 — 마지막 상태를 버리지 않는다.
        assert probe.seq[-1] == "emit", "마지막 진행 상태가 전달되지 않았다(trailing 없음)"

    def test_워커_스레드의_폭주도_합쳐지고_신호는_GUI_스레드에서_받는다(
        self, vm, bridge, clock, qtbot
    ):
        probe = _Probe(vm, direct=False)

        def work():
            for _ in range(200):
                bridge.progress_cb()

        t = threading.Thread(target=work)
        t.start()
        t.join(timeout=5)
        assert not t.is_alive()

        qtbot.waitUntil(lambda: probe.queue >= 1, timeout=2000)
        clock.t += 1.0
        qtbot.wait(_INTERVAL * 3)   # 이벤트 루프를 돌려 trailing 타이머를 집행한다

        assert 1 <= probe.queue <= 3, f"queue_changed {probe.queue}회"
        assert probe.threads_ok and all(probe.threads_ok), "GUI 스레드 밖에서 신호를 받았다"

    def test_완료는_합치지_않고_즉시_보낸다(self, vm, bridge, clock):
        probe = _Probe(vm)
        clock.t = 0.0
        for _ in range(5):
            bridge.progress_cb()
        before = probe.queue

        # 이벤트 루프를 돌리지 않는다 — 같은 호출 안에서 나가야 한다.
        bridge.completed_cb()

        assert probe.queue - before >= 1
        assert probe.history == 1
        assert probe.finished == [(True, "t")]

    def test_실패도_즉시_보내고_기존_실패_신호를_유지한다(self, vm, bridge, clock):
        probe = _Probe(vm)
        clock.t = 0.0
        for _ in range(5):
            bridge.progress_cb()
        before = probe.queue

        bridge.failed_cb("boom")

        assert probe.queue - before >= 1
        assert probe.finished == [(False, "boom")]
        assert len(probe.errors) == 1 and "boom" in probe.errors[0]

    def test_주기_상한은_1초보다_짧다(self):
        """C5 의 1Hz 이상 갱신 보장 — 합치기 주기가 그보다 길면 라이브 카드가 굼뜨다."""
        assert DownloadViewModel.PROGRESS_MIN_INTERVAL_MS < 1000

    def test_shutdown_뒤_남은_trailing_타이머가_터져도_예외가_없다(
        self, vm, bridge, clock, qtbot
    ):
        _Probe(vm)
        clock.t = 0.0
        for _ in range(50):
            bridge.progress_cb()

        vm.shutdown()
        clock.t += 1.0

        qtbot.wait(_INTERVAL * 2)   # pytest-qt 가 슬롯 안 예외를 실패로 바꾼다
