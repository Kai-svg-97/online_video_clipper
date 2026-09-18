"""음성 인식 버튼이 **이번 영상의** 파일을 기준으로 뜨는지.

상세화면 `load()`는 다운로드 목록을 훑어 `_clip_source_file`을 채우는데, 그 시점이
탭 조립보다 **뒤**다. 자막 탭 갱신을 그보다 먼저 부르면 첫 로드에는 버튼이 안 뜨고
두 번째부터는 **이전 영상의 파일**로 판단한다 — 실제로 초안이 그랬다.
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
        self.asked: list = []

    def has_index(self, video_id):
        return False

    def load_lines(self, video_id, text=""):
        pass

    def transcribe(self, video_id, media_path, language=""):
        self.asked.append((video_id, media_path))
        return True


def _detail(video_id, file_path):
    return SimpleNamespace(
        id=video_id, url="https://youtu.be/x", title="영상", channel_name="채널",
        duration_sec=600, published_at="", view_count=None, favorite=False,
        watched=False, description="", notes="", tags=(),
        downloads=(
            [SimpleNamespace(file_path=file_path, quality="1080p", fmt="mp4",
                             file_size_bytes=1)] if file_path else []
        ),
        failed_downloads=[], gemini_summary="", summary_status="",
        category_id=None, thumbnail_path="",
    )


@pytest.fixture
def media(tmp_path):
    path = tmp_path / "영상.mp4"
    path.write_bytes(b"m")
    return str(path)


@pytest.fixture
def widget(qtbot):
    vm = _SubtitleVM()
    w = VideoDetailWidget(subtitle_vm=vm)
    qtbot.addWidget(w)
    w.vm = vm       # type: ignore[attr-defined]
    return w


class TestAvailability:
    def test_첫_로드에서_바로_뜬다(self, widget, media):
        """조립 순서를 되돌리면 이 테스트가 먼저 깨진다."""
        widget.load(_detail(uuid4(), media), tag_ids={})
        assert widget._subtitle_tab._asr_btn.isHidden() is False

    def test_받아_둔_파일이_없으면_뜨지_않는다(self, widget):
        widget.load(_detail(uuid4(), ""), tag_ids={})
        assert widget._subtitle_tab._asr_btn.isHidden() is True

    def test_파일_있는_영상에서_없는_영상으로_가면_사라진다(self, widget, media):
        """이전 영상의 파일로 판단하면 여기서 잘못 남는다."""
        widget.load(_detail(uuid4(), media), tag_ids={})
        widget.load(_detail(uuid4(), ""), tag_ids={})
        assert widget._subtitle_tab._asr_btn.isHidden() is True

    def test_이번_영상의_파일로_요청한다(self, widget, media):
        vid = uuid4()
        widget.load(_detail(vid, media), tag_ids={})
        widget._on_transcribe_requested()
        assert widget.vm.asked == [(vid, media)]
