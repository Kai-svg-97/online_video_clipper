"""Windows 네이티브 프레임을 지우되 **창다움은 남긴다**.

단순히 `Qt.FramelessWindowHint`만 주면 Aero Snap·창 그림자·8방향 리사이즈·최대화
애니메이션·`Win+화살표`·시스템 메뉴가 **전부 사라진다**. 특히 "최대화 상태에서
드래그하면 복원되며 커서를 따라오는" 동작은 DPI가 다른 모니터 사이에서 수식으로
맞추기가 사실상 불가능하다.

그래서 창 스타일에 `WS_THICKFRAME | WS_CAPTION`을 **남겨 둔 채** `WM_NCCALCSIZE`로
프레임이 차지하는 영역만 0으로 만든다. 그러면 위 동작은 전부 OS 기본으로 들어오고,
우리가 할 일은 `WM_NCHITTEST`에서 "여기는 제목 표시줄"이라고 답해 주는 것뿐이다 —
드래그 코드를 한 줄도 쓰지 않는다.

## 절대 예외를 밖으로 내지 않는다

`nativeEvent`는 **메시지 루프 안**이다. 여기서 예외가 새면 `paintEvent`와 같은 부류로
진단 불가능하게 죽는다. 모든 처리를 감싸고, 한 번이라도 실패하면 훅을 꺼서 네이티브
동작으로 떨어진다 — 창이 조금 이상해지는 편이 앱이 사라지는 것보다 낫다.

## 의존성

`ctypes`(표준 라이브러리)만 쓴다. pywin32를 들이면 PyInstaller hidden-import 문제가
따라온다(`bootstrap/runtime.py`도 같은 이유로 `ctypes.windll`을 쓴다).
"""

from __future__ import annotations

import logging
from ctypes import (
    POINTER,
    Structure,
    byref,
    c_int,
    c_uint,
    c_void_p,
    cast,
    sizeof,
    windll,
)
from ctypes.wintypes import DWORD, HWND, LONG, LPARAM, POINT, RECT, UINT, WPARAM

from gui.frameless.geometry import (
    ACT_CLICK,
    ACT_HOVER_OFF,
    ACT_HOVER_ON,
    ACT_NONE,
    ACT_SWALLOW,
    HTCAPTION,
    HTCLIENT,
    HTMAXBUTTON,
    HTNOWHERE,
    WM_NCLBUTTONDOWN,
    WM_NCLBUTTONUP,
    WM_NCMOUSELEAVE,
    WM_NCMOUSEMOVE,
    autohide_inset,
    deflate_maximized,
    edge_hit,
    max_button_action,
    signed16,
)

logger = logging.getLogger(__name__)

# ── Win32 상수 ───────────────────────────────────────────────────────
GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_SYSMENU = 0x00080000

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020

WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084

SM_CXSIZEFRAME = 32
SM_CYSIZEFRAME = 33
SM_CXPADDEDBORDER = 92

SW_SHOWMAXIMIZED = 3
MONITOR_DEFAULTTONEAREST = 2

ABM_GETSTATE = 0x0004
ABM_GETAUTOHIDEBAREX = 0x000B
ABS_AUTOHIDE = 0x0001

DWMWA_NCRENDERING_POLICY = 2
DWMNCRP_ENABLED = 2


class MARGINS(Structure):
    _fields_ = [
        ("cxLeftWidth", c_int),
        ("cxRightWidth", c_int),
        ("cyTopHeight", c_int),
        ("cyBottomHeight", c_int),
    ]


class NCCALCSIZE_PARAMS(Structure):
    _fields_ = [("rgrc", RECT * 3), ("lppos", c_void_p)]


class WINDOWPLACEMENT(Structure):
    _fields_ = [
        ("length", UINT),
        ("flags", UINT),
        ("showCmd", UINT),
        ("ptMinPosition", POINT),
        ("ptMaxPosition", POINT),
        ("rcNormalPosition", RECT),
    ]


class MONITORINFO(Structure):
    _fields_ = [
        ("cbSize", DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", DWORD),
    ]


class APPBARDATA(Structure):
    _fields_ = [
        ("cbSize", DWORD),
        ("hWnd", HWND),
        ("uCallbackMessage", UINT),
        ("uEdge", UINT),
        ("rc", RECT),
        ("lParam", LPARAM),
    ]


class TRACKMOUSEEVENT(Structure):
    _fields_ = [
        ("cbSize", DWORD),
        ("dwFlags", DWORD),
        ("hwndTrack", HWND),
        ("dwHoverTime", DWORD),
    ]


class MSG(Structure):
    _fields_ = [
        ("hWnd", HWND),
        ("message", UINT),
        ("wParam", WPARAM),
        ("lParam", LPARAM),
        ("time", DWORD),
        ("pt", POINT),
    ]


_NATIVE_EVENT_TYPES = (b"windows_generic_MSG", b"windows_dispatcher_MSG")

TME_LEAVE = 0x0000_0002
TME_NONCLIENT = 0x0000_0010

# 우리가 가로채는 비클라이언트 마우스 메시지.
_NC_MOUSE_MESSAGES = frozenset(
    {WM_NCMOUSEMOVE, WM_NCLBUTTONDOWN, WM_NCLBUTTONUP, WM_NCMOUSELEAVE}
)


def _frame_thickness(hwnd: int, *, horizontal: bool) -> int:
    """리사이즈 프레임 두께(물리 픽셀) — **DPI를 반영한다**.

    100%와 150% 모니터에서 값이 다르다. DPI를 무시하면 모니터를 옮긴 뒤 최대화했을
    때 사방이 몇 px 어긋난 채 남는다.
    """
    index = SM_CXSIZEFRAME if horizontal else SM_CYSIZEFRAME
    try:
        dpi = windll.user32.GetDpiForWindow(hwnd)
        if dpi:
            frame = windll.user32.GetSystemMetricsForDpi(index, dpi)
            pad = windll.user32.GetSystemMetricsForDpi(SM_CXPADDEDBORDER, dpi)
            return int(frame) + int(pad)
    except (AttributeError, OSError):
        # Windows 10 1607 미만 — 시스템 전역 값으로 떨어진다.
        logger.debug("DPI별 시스템 메트릭을 쓸 수 없다 — 전역 값 사용", exc_info=True)
    frame = windll.user32.GetSystemMetrics(index)
    pad = windll.user32.GetSystemMetrics(SM_CXPADDEDBORDER)
    return int(frame) + int(pad)


def _autohide_edge(hwnd: int) -> int | None:
    """이 창이 있는 모니터에서 자동숨김 작업표시줄이 붙은 변(없으면 None).

    `Shell_TrayWnd`를 찾아 모니터 사각형과 비교하는 간이 방법도 있지만, 보조 모니터
    작업표시줄(`Shell_SecondaryTrayWnd`)에서 틀린다. 셸에 직접 묻는다.
    """
    data = APPBARDATA()
    data.cbSize = sizeof(APPBARDATA)
    state = windll.shell32.SHAppBarMessage(ABM_GETSTATE, byref(data))
    if not (int(state) & ABS_AUTOHIDE):
        return None

    info = MONITORINFO()
    info.cbSize = sizeof(MONITORINFO)
    monitor = windll.user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    if not monitor or not windll.user32.GetMonitorInfoW(monitor, byref(info)):
        return None

    for edge in (3, 1, 0, 2):   # 아래·위·왼쪽·오른쪽 순(흔한 순서)
        data.cbSize = sizeof(APPBARDATA)
        data.hWnd = 0
        data.uEdge = edge
        data.rc = info.rcMonitor
        if windll.shell32.SHAppBarMessage(ABM_GETAUTOHIDEBAREX, byref(data)):
            return edge
    return None


class FramelessHook:
    """창 하나에 붙어 네이티브 프레임만 지운다."""

    def __init__(self, window, title_bar) -> None:
        self._window = window
        self._title_bar = title_bar
        self._hwnd = 0

    # ── 설치 ──────────────────────────────────────────────────────
    def install(self) -> None:
        """스타일을 패치하고 그림자를 되살린다. 실패하면 예외를 올린다(호출부가 잡는다)."""
        self._hwnd = int(self._window.winId())

        # `or 0` — 스타일이 0이면 restype(c_void_p)이 None 을 돌려주고,
        # 그대로 `|` 를 걸면 TypeError 가 난다.
        style = windll.user32.GetWindowLongPtrW(self._hwnd, GWL_STYLE) or 0
        # `WS_THICKFRAME`이 스냅·리사이즈·최대화 애니메이션의 실제 주체다.
        # `WS_CAPTION`은 최대화 애니메이션과 DWM 그림자에 필요하다 — 프레임 자체는
        # 아래 `WM_NCCALCSIZE`에서 지운다.
        windll.user32.SetWindowLongPtrW(
            self._hwnd,
            GWL_STYLE,
            style
            | WS_THICKFRAME
            | WS_CAPTION
            | WS_MINIMIZEBOX
            | WS_MAXIMIZEBOX
            | WS_SYSMENU,
        )

        # 그림자. DWM 이 꺼져 있으면(원격 데스크톱 등) 실패하지만 기능만 빠진다.
        try:
            policy = c_int(DWMNCRP_ENABLED)
            windll.dwmapi.DwmSetWindowAttribute(
                self._hwnd, DWMWA_NCRENDERING_POLICY, byref(policy), sizeof(policy)
            )
            windll.dwmapi.DwmExtendFrameIntoClientArea(
                self._hwnd, byref(MARGINS(1, 1, 1, 1))
            )
        except OSError:
            logger.debug("DWM 그림자를 걸지 못했다 — 모양만 다르다", exc_info=True)

        self.reapply()

        handle = self._window.windowHandle()
        if handle is not None:
            # 100% → 150% 모니터로 옮기면 프레임 두께가 바뀐다. 다시 계산시키지
            # 않으면 최대화 시 사방이 어긋난 채 남는다.
            handle.screenChanged.connect(self._on_screen_changed)

    def reapply(self) -> None:
        """`WM_NCCALCSIZE`를 다시 돌린다."""
        windll.user32.SetWindowPos(
            self._hwnd, 0, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
        )

    def _on_screen_changed(self, _screen) -> None:
        try:
            self.reapply()
        except OSError:
            logger.exception("모니터 변경 후 프레임 재계산 실패")

    # ── 메시지 처리 ───────────────────────────────────────────────
    def handle(self, event_type, message) -> tuple[bool, int]:
        """`(처리했는가, 반환값)`. 처리하지 않으면 Qt 기본 동작으로 넘어간다."""
        if bytes(event_type) not in _NATIVE_EVENT_TYPES:
            return False, 0
        msg = MSG.from_address(int(message))
        if msg.hWnd != self._hwnd:
            return False, 0
        if msg.message == WM_NCCALCSIZE:
            return self._on_nccalcsize(msg)
        if msg.message == WM_NCHITTEST:
            return self._on_nchittest(msg)
        if msg.message in _NC_MOUSE_MESSAGES:
            return self._on_nc_mouse(msg)
        return False, 0

    def _on_nccalcsize(self, msg) -> tuple[bool, int]:
        """프레임이 차지하던 영역을 클라이언트로 편입한다(= 프레임이 사라진다)."""
        if msg.wParam:
            params = cast(msg.lParam, POINTER(NCCALCSIZE_PARAMS)).contents
            rect = params.rgrc[0]
        else:
            rect = cast(msg.lParam, POINTER(RECT)).contents

        maximized = self._is_maximized()
        fullscreen = self._is_fullscreen()

        if maximized and not fullscreen:
            # 최대화 시 Windows 는 창 사각형을 "작업영역 + 프레임 두께"로 잡는다.
            # 프레임을 지우면 클라이언트가 그 전체를 가져가 사방이 화면 밖으로
            # 나간다(우측 스크롤바가 잘린다). 프레임 두께만큼 되돌린다.
            #
            # **전체화면에는 적용하지 않는다** — 사방에 검은 띠가 남는다.
            left, top, right, bottom = deflate_maximized(
                (rect.left, rect.top, rect.right, rect.bottom),
                _frame_thickness(self._hwnd, horizontal=True),
                _frame_thickness(self._hwnd, horizontal=False),
            )
            rect.left, rect.top, rect.right, rect.bottom = left, top, right, bottom

        if maximized or fullscreen:
            # 자동숨김 작업표시줄이 있는 변을 100% 덮으면 마우스를 대도 표시줄이
            # 나오지 않는다. 몇 px 만 양보하면 그 동작이 살아난다.
            dl, dt, dr, db = autohide_inset(_autohide_edge(self._hwnd))
            rect.left += dl
            rect.top += dt
            rect.right -= dr
            rect.bottom -= db

        return True, 0

    def _on_nchittest(self, msg) -> tuple[bool, int]:
        """리사이즈 테두리와 제목 표시줄을 알려 준다(이동·스냅은 OS가 맡는다)."""
        x = signed16(msg.lParam & 0xFFFF)
        y = signed16((msg.lParam >> 16) & 0xFFFF)

        win_rect = RECT()
        if not windll.user32.GetWindowRect(self._hwnd, byref(win_rect)):
            return False, 0
        px = x - win_rect.left
        py = y - win_rect.top
        width = win_rect.right - win_rect.left
        height = win_rect.bottom - win_rect.top

        if not self._is_maximized():
            border = _frame_thickness(self._hwnd, horizontal=True)
            code = edge_hit(px, py, width, height, border)
            if code != HTNOWHERE:
                return True, code

        # 논리 좌표로 바꿔서 위젯에 묻는다 — 125%·150% 배율에서 물리 픽셀을 그대로
        # 넘기면 버튼 판정이 어긋난다.
        ratio = self._window.devicePixelRatioF() or 1.0
        code = self._title_bar.hit_test(_QPoint(int(px / ratio), int(py / ratio)))
        if code == HTMAXBUTTON:
            # Windows 11 이 여기에 분할 배치(스냅 레이아웃) 메뉴를 붙인다. 대신
            # 그 영역의 마우스를 OS 가 가져가므로 아래 `_on_nc_mouse`가 호버·클릭을
            # 되돌려 준다 — 그것이 없으면 스냅 메뉴는 뜨는데 버튼이 먹통이 된다.
            return True, HTMAXBUTTON
        if code == HTCAPTION:
            return True, HTCAPTION
        return False, HTCLIENT

    def _on_nc_mouse(self, msg) -> tuple[bool, int]:
        """최대화 버튼 위의 비클라이언트 마우스 — 호버·클릭을 Qt 쪽으로 되돌린다."""
        action = max_button_action(msg.message, int(msg.wParam))
        if action == ACT_NONE:
            return False, 0

        if action == ACT_HOVER_ON:
            self._title_bar.set_max_hover(True)
            self._track_nc_leave()
            # 삼키지 않는다 — 캡션 위 움직임은 OS 도 봐야 한다(스냅 메뉴 타이밍 등).
            return False, 0
        if action == ACT_HOVER_OFF:
            self._title_bar.set_max_hover(False)
            return False, 0
        if action == ACT_SWALLOW:
            return True, 0
        if action == ACT_CLICK:
            # 뗄 때 토글한다 — 실제 버튼처럼 누른 뒤 밖에서 떼면 취소된다.
            self._title_bar.set_max_hover(False)
            self._title_bar.click_max()
            return True, 0
        # 모르는 지시는 삼키지 않는다 — 삼키면 그 메시지가 필요한 쪽이 조용히 죽는다.
        return False, 0

    def _track_nc_leave(self) -> None:
        """커서가 비클라이언트 영역을 벗어나면 알려 달라고 등록한다.

        등록하지 않으면 `WM_NCMOUSELEAVE`가 오지 않아, 버튼 밖으로 나가도 **호버가
        켜진 채 남는다**.
        """
        track = TRACKMOUSEEVENT()
        track.cbSize = sizeof(TRACKMOUSEEVENT)
        track.dwFlags = TME_LEAVE | TME_NONCLIENT
        track.hwndTrack = self._hwnd
        track.dwHoverTime = 0
        windll.user32.TrackMouseEvent(byref(track))

    # ── 창 상태 ───────────────────────────────────────────────────
    def _is_maximized(self) -> bool:
        """**Qt의 `isMaximized()`를 믿지 않는다** — 메시지를 처리하는 시점에는
        Qt 상태가 아직 갱신되지 않았을 수 있다. OS 에 직접 묻는다."""
        placement = WINDOWPLACEMENT()
        placement.length = sizeof(WINDOWPLACEMENT)
        if not windll.user32.GetWindowPlacement(self._hwnd, byref(placement)):
            return False
        return placement.showCmd == SW_SHOWMAXIMIZED

    def _is_fullscreen(self) -> bool:
        """창이 모니터를 통째로 덮고 있는가(= 전체화면)."""
        win_rect = RECT()
        if not windll.user32.GetWindowRect(self._hwnd, byref(win_rect)):
            return False
        info = MONITORINFO()
        info.cbSize = sizeof(MONITORINFO)
        monitor = windll.user32.MonitorFromWindow(self._hwnd, MONITOR_DEFAULTTONEAREST)
        if not monitor or not windll.user32.GetMonitorInfoW(monitor, byref(info)):
            return False
        mon = info.rcMonitor
        return (
            win_rect.left <= mon.left
            and win_rect.top <= mon.top
            and win_rect.right >= mon.right
            and win_rect.bottom >= mon.bottom
        )


def _QPoint(x: int, y: int):
    """QPoint 를 늦게 임포트한다 — 이 모듈이 Qt 위젯 계층에 묶이지 않게."""
    from PyQt6.QtCore import QPoint  # noqa: PLC0415

    return QPoint(x, y)


# ctypes 시그니처 — 64비트에서 포인터가 int 로 잘리는 것을 막는다.
windll.user32.GetWindowLongPtrW.restype = c_void_p
windll.user32.GetWindowLongPtrW.argtypes = [HWND, c_int]
windll.user32.SetWindowLongPtrW.restype = c_void_p
windll.user32.SetWindowLongPtrW.argtypes = [HWND, c_int, c_void_p]
windll.user32.MonitorFromWindow.restype = c_void_p
windll.user32.MonitorFromWindow.argtypes = [HWND, DWORD]
windll.user32.GetMonitorInfoW.argtypes = [c_void_p, POINTER(MONITORINFO)]
windll.user32.GetSystemMetrics.restype = c_int
windll.user32.GetSystemMetrics.argtypes = [c_int]
windll.user32.SetWindowPos.argtypes = [
    HWND, c_void_p, c_int, c_int, c_int, c_int, c_uint,
]
windll.user32.GetWindowRect.argtypes = [HWND, POINTER(RECT)]
windll.user32.GetWindowPlacement.argtypes = [HWND, POINTER(WINDOWPLACEMENT)]
windll.user32.TrackMouseEvent.argtypes = [POINTER(TRACKMOUSEEVENT)]
windll.shell32.SHAppBarMessage.restype = LONG
windll.shell32.SHAppBarMessage.argtypes = [DWORD, POINTER(APPBARDATA)]
