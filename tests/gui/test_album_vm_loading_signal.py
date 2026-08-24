"""`AlbumViewModel.loading_changed` — 앨범 그리드·상세 스켈레톤이 의지하는 로딩 신호.

`load_albums`·`load_detail`은 백그라운드 스레드를 태우기 **전에** 곧바로
`loading_changed.emit(True)`를 내어 스켈레톤을 즉시 보여줄 수 있게 하고, 조회가
끝나면(성공·실패 모두) `loading_changed.emit(False)`로 끈다.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from gui.view_models.album_vm import AlbumViewModel


def _drain(vm: AlbumViewModel) -> None:
    for worker in list(vm._workers):
        worker.wait(3000)


def _vm(get_albums=None, get_detail=None) -> AlbumViewModel:
    return AlbumViewModel(
        get_albums=get_albums or MagicMock(),
        get_detail=get_detail or MagicMock(),
    )


class TestAlbumLoadingSignal:
    def test_앨범_목록_조회는_시작과_종료에_로딩_신호를_낸다(self, qtbot) -> None:
        get_albums = MagicMock()
        get_albums.handle.return_value = []
        vm = _vm(get_albums=get_albums)
        states: list[bool] = []
        vm.loading_changed.connect(states.append)

        with qtbot.waitSignal(vm.albums_changed, timeout=2000):
            vm.load_albums()

        assert states == [True, False]
        _drain(vm)

    def test_앨범_상세_조회도_로딩_신호를_낸다(self, qtbot) -> None:
        get_detail = MagicMock()
        get_detail.handle.return_value = None
        vm = _vm(get_detail=get_detail)
        states: list[bool] = []
        vm.loading_changed.connect(states.append)

        with qtbot.waitSignal(vm.detail_ready, timeout=2000):
            vm.load_detail("artist\x1falbum")

        assert states == [True, False]
        _drain(vm)

    def test_조회가_실패해도_로딩_신호를_끈다(self, qtbot) -> None:
        get_albums = MagicMock()
        get_albums.handle.side_effect = RuntimeError("boom")
        vm = _vm(get_albums=get_albums)
        states: list[bool] = []
        vm.loading_changed.connect(states.append)

        with qtbot.waitSignal(vm.error_occurred, timeout=2000):
            vm.load_albums()

        assert states == [True, False]
        _drain(vm)
