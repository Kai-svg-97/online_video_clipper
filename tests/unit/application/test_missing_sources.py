"""원본 소실 점검 유스케이스 — 중단·진행률·'확인 불가' 제외.

수백 건을 훑으며 영상당 네트워크 요청이 나가므로, **도중에 그만둘 수 있는지**와
**한 건이 터져도 계속하는지**가 실사용을 좌우한다.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from application.library.maintenance import FindMissingSourcesHandler
from domain.library.availability import (
    STATUS_OK,
    STATUS_PRIVATE,
    STATUS_REMOVED,
    STATUS_UNKNOWN,
    AvailabilityResult,
)


class _Repo:
    """`search(SearchQuery)` 페이지네이션만 흉내 낸다."""

    def __init__(self, count: int):
        self._aggs = [SimpleNamespace(_i=i) for i in range(count)]

    def search(self, query):
        return self._aggs[query.offset : query.offset + query.limit]


def _dto(agg):
    idx = agg._i
    return SimpleNamespace(id=uuid4(), title=f"영상{idx}", url=f"https://youtu.be/v{idx:09d}")


class _Checker:
    def __init__(self, statuses):
        self._statuses = statuses
        self.calls: list[str] = []

    def check(self, url):
        self.calls.append(url)
        status = self._statuses[(len(self.calls) - 1) % len(self._statuses)]
        if isinstance(status, Exception):
            raise status
        return AvailabilityResult(status)


def _handler(count, statuses):
    return FindMissingSourcesHandler(_Repo(count), _Checker(statuses), to_dto=_dto)


class TestFiltering:
    def test_삭제와_비공개만_보고한다(self):
        handler = _handler(3, [STATUS_OK, STATUS_REMOVED, STATUS_PRIVATE])
        found = handler.handle()
        assert [f.status for f in found] == [STATUS_REMOVED, STATUS_PRIVATE]

    def test_확인_불가는_보고하지_않는다(self):
        """네트워크가 끊긴 것을 두고 멀쩡한 영상을 지우게 하면 안 된다."""
        assert _handler(3, [STATUS_UNKNOWN]).handle() == []

    def test_전부_정상이면_빈_목록(self):
        assert _handler(5, [STATUS_OK]).handle() == []

    def test_결과에_제목과_주소가_담긴다(self):
        found = _handler(1, [STATUS_REMOVED]).handle()
        assert found[0].title == "영상0"
        assert found[0].url.startswith("https://youtu.be/")
        assert found[0].status_label == "삭제됨"


class TestProgressAndStop:
    def test_진행률은_1부터_전체까지_센다(self):
        seen: list[tuple[int, int]] = []
        _handler(3, [STATUS_OK]).handle(on_progress=lambda i, t: seen.append((i, t)))
        assert seen == [(1, 3), (2, 3), (3, 3)]

    def test_중단하면_더_묻지_않는다(self):
        checker = _Checker([STATUS_OK])
        handler = FindMissingSourcesHandler(_Repo(10), checker, to_dto=_dto)
        calls = {"n": 0}

        def should_stop():
            calls["n"] += 1
            return calls["n"] > 3

        handler.handle(should_stop=should_stop)
        assert len(checker.calls) == 3

    def test_중단해도_그때까지_찾은_것은_돌려준다(self):
        checker = _Checker([STATUS_REMOVED])
        handler = FindMissingSourcesHandler(_Repo(10), checker, to_dto=_dto)
        state = {"n": 0}

        def should_stop():
            state["n"] += 1
            return state["n"] > 2

        found = handler.handle(should_stop=should_stop)
        assert len(found) == 2


class TestResilience:
    def test_한_건이_터져도_나머지를_계속한다(self):
        """한 건 때문에 멈추면 앞서 찾은 것도 못 보여준다."""
        statuses = [RuntimeError("끊김"), STATUS_REMOVED, STATUS_REMOVED]
        found = _handler(3, statuses).handle()
        assert len(found) == 2

    def test_페이지네이션으로_전체를_훑는다(self):
        """메모리 규칙에 따라 50건씩 끊어 읽되, 빠뜨리는 영상이 없어야 한다."""
        checker = _Checker([STATUS_OK])
        FindMissingSourcesHandler(_Repo(120), checker, to_dto=_dto).handle()
        assert len(checker.calls) == 120


class TestEmpty:
    def test_라이브러리가_비면_아무것도_묻지_않는다(self):
        checker = _Checker([STATUS_OK])
        assert FindMissingSourcesHandler(_Repo(0), checker, to_dto=_dto).handle() == []
        assert checker.calls == []
