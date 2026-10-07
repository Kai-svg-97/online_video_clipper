"""영상 자막 목록은 스트림·화질 목록과 **같은 원본 info**를 공유한다(배치 6, B1-1).

왜: load와 ▶가 같은 URL로 yt-dlp를 두 번 돌리던 것 중 하나가 자막 목록 조회였다.
쿠키가 필요한 사용자(`_ydl_opts`)는 캐시의 익명 info와 자막 목록이 달라질 수 있으므로
기존 경로(`list_tracks(url, cookie_opts)`)를 그대로 쓴다 — 공유 때문에 자막을 잃으면 안 된다.

`gui/`는 `infrastructure/`를 임포트하지 않는다 — 트랙 추출은 자막 포트의
`tracks_from_info(info)`가 맡고, 시험은 가짜 포트로 그 경계를 검증한다.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from gui.widgets.player import stream as stream_mod
from gui.widgets.player.stream import _StreamWorker, _SubtitleListWorker
from gui.widgets.video_player import InlinePlayer
from infrastructure.subtitle.youtube_subtitles import SubtitleTrackInfo

_URL = "https://www.youtube.com/watch?v=abc"
_TRACKS = [
    SubtitleTrackInfo("ko", "한국어", "https://x/ko", "json3", False),
    SubtitleTrackInfo("en", "English", "https://x/en", "json3", True),
]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """모듈 전역 캐시를 비우고, 실사용 설정을 건드리지 않는다."""
    import config.settings as settings

    stream_mod._VSUB_LIST_CACHE.clear()
    monkeypatch.setattr(settings, "save_setting", lambda *a, **k: None)
    monkeypatch.setattr(settings, "VIDEO_SUBTITLE_LANG_1", "", raising=False)
    monkeypatch.setattr(settings, "VIDEO_SUBTITLE_LANG_2", "", raising=False)
    yield
    stream_mod._VSUB_LIST_CACHE.clear()


class _FakeSubs:
    """`IVideoSubtitleSource` — 어느 경로로 트랙을 만들었는지 기록한다."""

    def __init__(self) -> None:
        self.from_info: list[dict] = []
        self.list_calls: list[tuple[str, dict | None]] = []

    def tracks_from_info(self, info):
        self.from_info.append(info)
        return list(_TRACKS)

    def list_tracks(self, url, cookie_opts=None):
        self.list_calls.append((url, cookie_opts))
        return list(_TRACKS)

    def fetch_cues(self, track):
        return []

    def translated(self, track, target_lang):
        return track

    def translate_targets(self):
        return ()


class _FakeInfo:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, str | None, bool]] = []
        self._error = error

    def info(self, url, *, client=None, fresh=False):
        self.calls.append((url, client, fresh))
        if self._error is not None:
            raise self._error
        return {"id": "abc", "subtitles": {}, "stream_url": "http://good", "formats": []}


def _run_list_worker(worker) -> list[tuple[str, list]]:
    done: list = []
    worker.done.connect(lambda url, tracks: done.append((url, tracks)))
    worker.run()
    return done


class TestSubtitleListWorker:
    def test_쿠키가_없으면_공유_info에서_트랙을_뽑는다(self, qapp_instance):
        subs, info = _FakeSubs(), _FakeInfo()

        done = _run_list_worker(_SubtitleListWorker(subs, _URL, {}, info_source=info))

        assert info.calls == [(_URL, None, False)]
        assert len(subs.from_info) == 1
        assert subs.list_calls == [], "공유할 수 있는데 yt-dlp를 따로 돌렸다"
        assert done == [(_URL, _TRACKS)]
        assert len(done[0][1]) == 2

    def test_쿠키가_있으면_기존_경로를_쓴다(self, qapp_instance):
        """쿠키 사용자는 로그인 상태 자막이 보인다 — 익명 캐시로 대신하면 안 된다."""
        subs, info = _FakeSubs(), _FakeInfo()
        cookies = {"cookiefile": "x"}

        done = _run_list_worker(_SubtitleListWorker(subs, _URL, cookies, info_source=info))

        assert subs.list_calls == [(_URL, cookies)]
        assert info.calls == []
        assert subs.from_info == []
        assert done == [(_URL, _TRACKS)]

    def test_info_source가_없으면_기존_경로다(self, qapp_instance):
        subs = _FakeSubs()

        done = _run_list_worker(_SubtitleListWorker(subs, _URL, {}))

        assert subs.list_calls == [(_URL, {})]
        assert done == [(_URL, _TRACKS)]

    def test_조회가_실패하면_빈_목록이고_예외가_밖으로_나오지_않는다(self, qapp_instance):
        subs, info = _FakeSubs(), _FakeInfo(error=RuntimeError("boom"))

        done = _run_list_worker(_SubtitleListWorker(subs, _URL, {}, info_source=info))

        assert done == [(_URL, [])]
        assert len(info.calls) == 1


class TestPlayerWiring:
    def test_플레이어가_자막_워커에_info_source를_넘긴다(self, qapp_instance, qtbot):
        """실제 스레드로 끝까지 — 목록이 공유 info에서 만들어져 화면 상태에 들어간다."""
        subs, info = _FakeSubs(), _FakeInfo()
        player = InlinePlayer(subtitles=subs, info_source=info)
        qtbot.addWidget(player)
        player._video_url = _URL
        player._ydl_opts = {}

        player._load_video_subtitle_list()
        qtbot.waitUntil(lambda: len(player._vsub_available) == 2, timeout=5000)
        worker = player._vsub_list_worker
        qtbot.waitUntil(worker.isFinished, timeout=5000)

        assert info.calls == [(_URL, None, False)]
        assert subs.list_calls == []

    def test_쿠키_옵션이_있으면_플레이어도_기존_경로를_탄다(self, qapp_instance, qtbot):
        subs, info = _FakeSubs(), _FakeInfo()
        player = InlinePlayer(subtitles=subs, info_source=info)
        qtbot.addWidget(player)
        player._video_url = _URL
        player._ydl_opts = {"cookiefile": "x"}

        player._load_video_subtitle_list()
        qtbot.waitUntil(lambda: len(player._vsub_available) == 2, timeout=5000)
        qtbot.waitUntil(player._vsub_list_worker.isFinished, timeout=5000)

        assert subs.list_calls == [(_URL, {"cookiefile": "x"})]
        assert info.calls == []


class TestLoadAndPlaySharesOneExtract:
    def test_자막_목록과_스트림_확보는_extract_1회를_같이_쓴다(self, qapp_instance, qtbot, monkeypatch):
        """수용 기준 'load+▶ extract 1회' — 서로 다른 스레드에서 동시에 묻는다."""
        from infrastructure.media.video_info_cache import VideoInfoCache

        monkeypatch.setattr(stream_mod, "_stream_playable", lambda u: True)
        started, release = threading.Event(), threading.Event()
        calls: list = []
        lock = threading.Lock()

        def counting(url, client=None):
            with lock:
                calls.append((url, client))
            started.set()
            release.wait(5)
            return {"id": "abc", "stream_url": "http://good", "formats": []}

        cache = VideoInfoCache(counting)
        subs = _FakeSubs()

        class _YDL:
            def __init__(self, opts):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def process_ie_result(self, ie, download=False):
                return {"url": ie["stream_url"], "height": 360}

        module = SimpleNamespace(YoutubeDL=_YDL)
        sub_worker = _SubtitleListWorker(subs, _URL, {}, info_source=cache)
        stream_worker = _StreamWorker(_URL, "fmt", False, info_source=cache)
        done: list = []
        ready: list = []
        sub_worker.done.connect(lambda url, tracks: done.append(url))
        stream_worker.stream_ready.connect(lambda *a: ready.append(a))

        t1 = threading.Thread(target=sub_worker.run, daemon=True)
        t2 = threading.Thread(target=lambda: stream_worker._run_stream(module), daemon=True)
        t1.start()
        assert started.wait(2), "첫 extract가 시작되지 않았다"
        t2.start()
        # 두 번째 요청이 진행 중 요청에 합류할 때까지 기다린다(sleep 대신 상태를 본다).
        import time

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if any(e.waiters >= 1 for e in list(getattr(cache, "_inflight", {}).values())):
                break
            time.sleep(0)
        release.set()
        t1.join(5)
        t2.join(5)

        assert not t1.is_alive() and not t2.is_alive()
        assert len(calls) == 1, f"extract가 {len(calls)}회였다"
        # run()을 일반 스레드에서 직접 불렀으므로 신호가 메인 스레드 큐에 쌓여 있다 — 이벤트를 처리한다.
        qtbot.waitUntil(lambda: done == [_URL] and len(ready) == 1, timeout=5000)
        assert done == [_URL]
        assert len(ready) == 1 and ready[0][0] == "http://good"
