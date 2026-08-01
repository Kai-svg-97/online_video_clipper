"""업데이트 확인 인터벌과 설정 화면 상태 전이를 검증한다.

회귀 배경: 다운로드가 실패해도 확인 시작 시점에 `last_update_check` 를 기록해
다음 1시간 동안 재확인이 막혔다. 게다가 실패 시에는 기어의 빨간 점만 켜지고
설정 화면은 그대로여서, 사용자가 업데이트를 진행할 방법이 화면에 없었다.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import QWidget

from application.updater.dtos import UpdateDTO
from gui.updater import update_controller as ucmod
from gui.updater.update_controller import UpdateController


def _dto(version: str = "1.11.0") -> UpdateDTO:
    return UpdateDTO(
        version=version,
        asset_name="YouTubeContentManager-setup.exe",
        download_url="https://objects.githubusercontent.com/setup.exe",
        size_bytes=1234,
        sha256="a" * 64,
        release_notes="",
    )


@pytest.fixture
def saved(monkeypatch):
    """config.settings 를 가짜로 대체하고 저장된 설정을 기록한다."""
    import config.settings as real

    store: dict[str, object] = {}
    monkeypatch.setattr(real, "save_setting", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(real, "SNOOZED_UPDATE_VERSION", "", raising=False)
    monkeypatch.setattr(real, "AUTO_UPDATE_CHECK", True, raising=False)
    monkeypatch.setattr(real, "LAST_UPDATE_CHECK", 0, raising=False)
    return store


@pytest.fixture
def controller(qtbot, saved):
    parent = QWidget()
    qtbot.addWidget(parent)
    ctrl = UpdateController(MagicMock(), MagicMock(), parent)
    saved.clear()   # __init__ 의 스누즈 초기화 기록은 제외
    return ctrl


class TestCheckInterval:
    def test_download_failure_does_not_consume_interval(self, controller, saved):
        """실패했는데 인터벌을 소진하면 1시간 동안 재시도가 막힌다."""
        controller._on_download_failed("Read timed out.", _dto())
        assert "last_update_check" not in saved

    def test_check_failure_does_not_consume_interval(self, controller, saved):
        controller._on_failed("network down", interactive=False)
        assert "last_update_check" not in saved

    def test_success_consumes_interval(self, controller, saved, monkeypatch):
        monkeypatch.setattr(ucmod, "write_pending_update", lambda _p: True)
        controller._on_download_done("C:/tmp/setup.exe", _dto())
        assert "last_update_check" in saved

    def test_up_to_date_consumes_interval(self, controller, saved):
        controller._on_none_found(interactive=False)
        assert "last_update_check" in saved

    def test_interval_gate_uses_saved_timestamp(self, controller, monkeypatch):
        import config.settings as real

        monkeypatch.setattr(real, "LAST_UPDATE_CHECK", 0, raising=False)
        assert controller._should_check() is True

        monkeypatch.setattr(ucmod.time, "time", lambda: 1_000.0)
        monkeypatch.setattr(real, "LAST_UPDATE_CHECK", 999.0, raising=False)
        assert controller._should_check() is False, "방금 확인했으면 건너뛴다"


class TestFailureSignals:
    def test_failure_emits_notification_with_dto(self, controller, qtbot):
        seen: list = []
        controller.update_notification.connect(seen.append)
        controller._on_download_failed("boom", _dto("2.0.0"))
        assert [d.version for d in seen] == ["2.0.0"]

    def test_failure_ends_busy_state(self, controller):
        finished: list = []
        controller.check_finished.connect(lambda: finished.append(True))
        controller._on_download_failed("boom", _dto())
        assert finished, "확인 종료 신호가 없으면 '확인 중…' 표시가 남는다"


class TestSettingsHeaderStates:
    @pytest.fixture
    def panel(self, qtbot, qapp_instance):
        from gui.panels.settings_panel import SettingsPanel

        p = SettingsPanel()
        qtbot.addWidget(p)
        return p

    def test_download_failed_state_offers_install_button(self, panel):
        """빨간 점만 뜨고 설정 화면엔 아무것도 없던 상태를 막는다."""
        # 패널이 화면에 붙기 전이라 isVisible() 대신 명시적 숨김 상태로 판정한다.
        assert panel._upd_install_btn.isHidden(), "초기에는 설치 버튼이 없어야 한다"
        panel.set_update_available(_dto("1.11.0"))
        assert not panel._upd_install_btn.isHidden()
        assert "1.11.0" in panel._upd_status_lbl.text()

    def test_ready_state_shows_install_now(self, panel):
        panel.set_update_ready(_dto("1.11.0"))
        assert not panel._upd_install_btn.isHidden()
        assert panel._upd_install_btn.text() == "지금 설치"

    def test_install_button_emits_with_dto(self, panel):
        seen: list = []
        panel.install_update_requested.connect(seen.append)
        panel.set_update_available(_dto("1.11.0"))
        panel._upd_install_btn.click()
        assert [d.version for d in seen] == ["1.11.0"]

    def test_manual_check_button_is_wired(self, panel):
        """확인 버튼이 없으면 인터벌에 걸린 사용자는 재시도할 방법이 없다."""
        seen: list = []
        panel.check_update_requested.connect(lambda: seen.append(True))
        panel._upd_check_btn.click()
        assert seen

    def test_busy_disables_check_button(self, panel):
        panel.set_update_busy(True)
        assert not panel._upd_check_btn.isEnabled()
        assert "확인" in panel._upd_status_lbl.text()
        panel.set_update_busy(False)
        assert panel._upd_check_btn.isEnabled()

    def test_busy_reset_keeps_found_state(self, panel):
        """확인이 끝나도 이미 찾은 업데이트 표시를 지우면 안 된다."""
        panel.set_update_available(_dto("1.11.0"))
        panel.set_update_busy(False)
        assert "1.11.0" in panel._upd_status_lbl.text()
