"""LyricsTrack(현재 줄 판정)을 QApplication 없이 검증한다.

렌더(LyricsOverlay)와 분리한 이유가 이것 — 경계값·오프셋 로직은 Qt 없이 빠르게
돌릴 수 있어야 한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from gui.widgets.lyrics_overlay import LyricsCue, LyricsTrack


@dataclass(frozen=True)
class _Line:
    """SongInfoDTO.lyrics_lines 항목을 흉내낸 최소 구조."""
    original: str
    translation: str = ""
    start_ms: int | None = None


def _track(offset_ms: int = 0) -> LyricsTrack:
    return LyricsTrack(
        [
            LyricsCue(start_ms=1000, original="one", line_index=0),
            LyricsCue(start_ms=5000, original="two", line_index=1),
            LyricsCue(start_ms=9000, original="three", line_index=2),
        ],
        offset_ms=offset_ms,
    )


class TestIndexAt:
    def test_첫_줄_시작_전에는_None(self):
        assert _track().index_at(0) is None
        assert _track().index_at(999) is None

    def test_정확히_시작_시각이면_그_줄(self):
        assert _track().index_at(1000) == 0
        assert _track().index_at(5000) == 1

    def test_줄_사이에서는_직전_줄이_유지된다(self):
        assert _track().index_at(4999) == 0
        assert _track().index_at(8999) == 1

    def test_마지막_줄은_끝까지_유지된다(self):
        assert _track().index_at(999_999) == 2

    def test_역방향_seek도_정확하다(self):
        track = _track()
        assert track.index_at(9000) == 2
        assert track.index_at(1500) == 0


class TestOffset:
    def test_양수_오프셋은_자막을_늦춘다(self):
        track = _track(offset_ms=2000)
        assert track.index_at(1000) is None      # 원래 첫 줄 시점 → 아직 안 뜸
        assert track.index_at(3000) == 0

    def test_음수_오프셋은_자막을_앞당긴다(self):
        track = _track(offset_ms=-500)
        assert track.index_at(500) == 0

    def test_오프셋_변경이_즉시_반영된다(self):
        track = _track()
        assert track.index_at(1000) == 0
        track.offset_ms = 3000
        assert track.index_at(1000) is None

    def test_오프셋은_범위로_clamp된다(self):
        track = _track()
        track.offset_ms = 999_999
        assert track.offset_ms == 30_000
        track.offset_ms = -999_999
        assert track.offset_ms == -30_000


class TestCueAndStartOf:
    def test_cue_at은_해당_줄을_준다(self):
        assert _track().cue_at(5001).original == "two"

    def test_cue_at은_시작_전에는_None(self):
        assert _track().cue_at(0) is None

    def test_start_of는_오프셋을_더한_절대_위치(self):
        track = _track(offset_ms=1500)
        assert track.start_of(1) == 6500

    def test_start_of는_음수가_되지_않는다(self):
        track = _track(offset_ms=-5000)
        assert track.start_of(0) == 0

    def test_범위_밖_index는_0(self):
        assert _track().start_of(99) == 0


class TestEmpty:
    def test_빈_트랙은_is_empty(self):
        track = LyricsTrack([])
        assert track.is_empty is True
        assert track.index_at(1000) is None
        assert len(track) == 0

    def test_큐가_있으면_is_empty_False(self):
        assert _track().is_empty is False


class TestFromLines:
    def test_시간_정보가_있는_줄만_큐가_된다(self):
        lines = [
            _Line("no timing"),
            _Line("timed", "번역", 2000),
            _Line("also timed", "", 4000),
        ]
        track = LyricsTrack.from_lines(lines)
        assert len(track) == 2
        assert track.cue_at(2000).original == "timed"
        assert track.cue_at(2000).translation == "번역"

    def test_line_index는_원본_목록_기준이다(self):
        """노래 탭 하이라이트가 원본 줄을 가리켜야 한다."""
        lines = [_Line("untimed"), _Line("first", start_ms=1000)]
        track = LyricsTrack.from_lines(lines)
        assert track.cue_at(1000).line_index == 1

    def test_시간_정보가_없으면_빈_트랙(self):
        assert LyricsTrack.from_lines([_Line("a"), _Line("b")]).is_empty is True

    def test_정렬되지_않은_입력도_정렬된다(self):
        lines = [_Line("late", start_ms=9000), _Line("early", start_ms=1000)]
        track = LyricsTrack.from_lines(lines)
        assert track.index_at(1000) == 0
        assert track.cue_at(1000).original == "early"

    def test_오프셋을_함께_받는다(self):
        track = LyricsTrack.from_lines([_Line("a", start_ms=1000)], offset_ms=500)
        assert track.offset_ms == 500
