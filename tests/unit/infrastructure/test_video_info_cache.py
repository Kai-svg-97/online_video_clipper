"""VideoInfoCache — 같은 영상의 원본 info를 짧게 공유하는 캐시(배치 6, B1-1).

왜 필요한가: 상세 화면의 load와 ▶가 150ms 간격으로 같은 URL을 yt-dlp에 두 번 묻는다.
캐시가 **진행 중인 요청까지 합쳐** 한 번만 extract 하게 한다. 대신 URL이 만료되거나
403을 받는 경로(중계 refresh·클라이언트 폴백·재시도)는 캐시를 우회해야 하므로
`fresh=True`가 항상 새로 받고 캐시를 갈아 끼우는지도 고정한다.

시계는 생성자로 주입한다(전역 `time`을 패치하지 않는다). 스레드 동시성은 이벤트로
순서를 강제한다 — sleep으로 기다리지 않는다.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from infrastructure.media.video_info_cache import VideoInfoCache

_URL = "https://www.youtube.com/watch?v=abc"


class _Clock:
    """monotonic·epoch 두 시계를 함께 움직인다."""

    def __init__(self, wall: float = 1_700_000_000.0) -> None:
        self.mono = 1000.0
        self.epoch = wall
        self.wall0 = wall

    def now(self) -> float:
        return self.mono

    def wall(self) -> float:
        return self.epoch

    def tick(self, sec: float) -> None:
        self.mono += sec
        self.epoch += sec


def _info(expire: object = None, tag: int = 0) -> dict:
    """원본(process=False) info 모양 — googlevideo URL의 `expire` 쿼리가 TTL 근거다."""
    q = "" if expire is None else f"expire={expire}&"
    return {
        "id": "abc",
        "tag": tag,
        "formats": [
            # 스토리보드 같은 비 googlevideo 항목이 앞에 있어도 expire를 찾아야 한다.
            {"format_id": "sb0", "url": "https://i.ytimg.com/sb/abc/storyboard3_L0/default.jpg"},
            {"format_id": "18", "url": f"https://rr1.googlevideo.com/videoplayback?{q}id=1"},
        ],
    }


class _Extractor:
    def __init__(self, expire: object = None) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.expire = expire

    def __call__(self, url: str, client: str | None = None) -> dict:
        self.calls.append((url, client))
        return _info(self.expire, tag=len(self.calls))


def _cache(extract, clock: _Clock, **kw) -> VideoInfoCache:
    return VideoInfoCache(extract, now=clock.now, wall=clock.wall, **kw)


class TestPorts:
    def test_포트가_정의되어_있다(self):
        from domain.shared.ports import IVideoInfoSource, IVideoSubtitleSource

        assert hasattr(IVideoInfoSource, "info")
        assert hasattr(IVideoSubtitleSource, "tracks_from_info")

    def test_캐시는_info_포트를_구현한다(self):
        cache = VideoInfoCache(_Extractor())
        assert callable(cache.info)


class TestHitAndKeys:
    def test_같은_키를_두_번_물으면_extract_1회(self):
        clock, ex = _Clock(), _Extractor()
        cache = _cache(ex, clock)

        a = cache.info(_URL)
        b = cache.info(_URL)

        assert ex.calls == [(_URL, None)]
        assert a == b

    def test_클라이언트와_URL이_키에_들어간다(self):
        clock, ex = _Clock(), _Extractor()
        cache = _cache(ex, clock)

        cache.info(_URL)
        cache.info(_URL, client="android")
        cache.info(_URL + "2")

        assert ex.calls == [(_URL, None), (_URL, "android"), (_URL + "2", None)]
        # 각각 다시 물으면 적중이다.
        cache.info(_URL, client="android")
        assert len(ex.calls) == 3


class TestTtl:
    def test_expire가_멀면_30분이다(self):
        """TTL = min(3600 - 300, 1800) = 1800."""
        clock = _Clock()
        ex = _Extractor(expire=int(clock.wall0 + 3600))
        cache = _cache(ex, clock, max_ttl_sec=1800, margin_sec=300)

        cache.info(_URL)
        clock.tick(1799)
        cache.info(_URL)
        assert len(ex.calls) == 1, "1799초에는 적중이어야 한다"

        clock.tick(2)
        cache.info(_URL)
        assert len(ex.calls) == 2, "1801초에는 다시 받아야 한다"

    def test_expire가_가까우면_남은_시간에서_여유를_뺀다(self):
        """TTL = min(900 - 300, 1800) = 600."""
        clock = _Clock()
        ex = _Extractor(expire=int(clock.wall0 + 900))
        cache = _cache(ex, clock, max_ttl_sec=1800, margin_sec=300)

        cache.info(_URL)
        clock.tick(599)
        cache.info(_URL)
        assert len(ex.calls) == 1

        clock.tick(2)
        cache.info(_URL)
        assert len(ex.calls) == 2

    def test_expire가_없으면_기본값은_30분이다(self):
        """생성자 기본값(max_ttl_sec=1800)을 그대로 쓴다."""
        clock = _Clock()
        ex = _Extractor(expire=None)
        cache = VideoInfoCache(ex, now=clock.now, wall=clock.wall)

        cache.info(_URL)
        clock.tick(1799)
        cache.info(_URL)
        assert len(ex.calls) == 1

        clock.tick(2)
        cache.info(_URL)
        assert len(ex.calls) == 2

    @pytest.mark.parametrize("bad", ["abc", "", "12x"])
    def test_expire를_읽을_수_없으면_30분이다(self, bad):
        clock = _Clock()
        ex = _Extractor(expire=bad)
        cache = _cache(ex, clock)

        cache.info(_URL)
        clock.tick(1799)
        cache.info(_URL)
        assert len(ex.calls) == 1, "파싱 불가를 0초로 취급하면 캐시가 죽는다"

        clock.tick(2)
        cache.info(_URL)
        assert len(ex.calls) == 2, "파싱 불가를 무한으로 취급하면 만료 URL이 남는다"

    @pytest.mark.parametrize("remaining", [200, 300])
    def test_expire가_여유_안이면_캐시하지_않는다(self, remaining):
        """남은 시간이 margin(300) 이하면 TTL이 0 이하 — 음수 TTL로 영구 캐시되면 안 된다."""
        clock = _Clock()
        ex = _Extractor(expire=int(clock.wall0 + remaining))
        cache = _cache(ex, clock, max_ttl_sec=1800, margin_sec=300)

        cache.info(_URL)
        cache.info(_URL)

        assert len(ex.calls) == 2

    def test_TTL은_적중해도_늘어나지_않는다(self):
        clock, ex = _Clock(), _Extractor(expire=None)
        cache = _cache(ex, clock)

        cache.info(_URL)
        clock.tick(1000)
        cache.info(_URL)          # 적중
        clock.tick(801)           # 처음부터 1801초
        cache.info(_URL)

        assert len(ex.calls) == 2


class TestBound:
    def test_상한을_넘으면_가장_오래_안_쓴_것부터_버린다(self):
        clock, ex = _Clock(), _Extractor()
        cache = _cache(ex, clock, max_entries=3)

        for u in ("u1", "u2", "u3"):
            cache.info(u)
        cache.info("u1")                 # u1을 최근으로 만든다
        cache.info("u4")                 # u2가 밀려난다
        assert len(cache) <= 3

        n = len(ex.calls)
        cache.info("u2")                 # 밀려났으니 다시 받는다
        assert len(ex.calls) == n + 1
        n = len(ex.calls)
        cache.info("u1")                 # 최근에 썼으니 남아 있다
        assert len(ex.calls) == n
        assert len(cache) <= 3

    def test_기본_상한은_4에서_8_사이다(self):
        clock, ex = _Clock(), _Extractor()
        cache = _cache(ex, clock)

        for i in range(4):
            cache.info(f"u{i}")
        assert len(cache) == 4, "상한이 4보다 작으면 load+▶ 공유가 흔들린다"

        for i in range(4, 20):
            cache.info(f"u{i}")
        assert 4 <= len(cache) <= 8


class TestFresh:
    def test_fresh는_항상_새로_받고_캐시를_갈아_끼운다(self):
        clock, ex = _Clock(), _Extractor()
        cache = _cache(ex, clock)

        first = cache.info(_URL)
        second = cache.info(_URL, fresh=True)
        assert len(ex.calls) == 2
        assert second["tag"] == 2 and first["tag"] == 1

        third = cache.info(_URL)         # 새 결과가 캐시에 들어갔다
        assert len(ex.calls) == 2
        assert third["tag"] == 2

    def test_fresh는_캐시에_없던_키도_새로_받는다(self):
        clock, ex = _Clock(), _Extractor()
        cache = _cache(ex, clock)

        cache.info(_URL, fresh=True)
        cache.info(_URL, fresh=True)

        assert len(ex.calls) == 2


class TestFailure:
    def test_실패는_전파되고_캐시되지_않는다(self):
        clock = _Clock()
        calls: list = []

        def flaky(url, client=None):
            calls.append((url, client))
            if len(calls) == 1:
                raise RuntimeError("boom")
            return _info()

        cache = _cache(flaky, clock)
        with pytest.raises(RuntimeError, match="boom"):
            cache.info(_URL)

        assert cache.info(_URL)["id"] == "abc"
        assert len(calls) == 2


class _Blocking:
    """첫 호출이 `release`를 기다린다. 두 번째 호출부터는 즉시 돌려준다."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.error = error
        self._lock = threading.Lock()

    def __call__(self, url: str, client: str | None = None) -> dict:
        with self._lock:
            self.calls.append((url, client))
            first = len(self.calls) == 1
            tag = len(self.calls)
        if first:
            self.started.set()
            self.release.wait(5)
            if self.error is not None:
                raise self.error
        return _info(tag=tag)


def _waiters(cache: VideoInfoCache) -> int:
    inflight = getattr(cache, "_inflight", {})
    return max((e.waiters for e in list(inflight.values())), default=0)


def _wait_for_waiter(cache: VideoInfoCache, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _waiters(cache) >= 1:
            return True
        time.sleep(0)
    return False


class _Runner(threading.Thread):
    def __init__(self, fn) -> None:
        super().__init__(daemon=True)
        self._fn = fn
        self.result = None
        self.error: BaseException | None = None

    def run(self) -> None:
        try:
            self.result = self._fn()
        except BaseException as exc:  # noqa: BLE001 — 시험이 종류를 확인한다
            self.error = exc


class TestInFlightSharing:
    def test_동시에_같은_키를_물어도_extract는_1회다(self):
        """load와 ▶가 150ms 간격으로 같은 URL을 부른다 — 둘이 한 번을 같이 쓴다."""
        ex = _Blocking()
        cache = VideoInfoCache(ex)
        a = _Runner(lambda: cache.info(_URL))
        b = _Runner(lambda: cache.info(_URL))

        a.start()
        assert ex.started.wait(2), "첫 extract가 시작되지 않았다"
        b.start()
        assert _wait_for_waiter(cache), "두 번째 호출이 진행 중 요청에 합류하지 않았다"
        ex.release.set()
        a.join(2)
        b.join(2)

        assert not a.is_alive() and not b.is_alive()
        assert a.error is None and b.error is None
        assert len(ex.calls) == 1
        assert a.result == b.result and a.result is not None

    def test_진행_중_요청이_실패하면_합류자도_같은_예외를_받는다(self):
        ex = _Blocking(error=RuntimeError("extract failed"))
        cache = VideoInfoCache(ex)
        a = _Runner(lambda: cache.info(_URL))
        b = _Runner(lambda: cache.info(_URL))

        a.start()
        assert ex.started.wait(2)
        b.start()
        assert _wait_for_waiter(cache)
        ex.release.set()
        a.join(2)
        b.join(2)

        assert not a.is_alive() and not b.is_alive(), "합류자가 영원히 대기한다"
        assert isinstance(a.error, RuntimeError) and isinstance(b.error, RuntimeError)
        assert len(ex.calls) == 1

    def test_fresh는_진행_중_요청에_합류하지_않는다(self):
        """refresh 경로가 낡은 진행 중 결과를 받으면 만료 URL이 되풀이된다."""
        ex = _Blocking()
        cache = VideoInfoCache(ex)
        a = _Runner(lambda: cache.info(_URL))

        a.start()
        assert ex.started.wait(2)
        result = cache.info(_URL, fresh=True)       # 메인 스레드 — 블록되면 안 된다

        assert len(ex.calls) == 2, "fresh가 별도 extract를 하지 않았다"
        assert result["tag"] == 2
        ex.release.set()
        a.join(2)
        assert not a.is_alive()

    def test_진행_중_요청은_끝나면_정리된다(self):
        ex = _Blocking()
        cache = VideoInfoCache(ex)
        a = _Runner(lambda: cache.info(_URL))
        a.start()
        assert ex.started.wait(2)
        ex.release.set()
        a.join(2)

        assert not getattr(cache, "_inflight", {}), "끝난 요청이 남아 다음 호출을 막는다"


class TestThreadSafety:
    def test_여러_스레드가_섞어_불러도_깨지지_않는다(self):
        ex = _Extractor()
        cache = VideoInfoCache(ex, max_entries=4)
        keys = [f"u{i}" for i in range(10)]

        def work(i: int) -> None:
            for j in range(200):
                cache.info(keys[(i * 7 + j) % len(keys)])

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(work, i) for i in range(4)]
            for f in futures:
                f.result(timeout=20)

        assert len(cache) <= 4
        assert len(ex.calls) >= 1
