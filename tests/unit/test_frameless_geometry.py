"""프레임리스 창의 좌표 계산.

이 산술은 네이티브 메시지 핸들러가 쓴다 — 거기서 난 예외는 메시지 루프 안이라
`paintEvent`와 같은 부류로 **조용히 프로세스를 죽인다**. 그래서 계산을 순수 함수로
빼내 여기서 전부 밟아 본다. 화면도 Qt도 필요 없다.
"""

from __future__ import annotations

import pytest

from gui.frameless.geometry import (
    ACT_CLICK,
    ACT_HOVER_OFF,
    ACT_HOVER_ON,
    ACT_NONE,
    ACT_SWALLOW,
    AUTOHIDE_INSET,
    EDGE_BOTTOM,
    EDGE_LEFT,
    EDGE_RIGHT,
    EDGE_TOP,
    HTBOTTOM,
    HTBOTTOMLEFT,
    HTCAPTION,
    HTMAXBUTTON,
    HTBOTTOMRIGHT,
    HTLEFT,
    HTNOWHERE,
    HTRIGHT,
    HTTOP,
    HTTOPLEFT,
    HTTOPRIGHT,
    autohide_inset,
    deflate_maximized,
    WM_NCLBUTTONDOWN,
    WM_NCLBUTTONUP,
    WM_NCMOUSELEAVE,
    WM_NCMOUSEMOVE,
    edge_hit,
    max_button_action,
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


class TestMaxButtonAction:
    """최대화 버튼 위에서 `HTMAXBUTTON`을 돌려주면 Win11 이 분할 배치 메뉴를 띄운다.

    대가로 **그 영역의 마우스를 OS 가 가져간다** — Qt 는 클릭도 호버도 받지 못하므로
    비클라이언트 메시지를 직접 번역해 버튼을 살려 줘야 한다. 이 번역이 틀리면
    스냅 메뉴는 뜨는데 **최대화 버튼이 먹통이 된다**.
    """

    def test_버튼_위로_오면_호버를_켠다(self):
        assert max_button_action(WM_NCMOUSEMOVE, HTMAXBUTTON) == ACT_HOVER_ON

    def test_버튼을_벗어나면_호버를_끈다(self):
        """캡션으로 옮겨 갔는데 호버가 남으면 버튼이 계속 밝게 떠 있다."""
        assert max_button_action(WM_NCMOUSEMOVE, HTCAPTION) == ACT_HOVER_OFF

    def test_비클라이언트를_떠나면_호버를_끈다(self):
        assert max_button_action(WM_NCMOUSELEAVE, 0) == ACT_HOVER_OFF

    def test_누름은_삼킨다(self):
        """기본 처리에 맡기면 OS 가 자기 방식으로 버튼을 그리려 한다."""
        assert max_button_action(WM_NCLBUTTONDOWN, HTMAXBUTTON) == ACT_SWALLOW

    def test_뗄_때_토글한다(self):
        assert max_button_action(WM_NCLBUTTONUP, HTMAXBUTTON) == ACT_CLICK

    def test_버튼_밖에서_누르고_떼는_것은_건드리지_않는다(self):
        """캡션 클릭은 OS 의 것이다 — 삼키면 창 이동이 죽는다."""
        assert max_button_action(WM_NCLBUTTONDOWN, HTCAPTION) == ACT_NONE
        assert max_button_action(WM_NCLBUTTONUP, HTCAPTION) == ACT_NONE

    def test_모르는_메시지는_넘긴다(self):
        assert max_button_action(0x0999, HTMAXBUTTON) == ACT_NONE
