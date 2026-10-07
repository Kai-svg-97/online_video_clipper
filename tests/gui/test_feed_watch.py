"""구독 채널 새 영상 배경 감시 — 뷰모델 쪽 동작.

배경 감시가 지켜야 할 것은 "새 영상을 찾는다"보다 **찾지 말아야 할 때 안 찾는 것**에
가깝다. 잘못 만들면 두 가지로 사용자를 잃는다.

* 설치 직후 구독 피드 전체를 새 영상으로 알려 알림이 수십 개 뜬다 → 알림을 끈다.
* 배경 조회가 화면이 쓰는 목록·캐시를 갈아 끼워 **보던 채널이 사라진다**.

감시 주기 타이머 자체는 Qt가 보장하므로 여기서는 굴리지 않는다. 대신 조회가 끝난
뒤의 판정(`_on_watch_result`)을 직접 먹여 본다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from gui.view_models.feed_vm import FEED_ALL_KEY, FeedViewModel


def _item(n: int, title: str = ""):
    return SimpleNamespace(url=f"https://youtu.be/v{n:08d}", title=title or f"영상 {n}")


@pytest.fixture
def vm(qapp_instance, monkeypatch):
    """조회는 하지 않는 뷰모델 — 결과 처리만 본다."""
    fetched: list = []

    class _Handler:
        def handle(self, *a, **k):
            fetched.append(1)
            return []

    v = FeedViewModel(handler=_Handler())
    v.fetched = fetched          # type: ignore[attr-defined]
    return v


@pytest.fixture
def seen(monkeypatch):
    """`config.settings`의 기억을 메모리로 바꾼다 — 실제 config.yaml을 건드리지 않는다."""
    from config import settings as cfg

    store = {"urls": []}
    monkeypatch.setattr(cfg, "WATCH_SEEN_URLS", store["urls"], raising=False)

    def fake_save(key, value):
        if key == "watch_seen_urls":
            store["urls"] = list(value)
            monkeypatch.setattr(cfg, "WATCH_SEEN_URLS", store["urls"], raising=False)

    monkeypatch.setattr(cfg, "save_setting", fake_save)
    return store


class TestFirstRun:
    def test_처음에는_알리지_않는다(self, vm, seen, qtbot):
        """설치 직후 피드 전체를 알리면 사용자가 알림을 꺼 버린다."""
        with qtbot.assertNotEmitted(vm.new_videos_found):
            vm._on_watch_result([_item(1), _item(2)], FEED_ALL_KEY)

    def test_처음에도_기준선은_잡는다(self, vm, seen):
        vm._on_watch_result([_item(1), _item(2)], FEED_ALL_KEY)
        assert len(seen["urls"]) == 2


class TestDetection:
    def test_새_영상이_있으면_알린다(self, vm, seen, qtbot):
        vm._on_watch_result([_item(1)], FEED_ALL_KEY)          # 기준선

        with qtbot.waitSignal(vm.new_videos_found, timeout=1000) as sig:
            vm._on_watch_result([_item(2), _item(1)], FEED_ALL_KEY)

        count, body = sig.args
        assert count == 1
        assert "영상 2" in body

    def test_바뀐_게_없으면_알리지_않는다(self, vm, seen, qtbot):
        vm._on_watch_result([_item(1), _item(2)], FEED_ALL_KEY)

        with qtbot.assertNotEmitted(vm.new_videos_found):
            vm._on_watch_result([_item(2), _item(1)], FEED_ALL_KEY)

    def test_같은_영상을_두_번_알리지_않는다(self, vm, seen, qtbot):
        vm._on_watch_result([_item(1)], FEED_ALL_KEY)
        vm._on_watch_result([_item(2), _item(1)], FEED_ALL_KEY)   # 여기서 1건 알림

        with qtbot.assertNotEmitted(vm.new_videos_found):
            vm._on_watch_result([_item(2), _item(1)], FEED_ALL_KEY)

    def test_여러_건이면_수와_제목을_함께_준다(self, vm, seen, qtbot):
        vm._on_watch_result([_item(1)], FEED_ALL_KEY)

        with qtbot.waitSignal(vm.new_videos_found, timeout=1000) as sig:
            vm._on_watch_result(
                [_item(5), _item(4), _item(3), _item(2), _item(1)], FEED_ALL_KEY
            )

        count, body = sig.args
        assert count == 4
        assert "외 1개" in body


class TestIsolationFromUi:
    def test_감시_결과가_화면_목록을_갈아_끼우지_않는다(self, vm, seen):
        """배경 조회가 보던 채널을 지우면 안 된다."""
        vm._feed = [_item(99)]

        vm._on_watch_result([_item(1), _item(2)], FEED_ALL_KEY)

        assert [i.url for i in vm.feed] == [_item(99).url]

    def test_감시는_화면_캐시_키를_쓰지_않는다(self, vm, seen, monkeypatch):
        """같은 키를 쓰면 사용자가 보던 피드 캐시를 배경 결과가 덮는다."""
        started: list = []
        monkeypatch.setattr(
            vm, "_start",
            lambda fetch, on_ok, key, silent=False: started.append((key, silent)),
        )

        vm.check_new_videos()

        (key, silent), = started
        assert key != FEED_ALL_KEY
        assert silent is True          # 스피너를 띄우지 않는다


class TestSwitch:
    def test_설정이_꺼져_있으면_켜지지_않는다(self, vm, monkeypatch):
        from config import settings as cfg

        monkeypatch.setattr(cfg, "WATCH_NEW_VIDEOS", False, raising=False)
        assert vm.start_watching() is False

    def test_켜면_돌고_두_번_켜지지_않는다(self, vm, monkeypatch):
        from config import settings as cfg

        monkeypatch.setattr(cfg, "WATCH_NEW_VIDEOS", True, raising=False)
        monkeypatch.setattr(cfg, "WATCH_INTERVAL_MIN", 30, raising=False)

        assert vm.start_watching() is True
        assert vm.start_watching() is False

        vm.stop_watching()
        assert vm._watch_timer is None


class _Script:
    """질의 값으로 동작을 고르는 핸들러 대역.

    워커 스레드가 동시에 도므로 **호출 순서로 가르면 비결정적**이다(어느 스레드가
    먼저 `handle`에 닿을지 모른다). 그래서 질의의 `limit`(또는 채널 주소)로 고른다.
    각 동작은 `(on_progress) -> list`다.
    """

    def __init__(self, steps: dict, by=lambda q: q.limit):
        self._steps = steps
        self._by = by

    def handle(self, query, on_progress=None):
        return self._steps[self._by(query)](on_progress)


class TestGenerationPerKey:
    """세대 번호는 **키별**이다(성능 배치 7, C3).

    전역 `_gen`이면 배경 감시(`__watch__`)가 끼는 순간 진행 중이던 사용자 조회
    결과가 `gen` 불일치로 **통째로 버려진다** — 사용자가 새로고침을 눌렀는데 화면이
    갱신되지 않는다. 같은 키의 새 요청이 옛 요청을 대체하는 것만 유지한다.
    """

    @pytest.fixture
    def events(self):
        import threading

        evs = {"gate": threading.Event(), "start": threading.Event()}
        yield evs
        for e in evs.values():   # 워커가 남으면 프로세스가 죽는다
            e.set()

    @pytest.fixture
    def make_vm(self, qapp_instance, events, seen):
        made: list[FeedViewModel] = []

        def factory(handler, channel_handler=None):
            v = FeedViewModel(handler=handler, channel_handler=channel_handler)
            v.set_max_workers(4)
            made.append(v)
            return v

        yield factory
        for e in events.values():
            e.set()
        for v in made:
            v.shutdown()

    @staticmethod
    def _watch_recorder(vm, monkeypatch):
        done: list = []
        original = vm._on_watch_result

        def rec(items, key):
            done.append(key)
            original(items, key)

        monkeypatch.setattr(vm, "_on_watch_result", rec)
        return done

    def test_감시가_끼어도_사용자_조회_결과가_반영된다(self, make_vm, events, qtbot, monkeypatch):
        a = _item(1)

        def blocked(_p):
            events["gate"].wait(5)
            return [a]

        vm = make_vm(_Script({100: blocked, 50: lambda _p: []}))
        watch_done = self._watch_recorder(vm, monkeypatch)
        changed: list = []
        vm.feed_changed.connect(lambda: changed.append(1))

        vm.refresh(limit=100)          # 키 __all__ — 막힌 채
        vm.check_new_videos(limit=50)  # 키 __watch__ — 즉시 끝남
        qtbot.waitUntil(lambda: bool(watch_done), timeout=3000)
        events["gate"].set()

        qtbot.waitUntil(lambda: len(changed) == 1, timeout=3000)
        assert vm.feed == [a]

    def test_같은_키의_새_요청은_옛_결과를_여전히_버린다(self, make_vm, events, qtbot):
        a, b = _item(1), _item(2)

        def old(_p):
            events["gate"].wait(5)
            return [a]

        vm = make_vm(_Script({100: old, 101: lambda _p: [b]}))

        vm.refresh(limit=100)
        vm.refresh(limit=101)         # 같은 키 — 앞선 요청을 대체한다
        qtbot.waitUntil(lambda: vm.feed == [b], timeout=3000)
        events["gate"].set()
        qtbot.waitUntil(lambda: not vm._workers, timeout=3000)

        assert vm.feed == [b]         # 늦게 온 옛 결과가 덮지 않는다
        assert vm.get_cached(FEED_ALL_KEY) == [b]

    def test_다른_채널_요청도_서로_무효화하지_않는다(self, make_vm, events, qtbot):
        a, b = _item(1), _item(2)
        one, two = "https://youtube.com/@one", "https://youtube.com/@two"

        def first(_p):
            events["gate"].wait(5)
            return [a]

        vm = make_vm(
            _Script({100: lambda _p: []}),
            channel_handler=_Script(
                {one: first, two: lambda _p: [b]}, by=lambda q: q.channel_url
            ),
        )
        keyed: list = []
        changed: list = []
        vm.feed_key_changed.connect(lambda k, items: keyed.append((k, items)))
        vm.feed_changed.connect(lambda: changed.append(1))

        vm.load_channel(one)   # 막힌 채
        vm.load_channel(two)   # 즉시
        qtbot.waitUntil(lambda: len(keyed) == 1, timeout=3000)
        events["gate"].set()
        qtbot.waitUntil(lambda: len(keyed) == 2, timeout=3000)

        assert dict(keyed) == {two: [b], one: [a]}
        assert vm.get_cached(one) == [a]
        assert vm.get_cached(two) == [b]
        # 화면(vm.feed·feed_changed)은 현재 선택된 키(마지막에 고른 two)만 반영한다.
        assert vm.feed == [b]
        assert changed == [1]

    def test_부분_결과도_같은_키_판정이다(self, make_vm, events, qtbot, monkeypatch):
        a = _item(1)

        def partial_then_done(on_progress):
            events["start"].wait(5)
            if on_progress is not None:
                on_progress([a])      # 감시가 끝난 뒤에 부분 결과를 낸다
            return [a]

        vm = make_vm(_Script({100: partial_then_done, 50: lambda _p: []}))
        watch_done = self._watch_recorder(vm, monkeypatch)
        batches: list = []
        vm.feed_batch_appended.connect(batches.append)

        vm.refresh(limit=100)
        vm.check_new_videos(limit=50)
        qtbot.waitUntil(lambda: bool(watch_done), timeout=3000)
        events["start"].set()

        qtbot.waitUntil(lambda: bool(batches), timeout=3000)
        assert batches == [[a]]
