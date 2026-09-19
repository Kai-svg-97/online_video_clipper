"""프레임리스 창의 좌표 계산.

이 산술은 네이티브 메시지 핸들러가 쓴다 — 거기서 난 예외는 메시지 루프 안이라
`paintEvent`와 같은 부류로 **조용히 프로세스를 죽인다**. 그래서 계산을 순수 함수로
빼내 여기서 전부 밟아 본다. 화면도 Qt도 필요 없다.
"""

from __future__ import annotations

import pytest

from gui.frameless.geometry import (
    AUTOHIDE_INSET,
    EDGE_BOTTOM,
    EDGE_LEFT,
    EDGE_RIGHT,
    EDGE_TOP,
    HTBOTTOM,
    HTBOTTOMLEFT,
    HTBOTTOMRIGHT,
    HTLEFT,
    HTNOWHERE,
    HTRIGHT,
    HTTOP,
    HTTOPLEFT,
    HTTOPRIGHT,
    autohide_inset,
    deflate_maximized,
    edge_hit,
    signed16,
)

W, H, B = 1000, 700, 8


class TestEdgeHit:
    def test_가운데는_테두리가_아니다(self):
        assert edge_hit(500, 350, W, H, B) == HTNOWHERE

    @pytest.mark.parametrize(
        ("x", "y", "expected"),
        [
            (0, 350, HTLEFT),
            (W - 1, 350, HTRIGHT),
            (500, 0, HTTOP),
            (500, H - 1, HTBOTTOM),
        ],
    )
    def test_네_변(self, x, y, expected):
        assert edge_hit(x, y, W, H, B) == expected

    @pytest.mark.parametrize(
        ("x", "y", "expected"),
        [
            (0, 0, HTTOPLEFT),
            (W - 1, 0, HTTOPRIGHT),
            (0, H - 1, HTBOTTOMLEFT),
            (W - 1, H - 1, HTBOTTOMRIGHT),
        ],
    )
    def test_네_모서리(self, x, y, expected):
        """모서리를 변보다 먼저 판정하지 않으면 한 방향으로만 늘어난다."""
        assert edge_hit(x, y, W, H, B) == expected

    def test_테두리_바로_안쪽은_아니다(self):
        assert edge_hit(B, 350, W, H, B) == HTNOWHERE
        assert edge_hit(W - B - 1, 350, W, H, B) == HTNOWHERE

    def test_테두리_두께가_0이면_판정하지_않는다(self):
        """두께를 구하지 못한 경우(구버전 API 실패) 창을 못 쓰게 만들면 안 된다."""
        assert edge_hit(0, 0, W, H, 0) == HTNOWHERE

    def test_창이_아주_얇아도_좌우가_서로를_먹지_않는다(self):
        """폭이 테두리 두 배보다 작으면 좌우 판정이 겹친다."""
        assert edge_hit(0, 5, 10, 700, B) == HTTOPLEFT
        assert edge_hit(9, 350, 10, 700, B) == HTRIGHT

    def test_크기가_0이면_안전하다(self):
        assert edge_hit(0, 0, 0, 0, B) == HTNOWHERE

    def test_음수_좌표도_왼쪽_위로_친다(self):
        """보조 모니터가 왼쪽에 있으면 창 기준 좌표가 음수가 될 수 있다."""
        assert edge_hit(-3, -3, W, H, B) == HTTOPLEFT


class TestDeflateMaximized:
    def test_사방을_프레임_두께만큼_줄인다(self):
        """줄이지 않으면 최대화 시 우측 스크롤바가 화면 밖으로 나간다."""
        assert deflate_maximized((0, 0, 1920, 1040), 8, 8) == (8, 8, 1912, 1032)

    def test_가로세로_두께가_달라도_된다(self):
        assert deflate_maximized((0, 0, 100, 100), 3, 7) == (3, 7, 97, 93)

    def test_음수_원점도_유지된다(self):
        """주 모니터 왼쪽에 놓인 보조 모니터에서 최대화하면 원점이 음수다."""
        assert deflate_maximized((-1920, 0, 0, 1040), 8, 8) == (-1912, 8, -8, 1032)

    def test_두께가_0이면_그대로(self):
        assert deflate_maximized((0, 0, 100, 100), 0, 0) == (0, 0, 100, 100)


class TestAutohideInset:
    def test_자동숨김이_없으면_물러나지_않는다(self):
        assert autohide_inset(None) == (0, 0, 0, 0)

    @pytest.mark.parametrize(
        ("edge", "expected"),
        [
            (EDGE_LEFT, (AUTOHIDE_INSET, 0, 0, 0)),
            (EDGE_TOP, (0, AUTOHIDE_INSET, 0, 0)),
            (EDGE_RIGHT, (0, 0, AUTOHIDE_INSET, 0)),
            (EDGE_BOTTOM, (0, 0, 0, AUTOHIDE_INSET)),
        ],
    )
    def test_해당_변에서만_물러난다(self, edge, expected):
        assert autohide_inset(edge) == expected

    def test_한_변에서만_물러난다(self):
        for edge in (EDGE_LEFT, EDGE_TOP, EDGE_RIGHT, EDGE_BOTTOM):
            assert sum(1 for v in autohide_inset(edge) if v) == 1

    def test_양보하는_두께가_1보다_크다(self):
        """1px 은 배율에 따라 반올림으로 사라진다."""
        assert AUTOHIDE_INSET >= 2

    def test_모르는_값은_물러나지_않는다(self):
        assert autohide_inset(99) == (0, 0, 0, 0)


class TestSigned16:
    def test_양수는_그대로(self):
        assert signed16(100) == 100

    def test_음수를_푼다(self):
        """보조 모니터가 왼쪽/위에 있으면 화면 좌표가 음수다."""
        assert signed16(0xFFFF) == -1
        assert signed16(0x8000) == -32768

    def test_경계(self):
        assert signed16(0x7FFF) == 32767

    def test_상위_비트를_무시한다(self):
        """LPARAM 에서 꺼낼 때 상위 워드가 섞여 들어올 수 있다."""
        assert signed16(0x1234_0064) == 100
