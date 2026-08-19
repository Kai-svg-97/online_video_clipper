"""자막 파서 — json3 / WebVTT 규칙을 고정한다.

자막은 **한 글자만 어긋나도 바로 보이는** 기능이라 파싱 규칙을 테스트로 못박는다.
특히 YouTube 자동 자막의 두 가지 버릇이 중요하다.

* 단어 단위 타이밍 태그(`<00:00:01.234><c>단어</c>`)가 본문에 섞여 온다.
* 한 줄씩 밀려 올라가며 **같은 문장을 여러 번** 내보낸다 — 그대로 두면 화면에 같은
  말이 겹쳐 보인다.
"""
from __future__ import annotations

import json

from infrastructure.subtitle.parsers import parse_cues, parse_json3, parse_vtt


class TestJson3:
    def _raw(self, events) -> str:
        return json.dumps({"events": events})

    def test_시작과_길이로_구간을_만든다(self):
        raw = self._raw([
            {"tStartMs": 1000, "dDurationMs": 2000, "segs": [{"utf8": "안녕"}]},
        ])

        assert parse_json3(raw) == [(1000, 3000, "안녕")]

    def test_조각을_이어_붙인다(self):
        raw = self._raw([
            {"tStartMs": 0, "dDurationMs": 1000,
             "segs": [{"utf8": "안"}, {"utf8": "녕"}, {"utf8": " 세상"}]},
        ])

        assert parse_json3(raw)[0][2] == "안녕 세상"

    def test_텍스트가_없는_이벤트는_버린다(self):
        raw = self._raw([
            {"tStartMs": 0, "dDurationMs": 500},                       # segs 없음
            {"tStartMs": 500, "dDurationMs": 500, "segs": [{"utf8": "\n"}]},
            {"tStartMs": 1000, "dDurationMs": 500, "segs": [{"utf8": "말"}]},
        ])

        assert [c[2] for c in parse_json3(raw)] == ["말"]

    def test_json이_아니면_빈_목록(self):
        assert parse_json3("WEBVTT\n\n") == []


class TestVtt:
    def test_시간과_본문을_읽는다(self):
        raw = "WEBVTT\n\n00:00:01.000 --> 00:00:03.500\n안녕하세요\n"

        assert parse_vtt(raw) == [(1000, 3500, "안녕하세요")]

    def test_시간_이후의_위치_지정자는_무시한다(self):
        raw = ("WEBVTT\n\n00:00:01.000 --> 00:00:02.000 align:start position:0%\n"
               "본문\n")

        assert parse_vtt(raw) == [(1000, 2000, "본문")]

    def test_단어_타이밍_태그를_걷어낸다(self):
        raw = ("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n"
               "<00:00:00.320><c>오늘</c> <00:00:00.800><c>날씨</c>\n")

        assert parse_vtt(raw)[0][2] == "오늘 날씨"

    def test_이어지는_같은_문장은_하나로_합친다(self):
        """자동 자막은 같은 줄을 반복해 내보낸다 — 겹쳐 보이면 읽을 수 없다."""
        raw = ("WEBVTT\n\n"
               "00:00:01.000 --> 00:00:02.000\n같은 문장\n\n"
               "00:00:02.000 --> 00:00:04.000\n같은 문장\n")

        cues = parse_vtt(raw)

        assert cues == [(1000, 4000, "같은 문장")]

    def test_시간_줄이_없으면_빈_목록(self):
        assert parse_vtt("WEBVTT\n\n메모만 있음\n") == []

    def test_밀리초_구분자로_쉼표도_받는다(self):
        raw = "WEBVTT\n\n00:00:01,000 --> 00:00:02,000\n본문\n"

        assert parse_vtt(raw)[0][:2] == (1000, 2000)

    def test_시간_단위가_있어도_읽는다(self):
        raw = "WEBVTT\n\n01:02:03.000 --> 01:02:04.000\n본문\n"

        assert parse_vtt(raw)[0][0] == 3_723_000


class TestPickParser:
    def test_확장자_힌트를_따른다(self):
        raw = json.dumps({"events": [
            {"tStartMs": 0, "dDurationMs": 900, "segs": [{"utf8": "hi"}]}
        ]})

        assert parse_cues(raw, "json3")[0][2] == "hi"

    def test_힌트가_빗나가도_다른_파서로_구해_낸다(self):
        """출처가 준 확장자와 실제 내용이 어긋나는 경우가 있다 — 자막을 통째로 잃지 않는다."""
        vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n본문\n"

        assert parse_cues(vtt, "json3")[0][2] == "본문"

    def test_둘_다_아니면_빈_목록(self):
        assert parse_cues("그냥 텍스트", "vtt") == []
