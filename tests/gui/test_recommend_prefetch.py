"""추천 영상 미리 받기 — 끝에 닿기 전에 다음 묶음을 백그라운드로 받는다.

지키는 규칙:
* **끝에 도달하기 전에** 요청한다(끝까지 밀고 나서 받으면 빈 공백을 보며 기다린다).
* 조회 중이거나 바닥났으면 다시 요청하지 않는다 — 스크롤할 때마다 같은 검색을
  반복하면 조용히 네트워크만 축낸다.
* 씨앗을 새로 뽑지 않고 **같은 검색어를 더 깊이** 판다(`derive_seed_queries`는 목록당
  최대 3개뿐이라 더 뽑을 검색어가 없다). 이미 보여 준 URL은 제외해 중복을 막는다.
* 늦게 도착한 추가분은 그 사이 씨앗이 바뀌었으면 버린다.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from PyQt6.QtWidgets import QApplication

from application.library.dtos import FeedVideoDTO
from gui.panels.feed_panel import RecommendStrip
from gui.view_models.recommend_vm import RecommendViewModel


def _dto(i: int) -> FeedVideoDTO:
    return FeedVideoDTO(
        url=f"https://youtu.be/v{i}", title=f"영상 {i}", channel_name="채널",
        channel_id="c1", thumbnail_url="", thumbnail_path="", published_at="",
        view_count=None, duration_sec=None, in_library=False, yt_video_id=f"v{i}",
    )


class TestStripPrefetch:
    def _strip(self, qtbot, cards: int = 40) -> RecommendStrip:
        strip = RecommendStrip()
        qtbot.addWidget(strip)
        strip.resize(600, 200)
        strip.show()
        qtbot.waitExposed(strip)
        strip.set_items([_dto(i) for i in range(cards)])
        # 오프스크린 테스트에서는 카드 폭이 잡히기 전이라 스크롤 범위가 0이다 —
        # 내용이 넘치는 상황을 직접 만들어 스크롤 판정만 확인한다.
        strip._row_widget.setMinimumWidth(5000)
        QApplication.processEvents()
        qtbot.wait(30)
        return strip

    def test_끝에_닿기_전에_더_받기를_요청한다(self, qtbot):
        strip = self._strip(qtbot)
        bar = strip._scroll.horizontalScrollBar()
        assert bar.maximum() > 0, "카드가 넘쳐야 스크롤 판정이 의미 있다"
        got: list = []
        strip.load_more_requested.connect(lambda: got.append(1))

        # 아직 끝은 아니지만 여백(PREFETCH_MARGIN_PX) 안으로 들어온 지점
        bar.setValue(bar.maximum() - 10)

        assert got, "끝에 닿기 전에 미리 요청해야 한다"

    def test_처음_위치에서는_요청하지_않는다(self, qtbot):
        strip = self._strip(qtbot)
        bar = strip._scroll.horizontalScrollBar()
        got: list = []
        strip.load_more_requested.connect(lambda: got.append(1))

        bar.setValue(0)

        assert got == []

    def test_조회_중에는_다시_요청하지_않는다(self, qtbot):
        strip = self._strip(qtbot)
        strip.set_more_loading(True)
        got: list = []
        strip.load_more_requested.connect(lambda: got.append(1))
        bar = strip._scroll.horizontalScrollBar()

        bar.setValue(bar.maximum())

        assert got == []

    def test_바닥나면_더_요청하지_않는다(self, qtbot):
        strip = self._strip(qtbot)
        strip.set_more_exhausted(True)
        got: list = []
        strip.load_more_requested.connect(lambda: got.append(1))
        bar = strip._scroll.horizontalScrollBar()

        bar.setValue(bar.maximum())

        assert got == []

    def test_새_목록을_깔면_다시_받을_수_있다(self, qtbot):
        """씨앗이 바뀌면 바닥났다는 판정도 함께 무효다."""
        strip = self._strip(qtbot)
        strip.set_more_exhausted(True)

        strip.set_items([_dto(100)])

        assert strip._more_exhausted is False

    def test_접혀_있으면_요청하지_않는다(self, qtbot):
        strip = self._strip(qtbot)
        bar = strip._scroll.horizontalScrollBar()
        strip.set_expanded(False, notify=False)
        got: list = []
        strip.load_more_requested.connect(lambda: got.append(1))

        bar.setValue(bar.maximum())

        assert got == []

    def test_추가분은_기존_카드_뒤에_붙는다(self, qtbot):
        strip = self._strip(qtbot, cards=5)

        strip.append_items([_dto(90), _dto(91)])

        assert strip.count() == 7


class TestViewModelLoadMore:
    def _vm(self, handler) -> RecommendViewModel:
        return RecommendViewModel(handler=handler)

    def _loaded(self, vm, qtbot, items, seeds=("가", "나")):
        handler = vm._handler
        handler.handle.return_value = items
        with qtbot.waitSignal(vm.items_changed, timeout=3000):
            vm.load(seed_titles=seeds, limit=12)

    def test_같은_씨앗을_더_깊이_판다(self, qtbot):
        handler = MagicMock()
        vm = self._vm(handler)
        self._loaded(vm, qtbot, [_dto(1)])

        with qtbot.waitSignal(vm.more_ready, timeout=3000):
            handler.handle.return_value = [_dto(2)]
            vm.load_more(exclude_urls=frozenset({"https://youtu.be/v1"}))

        query = handler.handle.call_args.args[0]
        assert query.seed_titles == ("가", "나")          # 씨앗은 그대로
        assert query.per_query > 12                        # 더 깊이
        assert "https://youtu.be/v1" in query.exclude_urls  # 이미 본 것은 제외

    def test_페이지마다_더_깊어진다(self, qtbot):
        handler = MagicMock()
        vm = self._vm(handler)
        self._loaded(vm, qtbot, [_dto(1)])

        depths = []
        for i in range(2):
            with qtbot.waitSignal(vm.more_ready, timeout=3000):
                handler.handle.return_value = [_dto(10 + i)]
                vm.load_more()
            depths.append(handler.handle.call_args.args[0].per_query)

        assert depths[1] > depths[0]

    def test_추가분은_목록_뒤에_이어_붙는다(self, qtbot):
        """상세 화면 우측 추천 구역도 같은 목록을 본다 — VM이 들고 있어야 한다."""
        handler = MagicMock()
        vm = self._vm(handler)
        self._loaded(vm, qtbot, [_dto(1)])

        with qtbot.waitSignal(vm.more_ready, timeout=3000):
            handler.handle.return_value = [_dto(2)]
            vm.load_more()

        assert [d.url for d in vm.items] == [
            "https://youtu.be/v1", "https://youtu.be/v2",
        ]

    def test_빈_결과면_바닥났다고_알린다(self, qtbot):
        handler = MagicMock()
        vm = self._vm(handler)
        self._loaded(vm, qtbot, [_dto(1)])

        with qtbot.waitSignal(vm.more_exhausted, timeout=3000):
            handler.handle.return_value = []
            vm.load_more()

        handler.handle.reset_mock()
        vm.load_more()                      # 바닥난 뒤에는 아예 조회하지 않는다
        handler.handle.assert_not_called()

    def test_실패해도_보던_목록은_그대로다(self, qtbot):
        handler = MagicMock()
        vm = self._vm(handler)
        self._loaded(vm, qtbot, [_dto(1)])

        with qtbot.waitSignal(vm.more_exhausted, timeout=3000):
            handler.handle.side_effect = RuntimeError("검색 실패")
            vm.load_more()

        assert [d.url for d in vm.items] == ["https://youtu.be/v1"]

    def test_씨앗이_없으면_요청하지_않는다(self, qtbot):
        handler = MagicMock()
        vm = self._vm(handler)

        vm.load_more()

        handler.handle.assert_not_called()

    def test_씨앗이_바뀌면_깊이를_처음으로_되돌린다(self, qtbot):
        """다른 목록의 페이지 깊이를 물려받으면 첫 '더 받기'가 너무 깊게 판다.
        (같은 씨앗으로 되돌아온 경우는 캐시 재표시라 깊이를 이어 가는 것이 맞다.)"""
        handler = MagicMock()
        vm = self._vm(handler)
        self._loaded(vm, qtbot, [_dto(1)])
        for i in range(2):                      # 두 번 파 내려가 깊이를 키운다
            with qtbot.waitSignal(vm.more_ready, timeout=3000):
                handler.handle.return_value = [_dto(20 + i)]
                vm.load_more()
        deep = handler.handle.call_args.args[0].per_query

        self._loaded(vm, qtbot, [_dto(3)], seeds=("다", "라"))   # 다른 목록으로 이동
        with qtbot.waitSignal(vm.more_ready, timeout=3000):
            handler.handle.return_value = [_dto(4)]
            vm.load_more()

        assert handler.handle.call_args.args[0].per_query < deep
