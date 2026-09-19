"""프레임리스 창의 좌표 계산 — **순수 함수**, Qt도 ctypes도 모른다.

이 계산이 네이티브 메시지 핸들러 안에 섞여 있으면 검증할 방법이 없다. 거기서 난
예외는 메시지 루프 안이라 `paintEvent`와 같은 부류로 **조용히 프로세스를 죽인다.**
그래서 위험한 산술은 전부 여기로 빼고, 핸들러는 값을 받아 쓰기만 한다.
"""

from __future__ import annotations

# Win32 히트테스트 코드. 숫자를 그대로 돌려줘야 해서 여기 둔다.
HTNOWHERE = 0
HTCLIENT = 1
HTCAPTION = 2
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17

# 작업표시줄 변(`ABE_*`).
EDGE_LEFT = 0
EDGE_TOP = 1
EDGE_RIGHT = 2
EDGE_BOTTOM = 3

# 자동숨김 작업표시줄이 있는 변에 남겨 둘 두께(픽셀).
#
# 최대화 창이 그 변을 **100% 덮으면** Windows 는 마우스를 갖다 대도 작업표시줄을
# 다시 띄우지 않는다. 몇 픽셀만 양보하면 그 동작이 살아난다. 1px 은 배율에 따라
# 반올림으로 사라질 수 있어 2px 을 쓴다.
AUTOHIDE_INSET = 2


def edge_hit(x: int, y: int, width: int, height: int, border: int) -> int:
    """창 안의 한 점이 어느 리사이즈 테두리인가 — 아니면 0(`HTNOWHERE`).

    좌표는 **창 좌상단 기준**이고 단위는 물리 픽셀이다. 모서리를 변보다 **먼저**
    판정한다 — 그러지 않으면 모서리에서 한 방향으로만 늘어난다.
    """
    if border <= 0 or width <= 0 or height <= 0:
        return HTNOWHERE

    # 창이 테두리 두께의 두 배보다 얇으면 좌우(위아래) 판정이 겹친다. 그때는
    # 겹치는 쪽을 포기해 **한쪽 변이 반대쪽을 먹어 버리는 것**을 막는다.
    bx = min(border, max(1, width // 2))
    by = min(border, max(1, height // 2))

    left = x < bx
    right = x >= width - bx
    top = y < by
    bottom = y >= height - by

    if top and left:
        return HTTOPLEFT
    if top and right:
        return HTTOPRIGHT
    if bottom and left:
        return HTBOTTOMLEFT
    if bottom and right:
        return HTBOTTOMRIGHT
    if left:
        return HTLEFT
    if right:
        return HTRIGHT
    if top:
        return HTTOP
    if bottom:
        return HTBOTTOM
    return HTNOWHERE


def deflate_maximized(
    rect: tuple[int, int, int, int],
    frame_x: int,
    frame_y: int,
) -> tuple[int, int, int, int]:
    """최대화 창의 클라이언트 사각형을 프레임 두께만큼 줄인다.

    `WM_NCCALCSIZE`로 프레임을 지우면 **클라이언트가 원래 프레임이 차지하던 자리까지
    가져간다.** 최대화 시 Windows 는 창 사각형을 "작업영역 + 프레임 두께"로 잡으므로,
    그대로 두면 사방 몇 px 이 화면 밖으로 나가 우측 스크롤바가 잘린다.

    `(left, top, right, bottom)`을 받고 같은 형태로 돌려준다.
    """
    left, top, right, bottom = rect
    return (left + frame_x, top + frame_y, right - frame_x, bottom - frame_y)


def autohide_inset(edge: int | None) -> tuple[int, int, int, int]:
    """자동숨김 작업표시줄이 있는 변에서 물러날 양 `(left, top, right, bottom)`.

    `edge`가 `None`(자동숨김 없음)이면 전부 0이다.
    """
    if edge == EDGE_LEFT:
        return (AUTOHIDE_INSET, 0, 0, 0)
    if edge == EDGE_TOP:
        return (0, AUTOHIDE_INSET, 0, 0)
    if edge == EDGE_RIGHT:
        return (0, 0, AUTOHIDE_INSET, 0)
    if edge == EDGE_BOTTOM:
        return (0, 0, 0, AUTOHIDE_INSET)
    return (0, 0, 0, 0)


def signed16(value: int) -> int:
    """`LPARAM`에서 꺼낸 16비트 좌표를 부호 있는 값으로.

    보조 모니터가 주 모니터 **왼쪽/위**에 있으면 화면 좌표가 음수가 된다. 부호를
    풀지 않으면 그 모니터에서 리사이즈 테두리가 엉뚱한 곳에 생긴다.
    """
    value &= 0xFFFF
    return value - 0x10000 if value >= 0x8000 else value
