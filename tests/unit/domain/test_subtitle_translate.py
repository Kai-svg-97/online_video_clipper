"""자막 번역 규칙 — 묶어 보내고, 정렬이 깨지면 되돌린다.

번역기는 한 줄씩 호출하는 설계다(가사 40줄 기준). 자막은 수백~수천 줄이라 그대로
쓰면 왕복이 그만큼 난다. 그래서 묶어 보내는데, **그 순간 정렬이 깨질 위험이 생긴다** —
번역기가 줄을 합치거나 나누면 원문과 번역의 짝이 어긋나고, 그러면 엉뚱한 시점에
엉뚱한 말이 뜬다. 틀렸다는 티조차 나지 않아 가장 고약한 실패다.

여기서 고정하는 것이 그 안전장치다.
"""

from __future__ import annotations

from domain.library.subtitle_translate import (
    CHUNK_LINES,
    TRANSLATED_PREFIX,
    chunks,
    is_translated_lang,
    join_chunk,
    merge,
    needs_translation,
    split_chunk,
    translated_lang,
)


class TestLangKey:
    def test_원문과_겹치지_않는_키를_쓴다(self):
        """겹치면 다시 받은 자막이 번역을 통째로 덮어쓴다."""
        assert translated_lang("ko") == "tr-ko"
        assert translated_lang("ko") not in ("ko", "en", "asr-auto")

    def test_번역본을_알아본다(self):
        assert is_translated_lang("tr-ko") is True
        assert is_translated_lang("ko") is False
        assert is_translated_lang("asr-auto") is False
        assert is_translated_lang("") is False

    def test_접두가_지켜진다(self):
        assert translated_lang("en").startswith(TRANSLATED_PREFIX)


class TestNeedsTranslation:
    def test_이미_목표_언어면_하지_않는다(self):
        """한국어를 한국어로 번역하면 왕복만 낭비하고 결과도 나빠진다."""
        assert needs_translation(["안녕하세요"], detected="ko", target="ko") is False

    def test_다른_언어면_한다(self):
        assert needs_translation(["hello"], detected="en", target="ko") is True

    def test_언어를_몰라도_한다(self):
        assert needs_translation(["hello"], detected="", target="ko") is True

    def test_내용이_없으면_하지_않는다(self):
        assert needs_translation([], detected="", target="ko") is False
        assert needs_translation(["", "  "], detected="", target="ko") is False

    def test_기호뿐인_줄은_세지_않는다(self):
        assert needs_translation(["-", "♪"], detected="", target="ko") is False


class TestChunking:
    def test_묶음마다_시작_인덱스를_준다(self):
        """인덱스가 없으면 번역 결과를 제자리에 돌려놓을 수 없다."""
        got = chunks(["a"] * 95, size=40)
        assert [start for start, _ in got] == [0, 40, 80]

    def test_마지막_묶음은_짧을_수_있다(self):
        got = chunks(["a"] * 95, size=40)
        assert len(got[-1][1]) == 15

    def test_빈_목록은_묶음이_없다(self):
        assert chunks([]) == []

    def test_크기가_이상하면_기본값을_쓴다(self):
        assert len(chunks(["a"] * 100, size=0)) == len(chunks(["a"] * 100, CHUNK_LINES))

    def test_묶으면_왕복이_확_준다(self):
        """500줄이면 13번 — 한 줄씩이면 500번이다."""
        assert len(chunks(["a"] * 500)) == 13


class TestSplitVerifies:
    def test_줄_수가_맞으면_나눈다(self):
        got = split_chunk(["a", "b"], "가\n나")
        assert got == ["가", "나"]

    def test_줄이_합쳐지면_되돌린다(self):
        """번역기가 두 줄을 한 줄로 만들면 짝이 밀린다 — 억지로 맞추면 안 된다."""
        assert split_chunk(["a", "b"], "가 나") is None

    def test_줄이_늘어나도_되돌린다(self):
        assert split_chunk(["a", "b"], "가\n나\n다") is None

    def test_빈_응답이면_되돌린다(self):
        assert split_chunk(["a"], "") is None

    def test_원문이_빈_자리는_비운_채_둔다(self):
        """번역기가 빈 줄에 뭔가 채워 넣기도 한다."""
        assert split_chunk(["a", "  "], "가\n무언가") == ["가", ""]

    def test_앞뒤_공백을_턴다(self):
        assert split_chunk(["a"], "  가  ") == ["가"]


class TestMergeKeepsOriginal:
    def test_번역이_비면_원문을_남긴다(self):
        """빈 줄로 두면 그 시점에 자막이 사라져, 실패인지 말이 없는 건지 알 수 없다."""
        assert merge(["hello", "world"], ["안녕", ""]) == ["안녕", "world"]

    def test_전부_실패해도_원문이_남는다(self):
        assert merge(["a", "b"], ["", ""]) == ["a", "b"]

    def test_공백뿐인_번역도_실패로_본다(self):
        assert merge(["hello"], ["   "]) == ["hello"]

    def test_정상이면_번역을_쓴다(self):
        assert merge(["hello"], ["안녕"]) == ["안녕"]


class TestJoin:
    def test_줄바꿈으로_잇는다(self):
        assert join_chunk(["a", "b"]) == "a\nb"

    def test_빈_줄도_자리를_지킨다(self):
        """자리가 밀리면 뒤 줄이 전부 어긋난다."""
        assert join_chunk(["a", "", "b"]).split("\n") == ["a", "", "b"]

    def test_앞뒤_공백을_턴다(self):
        assert join_chunk(["  a  "]) == "a"
