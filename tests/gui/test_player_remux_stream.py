"""실시간 remux 스트림의 위치·seek 계약 — 네트워크 없이 분기만 검증한다.

**왜 이 시험이 필요한가**: remux 스트림은 파이프로 흘리는 fragmented mp4라
재생기가 길이도 모르고 seek도 못 한다. 그래서 위치 계산과 seek을 `InlinePlayer`가
직접 맡는다 — 이 계약이 깨지면 진행 막대가 멎거나(길이 0) seek이 제자리를 맴돈다.

seek은 ffmpeg를 그 지점에서 새로 띄우는 방식이라, 재생기의 위치는 **매번 0부터**
다시 센다. 영상 기준 위치 = 재생기 위치 + 스트림 시작 오프셋이다.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
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


@pytest.fixture()
def clock(monkeypatch):
    """seek 쿨다운 시계 — 쓰는 쪽 모듈(timeline)의 시계를 가변 셀로 바꾼다(ms)."""
    cell = [0]
    monkeypatch.setattr(
        "gui.widgets.player.mixins.timeline._monotonic_ms", lambda: cell[0]
    )
    return cell


def _source(player: InlinePlayer) -> str:
    return player._player.source().toString()


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
    def test_직전_커밋_직후의_seek은_바로_반영되지_않고_모였다_나간다(
        self, player, qtbot, clock
    ):
        """J/L 연타마다 ffmpeg를 새로 띄우면 화면이 멎는다.

        배치 6(A8)으로 바뀐 기대값: 첫 seek은 즉시 나가고(쿨다운 밖), **그 직후(600ms
        이내)** 의 seek만 모인다.
        """
        _ready(player)
        clock[0] = 0
        player._seek_to(10_000)                  # 이력 없음 → 즉시 커밋
        assert player._pending_seek_ms is None
        assert _source(player).endswith("?ss=10.000")

        clock[0] = 100
        player._seek_to(30_000)
        player._seek_to(60_000)
        assert player._pending_seek_ms == 60_000
        assert _source(player).endswith("?ss=10.000")

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

    def test_길이를_넘겨_seek_하지_않는다(self, player, clock):
        _ready(player)
        clock[0] = 0
        player._seek_to(1_000)                   # 쿨다운을 시작시킨다(즉시 커밋)
        clock[0] = 100
        player._seek_to(_DURATION + 60_000)
        assert player._pending_seek_ms == _DURATION

    def test_길이를_넘긴_첫_seek도_길이로_제한되어_즉시_나간다(self, player, clock):
        _ready(player)
        clock[0] = 0
        player._seek_to(_DURATION + 60_000)
        assert player._pending_seek_ms is None
        assert _source(player).endswith(f"?ss={_DURATION / 1000:.3f}")

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

    def test_먼_오프셋_스트림의_오류는_재시도_없이_위치를_유지해_병합으로_간다(
        self, player, monkeypatch
    ):
        """원본이 먼 오프셋을 거부하면 같은 실패가 반복된다 — 0부터 재시도하지 않는다."""
        _ready(player)
        player._stream_offset_ms = 20_000
        fetches, merges = [], []
        monkeypatch.setattr(player, "_fetch_stream", lambda: fetches.append(True))
        monkeypatch.setattr(player, "_fall_back_to_merge", lambda ms: merges.append(ms))
        player._on_error(QMediaPlayer.Error.ResourceError, "x")
        assert merges and 20_000 <= merges[0] < 20_000 + 5_000
        assert fetches == []
        assert player._stream_retries == 0

    def test_오프셋_0의_remux_오류는_먼저_재시도한다(self, player, monkeypatch):
        _ready(player)
        assert player._stream_offset_ms == 0
        fetches, merges = [], []
        monkeypatch.setattr(player, "_fetch_stream", lambda: fetches.append(True))
        monkeypatch.setattr(player, "_fall_back_to_merge", lambda ms: merges.append(ms))
        player._on_error(QMediaPlayer.Error.ResourceError, "x")
        assert fetches and merges == []
        assert player._stream_retries == 1

    def test_끝까지_봤으면_정상_보고한다(self, player):
        _ready(player)
        player._stream_offset_ms = _DURATION
        finished = []
        player.playback_finished.connect(lambda: finished.append(True))
        player._on_media_status(QMediaPlayer.MediaStatus.EndOfMedia)
        assert finished == [True]


class TestSeekCooldown:
    """A8 — 직전 커밋 뒤 600ms 이상 지났으면 즉시 커밋하고, 아니면 모아서 뒤에서 커밋한다.

    단발 seek은 300ms 디바운스를 기다릴 이유가 없고(첫 반응이 늦어 보인다), 연타는
    여전히 합쳐야 한다(ffmpeg를 매번 띄우면 화면이 멎는다). 모든 seek은 `_seek_to` 하나를
    거치고, 대기 중이면 `position_ms`는 목표를 답한다(재생 스트림 규칙).
    """

    @pytest.fixture()
    def sources(self, player, monkeypatch):
        """커밋이 실제로 소스를 바꿀 때마다 URL을 기록한다(setSource 횟수 = 커밋 횟수)."""
        # 실제 재생·오류가 상태(_close_remux 등)를 바꾸지 않게 한다 — 시험은 커밋 시점만 본다.
        monkeypatch.setattr(player, "_do_play_start", lambda: None)
        monkeypatch.setattr(player, "_fetch_stream", lambda: None)
        _ready(player)
        seen: list[str] = []
        player._player.sourceChanged.connect(lambda url: seen.append(url.toString()))
        return seen

    def test_쿨다운_상수는_600ms다(self):
        from gui.widgets.player.mixins import timeline

        assert timeline.SEEK_IMMEDIATE_GAP_MS == 600

    def test_첫_seek은_즉시_커밋된다(self, player, clock, sources):
        """커밋 이력이 없는 첫 seek이 시계 0에서도 쿨다운에 걸리면 안 된다."""
        clock[0] = 0
        player._seek_to(30_000)

        assert player._pending_seek_ms is None
        assert _source(player).endswith("?ss=30.000")
        assert player._seek_commit.isActive() is False
        assert player.position_ms == 30_000
        assert sources == [_source(player)]

    def test_경계_600ms면_즉시_커밋된다(self, player, clock, sources):
        clock[0] = 0
        player._seek_to(10_000)
        clock[0] = 600
        player._seek_to(40_000)

        assert player._pending_seek_ms is None
        assert _source(player).endswith("?ss=40.000")
        assert len(sources) == 2

    def test_경계_599ms면_모은다(self, player, clock, sources, qtbot):
        clock[0] = 0
        player._seek_to(10_000)
        clock[0] = 599
        player._seek_to(40_000)

        assert player._pending_seek_ms == 40_000
        assert player._seek_commit.isActive() is True
        assert _source(player).endswith("?ss=10.000")
        assert player.position_ms == 40_000, "대기 중에는 목표를 답해야 한다"

        qtbot.waitUntil(lambda: player._pending_seek_ms is None, timeout=2000)
        assert _source(player).endswith("?ss=40.000")
        assert len(sources) == 2

    def test_JL_5연타는_커밋이_정확히_2회다(self, player, clock, sources, qtbot):
        assert player._stream_duration_ms == _DURATION

        for t in (0, 50, 100, 150, 200):
            clock[0] = t
            player._seek_relative(+10)
        assert player._pending_seek_ms == 50_000
        qtbot.waitUntil(lambda: player._pending_seek_ms is None, timeout=2000)

        assert len(sources) == 2, sources     # 앞 1 + 뒤 1
        assert sources[0].endswith("?ss=10.000")
        assert sources[-1].endswith("?ss=50.000")

    def test_키_입력_L_5연타도_커밋이_2회다(self, player, clock, sources, qtbot):
        player.show()
        qtbot.waitExposed(player)
        player.activateWindow()
        player.setFocus()
        qtbot.waitUntil(player.isActiveWindow, timeout=3000)

        for t in (0, 50, 100, 150, 200):
            clock[0] = t
            qtbot.keyClick(player, Qt.Key.Key_L)
        qtbot.waitUntil(lambda: player._pending_seek_ms is None, timeout=2000)

        assert len(sources) == 2, sources
        assert sources[0].endswith("?ss=10.000")
        assert sources[-1].endswith("?ss=50.000")

    def test_뒤쪽_커밋도_쿨다운_시각을_갱신한다(self, player, clock, sources, qtbot):
        clock[0] = 0
        player._seek_to(10_000)                  # 즉시 커밋(t=0)
        clock[0] = 100
        player._seek_to(20_000)                  # 모은다
        clock[0] = 250                           # 타이머가 나가는 시각
        qtbot.waitUntil(lambda: player._pending_seek_ms is None, timeout=2000)
        assert player._last_seek_commit_ms == 250, "타이머 커밋이 시각을 갱신하지 않았다"

        clock[0] = 250 + 599
        player._seek_to(30_000)
        assert player._pending_seek_ms == 30_000, "직전 커밋 기준이어야 한다(첫 커밋 기준 아님)"

        qtbot.waitUntil(lambda: player._pending_seek_ms is None, timeout=2000)
        assert player._last_seek_commit_ms == 250 + 599
        clock[0] = 250 + 599 + 600
        player._seek_to(40_000)
        assert player._pending_seek_ms is None
        assert _source(player).endswith("?ss=40.000")

    def test_즉시_커밋도_쿨다운_시각을_갱신한다(self, player, clock, sources):
        clock[0] = 1_000
        player._seek_to(10_000)
        assert player._last_seek_commit_ms == 1_000

    def test_대기_중에_쿨다운이_지나면_최신_목표를_즉시_커밋하고_타이머를_끈다(
        self, player, clock, sources
    ):
        """늦은 타이머가 한 번 더 setSource 하면 같은 지점을 두 번 여는 낭비다."""
        clock[0] = 0
        player._seek_to(10_000)
        clock[0] = 100
        player._seek_to(20_000)                  # 모은다
        assert player._seek_commit.isActive() is True

        clock[0] = 700
        player._seek_to(30_000)                  # 직전 커밋(0) 기준 700ms → 즉시

        assert player._pending_seek_ms is None
        assert player._seek_commit.isActive() is False
        assert _source(player).endswith("?ss=30.000")
        assert len(sources) == 2

    def test_remux가_아닌_소스는_재생기에_맡기고_타이머를_쓰지_않는다(
        self, player, clock, monkeypatch
    ):
        monkeypatch.setattr(player, "_do_play_start", lambda: None)
        player._on_stream_ready("http://direct/video.mp4", "360p", False, 0)
        seen: list[str] = []
        player._player.sourceChanged.connect(lambda url: seen.append(url.toString()))

        clock[0] = 0
        player._seek_to(5_000)

        assert player._pending_seek_ms is None
        assert player._seek_commit.isActive() is False
        assert seen == [], "일반 소스의 seek이 소스를 갈아 끼우면 안 된다"

    def test_소스를_닫으면_다음_스트림의_첫_seek은_다시_즉시다(
        self, player, clock, sources
    ):
        clock[0] = 0
        player._seek_to(10_000)                  # 즉시 커밋(t=0)
        player._close_remux()
        _ready(player)

        clock[0] = 100                           # 쿨다운이 이어졌다면 모았을 시각
        player._seek_to(5_000)

        assert player._pending_seek_ms is None, "새 스트림의 첫 seek이 쿨다운에 걸렸다"
        assert _source(player).endswith("?ss=5.000")

    def test_상대_seek은_즉시_커밋_뒤에도_목표에서_이어_계산한다(
        self, player, clock, sources
    ):
        clock[0] = 0
        player._seek_to(10_000)
        clock[0] = 10
        player._seek_relative(+10)
        clock[0] = 20
        player._seek_relative(+10)

        assert player._pending_seek_ms == 30_000
        assert player.position_ms == 30_000
