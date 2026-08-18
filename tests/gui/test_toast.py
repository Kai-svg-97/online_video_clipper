"""토스트 알림 — 쌓임·자동 소멸·클릭 닫기 규칙을 고정한다.

완료 알림이 상태바 한 줄뿐이라 놓치기 쉬웠다. 다만 알림이 화면을 가리면 더 나쁘므로
개수 상한과 자동 소멸이 계약의 일부다.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from gui.toast import KIND_ERROR, KIND_SUCCESS, _manager_for, show_toast


def _gone(toast) -> bool:
    """사라졌는지 — 정리가 끝나면 C++ 객체가 먼저 삭제될 수 있다(그것도 '사라짐')."""
    try:
        return toast.isHidden()
    except RuntimeError:
        return True


def _host(qtbot) -> QWidget:
    host = QWidget()
    host.resize(900, 600)
    qtbot.addWidget(host)
    host.show()
    qtbot.waitExposed(host)
    return host


class TestShowToast:
    def test_알림이_창_안에_뜬다(self, qtbot):
        host = _host(qtbot)

        toast = show_toast(host, "등록 완료", KIND_SUCCESS)

        assert toast is not None
        assert toast.parentWidget() is host
        assert not toast.isHidden()

    def test_오른쪽_아래에_붙는다(self, qtbot):
        host = _host(qtbot)

        toast = show_toast(host, "등록 완료")

        assert toast.geometry().right() < host.width()
        assert toast.geometry().right() > host.width() // 2      # 오른쪽
        assert toast.geometry().bottom() > host.height() // 2    # 아래

    def test_여러_개는_위로_쌓인다(self, qtbot):
        host = _host(qtbot)

        first = show_toast(host, "첫 번째")
        second = show_toast(host, "두 번째")

        assert second.geometry().bottom() > first.geometry().bottom()

    def test_개수_상한을_넘으면_오래된_것이_사라진다(self, qtbot):
        host = _host(qtbot)

        for i in range(6):
            show_toast(host, f"알림 {i}")

        manager = _manager_for(host, create=False)
        # 사라지는 중인 것은 목록에서 즉시 빠진다 — 상한이 곧 화면에 쌓이는 최대치다.
        assert len(manager.visible_toasts()) == 4

    def test_빈_문자열은_띄우지_않는다(self, qtbot):
        host = _host(qtbot)

        assert show_toast(host, "") is None

    def test_부모가_없으면_아무_일도_하지_않는다(self):
        assert show_toast(None, "무시") is None


class TestDismiss:
    def test_클릭하면_사라진다(self, qtbot):
        host = _host(qtbot)
        toast = show_toast(host, "읽었음")

        toast.dismiss()
        qtbot.waitUntil(lambda: _gone(toast), timeout=2000)

    def test_시간이_지나면_스스로_사라진다(self, qtbot):
        host = _host(qtbot)
        toast = show_toast(host, "잠깐만", KIND_ERROR, msec=600)

        qtbot.waitUntil(lambda: _gone(toast), timeout=3000)

    def test_두_번_닫아도_안전하다(self, qtbot):
        host = _host(qtbot)
        toast = show_toast(host, "두 번")

        toast.dismiss()
        toast.dismiss()      # 사라지는 중 다시 호출 — 예외 없이 무시

        qtbot.waitUntil(lambda: _gone(toast), timeout=2000)


class TestFollowsWindow:
    def test_창_크기가_바뀌면_따라간다(self, qtbot):
        host = _host(qtbot)
        toast = show_toast(host, "따라와")
        before = toast.geometry().right()

        host.resize(1200, 700)
        qtbot.wait(50)

        assert toast.geometry().right() != before
        assert toast.geometry().right() < host.width()
