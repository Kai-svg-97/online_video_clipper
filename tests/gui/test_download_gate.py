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


class TestLiveRecording:
    """녹화는 게이트를 우회한다 — 방송은 지금 아니면 받을 수 없다."""

    def test_시간대가_닫혀_있어도_즉시_시작한다(self, vm, cfg, monkeypatch):
        """대기줄에 묶이면 그동안 방송이 끝난다."""
        monkeypatch.setattr(cfg, "DOWNLOAD_WINDOW_ENABLED", True, raising=False)
        monkeypatch.setattr(cfg, "DOWNLOAD_WINDOW_START", 3, raising=False)
        monkeypatch.setattr(cfg, "DOWNLOAD_WINDOW_END", 4, raising=False)
        _freeze_hour(monkeypatch, 12)

        assert vm.start_live_recording("https://y/live", "생방송") is True
        assert len(vm.launched) == 1
        assert vm.waiting_count == 0

    def test_동시_다운로드_한도가_차_있어도_시작한다(self, vm, cfg):
        _enqueue(vm, 5)                     # 한도 2를 이미 채운다
        assert len(vm.launched) == 2

        assert vm.start_live_recording("https://y/live", "생방송") is True
        assert len(vm.launched) == 3

    def test_녹화_자체_상한은_지킨다(self, vm, cfg):
        """녹화는 몇 시간씩 이어져 쌓아 두면 디스크가 먼저 찬다."""
        from domain.download.live import MAX_CONCURRENT_RECORDINGS

        for i in range(MAX_CONCURRENT_RECORDINGS):
            assert vm.start_live_recording(f"https://y/l{i}", f"방송{i}") is True
        assert vm.start_live_recording("https://y/over", "초과") is False
        assert len(vm.launched) == MAX_CONCURRENT_RECORDINGS

    def test_녹화는_일반_다운로드_자리를_막지_않는다(self, vm, cfg):
        """녹화를 한도 계산에 넣으면 장시간 녹화 하나가 큐를 통째로 멈춘다."""
        vm.start_live_recording("https://y/live", "생방송")
        _enqueue(vm, 3)
        # 녹화 1 + 일반 2(한도) = 3
        assert len(vm.launched) == 3
        assert vm.waiting_count == 1

    def test_녹화가_끝나면_자리를_돌려준다(self, vm, cfg):
        vm.start_live_recording("https://y/live", "생방송")
        rec_id = vm.launched[0]
        assert vm.recording_count == 1

        vm._cleanup_worker(rec_id)

        assert vm.recording_count == 0
        assert not vm.is_recording(rec_id)

    def test_녹화_여부를_알려준다(self, vm, cfg):
        """화면이 진행률 대신 경과·용량을 보여줄지 판단하는 근거."""
        vm.start_live_recording("https://y/live", "생방송")
        rec_id = vm.launched[0]
        _enqueue(vm, 1)
        normal_id = vm.launched[1]

        assert vm.is_recording(rec_id)
        assert not vm.is_recording(normal_id)

    def test_종료하면_녹화_목록도_비운다(self, vm, cfg):
        vm.start_live_recording("https://y/live", "생방송")
        vm.shutdown()
        assert vm.recording_count == 0


class TestLiveProbeRouting:
    """대기하게 된 작업만 라이브인지 확인하고, 방송 중이면 대기줄에서 빼낸다."""

    @pytest.fixture
    def probing_vm(self, qapp_instance, monkeypatch):
        from gui.view_models.download_vm import DownloadViewModel

        asked: list[str] = []

        def probe(url):
            asked.append(url)
            return "live" if "live" in url else "not_live"

        start = MagicMock()
        start.handle.side_effect = lambda cmd: type("Job", (), {"id": uuid4()})()
        model = DownloadViewModel(
            start_handler=start,
            cancel_handler=MagicMock(),
            queue_handler=MagicMock(handle=MagicMock(return_value=[])),
            history_handler=MagicMock(handle=MagicMock(return_value=[])),
            event_bridge=_Bridge(),
            live_status_fn=probe,
        )
        launched: list = []

        class _FakeWorker:
            def isRunning(self): return False
            def terminate(self): pass
            def wait(self, _ms=0): return True

        monkeypatch.setattr(
            model, "_launch",
            lambda jid: (launched.append(jid), model._workers.__setitem__(jid, _FakeWorker())),
        )
        # 실제 QThread 를 띄우지 않고 판정만 본다.
        monkeypatch.setattr(model, "_probe_live", lambda jid, url: model._on_live_probed(jid, probe(url)))
        model.launched = launched      # type: ignore[attr-defined]
        model.asked = asked            # type: ignore[attr-defined]
        return model

    def test_곧바로_시작하면_묻지_않는다(self, probing_vm, cfg):
        """모든 다운로드에 메타데이터 조회를 끼우면 흔한 경우가 1초씩 느려진다."""
        probing_vm.start_download("https://y/live1", "방송")
        assert probing_vm.asked == []
        assert len(probing_vm.launched) == 1

    def test_대기하게_되면_묻는다(self, probing_vm, cfg):
        for i in range(3):                       # 한도 2 → 세 번째가 대기
            probing_vm.start_download(f"https://y/normal{i}", f"영상{i}")
        assert probing_vm.asked == ["https://y/normal2"]

    def test_방송_중이면_대기줄에서_빼내_녹화한다(self, probing_vm, cfg):
        probing_vm.start_download("https://y/normal0", "영상0")
        probing_vm.start_download("https://y/normal1", "영상1")
        assert probing_vm.waiting_count == 0

        probing_vm.start_download("https://y/live-now", "생방송")

        assert probing_vm.waiting_count == 0          # 대기하지 않고
        assert probing_vm.recording_count == 1        # 녹화로 돌았다
        assert len(probing_vm.launched) == 3

    def test_라이브가_아니면_그대로_대기한다(self, probing_vm, cfg):
        for i in range(3):
            probing_vm.start_download(f"https://y/normal{i}", f"영상{i}")
        assert probing_vm.waiting_count == 1
        assert probing_vm.recording_count == 0

    def test_판정_함수가_없으면_기능만_꺼진다(self, vm, cfg):
        """라이브 판정 없이도 큐는 평소대로 동작해야 한다."""
        _enqueue(vm, 3)
        assert vm.waiting_count == 1
        assert vm.recording_count == 0
