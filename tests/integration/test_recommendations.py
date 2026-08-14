"""추천 후보 조회 핸들러 — 중복 제거·라이브러리 제외·실패 격리를 고정한다.

네트워크(yt-dlp) 대신 fake IMediaSource를 주입해 규칙만 검증한다.
"""
from __future__ import annotations

import pytest

from application.library.playlist_queries import (
    GetRecommendationsHandler,
    GetRecommendationsQuery,
)


def _entry(vid: str, title: str = "제목", channel: str = "채널") -> dict:
    return {
        "url": f"https://www.youtube.com/watch?v={vid}",
        "yt_video_id": vid,
        "title": title,
        "channel_name": channel,
        "channel_id": "UC0",
        "thumbnail": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
        "published_at": "",
        "view_count": None,
        "duration_sec": 120,
    }


class _FakeMediaSource:
    """검색어 → 결과 매핑. ``raise_for``에 든 검색어는 예외를 던진다."""

    def __init__(self, results: dict[str, list[dict]], raise_for: set[str] | None = None) -> None:
        self._results = results
        self._raise_for = raise_for or set()
        self.calls: list[tuple[str, int]] = []

    def fetch_search_videos(self, query: str, limit: int = 12, cookie_opts=None) -> list[dict]:
        self.calls.append((query, limit))
        if query in self._raise_for:
            raise RuntimeError("검색 실패")
        return self._results.get(query, [])


class _FakeVideoRepo:
    def __init__(self, existing: set[str] | None = None) -> None:
        self._existing = existing or set()

    def exists_by_url(self, url: str) -> bool:
        return url in self._existing


@pytest.fixture
def seeds() -> dict:
    # 세 제목 모두에 '아이유'가 있어 첫 검색어가 '아이유'로 고정된다.
    return {
        "seed_titles": ("아이유 밤편지", "아이유 좋은날", "아이유 Blueming"),
        "seed_channels": (),
        "seed_tags": (),
    }


class TestRecommendationHandler:
    def test_returns_dtos_for_search_results(self, seeds):
        src = _FakeMediaSource({"아이유": [_entry("a1"), _entry("a2")]})
        handler = GetRecommendationsHandler(src, _FakeVideoRepo())

        result = handler.handle(GetRecommendationsQuery(**seeds))

        assert [d.yt_video_id for d in result] == ["a1", "a2"]
        assert all(d.in_library is False for d in result)

    def test_videos_already_in_library_are_excluded(self, seeds):
        src = _FakeMediaSource({"아이유": [_entry("a1"), _entry("a2")]})
        repo = _FakeVideoRepo({"https://www.youtube.com/watch?v=a1"})
        handler = GetRecommendationsHandler(src, repo)

        result = handler.handle(GetRecommendationsQuery(**seeds))

        assert [d.yt_video_id for d in result] == ["a2"]

    def test_duplicates_across_queries_are_removed(self, seeds):
        # 두 검색어가 같은 영상을 돌려줘도 카드가 두 번 뜨면 안 된다.
        src = _FakeMediaSource(
            {"아이유": [_entry("dup"), _entry("a1")], "발라드": [_entry("dup"), _entry("b1")]}
        )
        handler = GetRecommendationsHandler(src, _FakeVideoRepo())

        result = handler.handle(
            GetRecommendationsQuery(**{**seeds, "seed_tags": ("발라드", "발라드")})
        )

        ids = [d.yt_video_id for d in result]
        assert ids.count("dup") == 1
        assert set(ids) == {"dup", "a1", "b1"}

    def test_excluded_urls_are_skipped(self, seeds):
        src = _FakeMediaSource({"아이유": [_entry("a1"), _entry("a2")]})
        handler = GetRecommendationsHandler(src, _FakeVideoRepo())

        result = handler.handle(
            GetRecommendationsQuery(
                **seeds,
                exclude_urls=frozenset({"https://www.youtube.com/watch?v=a1"}),
            )
        )

        assert [d.yt_video_id for d in result] == ["a2"]

    def test_one_failing_query_does_not_break_the_rest(self, seeds):
        src = _FakeMediaSource(
            {"발라드": [_entry("b1")]}, raise_for={"아이유"}
        )
        handler = GetRecommendationsHandler(src, _FakeVideoRepo())

        result = handler.handle(
            GetRecommendationsQuery(**{**seeds, "seed_tags": ("발라드", "발라드")})
        )

        assert [d.yt_video_id for d in result] == ["b1"]

    def test_no_seeds_means_no_search_call(self):
        src = _FakeMediaSource({})
        handler = GetRecommendationsHandler(src, _FakeVideoRepo())

        assert handler.handle(GetRecommendationsQuery()) == []
        assert src.calls == []

    def test_limit_is_respected(self, seeds):
        src = _FakeMediaSource({"아이유": [_entry(f"v{i}") for i in range(20)]})
        handler = GetRecommendationsHandler(src, _FakeVideoRepo())

        result = handler.handle(GetRecommendationsQuery(**seeds, limit=5))

        assert len(result) == 5

    def test_partial_batch_is_emitted_before_api_enrichment(self, seeds):
        src = _FakeMediaSource({"아이유": [_entry("a1")]})
        handler = GetRecommendationsHandler(src, _FakeVideoRepo())
        batches: list[list] = []

        result = handler.handle(
            GetRecommendationsQuery(**seeds), on_progress=batches.append
        )

        assert len(batches) == 1
        assert [d.yt_video_id for d in batches[0]] == ["a1"]
        assert [d.yt_video_id for d in result] == ["a1"]

    def test_api_metadata_fills_missing_view_count(self, seeds):
        entry = _entry("a1")
        entry["view_count"] = None
        src = _FakeMediaSource({"아이유": [entry]})

        class _FakeApi:
            def get_videos_channels(self, vids):
                return {"a1": {"view_count": 4242, "published_at": "2026-01-02T00:00:00Z"}}

        handler = GetRecommendationsHandler(src, _FakeVideoRepo(), _FakeApi())
        result = handler.handle(GetRecommendationsQuery(**seeds))

        assert result[0].view_count == 4242
        assert result[0].published_at == "2026-01-02T00:00:00Z"

    def test_api_failure_falls_back_to_search_metadata(self, seeds):
        src = _FakeMediaSource({"아이유": [_entry("a1")]})

        class _BrokenApi:
            def get_videos_channels(self, vids):
                raise RuntimeError("쿼터 초과")

        handler = GetRecommendationsHandler(src, _FakeVideoRepo(), _BrokenApi())
        result = handler.handle(GetRecommendationsQuery(**seeds))

        assert [d.yt_video_id for d in result] == ["a1"]
