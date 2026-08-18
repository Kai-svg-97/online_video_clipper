"""지금 재생 중 미니바 — 상세를 떠나도 재생이 이어지는 계약을 고정한다.

핵심 규칙 셋:
* **재생 중일 때만** 살려 둔다. 멈춰 있었으면 예전처럼 정지한다(안 보이는 곳에서
  자원만 붙들 이유가 없다).
* 복귀는 **다시 불러오지 않는다** — 위젯이 그대로 살아 있으므로 스택만 되돌린다.
  여기서 재로드가 끼면 재생이 끊기고 위치가 날아간다.
* 미니바로 듣는 중의 자동 다음곡은 **화면을 뺏지 않는다**(목록을 보던 중이었다).
"""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from gui.panels.library_panel import LibraryPanel
from gui.widgets.mini_player_bar import MiniPlayerBar, _fmt_ms


@pytest.fixture
def panel(qtbot, library_vm, download_vm, clip_vm, monkeypatch):
    import config.settings as settings
    monkeypatch.setattr(settings, "save_setting", lambda *a, **k: None)
    monkeypatch.setattr(library_vm, "load", lambda *a, **k: None)
    p = LibraryPanel(vm=library_vm, clip_vm=clip_vm, download_vm=download_vm)
    qtbot.addWidget(p)
    # 플레이어는 실제 미디어를 물리지 않는다 — 상태만 흉내 낸다.
    p._detail_widget.is_playing = MagicMock(return_value=True)
    p._detail_widget.stop_player = MagicMock()
    p._detail_widget.player_position_ms = MagicMock(return_value=12_000)
    p._detail_widget.player_duration_ms = MagicMock(return_value=200_000)
    p._detail_widget.next_payload = MagicMock(return_value=None)
    p._current_detail_payload = uuid4()
    p._remember_now_playing("어떤 노래", "어떤 채널", None)
    yield p
    for worker in list(library_vm._list_workers):
        worker.wait(3000)
    library_vm.shutdown()


class TestHandoff:
    def test_재생_중_상세를_떠나면_멈추지_않고_띠로_넘긴다(self, panel):
        seen: list = []
        panel.now_playing_changed.connect(seen.append)
        panel._nav_stack.setCurrentIndex(1)

        panel._on_back_from_detail()

        panel._detail_widget.stop_player.assert_not_called()
        assert seen and seen[-1]["title"] == "어떤 노래"

    def test_멈춰_있었으면_예전처럼_정지한다(self, panel):
        panel._detail_widget.is_playing.return_value = False
        seen: list = []
        panel.now_playing_changed.connect(seen.append)

        panel._on_back_from_detail()

        panel._detail_widget.stop_player.assert_called_once()
        assert seen == []          # 띠를 띄우지 않는다

    def test_재생할_영상_정보가_없으면_정지한다(self, panel):
        panel._current_detail_payload = None

        panel._on_back_from_detail()

        panel._detail_widget.stop_player.assert_called_once()


class TestControls:
    def _handoff(self, panel):
        panel._nav_stack.setCurrentIndex(1)
        panel._on_back_from_detail()

    def test_재생_위치를_주기적으로_알린다(self, panel):
        self._handoff(panel)
        seen: list = []
        panel.now_playing_progress.connect(lambda p, d, pl: seen.append((p, d, pl)))

        panel._tick_mini_player()

        assert seen == [(12_000, 200_000, True)]

    def test_재생_토글은_플레이어에_그대로_전달된다(self, panel):
        self._handoff(panel)
        panel._detail_widget.toggle_play = MagicMock()

        panel.mini_toggle_play()

        panel._detail_widget.toggle_play.assert_called_once()

    def test_탐색은_플레이어에_그대로_전달된다(self, panel):
        self._handoff(panel)
        panel._detail_widget.seek_to_ms = MagicMock()

        panel.mini_seek(45_000)

        panel._detail_widget.seek_to_ms.assert_called_once_with(45_000)

    def test_닫으면_재생을_멈추고_띠를_거둔다(self, panel):
        self._handoff(panel)
        seen: list = []
        panel.now_playing_changed.connect(seen.append)

        panel.mini_close()

        panel._detail_widget.stop_player.assert_called_once()
        assert seen == [None]

    def test_띠를_거두면_타이머도_멈춘다(self, panel):
        """보이지도 않는 띠를 위해 0.5초마다 계속 훑을 이유가 없다."""
        self._handoff(panel)
        assert panel._mini_timer.isActive()

        panel.mini_close()

        assert not panel._mini_timer.isActive()

    def test_띠가_없으면_조작을_무시한다(self, panel):
        panel._detail_widget.toggle_play = MagicMock()

        panel.mini_toggle_play()

        panel._detail_widget.toggle_play.assert_not_called()


class TestReturn:
    def test_클릭하면_다시_불러오지_않고_화면만_되돌린다(self, panel, monkeypatch):
        """재로드가 끼면 재생이 끊기고 위치가 날아간다 — 스택만 되돌려야 한다."""
        reloaded: list = []
        monkeypatch.setattr(panel, "_open_detail", lambda *a, **k: reloaded.append(a))
        panel._nav_stack.setCurrentIndex(1)
        panel._on_back_from_detail()

        panel.mini_open()

        assert panel._nav_stack.currentIndex() == 1
        assert reloaded == []
        panel._detail_widget.stop_player.assert_not_called()

    def test_복귀하면_띠는_사라진다(self, panel):
        panel._nav_stack.setCurrentIndex(1)
        panel._on_back_from_detail()
        seen: list = []
        panel.now_playing_changed.connect(seen.append)

        panel.mini_open()

        assert seen == [None]

    def test_복귀는_히스토리에_쌓인다(self, panel):
        panel._nav_stack.setCurrentIndex(1)
        panel._on_back_from_detail()
        before = len(panel._nav_history)

        panel.mini_open()

        assert len(panel._nav_history) == before + 1


class TestAutoNext:
    def test_미니바로_듣는_중_다음곡은_화면을_뺏지_않는다(self, panel, monkeypatch):
        seen: list = []
        monkeypatch.setattr(
            panel, "_open_detail",
            lambda vid, **kw: seen.append(kw.get("stay_on_list")),
        )
        panel._nav_stack.setCurrentIndex(1)
        panel._on_back_from_detail()

        panel._on_play_next(uuid4())

        assert seen == [True]

    def test_상세를_보는_중이면_평소대로_상세를_연다(self, panel, monkeypatch):
        seen: list = []
        monkeypatch.setattr(
            panel, "_open_detail",
            lambda vid, **kw: seen.append(kw.get("stay_on_list")),
        )

        panel._on_play_next(uuid4())

        assert seen == [None]      # stay_on_list 를 넘기지 않는다(화면 전환)


class TestMiniBarWidget:
    def test_시간_표기(self):
        assert _fmt_ms(0) == "0:00"
        assert _fmt_ms(61_000) == "1:01"
        assert _fmt_ms(3_723_000) == "1:02:03"

    def test_다음곡이_없으면_버튼을_숨긴다(self, qtbot):
        bar = MiniPlayerBar()
        qtbot.addWidget(bar)

        bar.set_track("제목", "채널", None, has_next=False)

        assert bar._btn_next.isHidden()

    def test_손잡이를_잡고_있는_동안은_위치가_튀지_않는다(self, qtbot):
        """0.5초 갱신이 끌던 손잡이를 되돌리면 탐색이 불가능해진다."""
        bar = MiniPlayerBar()
        qtbot.addWidget(bar)
        bar.set_duration(100_000)
        bar._on_slider_pressed()
        bar._slider.setValue(50_000)

        bar.set_position(1_000)

        assert bar._slider.value() == 50_000

    def test_손잡이를_놓으면_그_위치로_탐색을_요청한다(self, qtbot):
        bar = MiniPlayerBar()
        qtbot.addWidget(bar)
        bar.set_duration(100_000)
        got: list = []
        bar.seek_requested.connect(got.append)
        bar._on_slider_pressed()
        bar._slider.setValue(42_000)

        bar._on_slider_released()

        assert got == [42_000]

    def test_재생_상태가_아이콘에_반영된다(self, qtbot):
        bar = MiniPlayerBar()
        qtbot.addWidget(bar)

        bar.set_playing(True)
        assert bar._btn_play.text() == "⏸"
        bar.set_playing(False)
        assert bar._btn_play.text() == "▶"


class TestPositionReporting:
    """`position_ms`는 프로퍼티다 — 메서드처럼 부르면 조용히 0이 된다(실제 버그였다)."""

    def test_재생_위치를_프로퍼티에서_읽는다(self, qtbot):
        from gui.panels.video_detail_panel import VideoDetailWidget

        w = VideoDetailWidget()
        qtbot.addWidget(w)

        class _FakePlayer:
            position_ms = 7_500
            duration_ms = 90_000

        w._player = _FakePlayer()

        assert w.player_position_ms() == 7_500
        assert w.player_duration_ms() == 90_000
