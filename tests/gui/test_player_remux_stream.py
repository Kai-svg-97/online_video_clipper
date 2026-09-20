"""실시간 remux 스트림의 위치·seek 계약 — 네트워크 없이 분기만 검증한다.

**왜 이 시험이 필요한가**: remux 스트림은 파이프로 흘리는 fragmented mp4라
재생기가 길이도 모르고 seek도 못 한다. 그래서 위치 계산과 seek을 `InlinePlayer`가
직접 맡는다 — 이 계약이 깨지면 진행 막대가 멎거나(길이 0) seek이 제자리를 맴돈다.

seek은 ffmpeg를 그 지점에서 새로 띄우는 방식이라, 재생기의 위치는 **매번 0부터**
다시 센다. 영상 기준 위치 = 재생기 위치 + 스트림 시작 오프셋이다.
"""

from __future__ import annotations

import pytest
from PyQt6.QtMultimedia import QMediaPlayer

from gui.widgets.video_player import InlinePlayer

_PLAY_URL = "http://127.0.0.1:9/s/abc123/play.mp4"
_DURATION = 213_000


@pytest.fixture()
def player(qapp_instance, qtbot):
    p = InlinePlayer()
    qtbot.addWidget(p)
    p._video_url = "https://www.youtube.com/watch?v=x"
    yield p
    p._remux_url = ""      # 실제 중계 세션이 없으므로 정리 경로를 타지 않게 한다
    p.stop()


def _ready(player: InlinePlayer) -> None:
    """워커가 remux 스트림을 넘겨준 상태를 만든다."""
    player._on_stream_ready(_PLAY_URL, "1080p", False, _DURATION)


class TestRemuxStreamSetup:
    def test_길이를_우리가_들고_보고한다(self, player):
        """재생기는 이 소스의 길이를 모른다 — 우리가 답하지 않으면 막대가 멎는다."""
        _ready(player)
        assert player._effective_duration() == _DURATION
        assert player.duration_ms == _DURATION

    def test_처음_열_때_ss가_붙는다(self, player):
        _ready(player)
        assert player._player.source().toString().endswith("?ss=0.000")

    def test_이어보기_위치를_스트림_시작점에_태운다(self, player):
        """seek 불가 소스라 재생 뒤에 옮길 수 없다 — 열 때 실어 보내야 한다."""
        player._resume_ms = 90_000
        _ready(player)
        assert player._player.source().toString().endswith("?ss=90.000")
        assert player._stream_offset_ms == 90_000
        assert player._resume_ms == 0

    def test_일반_스트림은_remux로_보지_않는다(self, player):
        """duration_ms=0 이면 예전처럼 재생기가 직접 다루는 소스다."""
        player._on_stream_ready("http://direct/video.mp4", "360p", False, 0)
        assert player._remux_url == ""
        assert player._stream_duration_ms == 0
        assert "?ss=" not in player._player.source().toString()


class TestRemuxPosition:
    def test_위치에_스트림_오프셋을_더한다(self, player):
        _ready(player)
        player._stream_offset_ms = 60_000
        # 재생기는 새 스트림을 0부터 세므로, 그대로 쓰면 60초로 되돌아가 보인다.
        assert player.position_ms == 60_000 + max(0, player._player.position())


class TestRemuxSeek:
    def test_seek은_바로_반영되지_않고_모였다_나간다(self, player, qtbot):
        """J/L 연타마다 ffmpeg를 새로 띄우면 화면이 멎는다."""
        _ready(player)
        player._seek_to(30_000)
        player._seek_to(60_000)
        assert player._pending_seek_ms == 60_000
        assert player._player.source().toString().endswith("?ss=0.000")

        qtbot.waitUntil(lambda: player._pending_seek_ms is None, timeout=3000)
        assert player._stream_offset_ms == 60_000
        assert player._player.source().toString().endswith("?ss=60.000")

    def test_기다리는_동안_위치는_목표를_답한다(self, player):
        """옛 위치를 답하면 이어지는 상대 seek이 매번 제자리를 맴돈다."""
        _ready(player)
        player._seek_to(45_000)
        assert player.position_ms == 45_000

    def test_상대_seek은_목표에서_이어_계산한다(self, player):
        _ready(player)
        player._seek_to(45_000)
        player._seek_relative(10)
        assert player._pending_seek_ms == 55_000

    def test_길이를_넘겨_seek_하지_않는다(self, player):
        _ready(player)
        player._seek_to(_DURATION + 60_000)
        assert player._pending_seek_ms == _DURATION

    def test_일반_소스는_재생기에게_그대로_맡긴다(self, player):
        player._on_stream_ready("http://direct/video.mp4", "360p", False, 0)
        player._seek_to(5_000)
        assert player._pending_seek_ms is None   # 미루지 않는다


class TestTruncatedStream:
    """상위가 조각을 거부하면 **중간에서도** EndOfMedia가 온다 — 다 본 것이 아니다."""

    def test_중간에_끊기면_다_봤다고_보고하지_않는다(self, player, qtbot):
        _ready(player)
        player._stream_offset_ms = 10_000
        finished = []
        player.playback_finished.connect(lambda: finished.append(True))
        player._on_media_status(QMediaPlayer.MediaStatus.EndOfMedia)
        assert finished == []
        assert player._pending_seek_ms is not None   # 그 지점에서 이어 받는다

    def test_같은_자리에서_또_끊기면_병합_방식으로_내려간다(self, player, monkeypatch):
        """다시 받아도 같은 원본이다 — 방식을 바꿔야 한다(무한 재시도 금지).

        원본이 먼 오프셋을 거부하는 영상이 있어(실측: 파일 절반 이후 403) 실시간
        스트림이 그 자리에서 되풀이해 끊긴다. 그럴 땐 처음부터 순차로 받는 예전
        방식만 허용되므로 거기로 내려가야 재생이 이어진다.
        """
        _ready(player)
        player._stream_offset_ms = 10_000
        calls = []
        monkeypatch.setattr(player, "_fetch_stream", lambda: calls.append(True))
        player._on_media_status(QMediaPlayer.MediaStatus.EndOfMedia)
        player._pending_seek_ms = None
        player._on_media_status(QMediaPlayer.MediaStatus.EndOfMedia)
        assert calls, "다른 방식으로 다시 받아야 한다"
        assert player._prefer_remux is False
        assert player._resume_ms == 10_000, "끊긴 지점에서 이어야 한다"


class TestFallbackToMerge:
    def test_새_영상을_열면_다시_remux부터_시도한다(self, player):
        """버티지 못하는 것은 영상마다 다르다 — 한 번 실패했다고 계속 포기하지 않는다."""
        player._prefer_remux = False
        player._reset_stream_mode()
        assert player._prefer_remux is True

    def test_재생_오류가_반복되면_방식을_바꾼다(self, player, monkeypatch):
        from gui.widgets.player.constants import _MAX_STREAM_RETRIES

        _ready(player)
        calls = []
        monkeypatch.setattr(player, "_fetch_stream", lambda: calls.append(True))
        player._stream_retries = _MAX_STREAM_RETRIES
        player._on_error(QMediaPlayer.Error.NetworkError, "boom")
        assert player._prefer_remux is False
        assert calls

    def test_끝까지_봤으면_정상_보고한다(self, player):
        _ready(player)
        player._stream_offset_ms = _DURATION
        finished = []
        player.playback_finished.connect(lambda: finished.append(True))
        player._on_media_status(QMediaPlayer.MediaStatus.EndOfMedia)
        assert finished == [True]
