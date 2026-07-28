"""사이드바에서 불필요한 아이콘이 제거됐는지 검증한다.

- 상단 ▶ 로고: 장식일 뿐 기능이 없었다.
- 계정 버튼: 클릭 동작이 바로 아래 기어 버튼과 완전히 동일한 중복이었다.
- update_account_status(): _account_btn만 참조하며 호출처가 없는 죽은 코드였다.
"""
from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QStackedWidget

from gui.main_window import _SideBar


class TestSidebarIcons:
    def _bar(self, qapp_instance):
        return _SideBar(QStackedWidget())

    def test_no_play_logo_label(self, qapp_instance):
        bar = self._bar(qapp_instance)
        texts = [w.text() for w in bar.findChildren(QLabel)]
        assert "▶" not in texts

    def test_no_account_button(self, qapp_instance):
        bar = self._bar(qapp_instance)
        assert not hasattr(bar, "_account_btn")

    def test_dead_method_removed(self):
        assert not hasattr(_SideBar, "update_account_status")

    def test_nav_buttons_still_present(self, qapp_instance):
        """제거가 남은 내비게이션을 망가뜨리지 않았는지 — 주 4개 + 설정 1개."""
        bar = self._bar(qapp_instance)
        assert len(bar._buttons) == 5

    def test_settings_button_still_there(self, qapp_instance):
        bar = self._bar(qapp_instance)
        assert bar._settings_btn.toolTip() == "설정"
