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


class TestClickToDownload:
    """발견 즉시 받던 것을 **누를 때** 받도록 바꿨다.

    그래야 진행률 연출이 항상 보이고, 업데이트를 원치 않는 사용자의 회선·디스크를
    쓰지 않는다. 대신 "발견했는데 아무 일도 안 일어난다"로 보이면 안 되므로 배지와
    설정 헤더가 즉시 켜져야 한다.
    """

    def test_발견해도_받지_않는다(self, controller, monkeypatch):
        started: list = []
        monkeypatch.setattr(
            controller, "_start_download", lambda dto: started.append(dto)
        )
        controller._on_found(_dto(), interactive=False)
        assert not started, "누르기 전에 179MB를 받으면 안 된다"

    def test_발견하면_알린다(self, controller):
        seen: list = []
        controller.update_notification.connect(seen.append)
        controller._on_found(_dto("2.0.0"), interactive=False)
        assert [d.version for d in seen] == ["2.0.0"]

    def test_발견은_인터벌을_소진하지_않는다(self, controller, saved):
        """소진하면 앱을 껐다 켰을 때 확인을 건너뛰어 배지가 사라진다 —
        그러면 사용자는 업데이트할 방법을 잃는다."""
        controller._on_found(_dto(), interactive=False)
        assert "last_update_check" not in saved

    def test_확인_종료를_알린다(self, controller):
        """안 그러면 설정 화면에 '확인 중…'이 남는다."""
        finished: list = []
        controller.check_finished.connect(lambda: finished.append(True))
        controller._on_found(_dto(), interactive=False)
        assert finished

    def test_눌러야_받기_시작한다(self, controller, monkeypatch):
        started: list = []
        monkeypatch.setattr(
            controller, "_start_download", lambda dto: started.append(dto)
        )
        controller._on_found(_dto("2.0.0"), interactive=False)
        controller.start_download()
        assert [d.version for d in started] == ["2.0.0"]

    def test_찾은_것이_없으면_눌러도_조용하다(self, controller, monkeypatch):
        started: list = []
        monkeypatch.setattr(
            controller, "_start_download", lambda dto: started.append(dto)
        )
        controller.start_download()
        assert not started


class TestProgressRelay:
    def test_진행률을_밖으로_넘긴다(self, controller):
        """예전에는 워커가 진행률을 내는데 아무도 듣지 않았다."""
        seen: list = []
        controller.download_progress.connect(lambda d, t: seen.append((d, t)))
        controller._on_download_progress(50, 100)
        assert seen == [(50, 100)]

    def test_실패_사유를_밖으로_넘긴다(self, controller):
        """이유를 모르면 사용자가 다시 시도할 근거가 없다."""
        seen: list = []
        controller.download_failed.connect(seen.append)
        controller._on_download_failed("Read timed out.", _dto())
        assert seen == ["Read timed out."]


class TestCheckGuard:
    def test_설치에_들어갔으면_확인하지_않는다(self, controller, monkeypatch):
        ran: list = []
        monkeypatch.setattr(controller, "_run_check", controller._run_check)
        controller._installing = True
        controller.check_started.connect(lambda: ran.append(True))
        controller._run_check(interactive=False)
        assert not ran

    def test_받는_중에는_확인하지_않는다(self, controller):
        """예전에는 확인 워커만 봐서, 받는 도중 1시간 타이머가 돌면 배지 상태가
        진행률에서 '발견'으로 되돌아갔다."""
        class _Busy:
            @staticmethod
            def isRunning():
                return True

        controller._dl_worker = _Busy()
        ran: list = []
        controller.check_started.connect(lambda: ran.append(True))
        controller._run_check(interactive=False)
        assert not ran


class TestInstallAnnouncement:
    def test_설치_착수를_먼저_알린다(self, controller, monkeypatch, tmp_path):
        """말없이 창이 닫히면 사용자는 앱이 죽은 줄 안다."""
        marker = tmp_path / "pending.txt"
        marker.write_text("x", encoding="utf-8")
        monkeypatch.setattr(ucmod, "pending_marker_path", lambda: marker)

        order: list = []
        controller.install_started.connect(lambda: order.append("announced"))
        # `QApplication.instance` 자체를 갈아끼우면 pytest-qt 의 정리까지 망가진다
        # (그쪽도 같은 것을 부른다). 컨트롤러 모듈이 들고 있는 이름만 바꾼다.
        monkeypatch.setattr(ucmod, "QApplication", _FakeApp(order))

        controller.install_now()
        assert order == ["announced", "quit"], "안내보다 종료가 먼저면 아무도 못 본다"

    def test_아직_안_받았으면_받기부터_한다(self, controller, monkeypatch, tmp_path):
        """마커가 없는데 종료해 버리면 아무 일도 일어나지 않는다."""
        monkeypatch.setattr(
            ucmod, "pending_marker_path", lambda: tmp_path / "없음.txt"
        )
        started: list = []
        monkeypatch.setattr(
            controller, "_start_download", lambda dto: started.append(dto)
        )
        controller._last_dto = _dto("2.0.0")
        controller.install_now()
        assert [d.version for d in started] == ["2.0.0"]


class _FakeApp:
    """`ucmod.QApplication` 자리에 끼우는 가짜 — quit 순서만 기록한다."""

    def __init__(self, log: list) -> None:
        self._log = log

    def instance(self):
        return self

    def quit(self) -> None:
        self._log.append("quit")
