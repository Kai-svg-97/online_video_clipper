"""새 영상 감시 판정 — **순수 규칙**.

## 왜 날짜가 아니라 주소로 비교하나

"지난번 이후"를 날짜로 판정하는 것이 자연스럽지만, `published_at` 표기가 출처마다
다르다(yt-dlp 플랫 추출은 `YYYYMMDD`, YouTube API는 ISO 8601). 형식을 잘못 짚으면
**조용히 틀린다** — 알림이 안 오거나, 매번 전부가 새 영상이 된다. 그래서 지난번에
본 주소 목록과 비교한다.

여기서 고정하는 함정은 셋이다.

1. **처음 켠 것은 새 영상이 아니다** — 설치 직후 구독 피드 전체를 알리면 알림이
   수십 개 뜨고 사용자는 그 길로 알림을 꺼 버린다.
2. **기억이 밀려나면 같은 알림이 반복된다** — 아직 피드에 남아 있는 영상이 기억에서
   빠지면 다음 회차에 다시 '새 영상'이 된다.
3. **피드가 잠깐 짧아져도 기억을 통째로 갈지 않는다** — 채널 하나가 응답하지 않아
   피드가 줄면, 이전 기억을 버릴 경우 다음 조회에서 전부 새 영상이 된다.
"""

from __future__ import annotations

from domain.monitoring.watch import (
    DEFAULT_INTERVAL_MIN,
    MAX_INTERVAL_MIN,
    MIN_INTERVAL_MIN,
    NOTIFY_SAMPLE,
    SEEN_LIMIT,
    clamp_interval,
    next_seen,
    select_new,
    summarize,
)


def _urls(*ns: int) -> list[str]:
    return [f"https://youtu.be/v{n:08d}" for n in ns]


class TestFirstRun:
    def test_기억이_비면_아무것도_새_영상이_아니다(self):
        """설치 직후 피드 전체를 알리면 사용자가 알림을 꺼 버린다."""
        assert select_new(_urls(1, 2, 3), []) == []

    def test_첫_회차에도_기억은_남는다(self):
        """기준선을 잡아야 다음 회차부터 판정이 성립한다."""
        assert next_seen(_urls(1, 2, 3), []) == _urls(1, 2, 3)


class TestSelectNew:
    def test_지난번에_없던_것만_고른다(self):
        assert select_new(_urls(4, 3, 2, 1), _urls(1, 2)) == _urls(4, 3)

    def test_피드_순서를_지킨다(self):
        """최신이 위라, 알림 본문도 최신부터 읽혀야 한다."""
        assert select_new(_urls(9, 8, 7), _urls(7)) == _urls(9, 8)

    def test_바뀐_게_없으면_빈_목록(self):
        assert select_new(_urls(1, 2), _urls(2, 1)) == []

    def test_같은_주소가_두_번_와도_한_번만_센다(self):
        assert select_new(_urls(5) + _urls(5), _urls(1)) == _urls(5)

    def test_빈_주소는_무시한다(self):
        assert select_new(["", *_urls(5)], _urls(1)) == _urls(5)


class TestNextSeen:
    def test_이번_것을_앞에_두고_이전_것을_잇는다(self):
        assert next_seen(_urls(3, 2), _urls(2, 1)) == _urls(3, 2, 1)

    def test_피드가_짧아져도_이전_기억을_버리지_않는다(self):
        """채널 하나가 응답하지 않아 피드가 줄면, 버릴 경우 다음에 전부 새 영상이 된다."""
        shrunk = next_seen(_urls(3), _urls(3, 2, 1))
        assert select_new(_urls(3, 2, 1), shrunk) == []

    def test_상한을_넘지_않는다(self):
        big = next_seen(_urls(*range(500)), [], limit=10)
        assert len(big) == 10

    def test_상한은_피드_한_쪽보다_넉넉하다(self):
        """부족하면 아직 피드에 있는 영상이 밀려나 같은 알림이 반복된다."""
        assert SEEN_LIMIT > 100


class TestInterval:
    def test_너무_짧으면_올린다(self):
        """자주 확인하면 YouTube가 요청을 막는다."""
        assert clamp_interval(1) == MIN_INTERVAL_MIN

    def test_너무_길면_내린다(self):
        assert clamp_interval(99999) == MAX_INTERVAL_MIN

    def test_범위_안이면_그대로(self):
        assert clamp_interval(45) == 45

    def test_이상한_값이면_기본값(self):
        """설정 파일을 손으로 고쳐도 감시가 죽지 않아야 한다."""
        assert clamp_interval("사십오") == DEFAULT_INTERVAL_MIN
        assert clamp_interval(None) == DEFAULT_INTERVAL_MIN


class TestSummary:
    def test_제목_몇_개만_적고_나머지는_수로_줄인다(self):
        text = summarize([f"영상 {i}" for i in range(10)], total=10)
        assert text.count("\n") == NOTIFY_SAMPLE          # 제목 3줄 + 요약 1줄
        assert "외 7개" in text

    def test_적으면_전부_적는다(self):
        assert summarize(["가", "나"], total=2) == "가\n나"

    def test_제목을_모르면_수만_알린다(self):
        assert summarize(["", ""], total=2) == "새 영상 2개"
