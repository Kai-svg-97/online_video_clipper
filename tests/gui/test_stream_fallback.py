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
    # 워커는 gui/widgets/player/stream.py 안에 있다 — 그 모듈의 전역을 패치해야
    # 실제로 검증 함수가 바뀐다(video_player의 재수출 이름을 바꿔 봐야 소용없다).
    from gui.widgets.player import stream as stream_mod

    monkeypatch.setattr(stream_mod, "_stream_playable", playable)
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


# ── 배치 6: 스트림 워커가 info_source(캐시)를 쓰되 우회할 곳은 우회한다 ─────────
class _FakeInfoSource:
    """`IVideoInfoSource` — 호출을 (url, client, fresh)로 기록하고 클라이언트별 원본을 돌려준다."""

    def __init__(self, by_client: dict) -> None:
        self.calls: list[tuple[str, str | None, bool]] = []
        self._by_client = by_client

    def info(self, url, *, client=None, fresh=False):
        self.calls.append((url, client, fresh))
        raw = self._by_client.get(client)
        if raw is None:
            raise RuntimeError(f"Requested format is not available ({client})")
        return raw


class _ProcessingYoutubeDL:
    """원본 info를 `process_ie_result`로 처리하는 가짜 — `extract_info`는 쓰면 안 된다."""

    def __init__(self, opts, reg):
        self._opts = opts
        self._reg = reg
        reg["instances"].append(opts.get("format"))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, *a, **k):
        self._reg["extract_calls"].append(a)
        raise AssertionError("info_source가 있으면 직접 extract 하지 않는다")

    def process_ie_result(self, ie_result, download=False):
        self._reg["processed"].append(self._opts.get("format"))
        # 호출자가 넘긴 객체를 마음대로 바꾼다 — 캐시된 원본이 오염되면 안 된다.
        ie_result["mutated"] = True
        for f in ie_result.get("formats") or []:
            f["mutated"] = True
        if "video_url" in ie_result:      # 고화질(영상+오디오 분리) 선택
            return {
                "requested_formats": [
                    {"url": ie_result["video_url"], "filesize": 1000, "height": 1080},
                    {"url": ie_result["audio_url"], "filesize": 100},
                ],
                "duration": 100,
                "height": 1080,
            }
        return {"url": ie_result["stream_url"], "height": 360}


def _processing_module():
    reg = {"extract_calls": [], "processed": [], "instances": []}
    module = SimpleNamespace(YoutubeDL=lambda opts: _ProcessingYoutubeDL(opts, reg))
    return module, reg


def _raw(stream_url: str, **extra) -> dict:
    return {"id": "abc", "stream_url": stream_url, "formats": [{"format_id": "18"}], **extra}


_YT = "https://www.youtube.com/watch?v=abc"


def _patch_playable(monkeypatch, fn) -> None:
    from gui.widgets.player import stream as stream_mod

    monkeypatch.setattr(stream_mod, "_stream_playable", fn)


def _run_stream_sync(worker, module) -> tuple[list, list]:
    ready: list = []
    failed: list = []
    worker.stream_ready.connect(lambda *a: ready.append(a))
    worker.failed.connect(failed.append)
    worker._run_stream(module)
    return ready, failed


class TestStreamWorkerUsesInfoSource:
    def test_첫_클라이언트가_통과하면_캐시를_탄_조회_1회(self, qapp_instance, monkeypatch):
        _patch_playable(monkeypatch, lambda u: True)
        src = _FakeInfoSource({None: _raw("http://good")})
        module, reg = _processing_module()
        w = vp._StreamWorker(_YT, vp._DEFAULT_QUALITY_FMT, False, info_source=src)

        ready, failed = _run_stream_sync(w, module)

        assert failed == []
        assert len(ready) == 1 and ready[0][0] == "http://good"
        assert src.calls == [(_YT, None, False)]
        assert reg["extract_calls"] == [], "info_source가 있는데 직접 extract 했다"
        assert reg["processed"] == [vp._DEFAULT_QUALITY_FMT], "화질은 원본을 처리해 얻는다"

    def test_검증_실패_뒤의_모든_조회는_fresh다(self, qapp_instance, monkeypatch):
        """403 폴백이 캐시를 타면 같은 만료 URL을 되풀이해 받는다."""
        _patch_playable(monkeypatch, lambda u: u == "http://good")
        src = _FakeInfoSource({None: _raw("http://blocked"), "android": _raw("http://good")})
        module, _ = _processing_module()
        w = vp._StreamWorker(_YT, vp._DEFAULT_QUALITY_FMT, False, info_source=src)

        ready, failed = _run_stream_sync(w, module)

        assert failed == []
        assert ready[0][0] == "http://good"
        assert len(src.calls) >= 2
        assert src.calls[0] == (_YT, None, False)
        assert src.calls[1][1] == "android"
        assert all(fresh for (_, _, fresh) in src.calls[1:]), src.calls

    def test_모든_클라이언트가_실패해도_첫_URL로_시도하고_이후_조회는_fresh다(
        self, qapp_instance, monkeypatch
    ):
        _patch_playable(monkeypatch, lambda u: False)
        src = _FakeInfoSource({
            None: _raw("http://a"), "android": _raw("http://b"),
            "ios": _raw("http://c"), "tv": _raw("http://d"),
        })
        module, _ = _processing_module()
        w = vp._StreamWorker(_YT, vp._DEFAULT_QUALITY_FMT, False, info_source=src)

        ready, failed = _run_stream_sync(w, module)

        assert failed == []
        assert ready[0][0] == "http://a"          # 기존 동작 유지: 첫 미검증 URL
        assert [c for (_, c, _) in src.calls] == [None, "android", "ios", "tv"]
        assert all(fresh for (_, _, fresh) in src.calls[1:]), src.calls

    def test_fresh로_만든_워커는_첫_조회부터_fresh다(self, qapp_instance, monkeypatch):
        """`_on_error` 재시도 — 방금 실패한 URL이 캐시에 남아 있다."""
        _patch_playable(monkeypatch, lambda u: True)
        src = _FakeInfoSource({None: _raw("http://good")})
        module, _ = _processing_module()
        w = vp._StreamWorker(_YT, vp._DEFAULT_QUALITY_FMT, False, info_source=src, fresh=True)

        _run_stream_sync(w, module)

        assert src.calls == [(_YT, None, True)]

    def test_info_source가_없으면_예전처럼_직접_추출한다(self, qapp_instance, monkeypatch):
        module, reg = _fake_yt_dlp({None: _info("http://good")})
        ready, failed = _run(_worker(), module, monkeypatch, lambda u: True)
        assert ready and failed == []
        assert reg["calls"] == [None]

    def test_원본은_처리_중에_오염되지_않는다(self, qapp_instance, monkeypatch):
        """캐시된 원본을 그대로 처리하면 다음 화질 선택이 이전 선택을 물려받는다."""
        from infrastructure.media.video_info_cache import VideoInfoCache

        _patch_playable(monkeypatch, lambda u: True)
        cache = VideoInfoCache(lambda url, client=None: _raw("http://good"))
        module, _ = _processing_module()
        w = vp._StreamWorker(_YT, vp._DEFAULT_QUALITY_FMT, False, info_source=cache)

        _run_stream_sync(w, module)
        again = cache.info(_YT)

        assert "mutated" not in again
        assert all("mutated" not in f for f in again["formats"])


def _install_worker_spy(monkeypatch):
    """`_fetch_stream`이 만드는 워커의 생성 인자를 기록한다(스레드는 시작하지 않는다)."""
    from gui.widgets.player.stream import _StreamWorker

    class _Spy(_StreamWorker):
        created: list = []

        def __init__(self, *args, **kwargs):
            _Spy.created.append((args, kwargs))
            super().__init__(*args, **kwargs)

        def start(self, *a, **k):
            pass

    _Spy.created = []
    # 쓰는 쪽 모듈(stream_source)이 자기 네임스페이스로 임포트했다.
    monkeypatch.setattr("gui.widgets.player.mixins.stream_source._StreamWorker", _Spy)
    return _Spy


class TestQualitySwitchReusesInfo:
    """B1-2/B1-3 — 화질 전환은 캐시된 원본에 포맷만 다시 골라 extract 0회다."""

    def test_화질을_바꿔도_extract는_늘지_않는다(self, qapp_instance, monkeypatch):
        from infrastructure.media.video_info_cache import VideoInfoCache

        _patch_playable(monkeypatch, lambda u: True)
        extracts: list = []

        def extract(url, client=None):
            extracts.append((url, client))
            return _raw("http://good")

        cache = VideoInfoCache(extract)
        module, reg = _processing_module()

        first = vp._StreamWorker(_YT, "fmt-1080", False, info_source=cache)
        _run_stream_sync(first, module)
        second = vp._StreamWorker(_YT, "fmt-720", False, info_source=cache)
        ready, failed = _run_stream_sync(second, module)

        assert failed == [] and len(ready) == 1
        assert len(extracts) == 1, "화질 전환이 다시 extract 했다"
        assert reg["processed"] == ["fmt-1080", "fmt-720"], "새 화질로 다시 골라야 한다"
        assert reg["instances"] == ["fmt-1080", "fmt-720"], "화질마다 새 YoutubeDL이어야 한다"

    def test_플레이어는_화질_전환_워커에_info_source를_넘기고_fresh가_아니다(
        self, qapp_instance, monkeypatch
    ):
        spy = _install_worker_spy(monkeypatch)
        src = _FakeInfoSource({None: _raw("http://good")})
        p = vp.InlinePlayer(info_source=src)
        try:
            p._video_url = _YT
            monkeypatch.setattr(
                QMediaPlayer, "playbackState",
                lambda self: QMediaPlayer.PlaybackState.PlayingState,
            )
            p._on_quality_changed("fmt-720", "720p", False)

            assert spy.created, "화질 전환이 워커를 만들지 않았다"
            args, kwargs = spy.created[-1]
            assert args[1] == "fmt-720"
            assert kwargs.get("info_source") is src
            assert kwargs.get("fresh", False) is False
        finally:
            p._remux_url = ""
            p.deleteLater()


class TestRemuxUsesInfoSource:
    def _remux_worker(self, monkeypatch, src, relay):
        monkeypatch.setattr("utils.resources.get_ffmpeg_path", lambda: "ffmpeg")
        return vp._StreamWorker(
            _YT, "fmt-1080", True, info_source=src, relay=relay, prefer_remux=True
        )

    @staticmethod
    def _relay():
        from unittest.mock import MagicMock

        relay = MagicMock()
        relay.source.side_effect = lambda url, headers, size: ("src", url)
        relay.open_session.return_value = "http://127.0.0.1:1/s/x/play.mp4"
        return relay

    @staticmethod
    def _hq_raw(tag: str) -> dict:
        return {"id": "abc", "video_url": f"http://v/{tag}", "audio_url": f"http://a/{tag}",
                "formats": [{"format_id": "137"}]}

    def test_중계_refresh는_fresh로_원래_클라이언트를_다시_묻는다(
        self, qapp_instance, monkeypatch
    ):
        """refresh는 URL이 만료됐을 때 불린다 — 캐시를 타면 만료 URL을 또 받는다."""
        src = _FakeInfoSource({None: self._hq_raw("old")})
        relay = self._relay()
        module, _ = _processing_module()
        w = self._remux_worker(monkeypatch, src, relay)
        ready: list = []
        w.stream_ready.connect(lambda *a: ready.append(a))

        w._run_remux(module)

        assert len(ready) == 1, "remux가 시작되지 않았다"
        assert src.calls == [(_YT, None, False)]
        refresh = relay.open_session.call_args.kwargs["refresh"]

        sources = refresh()

        assert src.calls[-1] == (_YT, None, True)
        assert len(src.calls) == 2
        assert sources[0] is not None

    def test_refresh는_캐시를_새_결과로_갈아_끼운다(self, qapp_instance, monkeypatch):
        """우회만 하고 캐시에 낡은 URL을 남기면 다음 재생이 또 만료 URL을 받는다."""
        from infrastructure.media.video_info_cache import VideoInfoCache

        extracts: list = []

        def extract(url, client=None):
            extracts.append((url, client))
            return self._hq_raw(f"gen{len(extracts)}")

        cache = VideoInfoCache(extract)
        relay = self._relay()
        module, _ = _processing_module()
        w = self._remux_worker(monkeypatch, cache, relay)
        w._run_remux(module)
        refresh = relay.open_session.call_args.kwargs["refresh"]

        refresh()
        assert len(extracts) == 2, "refresh가 캐시를 탔다"

        latest = cache.info(_YT)
        assert len(extracts) == 2
        assert latest["video_url"] == "http://v/gen2", "캐시에 낡은 결과가 남았다"

    def test_병합은_캐시를_쓰지_않는다(self, qapp_instance, monkeypatch):
        """다운로드를 겸하는 extract라 캐시에 섞으면 안 된다."""
        import os

        monkeypatch.setattr("utils.resources.get_ffmpeg_path", lambda: "ffmpeg")
        src = _FakeInfoSource({None: _raw("http://good")})
        made: list = []

        class _MergeYDL:
            def __init__(self, opts):
                self._opts = opts

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def extract_info(self, url, download=False):
                assert download is True
                path = self._opts["outtmpl"].replace("%(ext)s", "mp4")
                with open(path, "wb") as fh:
                    fh.write(b"x")
                made.append(path)
                return {"requested_downloads": [{"filepath": path, "height": 1080}]}

            def prepare_filename(self, info):
                return made[-1]

        w = vp._StreamWorker(_YT, "fmt-1080", True, info_source=src, prefer_remux=False)
        ready: list = []
        w.stream_ready.connect(lambda *a: ready.append(a))
        try:
            w._run_merge(SimpleNamespace(YoutubeDL=lambda opts: _MergeYDL(opts)))
        finally:
            for path in made:
                try:
                    os.remove(path)
                    os.rmdir(os.path.dirname(path))
                except OSError:
                    pass

        assert len(ready) == 1 and ready[0][2] is True
        assert src.calls == [], "병합이 info_source를 불렀다"


class TestPlayerFreshOnErrorRetry:
    def _player(self, monkeypatch):
        spy = _install_worker_spy(monkeypatch)
        src = _FakeInfoSource({None: _raw("http://good")})
        p = vp.InlinePlayer(info_source=src)
        p._video_url = _YT
        p._playing_local = False
        p._stream_retries = 0
        return p, spy, src

    def test_일반_재생은_fresh가_아니다(self, qapp_instance, monkeypatch):
        p, spy, src = self._player(monkeypatch)
        try:
            p._fetch_stream()

            _, kwargs = spy.created[-1]
            assert kwargs.get("info_source") is src
            assert kwargs.get("fresh", False) is False
        finally:
            p.deleteLater()

    def test_재생_오류_재시도는_fresh다(self, qapp_instance, monkeypatch):
        """재시도가 캐시를 타면 방금 실패한 URL을 다시 받는다."""
        p, spy, _ = self._player(monkeypatch)
        try:
            p._on_error(QMediaPlayer.Error.NetworkError, "boom")

            assert spy.created, "재시도가 워커를 만들지 않았다"
            _, kwargs = spy.created[-1]
            assert kwargs.get("fresh") is True
        finally:
            p.deleteLater()

    def test_remux_오프셋_0의_오류_재시도도_fresh다(self, qapp_instance, monkeypatch):
        p, spy, _ = self._player(monkeypatch)
        try:
            p._on_stream_ready("http://127.0.0.1:9/s/abc/play.mp4", "1080p", False, 213_000)
            assert p._stream_offset_ms == 0
            spy.created.clear()

            p._on_error(QMediaPlayer.Error.ResourceError, "x")

            assert spy.created and spy.created[-1][1].get("fresh") is True
        finally:
            p._remux_url = ""
            p.deleteLater()

    def test_fresh는_한_번만_쓰인다(self, qapp_instance, monkeypatch):
        """재시도가 끝난 뒤의 일반 재생·화질 전환은 다시 캐시를 쓴다."""
        p, spy, _ = self._player(monkeypatch)
        try:
            p._on_error(QMediaPlayer.Error.NetworkError, "boom")
            assert spy.created[-1][1].get("fresh") is True

            p._fetch_stream()

            assert spy.created[-1][1].get("fresh", False) is False
        finally:
            p.deleteLater()
