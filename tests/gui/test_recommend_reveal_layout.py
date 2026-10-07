"""추천 띠 등장/퇴장 연출 중 재배치 상한 · 패널 단위 배선(D5-c).

계획: `.omc/research/perf/test_plan_batch8.md` 4절(C1~C5; C6·C7은 test_panel_teardown.py).

연출 중에 라이브러리 목록(`_view_stack`)이 매 프레임 다시 배치되면 목록 영역의 그리기
비용이 프레임마다 든다. 구조적 성질만 고정한다 — 시간 수치는 쓰지 않는다.
"""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from PyQt6.QtCore import QEvent, QObject, QPoint

from application.library.dtos import FeedVideoDTO, VideoDTO
from gui.anim import running_animation_count
from gui.panels.library_panel import _QWIDGET_MAX_H, LibraryPanel


class _ResizeCounter(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.n = 0

    def eventFilter(self, obj, ev) -> bool:   # noqa: N802
        if ev.type() == QEvent.Type.Resize:
            self.n += 1
        return False


def _drain(library_vm) -> None:
    for worker in list(library_vm._list_workers):
        worker.wait(3000)
    library_vm.shutdown()


def _dto(title="파이썬 강의"):
    return VideoDTO(
        id=uuid4(),
        url=f"https://youtu.be/{uuid4().hex[:11]}",
        title=title,
        channel_name="코딩채널",
        thumbnail_path="",
        duration_sec=60,
        favorite=False,
        watched=False,
        category_id=None,
        tag_names=("개발",),
    )


def _feed(i: int, *, final: bool = True) -> FeedVideoDTO:
    vid = f"rec{i:08d}"
    return FeedVideoDTO(
        url=f"https://www.youtube.com/watch?v={vid}",
        title=f"{'최종' if final else '부분'} {i}",
        channel_name="채널",
        channel_id="UC0",
        thumbnail_url="",
        thumbnail_path="",
        published_at="2026-09-30" if final else "",
        view_count=100 + i if final else None,
        duration_sec=100,
        in_library=False,
        yt_video_id=vid,
    )


@pytest.fixture
def recommend_vm():
    vm = MagicMock()
    for sig in ("items_changed", "partial_ready", "loading_changed", "error_occurred"):
        getattr(vm, sig).connect = MagicMock()
    return vm


@pytest.fixture
def panel(qtbot, library_vm, download_vm, clip_vm, recommend_vm, monkeypatch):
    # test_recommend_panel_wiring.py의 panel 픽스처와 같다 — 실사용 설정을 읽지도 쓰지도 않는다.
    import config.settings as settings
    monkeypatch.setattr(settings, "save_setting", lambda *a, **k: None)
    monkeypatch.setattr(settings, "RECOMMEND_STRIP_EXPANDED", True, raising=False)
    monkeypatch.setattr(settings, "RECOMMEND_STRIP_HEIGHT", 250, raising=False)
    monkeypatch.setattr(library_vm, "load", lambda *a, **k: None)
    p = LibraryPanel(
        vm=library_vm,
        clip_vm=clip_vm,
        download_vm=download_vm,
        recommend_vm=recommend_vm,
    )
    qtbot.addWidget(p)
    yield p
    _drain(library_vm)


@pytest.fixture
def shown(panel, qtbot):
    panel.resize(1280, 800)
    panel.show()
    qtbot.waitExposed(panel)
    qtbot.waitUntil(lambda: panel._centre_splitter.sizes()[0] > 0, timeout=3000)
    return panel


@pytest.fixture
def counter(shown):
    c = _ResizeCounter()
    shown._view_stack.installEventFilter(c)
    c.n = 0
    yield c   # 시험 끝까지 참조를 붙든다
    try:
        shown._view_stack.removeEventFilter(c)
    except RuntimeError:
        pass


def _run_reveal(panel, qtbot, counter):
    """등장 연출을 돌리고 (프레임 수, Resize 수)를 돌려준다."""
    counter.n = 0
    panel._on_recommend_items([_feed(i) for i in range(3)])
    anim = panel._recommend_anim
    assert anim is not None, "연출이 시작되지 않았다(공간 부족 분기?)"
    frames: list = []
    anim.valueChanged.connect(frames.append)
    qtbot.waitUntil(lambda: panel._recommend_anim is None, timeout=3000)
    return len(frames), counter.n


class TestRevealRelayout:
    def test_C1_등장_연출_동안_라이브러리_목록이_매_프레임_다시_배치되지_않는다(
        self, shown, qtbot, counter
    ):
        frames, resizes = _run_reveal(shown, qtbot, counter)

        assert frames >= 5, f"연출이 실제로 돌지 않았다(프레임 {frames})"
        assert resizes <= 2, f"_view_stack Resize {resizes}회(프레임 {frames})"

    def test_C2_연출은_여전히_아래에서_올라오는_모양이다(self, shown, qtbot, counter):
        panel = shown
        strip = panel._recommend_strip
        samples: list[int] = []

        def _poll() -> bool:
            if strip.isVisible():
                samples.append(strip.mapTo(panel, QPoint(0, 0)).y())
            return panel._recommend_anim is None

        panel._on_recommend_items([_feed(i) for i in range(3)])
        assert panel._recommend_anim is not None, "연출이 시작되지 않았다"
        qtbot.waitUntil(_poll, timeout=3000)

        assert len(set(samples)) >= 3, f"위쪽 가장자리가 {len(set(samples))}단계뿐: {samples}"
        assert all(a >= b for a, b in zip(samples, samples[1:])), f"단조 감소가 아니다: {samples}"
        final_y = strip.mapTo(panel, QPoint(0, 0)).y()
        assert samples[-1] == final_y
        assert panel._centre_splitter.sizes()[1] == panel._recommend_height
        assert strip.maximumHeight() == _QWIDGET_MAX_H

    def test_C3_퇴장_연출도_목록을_매_프레임_재배치하지_않는다(
        self, shown, qtbot, counter, library_vm
    ):
        panel = shown
        _run_reveal(panel, qtbot, counter)
        library_vm._videos = [_dto()]

        counter.n = 0
        panel._refresh_recommendations()    # 퇴장 시작
        anim = panel._recommend_anim
        assert anim is not None, "퇴장 연출이 시작되지 않았다"
        frames: list = []
        anim.valueChanged.connect(frames.append)
        qtbot.waitUntil(lambda: panel._recommend_anim is None, timeout=3000)

        assert len(frames) >= 5, f"연출이 실제로 돌지 않았다(프레임 {len(frames)})"
        assert counter.n <= 2, f"_view_stack Resize {counter.n}회(프레임 {len(frames)})"
        assert panel._recommend_strip.isHidden()

    def test_C4_연출_도중_새_결과가_와도_마지막_상태가_일관된다(
        self, shown, qtbot, counter, library_vm
    ):
        panel = shown
        library_vm._videos = [_dto()]
        anims_before = running_animation_count()

        def _wait_frames(n: int) -> None:
            anim = panel._recommend_anim
            assert anim is not None
            seen: list = []
            anim.valueChanged.connect(seen.append)
            qtbot.waitUntil(lambda: len(seen) >= n, timeout=3000)

        panel._on_recommend_items([_feed(i) for i in range(3)])     # 등장
        _wait_frames(2)
        panel._refresh_recommendations()                             # 퇴장
        _wait_frames(2)
        panel._on_recommend_items([_feed(i, final=True) for i in range(3)])   # 재등장
        qtbot.waitUntil(lambda: panel._recommend_anim is None, timeout=3000)

        assert panel._recommend_strip.isVisibleTo(panel)
        assert panel._centre_splitter.sizes()[1] == panel._recommend_height
        assert panel._recommend_strip.maximumHeight() == _QWIDGET_MAX_H
        qtbot.waitUntil(lambda: running_animation_count() == anims_before, timeout=3000)


class TestPanelWiring:
    def test_C5_부분에서_최종이_와도_띠_카드가_재사용된다(self, panel):
        panel._on_recommend_partial([_feed(i, final=False) for i in range(18)])
        strip = panel._recommend_strip

        def _cards():
            return [
                strip._row.itemAt(i).widget()
                for i in range(strip._row.count())
                if strip._row.itemAt(i).widget() is not None
                and type(strip._row.itemAt(i).widget()).__name__ == "_FeedCard"
            ]

        cards0 = _cards()
        ids0 = [id(c) for c in cards0]
        assert len(cards0) == 18
        assert not strip.isVisibleTo(panel), "부분 결과 단계에서는 띠가 감춰져 있어야 한다"

        panel._on_recommend_items([_feed(i, final=True) for i in range(18)])

        assert [id(c) for c in _cards()] == ids0, "최종 결과에서 카드가 다시 만들어졌다"
