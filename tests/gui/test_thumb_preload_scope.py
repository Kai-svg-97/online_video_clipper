"""썸네일 프리로드 범위·뷰 전환 (성능 배치 7, A7).

회귀 배경:
* 다음 쪽이 붙을 때마다 **누적 목록 전체**를 다시 프리로드 요청했다(쪽 N개면 N*50건).
* 아이콘 뷰에서 리스트 뷰로 바꿔도 리스트 크기(213x120) 프리로드가 시작되지 않아,
  스크롤할 때마다 캐시 미스를 겪었다.

로더는 가짜로 바꿔 **무엇을 넘겼는지**만 본다(실제 디코드는 `test_thumbnail_decode.py`).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from PyQt6.QtCore import QThread, pyqtSignal

from application.library.dtos import VideoDTO
from gui.panels.library.constants import _TH_ICON, _TH_LIST, _TW_ICON, _TW_LIST
from gui.panels.library_panel import _VIEW_ICON, _VIEW_LIST, LibraryPanel


class FakeLoader(QThread):
    """넘겨받은 항목만 기록하고 즉시 끝나는 로더."""

    batch_ready = pyqtSignal(list)
    instances: list["FakeLoader"] = []

    def __init__(self, items, parent=None) -> None:
        super().__init__(parent)
        self.items = list(items)
        self.cancelled = False
        FakeLoader.instances.append(self)

    def cancel(self) -> None:
        self.cancelled = True

    def run(self) -> None:
        return


def _dto(i: int) -> VideoDTO:
    return VideoDTO(
        id=uuid4(),
        url=f"https://youtu.be/scope{i:05d}",
        title=f"영상 {i}",
        channel_name="채널",
        thumbnail_path=f"scope_{i}.jpg",
        duration_sec=60,
        favorite=False,
        watched=False,
        category_id=None,
    )


def _drain(qtbot) -> None:
    def all_done() -> bool:
        for inst in FakeLoader.instances:
            try:
                if not inst.isFinished():
                    return False
            except RuntimeError:
                continue
        return True

    qtbot.waitUntil(all_done, timeout=3000)


@pytest.fixture
def panel(qtbot, library_vm, download_vm, clip_vm, monkeypatch):
    FakeLoader.instances = []
    # 쓰는 쪽 모듈을 패치한다(재수출 이름은 소용없다).
    monkeypatch.setattr("gui.panels.library.mixins.video_list._ThumbBgLoader", FakeLoader)
    p = LibraryPanel(vm=library_vm, clip_vm=clip_vm, download_vm=download_vm)
    # 이벤트를 돌리는 동안 뷰포트 채우기가 목록을 다시 읽어 갈아 끼우지 않게 한다.
    monkeypatch.setattr(p, "_maybe_fill_viewport", lambda: None)
    qtbot.addWidget(p)
    p._view_stack.setCurrentIndex(_VIEW_ICON)
    FakeLoader.instances.clear()
    yield p
    _drain(qtbot)
    for worker in list(library_vm._list_workers):
        worker.wait(3000)
    library_vm.shutdown()


class TestPreloadScope:
    def test_첫_쪽은_50건을_넘긴다(self, panel, library_vm, qtbot):
        library_vm._videos = [_dto(i) for i in range(50)]

        panel._on_videos_changed()

        assert len(FakeLoader.instances) == 1
        assert len(FakeLoader.instances[0].items) == 50
        _drain(qtbot)

    def test_다음_쪽이_붙으면_새로_붙은_쪽만_넘긴다(self, panel, library_vm, qtbot):
        videos = [_dto(i) for i in range(50)]
        library_vm._videos = videos
        panel._on_videos_changed()
        _drain(qtbot)
        FakeLoader.instances.clear()

        # 실제 붙이기와 같다 — 같은 리스트 객체에 이어 붙인다(이벤트를 돌리는 동안
        # 다른 경로가 뷰모델 목록을 비울 수 있어 다시 꽂는다).
        videos.extend(_dto(i) for i in range(50, 100))
        library_vm._videos = videos
        panel._on_videos_changed()

        assert len(FakeLoader.instances) == 1
        items = FakeLoader.instances[0].items
        assert len(items) == 50, f"누적 {len(items)}건 전체를 다시 넘겼다"
        assert {p for p, _w, _h in items} == {f"scope_{i}.jpg" for i in range(50, 100)}
        _drain(qtbot)

    def test_목록이_교체되면_교체된_전체를_넘긴다(self, panel, library_vm, qtbot):
        library_vm._videos = [_dto(i) for i in range(50)]
        panel._on_videos_changed()
        _drain(qtbot)
        FakeLoader.instances.clear()

        library_vm._videos = [_dto(i) for i in range(1000, 1030)]   # 새 목록(append 아님)
        panel._on_videos_changed()

        assert len(FakeLoader.instances) == 1
        assert len(FakeLoader.instances[0].items) == 30
        _drain(qtbot)


class TestPreloadOnViewSwitch:
    def test_아이콘에서_리스트로_바꾸면_리스트_크기로_프리로드한다(
        self, panel, library_vm, qtbot
    ):
        library_vm._videos = [_dto(i) for i in range(50)]
        panel._on_videos_changed()
        _drain(qtbot)
        FakeLoader.instances.clear()

        panel._switch_view(_VIEW_LIST)

        assert len(FakeLoader.instances) >= 1, "뷰를 바꿔도 프리로드가 시작되지 않았다"
        items = FakeLoader.instances[-1].items
        assert len(items) >= min(12, 50)
        assert {(w, h) for _p, w, h in items} == {(_TW_LIST, _TH_LIST)}
        assert (_TW_LIST, _TH_LIST) != (_TW_ICON, _TH_ICON)
        _drain(qtbot)

    def test_같은_뷰로_다시_전환하면_추가_프리로드가_없다(self, panel, library_vm, qtbot):
        library_vm._videos = [_dto(i) for i in range(50)]
        panel._on_videos_changed()
        panel._switch_view(_VIEW_LIST)
        _drain(qtbot)
        FakeLoader.instances.clear()

        panel._switch_view(_VIEW_LIST)

        assert FakeLoader.instances == []
