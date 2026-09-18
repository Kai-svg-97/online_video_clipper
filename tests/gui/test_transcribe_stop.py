"""음성 인식 중단 — 버튼이 **언제** 뜨고, 멈춘 뒤 뭐라고 말하는가.

이 기능의 함정은 버튼 자체가 아니라 **단계 구분**이다.

- 모델을 내려받는 동안에는 협조적 중단이 걸리지 않는다(내려받기가 끝나야 첫 판정이
  돈다). 그때 버튼을 띄우면 몇 분간 눌러도 반응이 없어 고장처럼 보인다.
- 중단 뒤에도 진행률 신호가 한두 번 더 온다. 그걸로 안내를 덮으면 "중단하는 중"이
  사라져 눌린 줄 모른다.
- 중단해서 결과가 0줄인 것과, 끝까지 듣고 말을 못 찾은 것은 **다른 사건**이다.
  구분하지 않으면 중단한 사람에게 "말을 찾지 못했다"고 말하게 된다.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from PyQt6.QtCore import QObject, pyqtSignal

from gui.panels.video_detail_panel import VideoDetailWidget


class _SubtitleVM(QObject):
    lines_loaded = pyqtSignal(object, object)
    index_started = pyqtSignal(object)
    index_finished = pyqtSignal(object, int)
    bulk_progress = pyqtSignal(int, int, str)
    bulk_finished = pyqtSignal(object)
    transcribe_started = pyqtSignal(object)
    transcribe_model_downloading = pyqtSignal(str)
    transcribe_progress = pyqtSignal(object, float)
    transcribe_finished = pyqtSignal(object, int)

    can_transcribe = True

    def __init__(self):
        super().__init__()
        self.stopped: list = []

    def has_index(self, video_id):
        return False

    def load_lines(self, video_id, text=""):
        self.lines_loaded.emit(video_id, [])

    def transcribe(self, video_id, media_path, language=""):
        return True

    def stop_transcribe(self, video_id):
        self.stopped.append(video_id)


def _detail(video_id, file_path):
    return SimpleNamespace(
        id=video_id, url="https://youtu.be/x", title="영상", channel_name="채널",
        duration_sec=600, published_at="", view_count=None, favorite=False,
        watched=False, description="", notes="", tags=(),
        downloads=[
            SimpleNamespace(file_path=file_path, quality="1080p", fmt="mp4",
                            file_size_bytes=1)
        ],
        failed_downloads=[], gemini_summary="", summary_status="",
        category_id=None, thumbnail_path="",
    )


@pytest.fixture
def media(tmp_path):
    path = tmp_path / "영상.mp4"
    path.write_bytes(b"m")
    return str(path)


@pytest.fixture
def widget(qtbot, media):
    vm = _SubtitleVM()
    w = VideoDetailWidget(subtitle_vm=vm)
    qtbot.addWidget(w)
    w.vm = vm                       # type: ignore[attr-defined]
    w.vid = uuid4()                 # type: ignore[attr-defined]
    w.load(_detail(w.vid, media), tag_ids={})
    return w


class TestVisibility:
    def test_시작_전에는_보이지_않는다(self, widget):
        assert widget._subtitle_tab._stop_btn.isHidden() is True

    def test_전사를_시작하면_보인다(self, widget):
        widget._on_transcribe_requested()
        assert widget._subtitle_tab._stop_btn.isHidden() is False

    def test_모델을_내려받는_동안에는_숨긴다(self, widget):
        """눌러도 몇 분간 반응이 없는 버튼을 띄우지 않는다."""
        widget._on_transcribe_requested()
        widget.vm.transcribe_model_downloading.emit("base")
        assert widget._subtitle_tab._stop_btn.isHidden() is True

    def test_내려받기가_끝나고_소리를_듣기_시작하면_다시_보인다(self, widget):
        widget._on_transcribe_requested()
        widget.vm.transcribe_model_downloading.emit("base")
        widget.vm.transcribe_progress.emit(widget.vid, 0.1)
        assert widget._subtitle_tab._stop_btn.isHidden() is False

    def test_자막이_채워지면_사라진다(self, widget):
        widget._on_transcribe_requested()
        widget._subtitle_tab.set_lines(
            [SimpleNamespace(start_ms=0, text="말")], indexed=True
        )
        assert widget._subtitle_tab._stop_btn.isHidden() is True


class TestStopRequest:
    def test_이번_영상의_id로_멈춘다(self, widget):
        widget._on_transcribe_requested()
        widget._subtitle_tab._stop_btn.click()
        assert widget.vm.stopped == [widget.vid]

    def test_누른_뒤에는_다시_눌리지_않는다(self, widget):
        """협조적 중단이라 한 박자 걸린다 — 연타로 같은 요청을 쌓지 않는다."""
        widget._on_transcribe_requested()
        widget._subtitle_tab._stop_btn.click()
        assert widget._subtitle_tab._stop_btn.isEnabled() is False

    def test_뒤늦게_온_진행률이_중단_안내를_덮지_않는다(self, widget):
        widget._on_transcribe_requested()
        widget._subtitle_tab._stop_btn.click()
        widget.vm.transcribe_progress.emit(widget.vid, 0.9)
        assert "중단" in widget._subtitle_tab._empty_lbl.text()

    def test_내려받는_중_중단이면_그_사정을_말한다(self, widget):
        widget._on_transcribe_requested()
        widget.vm.transcribe_model_downloading.emit("base")
        widget._on_transcribe_stop_requested()
        assert "내려받기" in widget._subtitle_tab._empty_lbl.text()


class TestFinishMessage:
    def test_중단해서_0줄이면_말을_못_찾았다고_하지_않는다(self, widget):
        widget._on_transcribe_requested()
        widget._subtitle_tab._stop_btn.click()
        widget.vm.transcribe_finished.emit(widget.vid, 0)
        text = widget._subtitle_tab._empty_lbl.text()
        assert "중단했습니다" in text
        assert "찾지 못했" not in text

    def test_중단하지_않고_0줄이면_이유를_설명한다(self, widget):
        widget._on_transcribe_requested()
        widget.vm.transcribe_finished.emit(widget.vid, 0)
        assert "찾지 못했" in widget._subtitle_tab._empty_lbl.text()

    def test_중단_상태는_다음_전사로_이어지지_않는다(self, widget):
        """끝난 뒤에도 플래그가 남으면 다음 전사가 시작하자마자 '중단'이 된다."""
        widget._on_transcribe_requested()
        widget._subtitle_tab._stop_btn.click()
        widget.vm.transcribe_finished.emit(widget.vid, 0)

        widget._on_transcribe_requested()
        widget.vm.transcribe_finished.emit(widget.vid, 0)
        assert "찾지 못했" in widget._subtitle_tab._empty_lbl.text()
