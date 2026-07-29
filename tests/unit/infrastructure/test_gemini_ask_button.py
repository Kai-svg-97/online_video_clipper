"""Gemini Ask("질문하기") 버튼 탐색이 실제로 대기하는지 검증한다.

회귀 배경: 원래 코드는 `Locator.is_visible(timeout=_BUTTON_SCAN_TIMEOUT_MS)`로 버튼을
찾았다. 그런데 Playwright 문서는 이 timeout 을 "Deprecated: This option is ignored.
locator.is_visible() does not wait for the element to become visible and returns
immediately." 라고 명시한다. 즉 5초 대기를 의도했지만 실제로는 0초였다.

그래서 버튼이 조금 늦게 렌더되는 영상(액션 행에 아직 회색 플레이스홀더가 있는 상태)에서
6개 셀렉터 검사가 0.2초 만에 끝나고 "미발견"으로 포기했다. 다른 영상은 로그인 확인에
걸리는 몇 초 동안 버튼이 이미 렌더돼 우연히 성공했을 뿐이다.
"""
from __future__ import annotations

import pytest

from infrastructure.browser.gemini_extractor import (
    _ASK_BUTTON_SELECTORS,
    GeminiExtractor,
)


class _FakeLocator:
    """지정한 대기 시간 이상 기다려 줄 때만 '보이게' 되는 가짜 Locator."""

    def __init__(self, appear_after_ms: int | None, log: list) -> None:
        self._appear_after_ms = appear_after_ms   # None = 영원히 안 나타남
        self._log = log
        self._parts = 1

    # 여러 셀렉터를 하나로 합치는 Playwright API
    def or_(self, other: "_FakeLocator") -> "_FakeLocator":
        soonest: int | None = None
        for cand in (self._appear_after_ms, other._appear_after_ms):
            if cand is not None and (soonest is None or cand < soonest):
                soonest = cand
        merged = _FakeLocator(soonest, self._log)
        merged._parts = self._parts + other._parts
        return merged

    @property
    def first(self) -> "_FakeLocator":
        return self

    def wait_for(self, state: str = "visible", timeout: float | None = None) -> None:
        self._log.append(("wait_for", state, timeout))
        if self._appear_after_ms is None:
            raise TimeoutError("element never appeared")
        if timeout is None or timeout < self._appear_after_ms:
            raise TimeoutError("timeout too short")

    def is_visible(self, timeout: float | None = None) -> bool:
        # 실제 Playwright 처럼 대기하지 않는다 — 옛 구현이 이걸 썼다.
        self._log.append(("is_visible", timeout))
        return False


class _FakePage:
    def __init__(self, appear_after_ms: int | None) -> None:
        self.calls: list = []
        self._appear_after_ms = appear_after_ms

    def locator(self, selector: str) -> _FakeLocator:
        self.calls.append(("locator", selector))
        return _FakeLocator(self._appear_after_ms, self.calls)


@pytest.fixture
def extractor():
    return GeminiExtractor()


class TestFindAskButton:
    def test_finds_button_that_appears_late(self, extractor):
        """핵심 회귀 — 버튼이 3초 뒤에 나타나도 찾아야 한다."""
        page = _FakePage(appear_after_ms=3_000)

        btn = extractor._find_ask_button(page)

        assert btn is not None, "늦게 렌더되는 버튼을 놓쳤다(대기하지 않음)"

    def test_actually_waits_instead_of_instant_check(self, extractor):
        """is_visible 이 아니라 wait_for 로 기다려야 한다.

        is_visible 의 timeout 인자는 Playwright 가 무시하므로 대기 수단이 될 수 없다.
        """
        page = _FakePage(appear_after_ms=3_000)

        extractor._find_ask_button(page)

        kinds = {c[0] for c in page.calls}
        assert "wait_for" in kinds, "wait_for 로 대기하지 않았다"
        assert "is_visible" not in kinds, (
            "is_visible 로 즉시 판정하고 있다 — Playwright 가 timeout 을 무시한다"
        )

    def test_returns_none_when_button_never_appears(self, extractor):
        """미지원 영상 등 정말 버튼이 없으면 None 을 반환해야 한다."""
        page = _FakePage(appear_after_ms=None)

        assert extractor._find_ask_button(page) is None

    def test_uses_single_total_budget_not_per_selector(self, extractor):
        """셀렉터마다 따로 기다리면 미지원 영상에서 6배로 느려진다.

        모든 셀렉터를 하나로 합쳐 총 예산 한 번만 소비해야 한다.
        """
        page = _FakePage(appear_after_ms=None)

        extractor._find_ask_button(page)

        waits = [c for c in page.calls if c[0] == "wait_for"]
        assert len(waits) == 1, f"wait_for 를 {len(waits)}회 호출했다 — 총 예산 1회여야 한다"

    def test_all_selectors_are_combined(self, extractor):
        """기존 fallback 셀렉터 전체가 순서대로 후보에 포함돼야 한다.

        각 셀렉터에는 visible 필터가 덧붙는다(숨은 첫 매칭 회피).
        """
        page = _FakePage(appear_after_ms=1_000)

        extractor._find_ask_button(page)

        used = [c[1] for c in page.calls if c[0] == "locator"]
        assert len(used) == len(_ASK_BUTTON_SELECTORS)
        for got, base in zip(used, _ASK_BUTTON_SELECTORS):
            assert got.startswith(base), f"{base!r} 셀렉터가 빠졌다 (got {got!r})"

    def test_budget_is_generous_enough_for_slow_pages(self, extractor):
        """관측된 실패 사례는 페이지가 아직 스켈레톤 상태였다. 넉넉히 기다려야 한다."""
        page = _FakePage(appear_after_ms=10_000)

        assert extractor._find_ask_button(page) is not None


class _HiddenFirstPage:
    """첫 매칭이 숨은 요소인 페이지.

    실측: 지원되는 영상에서 `button[aria-label*='질문하기']`는 5개 매칭 중 첫 번째가
    숨어 있었다. 셀렉터를 그대로 or_ 로 합치면 `.first`가 그 숨은 요소를 가리켜
    `wait_for(state="visible")`가 영원히 실패한다. `>> visible=true` 로 걸러야 한다.
    """

    def __init__(self) -> None:
        self.calls: list = []

    def locator(self, selector: str) -> _FakeLocator:
        self.calls.append(("locator", selector))
        # visible 필터가 없으면 숨은 첫 매칭이 잡혀 영원히 안 보인다.
        appear = 1_000 if "visible=true" in selector else None
        return _FakeLocator(appear, self.calls)


class TestVisibleOnlyMatching:
    def test_filters_to_visible_matches(self, extractor):
        """핵심 회귀 — 숨은 첫 매칭 때문에 버튼을 놓치면 안 된다."""
        page = _HiddenFirstPage()

        assert extractor._find_ask_button(page) is not None, (
            "숨은 첫 매칭에 걸려 버튼을 놓쳤다 — 셀렉터에 visible 필터가 필요하다"
        )

    def test_every_selector_carries_visible_filter(self, extractor):
        page = _HiddenFirstPage()
        extractor._find_ask_button(page)

        used = [c[1] for c in page.calls if c[0] == "locator"]
        assert used, "locator 를 호출하지 않았다"
        for sel in used:
            assert "visible=true" in sel, f"visible 필터 없는 셀렉터: {sel}"


class _StatePage:
    """로그인 판정용 가짜 페이지 — 셀렉터별로 나타나는 시점을 지정한다."""

    def __init__(self, visible_after: dict[str, int | None]) -> None:
        self._visible_after = visible_after
        self.calls: list = []

    def locator(self, selector: str) -> _FakeLocator:
        self.calls.append(("locator", selector))
        appear = None
        for frag, after in self._visible_after.items():
            if frag in selector:
                appear = after
                break
        return _FakeLocator(appear, self.calls)


class TestDetectLoginState:
    """로그인 판정도 같은 is_visible 오용을 쓰고 있었다.

    그래서 로그인이 됐는데도 "판별 불가"로 기록돼, 실패 원인을 잘못 짚게 만들었다.
    """

    def test_signed_in_when_avatar_appears(self, extractor):
        page = _StatePage({"avatar-btn": 2_000})
        assert extractor._detect_login_state(page) == "signed_in"

    def test_signed_out_when_login_link_appears(self, extractor):
        page = _StatePage({"avatar-btn": None, "로그인": 1_000})
        assert extractor._detect_login_state(page) == "signed_out"

    def test_unknown_when_neither_appears(self, extractor):
        page = _StatePage({"avatar-btn": None, "로그인": None})
        assert extractor._detect_login_state(page) == "unknown"

    def test_waits_for_avatar_instead_of_instant_check(self, extractor):
        """아바타가 늦게 렌더돼도 로그인으로 판정해야 한다."""
        page = _StatePage({"avatar-btn": 5_000})

        assert extractor._detect_login_state(page) == "signed_in"
        kinds = {c[0] for c in page.calls}
        assert "is_visible" not in kinds, "is_visible 로 즉시 판정하고 있다"
