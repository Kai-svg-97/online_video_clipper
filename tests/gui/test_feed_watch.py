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
