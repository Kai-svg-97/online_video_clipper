"""`LibraryViewModel.loading_changed` — 목록 스켈레톤이 의지하는 로딩 신호.

기존 `loading_key_changed`는 트리 노드 키가 있을 때만(카테고리·재생목록 클릭)
발행됐다. 검색 조회(`set_search_text`)는 노드 키가 없어 어떤 로딩 신호도 내지
않았고, 그 결과 검색 중에는 화면이 아무 말도 하지 않았다(체감 지연이 가장 큰
경로). `loading_changed`는 노드 키 유무와 무관하게 **깊이 카운터**로 발행되어
이 경로를 메운다.
"""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal


def _drain(library_vm) -> None:
    for worker in list(library_vm._list_workers):
        worker.wait(3000)
    library_vm.shutdown()


class TestLoadingChangedSignal:
    def test_단일_조회는_시작과_종료에_로딩_신호를_낸다(self, qtbot, library_vm):
        states: list[bool] = []
        library_vm.loading_changed.connect(states.append)

        with qtbot.waitSignal(library_vm.loading_changed, timeout=2000):
            library_vm.load()

        qtbot.waitUntil(lambda: states == [True, False], timeout=2000)
        _drain(library_vm)

    def test_검색_조회도_로딩_신호를_낸다(self, qtbot, library_vm):
        """예전에는 검색 경로가 로딩 신호를 전혀 내지 않았다 — 이제는 낸다."""
        states: list[bool] = []
        library_vm.loading_changed.connect(states.append)

        library_vm.set_search_text("파이썬")

        qtbot.waitUntil(lambda: states == [True, False], timeout=2000)
        _drain(library_vm)

    def test_캐시_적중은_로딩_신호를_내지_않는다(self, qtbot, library_vm):
        states: list[bool] = []

        # 캐시를 데운다(첫 조회는 실제로 워커를 태운다).
        with qtbot.waitSignal(library_vm.loading_changed, timeout=2000):
            library_vm.load()
        qtbot.waitUntil(lambda: library_vm._list_inflight == 0, timeout=2000)
        _drain(library_vm)

        library_vm.loading_changed.connect(states.append)
        library_vm.load()  # 동일 필터 — 캐시 적중, 스피너 없이 즉시 표시

        assert states == []

    def test_겹치는_조회는_먼저_끝난_쪽이_로딩_신호를_끄지_않는다(
        self, qtbot, library_vm, monkeypatch
    ) -> None:
        """실제 스레드 타이밍에 의존하지 않도록, 워커를 가짜로 바꿔 완료 순서를
        직접 통제한다(첫 번째 조회를 먼저 등록하고, 두 번째가 아직 진행 중인
        상태에서 첫 번째만 끝내 본다)."""
        import gui.view_models.library_vm as vm_mod

        started: list[object] = []

        class _FakeWorker(QObject):
            finished_ok = pyqtSignal(list, bool)
            finished_err = pyqtSignal(str)
            finished = pyqtSignal()

            def __init__(self, fetch_fn, append, parent=None) -> None:
                super().__init__(parent)

            def start(self) -> None:
                started.append(self)

        monkeypatch.setattr(vm_mod, "_ListVideosWorker", _FakeWorker)

        states: list[bool] = []
        library_vm.loading_changed.connect(states.append)

        library_vm._refresh_videos(node_key="k1")
        library_vm._refresh_videos(node_key="k2")

        assert states == [True]  # 두 번째는 이미 로딩 중이므로 신호가 또 나지 않는다
        assert len(started) == 2

        # 첫 번째(느린 조회라 가정)가 먼저 끝났다 — 두 번째는 아직 진행 중.
        started[0].finished_ok.emit([], False)
        started[0].finished.emit()

        assert states == [True]  # 아직 하나가 진행 중이므로 False가 나오면 안 된다

        started[1].finished_ok.emit([], False)
        started[1].finished.emit()

        assert states == [True, False]
        assert library_vm._list_inflight == 0
