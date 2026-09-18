"""자막 → 제안 구간 규칙.

이 기능의 실패는 **쓸모없는 제안**이다(틀렸다고 앱이 죽지는 않는다). 그래서 "말이
몰린 곳이 위로 오는가", "인사말이 1등을 차지하지 않는가", "같은 데를 여러 번
제안하지 않는가" 같은 **쓸모의 조건**을 고정한다.
"""

from __future__ import annotations

from domain.clip.highlights import (
    MIN_SEC,
    Highlight,
    suggest_highlights,
)


def _cues(spec):
    """`(시작초, 길이초, 글자수)` → 자막 큐."""
    out = []
    for start, dur, chars in spec:
        out.append((int(start * 1000), int((start + dur) * 1000), "말" * chars))
    return out


class TestEmpty:
    def test_자막이_없으면_제안하지_않는다(self):
        """이 기능은 자막 위에서만 성립한다."""
        assert suggest_highlights([], duration_sec=600) == []

    def test_길이를_모르면_제안하지_않는다(self):
        assert suggest_highlights(_cues([(0, 5, 50)]), duration_sec=0) == []

    def test_상한이_0이면_빈_목록(self):
        assert suggest_highlights(_cues([(0, 5, 50)]), duration_sec=600, limit=0) == []


class TestDensity:
    def test_말이_몰린_곳이_위로_온다(self):
        cues = _cues(
            [(60, 5, 5), (70, 5, 5)]                      # 한산한 구간
            + [(300 + i * 4, 4, 60) for i in range(12)]   # 말이 몰린 구간
        )
        picks = suggest_highlights(cues, duration_sec=600, limit=1)
        assert picks and 280 <= picks[0].start_sec <= 320, picks[0].start_sec

    def test_모든_구간이_한산하면_그래도_제안한다(self):
        """완벽한 편집점이 아니라 '어디부터 볼까'를 줄여 주는 것이 목적이다."""
        cues = _cues([(i * 30, 5, 10) for i in range(10)])
        assert suggest_highlights(cues, duration_sec=600, limit=3)


class TestIntro:
    def test_시작부_인사말이_1등을_차지하지_않는다(self):
        """인사·구독 요청은 빠르게 말해 글자 밀도가 본론보다 훨씬 높다.

        배수로 깎는 방식은 밀도 차가 조금만 커도 무력해진다(0.35배로 깎아도
        3.3배 촘촘한 인사말이 1등이었다).
        """
        cues = _cues(
            [(i * 3, 3, 80) for i in range(12)]            # 0~36초: 아주 촘촘
            + [(200 + i * 5, 5, 40) for i in range(10)]    # 200초대: 보통
        )
        picks = suggest_highlights(cues, duration_sec=600, limit=1)
        assert picks[0].start_sec >= 45, picks[0].start_sec


class TestChapters:
    def test_챕터_경계로_당긴다(self):
        cues = _cues([(302 + i * 4, 4, 50) for i in range(10)])
        chapters = [("본론", 300.0, 400.0)]
        picks = suggest_highlights(cues, duration_sec=600, chapters=chapters, limit=1)
        assert picks[0].start_sec == 300.0
        assert picks[0].title == "본론"

    def test_멀리_떨어진_챕터로는_당기지_않는다(self):
        """30초 넘게 떨어진 것은 남의 챕터다."""
        cues = _cues([(300 + i * 4, 4, 50) for i in range(10)])
        chapters = [("딴것", 100.0, 200.0)]
        picks = suggest_highlights(cues, duration_sec=600, chapters=chapters, limit=1)
        assert picks[0].start_sec != 100.0
        assert picks[0].title == ""

    def test_시작부밖에_없으면_그거라도_준다(self):
        """짧은 영상은 전부가 시작부다 — 빈 목록을 주면 기능이 없는 것과 같다."""
        cues = _cues([(i * 3, 3, 40) for i in range(10)])   # 0~30초
        assert suggest_highlights(cues, duration_sec=35, limit=3)


class TestChaptersMore:
    def test_챕터가_없어도_동작한다(self):
        cues = _cues([(300 + i * 4, 4, 50) for i in range(10)])
        assert suggest_highlights(cues, duration_sec=600, chapters=None, limit=1)


class TestDeduplication:
    def test_같은_데를_여러_번_제안하지_않는다(self):
        cues = _cues([(300 + i * 2, 2, 60) for i in range(30)])
        picks = suggest_highlights(cues, duration_sec=900, limit=5)
        for i, a in enumerate(picks):
            for b in picks[i + 1:]:
                overlap = min(a.end_sec, b.end_sec) - max(a.start_sec, b.start_sec)
                shorter = min(a.duration_sec, b.duration_sec)
                assert overlap <= 0 or overlap / shorter < 0.5

    def test_상한을_지킨다(self):
        cues = _cues([(i * 10, 8, 40) for i in range(60)])
        assert len(suggest_highlights(cues, duration_sec=600, limit=3)) <= 3


class TestShape:
    def test_시간_순으로_돌려준다(self):
        """점수 순으로 늘어놓으면 영상의 흐름을 잃는다."""
        cues = _cues([(i * 40, 10, 30 + (i % 5) * 20) for i in range(15)])
        picks = suggest_highlights(cues, duration_sec=600, limit=5)
        assert [p.start_sec for p in picks] == sorted(p.start_sec for p in picks)

    def test_구간이_최소_길이보다_짧지_않다(self):
        cues = _cues([(i * 10, 8, 40) for i in range(20)])
        picks = suggest_highlights(cues, duration_sec=600, limit=5)
        assert all(p.duration_sec >= MIN_SEC for p in picks)

    def test_영상_길이를_넘지_않는다(self):
        """끝을 넘기면 ffmpeg 추출이 실패하거나 빈 클립이 나온다."""
        cues = _cues([(280 + i * 3, 3, 50) for i in range(10)])
        picks = suggest_highlights(cues, duration_sec=300, limit=3)
        assert all(p.end_sec <= 300 for p in picks)

    def test_점수가_양수다(self):
        cues = _cues([(100 + i * 5, 5, 40) for i in range(10)])
        assert all(p.score > 0 for p in suggest_highlights(cues, duration_sec=600))


class TestHighlightValue:
    def test_구간_길이(self):
        assert Highlight(10.0, 70.0, 1.0).duration_sec == 60.0
