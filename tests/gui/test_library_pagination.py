"""라이브러리 무한 스크롤 — 51번째 영상부터 보이는가.

목록 조회는 한 쪽 50개다(메모리 규칙). 그런데 **다음 쪽을 부르는 쪽이 아무도 없어서**
51번째부터는 화면에서 사라져 있었다(영상 60개로 재현: 첫 화면 50, 끝까지 내려도 50).

붙이고 나서 새로 생기는 함정이 둘이다.

1. 바닥 근처에서 스크롤 신호가 연달아 온다 — 막지 않으면 같은 쪽을 여러 번 읽어
   목록에 중복이 쌓인다.
2. 삭제·태그 변경 등은 **쪽 번호를 되돌리지 않고** 목록을 다시 읽는다. 그때 현재
   쪽만 읽으면 목록이 151번째부터로 튄다(붙이기 전에는 늘 0쪽이라 안 드러났다).
"""

from __future__ import annotations

from config.settings import DEFAULT_PAGE_SIZE
from gui.view_models.library_vm import LibraryViewModel


class _Fake:
    """`GetVideosHandler` 대역 — limit/offset 을 그대로 지킨다."""

    def __init__(self, total: int):
        self.total = total
        self.calls: list[tuple[int, int]] = []

    def handle(self, query):
        limit = getattr(query, "limit", DEFAULT_PAGE_SIZE)
        offset = getattr(query, "offset", 0)
        self.calls.append((limit, offset))
        return [f"v{i}" for i in range(offset, min(self.total, offset + limit))]


def _vm(total: int) -> tuple[LibraryViewModel, _Fake]:
    """워커를 타지 않도록 `_refresh_videos` 의 조회부만 진짜로 굴린다.

    목록 조회는 QThread 로 도는데, 테스트에서 그것까지 굴리면 느리고 흔들린다.
    여기서 보려는 것은 **쪽 번호와 limit/offset 산술**이므로 워커는 즉시 실행으로
    바꾼다(같은 인자로 같은 코드가 돈다).
    """
    vm = LibraryViewModel.__new__(LibraryViewModel)
    fake = _Fake(total)

    def run_now(fetch, append, gen, ck, on_done, node_key, req_limit):
        videos = fetch()
        vm._has_more = len(videos) >= req_limit
        if append:
            vm._videos.extend(videos)
        else:
            vm._videos = videos
        if on_done:
            on_done()

    vm._videos = []
    vm._has_more = False
    vm._current_page = 0
    vm._list_gen = 0
    vm._list_inflight = 0
    vm._video_cache = {}
    vm._search_text = ""
    vm._filter_category_id = None
    vm._filter_playlist_id = None
    vm._filter_playlist_video_ids = []
    vm._filter_tag_ids = []
    vm._filter_categorized_only = False
    vm._sort_by, vm._sort_asc = "created_at", False
    vm._get_videos = fake
    vm._search_videos = fake
    vm._get_playlist_items = None
    vm._enqueue_list = run_now
    return vm, fake


class TestPaging:
    def test_첫_쪽은_한_쪽만_읽는다(self):
        vm, _ = _vm(total=60)
        vm._refresh_videos()
        assert len(vm._videos) == DEFAULT_PAGE_SIZE

    def test_다음_쪽을_이어_붙인다(self):
        """붙이기 전에는 여기서 50에 멈춰 있었다."""
        vm, _ = _vm(total=60)
        vm._refresh_videos()
        vm.load_next_page()
        assert len(vm._videos) == 60

    def test_이어_붙일_때_앞_쪽을_버리지_않는다(self):
        vm, _ = _vm(total=60)
        vm._refresh_videos()
        first = vm._videos[0]
        vm.load_next_page()
        assert vm._videos[0] == first

    def test_끝에_닿으면_더_읽지_않는다(self):
        vm, fake = _vm(total=60)
        vm._refresh_videos()
        vm.load_next_page()
        before = len(fake.calls)

        assert vm.load_next_page() is False
        assert len(fake.calls) == before

    def test_딱_한_쪽이면_더_없다고_본다(self):
        vm, _ = _vm(total=DEFAULT_PAGE_SIZE)
        vm._refresh_videos()
        # 꽉 채워 왔으니 '있을 수도' 있다 — 한 번 더 물어보고 끝난다.
        assert vm.has_more is True
        vm.load_next_page()
        assert vm.has_more is False

    def test_한_쪽도_못_채우면_처음부터_더_없다(self):
        vm, _ = _vm(total=10)
        vm._refresh_videos()
        assert vm.has_more is False
        assert vm.load_next_page() is False


class TestDoubleCall:
    def test_읽는_중에는_또_읽지_않는다(self):
        """바닥 근처에서 스크롤 신호가 연달아 와도 같은 쪽을 두 번 읽지 않는다."""
        vm, fake = _vm(total=300)
        vm._refresh_videos()
        vm._list_inflight = 1          # 조회가 아직 안 끝난 상태

        assert vm.load_next_page() is False
        assert vm._current_page == 0   # 쪽 번호도 넘어가지 않는다

    def test_연달아_불러도_쪽이_한_칸씩만_간다(self):
        vm, _ = _vm(total=300)
        vm._refresh_videos()
        vm.load_next_page()
        assert vm._current_page == 1
        assert len(vm._videos) == 100


class TestRefreshKeepsLoadedPages:
    def test_삭제_후_재조회가_읽어_둔_쪽을_통째로_다시_읽는다(self):
        """쪽 번호를 되돌리지 않는 재조회 경로 — 목록이 151번째부터로 튀면 안 된다."""
        vm, fake = _vm(total=300)
        vm._refresh_videos()
        vm.load_next_page()
        vm.load_next_page()
        assert len(vm._videos) == 150

        vm._refresh_videos(bust_cache=True)    # 삭제·태그 변경이 부르는 경로

        assert vm._videos[0] == "v0"
        assert len(vm._videos) == 150
        assert fake.calls[-1] == (150, 0)      # offset 0 부터 150개

    def test_재조회가_끝을_다시_판정한다(self):
        vm, _ = _vm(total=120)
        vm._refresh_videos()
        vm.load_next_page()
        vm.load_next_page()
        assert len(vm._videos) == 120

        vm._refresh_videos(bust_cache=True)

        assert vm.has_more is False
        assert len(vm._videos) == 120


class TestCache:
    def test_쪽을_넘긴_뒤에는_캐시를_쓰지_않는다(self):
        """캐시는 '첫 쪽'만 담는 구조라, 여러 쪽 분량을 같은 키로 넣으면 섞인다."""
        vm, _ = _vm(total=300)
        vm._refresh_videos()
        vm.load_next_page()

        vm._refresh_videos()

        assert len(vm._videos) == 100
