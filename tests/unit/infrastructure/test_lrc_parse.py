"""LRC(가사 타이밍) 파싱 검증.

LRCLIB의 syncedLyrics를 줄별 시각으로 바꾸는 순수 함수라 I/O 없이 테스트한다.
"""
from __future__ import annotations

from infrastructure.song.lrc import parse_lrc


class TestBasicTimestamps:
    def test_밀리초_포함(self):
        assert parse_lrc("[01:23.45]가사") == [(83450, "가사")]

    def test_밀리초_3자리(self):
        assert parse_lrc("[01:23.456]가사") == [(83456, "가사")]

    def test_밀리초_생략(self):
        assert parse_lrc("[01:23]가사") == [(83000, "가사")]

    def test_타임스탬프_뒤_공백_제거(self):
        assert parse_lrc("[00:05.00]   hello  ") == [(5000, "hello")]

    def test_여러_줄_시각_오름차순(self):
        text = "[00:10.00]둘\n[00:05.00]하나"
        assert parse_lrc(text) == [(5000, "하나"), (10000, "둘")]


class TestMultiTimestamp:
    def test_한_줄_다중_타임스탬프는_전개된다(self):
        text = "[00:10.00][01:10.00]후렴"
        assert parse_lrc(text) == [(10000, "후렴"), (70000, "후렴")]


class TestMetaTags:
    def test_메타태그는_버린다(self):
        text = "[ar:가수]\n[ti:제목]\n[al:앨범]\n[by:작성자]\n[length:03:20]\n[00:01.00]가사"
        assert parse_lrc(text) == [(1000, "가사")]

    def test_offset_태그는_모든_시각에_더한다(self):
        # LRC 표준: offset은 밀리초, 음수면 앞당김
        text = "[offset:-500]\n[00:10.00]가사"
        assert parse_lrc(text) == [(9500, "가사")]

    def test_offset으로_음수가_되면_0으로_보정(self):
        text = "[offset:-5000]\n[00:01.00]가사"
        assert parse_lrc(text) == [(0, "가사")]


class TestUntimedAndEdgeCases:
    def test_타임스탬프_없는_줄은_None으로_보존(self):
        text = "[00:01.00]첫줄\n주석 같은 줄"
        assert parse_lrc(text) == [(1000, "첫줄"), (None, "주석 같은 줄")]

    def test_타임스탬프_없는_줄은_맨_뒤로_모인다(self):
        text = "[00:20.00]나중\n무시간\n[00:10.00]먼저"
        assert parse_lrc(text) == [(10000, "먼저"), (20000, "나중"), (None, "무시간")]

    def test_빈_입력(self):
        assert parse_lrc("") == []
        assert parse_lrc("   \n  \n") == []

    def test_깨진_대괄호는_텍스트로_취급(self):
        assert parse_lrc("[00:1x.00]가사") == [(None, "[00:1x.00]가사")]

    def test_내부_빈_줄은_보존된다(self):
        text = "[00:01.00]가사\n\n[00:02.00]다음"
        assert parse_lrc(text) == [(1000, "가사"), (2000, "다음"), (None, "")]

    def test_CRLF_처리(self):
        assert parse_lrc("[00:01.00]가사\r\n[00:02.00]둘") == [(1000, "가사"), (2000, "둘")]

    def test_빈_가사_줄도_시각을_갖는다(self):
        # 간주 구간 표기 — 텍스트가 비어도 시각은 유효하다
        assert parse_lrc("[00:30.00]") == [(30000, "")]
