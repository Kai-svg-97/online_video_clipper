"""스트림 확보 견고성 — 403 간헐 실패 시 다른 클라이언트로 재시도하는지.

실측 배경: 같은 영상의 googlevideo URL이 기본(web) 클라이언트에서 어떤 때는 200,
어떤 때는 403을 돌려준다. 예전에는 첫 시도가 실패하면 그대로 포기하고 기본 브라우저를
열어버려 "앱에서 재생이 안 된다"는 신고로 이어졌다. 네트워크 없이 가짜 yt-dlp로
분기만 검증한다.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from PyQt6.QtMultimedia import QMediaPlayer

from gui.widgets import video_player as vp


# ── 포맷 선택 (순수 함수) ────────────────────────────────────────────
class TestPickStreamUrl:
    def test_최상위_url을_그대로_쓴다(self):
        url, fmt = vp._pick_stream_url({"url": "http://direct", "height": 360})
        assert url == "http://direct"
        assert fmt.get("height") == 360

    def test_muxed_mp4를_우선한다(self):
        info = {
            "formats": [
                {"url": "http://mp4", "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a",
                 "height": 360},
                {"url": "http://webm", "ext": "webm", "vcodec": "vp9", "acodec": "opus",
                 "height": 720},
            ]
        }
        url, _ = vp._pick_stream_url(info)
        assert url == "http://mp4"

    def test_mp4가_없으면_다른_muxed를_쓴다(self):
        info = {
            "formats": [
                {"url": "http://webm", "ext": "webm", "vcodec": "vp9", "acodec": "opus"},
            ]
        }
        url, _ = vp._pick_stream_url(info)
        assert url == "http://webm"

    def test_영상만_있는_포맷은_고르지_않는다(self):
        """무음 재생·재생 실패로 이어지므로 차라리 다음 후보로 넘어가야 한다."""
        info = {
            "formats": [
                {"url": "http://videoonly", "ext": "mp4", "vcodec": "avc1", "acodec": "none"},
                {"url": "http://audioonly", "ext": "m4a", "vcodec": "none", "acodec": "mp4a"},
            ]
        }
        assert vp._pick_stream_url(info) == ("", {})


class TestIsYoutube:
    @pytest.mark.parametrize(
        "url", ["https://www.youtube.com/watch?v=x", "https://youtu.be/x"]
    )
    def test_youtube(self, url):
        assert vp._is_youtube(url) is True

    def test_다른_사이트(self):
        assert vp._is_youtube("https://vimeo.com/123") is False


# ── 검증 요청 형태 (실제 재생기와 같아야 한다) ────────────────────────
class _FakeResp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    def close(self) -> None:
        pass


class TestProbeMatchesPlayer:
    """검증 요청은 ffmpeg가 파일을 열 때와 **같은 형태**여야 한다.

    실측: 같은 URL이 `bytes=0-1`(제한 범위)에는 206, `bytes=0-`(열린 범위)에는 403을
    준다. 제한 범위로 확인하면 검증은 통과하는데 재생은 403으로 실패했다(위양성).
    """

    def _spy(self, monkeypatch, status: int) -> dict:
        seen: dict = {}

        def fake_get(url, headers=None, stream=None, timeout=None):
            seen["url"] = url
            seen.update(headers or {})
            return _FakeResp(status)

        monkeypatch.setattr("requests.get", fake_get)
        return seen

    def test_열린_범위로_확인한다(self, monkeypatch):
        seen = self._spy(monkeypatch, 206)
        assert vp._stream_playable("http://x") is True
        assert seen["Range"] == "bytes=0-"

    def test_403이면_재생_불가로_본다(self, monkeypatch):
        self._spy(monkeypatch, 403)
        assert vp._stream_playable("http://x") is False

    def test_요청_자체가_실패하면_불가로_본다(self, monkeypatch):
        def boom(*a, **k):
            raise OSError("network down")

        monkeypatch.setattr("requests.get", boom)
        assert vp._stream_playable("http://x") is False


# ── 클라이언트 대체 재시도 ───────────────────────────────────────────
def _info(url: str) -> dict:
    return {"url": url, "height": 360}


class _FakeYoutubeDL:
    def __init__(self, opts, reg):
        self._opts = opts
        self._reg = reg

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        clients = ((self._opts.get("extractor_args") or {}).get("youtube") or {}).get(
            "player_client"
        ) or []
        client = clients[0] if clients else None
        self._reg["calls"].append(client)
        info = self._reg["by_client"].get(client)
        if info is None:
            raise RuntimeError(f"Requested format is not available ({client})")
        return info


def _fake_yt_dlp(by_client: dict):
    reg = {"calls": [], "by_client": by_client}
    module = SimpleNamespace(YoutubeDL=lambda opts: _FakeYoutubeDL(opts, reg))
    return module, reg


def _worker(url: str = "https://www.youtube.com/watch?v=abc") -> vp._StreamWorker:
    """QThread 초기화 없이 로직만 쓰는 워커(신호는 클래스 속성이라 그대로 동작)."""
    w = vp._StreamWorker(url, vp._DEFAULT_QUALITY_FMT, False)
    return w


def _run(worker, module, monkeypatch, playable) -> tuple[list, list]:
    monkeypatch.setattr(vp, "_stream_playable", playable)
    ready: list = []
    failed: list = []
    worker.stream_ready.connect(
        lambda src, quality, is_local: ready.append((src, quality, is_local))
    )
    worker.failed.connect(failed.append)
    worker._run_stream(module)
    return ready, failed


class TestClientFallback:
    def test_기본_클라이언트가_403이면_다음_클라이언트로_넘어간다(
        self, qapp_instance, monkeypatch
    ):
        module, reg = _fake_yt_dlp(
            {None: _info("http://blocked"), "android": _info("http://good")}
        )
        ready, failed = _run(
            _worker(), module, monkeypatch, lambda u: u == "http://good"
        )
        assert failed == []
        assert ready == [("http://good", "360p", False)]
        assert reg["calls"] == [None, "android"]

    def test_첫_시도가_되면_더_시도하지_않는다(self, qapp_instance, monkeypatch):
        module, reg = _fake_yt_dlp({None: _info("http://good")})
        ready, failed = _run(_worker(), module, monkeypatch, lambda u: True)
        assert ready and failed == []
        assert reg["calls"] == [None]

    def test_추출_예외가_나도_다음_클라이언트를_시도한다(
        self, qapp_instance, monkeypatch
    ):
        # None 클라이언트는 by_client에 없어 예외를 던진다
        module, reg = _fake_yt_dlp({"android": _info("http://good")})
        ready, failed = _run(_worker(), module, monkeypatch, lambda u: True)
        assert ready == [("http://good", "360p", False)]
        assert reg["calls"][:2] == [None, "android"]

    def test_검증이_전부_실패하면_그래도_첫_URL로_재생을_시도한다(
        self, qapp_instance, monkeypatch
    ):
        """확인 요청이 막히는 환경(프록시)에서 재생을 통째로 잃지 않기 위한 안전판."""
        module, reg = _fake_yt_dlp(
            {None: _info("http://a"), "android": _info("http://b"),
             "ios": _info("http://c"), "tv": _info("http://d")}
        )
        ready, failed = _run(_worker(), module, monkeypatch, lambda u: False)
        assert failed == []
        assert ready == [("http://a", "360p", False)]
        assert reg["calls"] == [None, "android", "ios", "tv"]

    def test_URL을_하나도_못_얻으면_실패를_알린다(self, qapp_instance, monkeypatch):
        module, reg = _fake_yt_dlp({})   # 모든 클라이언트에서 추출 예외
        ready, failed = _run(_worker(), module, monkeypatch, lambda u: True)
        assert ready == []
        assert len(failed) == 1
        assert reg["calls"] == [None, "android", "ios", "tv"]

    def test_유튜브가_아니면_기본_클라이언트만_시도한다(
        self, qapp_instance, monkeypatch
    ):
        """다른 사이트에서 YouTube 클라이언트를 바꿔 재시도해봐야 의미가 없다."""
        module, reg = _fake_yt_dlp({None: _info("http://a")})
        _run(_worker("https://vimeo.com/1"), module, monkeypatch, lambda u: False)
        assert reg["calls"] == [None]


# ── 재생 오류 후 자동 재시도 / 브라우저 자동 실행 제거 ──────────────────
@pytest.fixture
def player(qapp_instance):
    p = vp.InlinePlayer()
    p.resize(320, 180)
    yield p
    p.deleteLater()


class TestPlaybackErrorRetry:
    def test_스트리밍_오류는_한_번_다시_받는다(self, player, monkeypatch):
        calls: list = []
        monkeypatch.setattr(player, "_fetch_stream", lambda: calls.append(1))
        failed: list = []
        player.playback_failed.connect(failed.append)
        player._video_url = "https://www.youtube.com/watch?v=abc"
        player._playing_local = False
        player._stream_retries = 0

        player._on_error(QMediaPlayer.Error.NetworkError, "boom")
        assert calls == [1] and failed == []      # 조용히 재시도

        player._on_error(QMediaPlayer.Error.NetworkError, "boom")
        assert calls == [1] and failed == ["boom"]  # 예산 소진 → 실패 통지

    def test_로컬_파일_오류는_재시도하지_않는다(self, player, monkeypatch):
        """다시 받아도 같은 파일이라 반복해봐야 소용없다."""
        calls: list = []
        monkeypatch.setattr(player, "_fetch_stream", lambda: calls.append(1))
        failed: list = []
        player.playback_failed.connect(failed.append)
        player._video_url = "https://www.youtube.com/watch?v=abc"
        player._playing_local = True

        player._on_error(QMediaPlayer.Error.FormatError, "codec")
        assert calls == [] and failed == ["codec"]

    def test_재생이_시작되면_재시도_예산이_회복된다(self, player):
        player._stream_retries = 1
        player._on_playback_state(QMediaPlayer.PlaybackState.PlayingState)
        assert player._stream_retries == 0

    def test_실패_메시지를_영상_자리에_보여준다(self, player):
        player.show_playback_error("스트림 URL이 거부되었습니다(재생 서버 403).")
        assert player._status_lbl.isHidden() is False
        assert "재생 실패" in player._status_lbl.text()


class TestNoBrowserAutoOpen:
    def test_재생_실패가_브라우저를_열지_않는다(self, qapp_instance, monkeypatch):
        """사용자는 앱에서 보려고 누른 것이다 — 창이 튀면 안 된다."""
        from gui.panels import video_detail_panel as vdp
        from gui.panels.detail.mixins import info as info_mixin

        opened: list = []
        # 브라우저를 여는 곳은 상단 🌐 버튼(info mixin)뿐이다 — **쓰는 쪽 모듈**을
        # 패치해야 실제로 열렸는지 알 수 있다(재생 실패 경로는 여기를 부르면 안 된다).
        monkeypatch.setattr(
            info_mixin.QDesktopServices, "openUrl", lambda url: opened.append(url)
        )
        widget = vdp.VideoDetailWidget()
        widget._current_url = "https://www.youtube.com/watch?v=abc"

        widget._on_play_failed("스트림 URL이 거부되었습니다(재생 서버 403).")

        assert opened == []
        assert "재생 실패" in widget._player._status_lbl.text()
        widget.deleteLater()
