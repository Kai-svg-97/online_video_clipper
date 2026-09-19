"""프레임리스 설치 가드 — **걸 수 없을 때 조용히 물러나는가**.

여기서 예외가 밖으로 나가면 창이 만들어지지 않아 **앱이 아예 뜨지 않는다.** 그래서
가장 중요한 성질은 "잘 걸린다"가 아니라 **"못 걸어도 앱이 산다"**이다.

특히 `sys.platform`만 보면 부족하다 — 윈도우에서 `QT_QPA_PLATFORM=offscreen`으로
돌 때 `winId()`는 HWND 가 아니고, 그 값을 `SetWindowLongPtr` 에 넘기면 엉뚱한
핸들을 건드린다. CI 가 바로 그 경로로 들어온다.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QMainWindow

from gui import frameless
from gui.frameless import (
    ESCAPE_HATCH_ENV,
    can_install,
    install_frameless,
    safe_dispatch,
)


class TestCanInstall:
    def test_윈도우가_아니면_걸지_않는다(self, monkeypatch):
        monkeypatch.setattr(frameless.sys, "platform", "linux")
        assert can_install() is False

    def test_offscreen_플랫폼에서는_걸지_않는다(self, monkeypatch):
        """winId()가 HWND 가 아니다 — 넘기면 엉뚱한 핸들을 건드린다."""
        monkeypatch.setattr(frameless.sys, "platform", "win32")
        from PyQt6.QtGui import QGuiApplication

        monkeypatch.setattr(
            QGuiApplication, "platformName", staticmethod(lambda: "offscreen")
        )
        assert can_install() is False

    def test_탈출구_환경변수가_있으면_걸지_않는다(self, monkeypatch):
        """사용자 환경에서 도저히 맞지 않을 때 되돌릴 방법이 있어야 한다."""
        monkeypatch.setattr(frameless.sys, "platform", "win32")
        monkeypatch.setenv(ESCAPE_HATCH_ENV, "1")
        assert can_install() is False

    def test_플랫폼_확인이_터져도_False(self, monkeypatch):
        monkeypatch.setattr(frameless.sys, "platform", "win32")
        monkeypatch.delenv(ESCAPE_HATCH_ENV, raising=False)
        from PyQt6.QtGui import QGuiApplication

        def _boom():
            raise RuntimeError("plugin gone")

        monkeypatch.setattr(QGuiApplication, "platformName", staticmethod(_boom))
        assert can_install() is False


class TestInstallNeverRaises:
    def test_걸_수_없으면_None(self, qtbot, monkeypatch):
        monkeypatch.setattr(frameless, "can_install", lambda: False)
        win = QMainWindow()
        qtbot.addWidget(win)
        assert install_frameless(win, object()) is None

    def test_설치_중_예외가_새어_나오지_않는다(self, qtbot, monkeypatch):
        """예외가 나가면 창 생성이 실패해 앱이 아예 뜨지 않는다."""
        monkeypatch.setattr(frameless, "can_install", lambda: True)

        class _Exploding:
            def __init__(self, *a):
                raise OSError("SetWindowLongPtr failed")

        import gui.frameless.win32_hook as hook_mod

        monkeypatch.setattr(hook_mod, "FramelessHook", _Exploding, raising=False)
        win = QMainWindow()
        qtbot.addWidget(win)
        assert install_frameless(win, object()) is None


class TestSafeDispatch:
    """훅이 터져도 창은 살아야 한다.

    이 판단은 `MainWindow.nativeEvent` 밖으로 빼 뒀다 — 거기 두면 창을 통째로
    만들어야만 검증할 수 있고, 정작 지켜야 할 성질은 창과 무관하다.
    """

    def test_훅이_없으면_처리하지_않는다(self):
        assert safe_dispatch(None, b"windows_generic_MSG", 0) == (False, 0, None)

    def test_훅이_처리하면_그_값을_돌려준다(self):
        class _Good:
            def handle(self, *_a):
                return True, 2      # HTCAPTION

        hook = _Good()
        handled, result, keep = safe_dispatch(hook, b"windows_generic_MSG", 0)
        assert (handled, result) == (True, 2)
        assert keep is hook

    def test_훅이_넘기면_Qt에_맡긴다(self):
        class _Passes:
            def handle(self, *_a):
                return False, 0

        hook = _Passes()
        handled, _, keep = safe_dispatch(hook, b"windows_generic_MSG", 0)
        assert handled is False
        assert keep is hook, "처리하지 않은 것과 고장난 것은 다르다"

    def test_훅이_터지면_꺼진다(self):
        """한 번 터진 훅을 계속 부르면 메시지마다 죽는다."""
        class _Bad:
            def handle(self, *_a):
                raise ValueError("bad message")

        handled, _, keep = safe_dispatch(_Bad(), b"windows_generic_MSG", 0)
        assert handled is False
        assert keep is None

    def test_엉뚱한_반환값도_터지지_않는다(self):
        """훅이 튜플이 아닌 것을 돌려줘도 메시지 루프를 죽이면 안 된다."""
        class _Weird:
            def handle(self, *_a):
                return "말이 안 되는 값"

        assert safe_dispatch(_Weird(), b"windows_generic_MSG", 0) == (False, 0, None)


class TestNeverCallsSuperNativeEvent:
    """`super().nativeEvent(...)`를 부르면 **프로세스가 죽는다**.

    PyQt 6.11 에서 파이썬 오버라이드가 그 기본 구현을 호출하면 액세스 위반으로
    앱이 즉시 사라진다(0xC000041D — 창이 만들어지는 바로 그 순간). 화면에는
    아무것도 안 나오고 로그도 없어 원인을 찾기 어렵다.

    `False`를 돌려주는 것과 의미가 같다 — Qt 기본 구현도 "처리하지 않았다"만
    반환한다. 나중에 누가 "기본 구현도 불러야 맞지 않나" 하고 되돌리는 것을 막는다.
    """

    def test_gui_전역에_super_nativeEvent_호출이_없다(self):
        import ast
        from pathlib import Path

        offenders: list[str] = []
        for path in Path("gui").rglob("*.py"):
            if "__pycache__" in str(path):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not isinstance(func, ast.Attribute) or func.attr != "nativeEvent":
                    continue
                inner = func.value
                if isinstance(inner, ast.Call) and getattr(
                    inner.func, "id", ""
                ) == "super":
                    offenders.append(f"{path.as_posix()}:{node.lineno}")

        assert not offenders, (
            "super().nativeEvent() 호출은 PyQt 6.11 에서 프로세스를 죽인다 "
            f"(0xC000041D). `return False, 0` 을 쓸 것: {offenders}"
        )
