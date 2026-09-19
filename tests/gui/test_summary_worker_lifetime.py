"""요약 워커 수명 — 끝난 뒤 레지스트리를 놓아 주는가.

요약 추출은 수십 초 걸리는 QThread다. 여기서 수명을 잘못 다루면 증상이 **종료할 때**
나타나 원인을 찾기 어렵다.

예전 코드는 `worker.finished.connect(worker.deleteLater)`를 걸었다. 그러면 끝나는
순간 C++ 객체가 사라지는데, `gui/workers.py`의 레지스트리에는 그 객체가 그대로 남는다.
종료 시 `wait_all()`이 거기서 `RuntimeError`를 내고, 그것이 `closeEvent` 밖으로 새면
**나머지 워커를 아무도 기다려 주지 않는다** — 실행 중 QThread가 파괴되며 프로세스가
죽는 바로 그 경로다(CLAUDE.md).
"""

from __future__ import annotations

import gui.workers as workers
from gui.workers import running_count, track_thread, wait_all


class _Dead:
    """파괴된 C++ 객체를 흉내 낸다 — 무엇을 물어도 RuntimeError."""

    def isRunning(self):
        raise RuntimeError("wrapped C/C++ object has been deleted")

    def wait(self, _ms=0):
        raise RuntimeError("wrapped C/C++ object has been deleted")


class _Alive:
    def __init__(self):
        self.waited = False

    def isRunning(self):
        return True

    def wait(self, _ms=0):
        self.waited = True
        return True


class TestWaitAllSurvivesDeadWorker:
    def test_죽은_워커가_있어도_터지지_않는다(self, qapp_instance):
        dead = _Dead()
        workers._RUNNING.add(dead)
        try:
            wait_all(10)          # 예외가 새면 종료 경로가 무너진다
        finally:
            workers._RUNNING.discard(dead)

    def test_죽은_워커를_레지스트리에서_걷어낸다(self, qapp_instance):
        dead = _Dead()
        workers._RUNNING.add(dead)
        before = running_count()

        wait_all(10)

        assert running_count() == before - 1

    def test_죽은_워커_뒤의_살아_있는_워커도_기다린다(self, qapp_instance):
        """중간에 터지면 그 뒤가 통째로 건너뛰어진다 — 가장 위험한 경우다."""
        dead, alive = _Dead(), _Alive()
        workers._RUNNING.add(dead)
        workers._RUNNING.add(alive)
        try:
            wait_all(10)
            assert alive.waited is True
        finally:
            workers._RUNNING.discard(dead)
            workers._RUNNING.discard(alive)


class TestSummaryMixinDoesNotDeleteWorker:
    def test_금지된_deleteLater를_걸지_않는다(self):
        """이 한 줄이 종료 경로를 깨뜨렸다 — AST가 아니라 소스로 고정한다."""
        from pathlib import Path

        src = Path("gui/panels/detail/mixins/summary.py").read_text(encoding="utf-8")
        # 주석으로 남긴 설명은 괜찮다 — 실제 호출만 막는다.
        calls = [
            ln for ln in src.splitlines()
            if "deleteLater" in ln and not ln.lstrip().startswith("#")
        ]
        assert calls == []

    def test_끝나면_레지스트리를_놓아_준다(self, qapp_instance):
        from pathlib import Path

        src = Path("gui/panels/detail/mixins/summary.py").read_text(encoding="utf-8")
        assert "retire_thread(self._gemini_worker" in src


class TestTrackedWorkerRoundTrip:
    def test_등록하고_놓으면_수가_돌아온다(self, qapp_instance):
        from PyQt6.QtCore import QThread

        before = running_count()
        worker = track_thread(QThread())
        assert running_count() == before + 1

        workers._release(worker)
        assert running_count() == before


class TestRefreshTellsWhyItDidNothing:
    """⟳ 가 조용히 돌아가면 "기능이 죽었다"로 보이고 로그에도 흔적이 없다.

    실제로 이 침묵 때문에 원인 추적이 막혔다 — 설치본 로그에 요약 관련 기록이
    한 줄도 없어, 버튼을 눌렀는지조차 알 수 없었다.
    """

    def _widget(self, qtbot):
        from gui.panels.video_detail_panel import VideoDetailWidget

        w = VideoDetailWidget()
        qtbot.addWidget(w)
        return w

    def test_표시_중인_영상이_없으면_그렇게_말한다(self, qtbot):
        w = self._widget(qtbot)
        w._detail = None

        w._on_refresh_summary()

        assert w._summary_status_lbl.text()

    def test_스트리밍_영상이면_담으라고_말한다(self, qtbot):
        from types import SimpleNamespace
        from uuid import uuid4

        w = self._widget(qtbot)
        w._detail = SimpleNamespace(id=uuid4(), url="https://youtu.be/x")
        w._streaming = True

        w._on_refresh_summary()

        assert "라이브러리" in w._summary_status_lbl.text()

    def test_이미_돌고_있으면_중복으로_띄우지_않는다(self, qtbot, monkeypatch):
        from types import SimpleNamespace
        from uuid import uuid4

        import gui.panels.detail.mixins.summary as sm

        started = []
        monkeypatch.setattr(
            sm, "_GeminiSummaryWorker",
            lambda *a, **k: started.append(1) or SimpleNamespace(
                done=SimpleNamespace(connect=lambda *_: None), start=lambda: None
            ),
        )
        monkeypatch.setattr(sm, "track_thread", lambda w, *a, **k: w)

        w = self._widget(qtbot)
        w._detail = SimpleNamespace(id=uuid4(), url="https://youtu.be/x")
        w._streaming = False
        w._gemini_worker = object()          # 이미 진행 중

        w._on_refresh_summary()

        assert started == []
        assert "이미" in w._summary_status_lbl.text()
