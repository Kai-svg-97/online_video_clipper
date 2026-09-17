"""플레이어의 SponsorBlock 건너뛰기 동작.

진짜 재생 없이 `_maybe_skip`을 직접 먹여 판정만 본다 — 여기서 잡고 싶은 건 미디어
백엔드가 아니라 **언제 넘기고 언제 넘기지 않는가**다. 특히 "한 번 건너뛴 구간을
사용자가 되감아 보려 할 때 다시 튕기지 않는가"는 실제로 겪기 전엔 놓치기 쉽다.
"""

from __future__ import annotations

import pytest

from domain.clip.sponsor import SkipSegment
from gui.widgets.video_player import InlinePlayer

SEGS = [SkipSegment("sponsor", 10.0, 20.0), SkipSegment("intro", 40.0, 50.0)]


@pytest.fixture
def player(qtbot):
    p = InlinePlayer()
    qtbot.addWidget(p)
    return p


class TestSkipping:
    def test_구간_안이면_끝으로_넘긴다(self, player):
        player.set_skip_segments(SEGS)
        moved: list[int] = []
        player._player.setPosition = moved.append

        player._maybe_skip(15_000)

        assert moved == [20_000]

    def test_구간_밖이면_가만히_둔다(self, player):
        player.set_skip_segments(SEGS)
        moved: list[int] = []
        player._player.setPosition = moved.append

        player._maybe_skip(5_000)

        assert moved == []

    def test_건너뛰면_알림_신호가_나간다(self, player, qtbot):
        player.set_skip_segments(SEGS)
        player._player.setPosition = lambda _ms: None
        got: list[str] = []
        player.segment_skipped.connect(got.append)

        player._maybe_skip(15_000)

        assert got == ["스폰서 광고"]

    def test_구간이_없으면_아무_일도_없다(self, player):
        moved: list[int] = []
        player._player.setPosition = moved.append

        player._maybe_skip(15_000)

        assert moved == []


class TestNoBounce:
    def test_한_번_건너뛴_구간은_다시_건너뛰지_않는다(self, player):
        """되감아 그 구간을 보려는 사용자를 계속 튕겨내면 볼 방법이 없다."""
        player.set_skip_segments(SEGS)
        moved: list[int] = []
        player._player.setPosition = moved.append

        player._maybe_skip(15_000)
        player._maybe_skip(12_000)   # 사용자가 일부러 되감았다

        assert moved == [20_000]

    def test_다른_구간은_여전히_건너뛴다(self, player):
        player.set_skip_segments(SEGS)
        moved: list[int] = []
        player._player.setPosition = moved.append

        player._maybe_skip(15_000)
        player._maybe_skip(45_000)

        assert moved == [20_000, 50_000]


class TestLifetime:
    def test_늦게_도착한_결과는_지금_위치에도_적용된다(self, player):
        """조회가 비동기라 재생이 이미 구간 안에 들어간 뒤 도착하는 일이 흔하다."""
        player._player.position = lambda: 15_000
        moved: list[int] = []
        player._player.setPosition = moved.append

        player.set_skip_segments(SEGS)

        assert moved == [20_000]

    def test_빈_목록을_주면_판정하지_않는다(self, player):
        player._player.position = lambda: 15_000
        moved: list[int] = []
        player._player.setPosition = moved.append

        player.set_skip_segments([])

        assert moved == []
