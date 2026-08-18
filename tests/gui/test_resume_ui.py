"""이어보기 GUI 배선 — 위치 보고 주기와 '자동 재생 안 함' 규칙을 고정한다.

특히 중요한 것: 저장된 위치가 있다고 **재생을 자동으로 시작하면 안 된다**.
목록에서 카드를 눌렀을 뿐인데 소리가 나면 놀란다(자동 전환은 autoplay로만 온다).
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from gui.panels.video_detail_panel import VideoDetailWidget


def _detail(video_id=None, position=0):
    return SimpleNamespace(
        id=video_id or uuid4(),
        url="https://youtu.be/resume01",
        title="영상", channel_name="채널", duration_sec=600,
        published_at="", view_count=None, favorite=False, watched=False,
        description="", notes="", tags=(), downloads=[], failed_downloads=[],
        gemini_summary="", summary_status="", category_id=None, thumbnail_path="",
        last_position_ms=position,
    )


class TestPositionReporting:
    def test_재생_중에만_위치를_보고한다(self, qtbot):
        w = VideoDetailWidget()
        qtbot.addWidget(w)
        w.load(_detail(), tag_ids={})

        w._on_playback_state_for_position(True)
        assert w._position_timer.isActive()

        w._on_playback_state_for_position(False)
        assert not w._position_timer.isActive()

    def test_스트리밍_영상은_보고하지_않는다(self, qtbot):
        from application.library.dtos import FeedVideoDTO

        w = VideoDetailWidget()
        qtbot.addWidget(w)
        w.load_stream(FeedVideoDTO(
            url="https://youtu.be/stream01", title="스트리밍", channel_name="채널",
            channel_id="UC0", thumbnail_url="", thumbnail_path="", published_at="",
            view_count=None, duration_sec=100, in_library=False, yt_video_id="stream01",
        ))
        got: list = []
        w.playback_position_changed.connect(lambda *a: got.append(a))

        w._on_playback_state_for_position(True)
        w._report_position()

        assert not w._position_timer.isActive()
        assert got == []       # 저장할 곳이 없다(안정적 video_id 없음)

    def test_화면을_떠날_때_마지막_위치를_한_번_더_남긴다(self, qtbot, monkeypatch):
        w = VideoDetailWidget()
        qtbot.addWidget(w)
        vid = uuid4()
        w.load(_detail(vid), tag_ids={})
        monkeypatch.setattr(w, "player_position_ms", lambda: 42_000)
        got: list = []
        w.playback_position_changed.connect(lambda video_id, pos: got.append((video_id, pos)))

        w.stop_player()

        assert got == [(vid, 42_000)]
        assert not w._position_timer.isActive()


class TestResumeDoesNotAutoplay:
    def test_저장된_위치가_있어도_자동_재생하지_않는다(self, qtbot, monkeypatch):
        w = VideoDetailWidget()
        qtbot.addWidget(w)
        played: list = []
        monkeypatch.setattr(w._player, "play", lambda: played.append(1))

        w.load(_detail(position=120_000), tag_ids={}, resume_ms=120_000)
        qtbot.wait(250)

        assert played == []

    def test_autoplay를_주면_재생한다(self, qtbot, monkeypatch):
        w = VideoDetailWidget()
        qtbot.addWidget(w)
        played: list = []
        monkeypatch.setattr(w._player, "play", lambda: played.append(1))

        w.load(_detail(), tag_ids={}, autoplay=True)
        qtbot.wait(250)

        assert played == [1]
