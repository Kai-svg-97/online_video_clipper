"""SponsorBlock 구간 조회 유스케이스 — 캐시와 꺼짐 조건.

같은 영상을 되풀이해 여는 화면(뒤로가기·재생목록 왕복·앨범 이어재생)이라 **영상당
한 번만 묻는 것**이 이 핸들러의 존재 이유다.
"""

from __future__ import annotations

import pytest

from application.clip.sponsor_queries import (
    GetSkipSegmentsHandler,
    GetSkipSegmentsQuery,
    parse_categories,
)

URL = "https://www.youtube.com/watch?v=abcdefghijk"


class _Source:
    def __init__(self, segments=None):
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self._segments = segments if segments is not None else [("sponsor", 10.0, 20.0)]

    def fetch_segments(self, video_id, categories):
        self.calls.append((video_id, categories))
        return self._segments


@pytest.fixture
def cfg_on(monkeypatch):
    from config import settings as cfg
    monkeypatch.setattr(cfg, "SPONSORBLOCK_SKIP", True, raising=False)
    monkeypatch.setattr(cfg, "SPONSORBLOCK_CATEGORIES", "sponsor,selfpromo", raising=False)
    return cfg


class TestLookup:
    def test_URL에서_영상ID를_뽑아_묻는다(self, cfg_on):
        src = _Source()
        segs = GetSkipSegmentsHandler(src).handle(GetSkipSegmentsQuery(URL))
        assert src.calls == [("abcdefghijk", ("sponsor", "selfpromo"))]
        assert [s.category for s in segs] == ["sponsor"]

    def test_결과는_정리된_구간이다(self, cfg_on):
        src = _Source([("sponsor", 30.0, 40.0), ("sponsor", 10.0, 20.0)])
        segs = GetSkipSegmentsHandler(src).handle(GetSkipSegmentsQuery(URL))
        assert [s.start_sec for s in segs] == [10.0, 30.0]

    def test_고르지_않은_카테고리는_결과에서_빠진다(self, cfg_on):
        """공급자가 더 많이 돌려줘도 사용자가 고른 것만 남아야 한다."""
        src = _Source([("intro", 10.0, 20.0)])
        assert GetSkipSegmentsHandler(src).handle(GetSkipSegmentsQuery(URL)) == []


class TestCache:
    def test_같은_영상은_한_번만_묻는다(self, cfg_on):
        src = _Source()
        handler = GetSkipSegmentsHandler(src)
        handler.handle(GetSkipSegmentsQuery(URL))
        handler.handle(GetSkipSegmentsQuery(URL))
        handler.handle(GetSkipSegmentsQuery("https://youtu.be/abcdefghijk"))  # 같은 id
        assert len(src.calls) == 1

    def test_결과가_없어도_캐시한다(self, cfg_on):
        """없다는 답도 답이다 — 캐시하지 않으면 열 때마다 헛왕복이 생긴다."""
        src = _Source([])
        handler = GetSkipSegmentsHandler(src)
        handler.handle(GetSkipSegmentsQuery(URL))
        handler.handle(GetSkipSegmentsQuery(URL))
        assert len(src.calls) == 1

    def test_카테고리를_바꾸면_다시_묻는다(self, cfg_on, monkeypatch):
        src = _Source()
        handler = GetSkipSegmentsHandler(src)
        handler.handle(GetSkipSegmentsQuery(URL))
        monkeypatch.setattr(cfg_on, "SPONSORBLOCK_CATEGORIES", "sponsor", raising=False)
        handler.handle(GetSkipSegmentsQuery(URL))
        assert len(src.calls) == 2


class TestOff:
    def test_설정을_끄면_묻지_않는다(self, cfg_on, monkeypatch):
        src = _Source()
        monkeypatch.setattr(cfg_on, "SPONSORBLOCK_SKIP", False, raising=False)
        assert GetSkipSegmentsHandler(src).handle(GetSkipSegmentsQuery(URL)) == []
        assert src.calls == []

    def test_카테고리를_모두_끄면_묻지_않는다(self, cfg_on, monkeypatch):
        src = _Source()
        monkeypatch.setattr(cfg_on, "SPONSORBLOCK_CATEGORIES", "", raising=False)
        assert GetSkipSegmentsHandler(src).handle(GetSkipSegmentsQuery(URL)) == []
        assert src.calls == []

    def test_YouTube가_아니면_묻지_않는다(self, cfg_on):
        """SponsorBlock은 YouTube 영상만 다룬다."""
        src = _Source()
        assert GetSkipSegmentsHandler(src).handle(
            GetSkipSegmentsQuery("https://vimeo.com/123456")
        ) == []
        assert src.calls == []


class TestParseCategories:
    def test_공백과_빈_항목을_털어낸다(self):
        assert parse_categories(" sponsor , , selfpromo ") == ("sponsor", "selfpromo")

    def test_빈_문자열은_빈_튜플(self):
        assert parse_categories("") == ()
