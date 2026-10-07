"""MonitoringVM.load 가 한 번만 돈다 — 라이브러리 패널과 모니터링 패널 (성능 배치 1, B3-b).

두 패널이 각자 `singleShot(0, vm.load)` 를 예약해 구독 조회가 두 번 돌던 것을 하나로 합친다.
하나만 도는 대신 **두 화면 모두** 신호로 갱신돼야 한다.
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import QCoreApplication

from gui.panels.library_panel import LibraryPanel
from gui.panels.monitoring_panel import MonitoringPanel


def _pump() -> None:
    QCoreApplication.processEvents()
    QCoreApplication.processEvents()


def _build(qtbot, library_vm, download_vm, clip_vm, monitoring_vm, monkeypatch):
    import config.settings as settings

    monkeypatch.setattr(settings, "save_setting", lambda *a, **k: None)
    monkeypatch.setattr(library_vm, "load", lambda *a, **k: None)
    # MainWindow 와 같은 순서 — 라이브러리 먼저, 모니터링 다음.
    lib = LibraryPanel(
        vm=library_vm, clip_vm=clip_vm, download_vm=download_vm,
        monitoring_vm=monitoring_vm,
    )
    qtbot.addWidget(lib)
    mon = MonitoringPanel(monitoring_vm)
    qtbot.addWidget(mon)
    return lib, mon


@pytest.fixture
def cleanup(library_vm):
    yield
    for worker in list(library_vm._list_workers):
        worker.wait(3000)
    library_vm.shutdown()


class TestSingleLoad:
    def test_구독_조회는_정확히_한_번이다(
        self, qtbot, library_vm, download_vm, clip_vm, monitoring_vm, monkeypatch, cleanup
    ):
        _keep = _build(qtbot, library_vm, download_vm, clip_vm, monitoring_vm, monkeypatch)
        _pump()
        assert monitoring_vm._get_subs.handle.call_count == 1

    def test_두_화면이_모두_갱신된다(
        self, qtbot, library_vm, download_vm, clip_vm, monitoring_vm, monkeypatch, cleanup
    ):
        calls: list[str] = []
        # 바운드 메서드는 connect 시점에 묶이므로 패널 생성 전에 클래스에 건다.
        monkeypatch.setattr(
            MonitoringPanel, "_refresh_list",
            lambda self, *a: calls.append("list"),
        )
        monkeypatch.setattr(
            LibraryPanel, "_refresh_unified_tree",
            lambda self, *a: calls.append("tree"),
        )
        _keep = _build(qtbot, library_vm, download_vm, clip_vm, monitoring_vm, monkeypatch)
        _pump()
        assert sorted(calls) == ["list", "tree"]

    def test_실패해도_오류_신호는_한_번이다(
        self, qtbot, library_vm, download_vm, clip_vm, monitoring_vm, monkeypatch, cleanup
    ):
        monitoring_vm._get_subs.handle.side_effect = RuntimeError("x")
        errors: list[str] = []
        monitoring_vm.error_occurred.connect(errors.append)
        _keep = _build(qtbot, library_vm, download_vm, clip_vm, monitoring_vm, monkeypatch)
        _pump()
        assert len(errors) == 1  # 2회면 중복 load 회귀
