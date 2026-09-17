"""SponsorBlock 구간 정리·판정 규칙.

구간 데이터는 여러 사람이 제출한 것을 그대로 받는다 — 겹치고, 순서가 뒤섞이고,
시작이 끝보다 큰 것도 온다. 정리를 빠뜨리면 건너뛰기가 앞뒤로 튄다.
"""

from __future__ import annotations

from domain.clip.sponsor import (
    DEFAULT_SKIP_CATEGORIES,
    SKIP_CATEGORY_NAMES,
    SkipSegment,
    normalize_segments,
    segment_at,
)


class TestNormalize:
    def test_시작_순으로_정렬한다(self):
        segs = normalize_segments([("sponsor", 60, 70), ("sponsor", 10, 20)])
        assert [s.start_sec for s in segs] == [10.0, 60.0]

    def test_겹치는_구간을_합친다(self):
        """합치지 않으면 앞 구간 끝으로 넘긴 자리가 다시 다음 구간 안이라 연달아 튄다."""
        segs = normalize_segments([("sponsor", 10, 30), ("selfpromo", 25, 50)])
        assert len(segs) == 1
        assert (segs[0].start_sec, segs[0].end_sec) == (10.0, 50.0)

    def test_맞닿은_구간도_합친다(self):
        segs = normalize_segments([("sponsor", 10, 30), ("sponsor", 30, 40)])
        assert [(s.start_sec, s.end_sec) for s in segs] == [(10.0, 40.0)]

    def test_안에_완전히_들어간_구간은_끝을_늘리지_않는다(self):
        segs = normalize_segments([("sponsor", 10, 60), ("sponsor", 20, 30)])
        assert [(s.start_sec, s.end_sec) for s in segs] == [(10.0, 60.0)]

    def test_떨어진_구간은_그대로_둔다(self):
        segs = normalize_segments([("sponsor", 10, 20), ("sponsor", 30, 40)])
        assert len(segs) == 2

    def test_너무_짧은_구간은_버린다(self):
        """1초짜리를 건너뛰면 화면만 덜컥거리고 얻는 게 없다."""
        assert normalize_segments([("sponsor", 10, 10.5)]) == []

    def test_시작이_끝보다_크면_버린다(self):
        assert normalize_segments([("sponsor", 50, 10)]) == []

    def test_음수_시작은_버린다(self):
        assert normalize_segments([("sponsor", -5, 20)]) == []

    def test_모르는_카테고리는_버린다(self):
        assert normalize_segments([("bogus_category", 10, 20)]) == []

    def test_고른_카테고리만_남긴다(self):
        segs = normalize_segments(
            [("sponsor", 10, 20), ("intro", 30, 40)], categories=("sponsor",)
        )
        assert [s.category for s in segs] == ["sponsor"]

    def test_합쳐진_구간은_먼저_시작한_카테고리를_쓴다(self):
        segs = normalize_segments([("intro", 10, 30), ("sponsor", 20, 50)])
        assert segs[0].category == "intro"


class TestSegmentAt:
    SEGS = [SkipSegment("sponsor", 10.0, 20.0), SkipSegment("intro", 40.0, 50.0)]

    def test_구간_안이면_찾는다(self):
        assert segment_at(self.SEGS, 15.0).category == "sponsor"

    def test_시작_경계는_포함이다(self):
        assert segment_at(self.SEGS, 10.0) is not None

    def test_끝_경계는_포함하지_않는다(self):
        """포함하면 구간 끝으로 넘긴 직후 같은 구간이 다시 잡혀 제자리에서 튄다."""
        assert segment_at(self.SEGS, 20.0) is None

    def test_구간_밖이면_None(self):
        assert segment_at(self.SEGS, 5.0) is None
        assert segment_at(self.SEGS, 30.0) is None
        assert segment_at(self.SEGS, 99.0) is None

    def test_빈_목록이면_None(self):
        assert segment_at([], 15.0) is None


class TestMetadata:
    def test_표시_이름은_한글이다(self):
        assert SkipSegment("sponsor", 0, 10).display_name == "스폰서 광고"

    def test_모르는_카테고리는_키를_그대로_보여준다(self):
        assert SkipSegment("unknown", 0, 10).display_name == "unknown"

    def test_기본_카테고리는_광고성만_고른다(self):
        """인트로·잡담은 그걸 보려고 튼 사람도 있어 기본에서 뺀다."""
        assert set(DEFAULT_SKIP_CATEGORIES) <= set(SKIP_CATEGORY_NAMES)
        assert "intro" not in DEFAULT_SKIP_CATEGORIES
        assert "sponsor" in DEFAULT_SKIP_CATEGORIES

    def test_구간_길이(self):
        assert SkipSegment("sponsor", 10.0, 25.0).duration_sec == 15.0
