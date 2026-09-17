"""자막 일괄 색인 — 건너뛰기·중단·집계.

영상당 네트워크 왕복이 1초 안팎이라 수백 건이면 10분을 넘긴다. 그래서
**이미 색인된 것을 건너뛰는지**와 **도중에 그만둘 수 있는지**가 이 기능의 쓸모를
좌우한다 — 중단했다가 다시 시작할 때 처음부터 되풀이하면 영원히 끝나지 않는다.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from application.library.subtitle_commands import BulkIndexSubtitlesHandler
from application.library.subtitle_queries import GetSubtitleCoverageHandler


class _VideoRepo:
    def __init__(self, count: int):
        self.ids = [uuid4() for _ in range(count)]
        self._aggs = [
            SimpleNamespace(
                id=vid,
                video=SimpleNamespace(title=f"영상{i}", url=f"https://youtu.be/v{i:09d}"),
            )
            for i, vid in enumerate(self.ids)
        ]

    def search(self, query):
        return self._aggs[query.offset : query.offset + query.limit]

    def count(self, query):
        return len(self._aggs)


class _SubtitleRepo:
    def __init__(self, indexed=()):
        self._indexed = set(indexed)

    def indexed_video_ids(self):
        return set(self._indexed)


class _Fetch:
    """`FetchAndIndexSubtitlesHandler` 대역 — url 끝자리로 결과를 정한다."""

    def __init__(self, no_subtitle_for=()):
        self.calls: list[str] = []
        self._empty = set(no_subtitle_for)

    def handle(self, cmd):
        self.calls.append(cmd.url)
        return 0 if cmd.url in self._empty else 12


def _handler(video_repo, subtitle_repo, fetch):
    return BulkIndexSubtitlesHandler(video_repo, subtitle_repo, fetch)


class TestSkipping:
    def test_이미_색인된_영상은_건너뛴다(self):
        videos = _VideoRepo(5)
        fetch = _Fetch()
        result = _handler(videos, _SubtitleRepo(videos.ids[:2]), fetch).handle()
        assert len(fetch.calls) == 3
        assert result.skipped == 2
        assert result.indexed == 3

    def test_전부_색인돼_있으면_아무것도_받지_않는다(self):
        videos = _VideoRepo(4)
        fetch = _Fetch()
        result = _handler(videos, _SubtitleRepo(videos.ids), fetch).handle()
        assert fetch.calls == []
        assert result.scanned == 0

    def test_색인_현황_조회가_실패해도_전부_확인한다(self):
        class _Broken:
            def indexed_video_ids(self):
                raise RuntimeError("DB 오류")

        videos = _VideoRepo(3)
        fetch = _Fetch()
        _handler(videos, _Broken(), fetch).handle()
        assert len(fetch.calls) == 3


class TestCounting:
    def test_자막이_없는_영상을_따로_센다(self):
        videos = _VideoRepo(3)
        fetch = _Fetch(no_subtitle_for={"https://youtu.be/v000000001"})
        result = _handler(videos, _SubtitleRepo(), fetch).handle()
        assert (result.indexed, result.no_subtitle) == (2, 1)

    def test_확인한_영상_수를_센다(self):
        result = _handler(_VideoRepo(7), _SubtitleRepo(), _Fetch()).handle()
        assert result.scanned == 7

    def test_라이브러리가_비면_0건이다(self):
        result = _handler(_VideoRepo(0), _SubtitleRepo(), _Fetch()).handle()
        assert (result.indexed, result.scanned, result.stopped) == (0, 0, False)


class TestProgressAndStop:
    def test_진행률은_건너뛴_영상을_빼고_센다(self):
        """이미 색인된 것까지 세면 '3/10에서 끝났다'처럼 보인다."""
        videos = _VideoRepo(5)
        seen: list[tuple[int, int, str]] = []
        _handler(videos, _SubtitleRepo(videos.ids[:2]), _Fetch()).handle(
            on_progress=lambda i, t, title: seen.append((i, t, title))
        )
        assert [s[1] for s in seen] == [3, 3, 3]
        assert [s[0] for s in seen] == [1, 2, 3]

    def test_중단하면_더_받지_않는다(self):
        fetch = _Fetch()
        state = {"n": 0}

        def should_stop():
            state["n"] += 1
            return state["n"] > 2

        result = _handler(_VideoRepo(10), _SubtitleRepo(), fetch).handle(
            should_stop=should_stop
        )
        assert len(fetch.calls) == 2
        assert result.stopped is True

    def test_중단해도_그때까지의_집계를_돌려준다(self):
        fetch = _Fetch()
        state = {"n": 0}

        def should_stop():
            state["n"] += 1
            return state["n"] > 3

        result = _handler(_VideoRepo(10), _SubtitleRepo(), fetch).handle(
            should_stop=should_stop
        )
        assert result.indexed == 3

    def test_페이지네이션으로_전체를_훑는다(self):
        fetch = _Fetch()
        _handler(_VideoRepo(120), _SubtitleRepo(), fetch).handle()
        assert len(fetch.calls) == 120


class TestCoverage:
    def test_색인_수와_전체_수를_함께_알려준다(self):
        videos = _VideoRepo(10)
        coverage = GetSubtitleCoverageHandler(
            videos, _SubtitleRepo(videos.ids[:4])
        ).handle()
        assert (coverage.indexed_videos, coverage.total_videos) == (4, 10)
        assert coverage.remaining == 6

    def test_조회가_실패해도_0으로_답한다(self):
        class _Broken:
            def indexed_video_ids(self):
                raise RuntimeError("DB 오류")

        coverage = GetSubtitleCoverageHandler(_VideoRepo(3), _Broken()).handle()
        assert coverage.indexed_videos == 0

    def test_남은_수가_음수가_되지_않는다(self):
        """색인만 있고 영상이 지워진 상태에서도 화면이 이상해지지 않게."""
        videos = _VideoRepo(1)
        coverage = GetSubtitleCoverageHandler(
            videos, _SubtitleRepo([uuid4(), uuid4(), uuid4()])
        ).handle()
        assert coverage.remaining == 0
