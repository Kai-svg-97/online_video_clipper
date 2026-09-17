"""설명 → 챕터 구간 파싱 규칙.

실제 YouTube 설명은 지저분하다 — 불릿·괄호·대시가 섞이고, 본문 한복판에 "10:30에
촬영" 같은 시각 표기가 들어간다. 오탐을 하나라도 통과시키면 챕터 목록이 못 쓰게
되므로 걸러내는 쪽을 특히 촘촘히 고정한다.
"""

from __future__ import annotations

from domain.clip.chapters import Chapter, parse_chapters


class TestBasic:
    def test_줄머리_타임스탬프를_구간으로_잇는다(self):
        desc = "0:00 인트로\n1:30 본론\n5:00 마무리"
        assert parse_chapters(desc, duration_sec=600) == [
            Chapter("인트로", 0.0, 90.0),
            Chapter("본론", 90.0, 300.0),
            Chapter("마무리", 300.0, 600.0),
        ]

    def test_시간_단위_타임스탬프(self):
        desc = "0:00 시작\n1:02:03 한참 뒤"
        chapters = parse_chapters(desc, duration_sec=4000)
        assert chapters[1].start_sec == 3723.0

    def test_장식_기호를_흘려보낸다(self):
        desc = "- (0:00) 인트로\n• [2:00] — 본론"
        chapters = parse_chapters(desc, duration_sec=300)
        assert [c.title for c in chapters] == ["인트로", "본론"]

    def test_제목이_앞에_오는_형식도_받는다(self):
        desc = "인트로 - 0:00\n본론 - 2:00"
        chapters = parse_chapters(desc, duration_sec=300)
        assert [(c.title, c.start_sec) for c in chapters] == [("인트로", 0.0), ("본론", 120.0)]

    def test_제목이_없으면_번호를_붙인다(self):
        chapters = parse_chapters("0:00\n1:00", duration_sec=120)
        assert [c.title for c in chapters] == ["챕터 1", "챕터 2"]


class TestRejection:
    def test_챕터가_하나면_인정하지_않는다(self):
        assert parse_chapters("0:00 인트로", duration_sec=600) == []

    def test_설명이_비면_빈_목록(self):
        assert parse_chapters("", duration_sec=600) == []

    def test_본문_중간의_시각_표기는_무시한다(self):
        """'10:30에 촬영했습니다' 같은 줄이 챕터로 잡히면 목록이 못 쓰게 된다."""
        desc = "이 영상은 10:30에 촬영했습니다.\n장비는 12:00에 설치했고요."
        assert parse_chapters(desc, duration_sec=600) == []

    def test_뒤로_가는_타임스탬프는_건너뛴다(self):
        desc = "0:00 인트로\n5:00 본론\n1:00 (예전 영상 참고)\n8:00 마무리"
        chapters = parse_chapters(desc, duration_sec=600)
        assert [c.start_sec for c in chapters] == [0.0, 300.0, 480.0]

    def test_초가_60_이상이면_타임스탬프가_아니다(self):
        assert parse_chapters("0:00 인트로\n1:75 이상한값", duration_sec=600) == []

    def test_시가_없는데_분이_60_이상이면_무시(self):
        assert parse_chapters("0:00 인트로\n99:99 이상한값", duration_sec=600) == []


class TestEnding:
    def test_마지막_끝은_영상_길이다(self):
        chapters = parse_chapters("0:00 A\n1:00 B", duration_sec=222)
        assert chapters[-1].end_sec == 222.0

    def test_영상_길이를_모르면_마지막_챕터를_버린다(self):
        """끝을 모르는 구간은 추출할 수 없다 — 억지로 추측하면 잘린 클립이 나온다."""
        chapters = parse_chapters("0:00 A\n1:00 B\n2:00 C", duration_sec=0)
        assert [c.title for c in chapters] == ["A", "B"]
        assert chapters[-1].end_sec == 120.0

    def test_길이가_마지막_시작보다_짧으면_버린다(self):
        chapters = parse_chapters("0:00 A\n1:00 B\n9:00 C", duration_sec=100)
        assert [c.title for c in chapters] == ["A", "B"]

    def test_버린_뒤_하나만_남으면_챕터로_보지_않는다(self):
        assert parse_chapters("0:00 A\n1:00 B", duration_sec=0) == []


class TestDuration:
    def test_구간_길이(self):
        chapters = parse_chapters("0:00 A\n0:30 B", duration_sec=100)
        assert chapters[0].duration_sec == 30.0
        assert chapters[1].duration_sec == 70.0
