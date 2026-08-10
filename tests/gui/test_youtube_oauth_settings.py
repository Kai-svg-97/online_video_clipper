"""설정 패널 — Google 계정 연결(단일 버튼) UX 테스트.

Client ID/Secret 입력 필드가 완전히 사라지고, 번들된 Desktop OAuth 클라이언트가
없으면 연결 버튼이 비활성화되며, 무인자 run_auth_flow()로 연결이 이루어지는지
검증한다.
"""
from __future__ import annotations


class FakeOAuth:
    def __init__(self, configured: bool = True, authenticated: bool = False) -> None:
        self.configured = configured
        self.authenticated = authenticated
        self.run_calls = 0

    def has_client_config(self) -> bool:
        return self.configured

    def is_authenticated(self) -> bool:
        return self.authenticated

    def get_channel_name(self) -> str | None:
        return "Synthetic Channel" if self.authenticated else None

    def run_auth_flow(self):
        self.run_calls += 1
        self.authenticated = True
        return object()

    def clear(self) -> None:
        self.authenticated = False


class FailingFakeOAuth(FakeOAuth):
    def run_auth_flow(self):
        self.run_calls += 1
        raise RuntimeError("synthetic auth failure")


def test_youtube_oauth_uses_single_google_connect_button(qtbot):
    from gui.panels.settings_panel import SettingsPanel

    panel = SettingsPanel(get_tags_fn=lambda: [], yt_oauth=FakeOAuth())
    qtbot.addWidget(panel)
    assert panel._yt_auth_btn.text() == "Google 계정으로 연결"
    assert not hasattr(panel, "_yt_client_id_edit")
    assert not hasattr(panel, "_yt_client_secret_edit")


def test_missing_bundled_client_disables_connect(qtbot):
    from gui.panels.settings_panel import SettingsPanel

    panel = SettingsPanel(get_tags_fn=lambda: [], yt_oauth=FakeOAuth(configured=False))
    qtbot.addWidget(panel)
    assert not panel._yt_auth_btn.isEnabled()
    assert "배포자" in panel._yt_status_lbl.text()


def test_connected_state_shows_channel_name_and_button_label(qtbot):
    from gui.panels.settings_panel import SettingsPanel

    panel = SettingsPanel(
        get_tags_fn=lambda: [], yt_oauth=FakeOAuth(authenticated=True)
    )
    qtbot.addWidget(panel)
    assert "Synthetic Channel" in panel._yt_status_lbl.text()
    assert panel._yt_auth_btn.text() == "Google 계정 다시 연결"


def test_click_connect_runs_auth_flow_with_no_credentials_and_shows_restart_notice(qtbot):
    from gui.panels.settings_panel import SettingsPanel

    fake = FakeOAuth()
    panel = SettingsPanel(get_tags_fn=lambda: [], yt_oauth=fake)
    qtbot.addWidget(panel)

    panel._yt_auth_btn.click()
    assert panel._yt_auth_btn.text() == "연결 중…"
    assert not panel._yt_auth_btn.isEnabled()

    qtbot.waitUntil(lambda: fake.run_calls == 1, timeout=5000)
    qtbot.waitUntil(lambda: panel._yt_auth_worker is None, timeout=5000)

    assert panel._yt_auth_btn.isEnabled()
    assert "연결됨" in panel._yt_status_lbl.text()
    assert "Synthetic Channel" in panel._yt_status_lbl.text()
    assert "다시 시작" in panel._yt_status_lbl.text()


def test_click_connect_failure_shows_error_and_reenables_button(qtbot):
    from gui.panels.settings_panel import SettingsPanel

    fake = FailingFakeOAuth()
    panel = SettingsPanel(get_tags_fn=lambda: [], yt_oauth=fake)
    qtbot.addWidget(panel)

    panel._yt_auth_btn.click()
    qtbot.waitUntil(lambda: fake.run_calls == 1, timeout=5000)
    qtbot.waitUntil(lambda: panel._yt_auth_worker is None, timeout=5000)

    assert panel._yt_auth_btn.isEnabled()
    assert panel._yt_auth_btn.text() == "Google 계정으로 연결"
    assert "synthetic auth failure" in panel._yt_status_lbl.text()


def test_disconnect_clears_adapter_and_refreshes_status(qtbot):
    from gui.panels.settings_panel import SettingsPanel

    fake = FakeOAuth(authenticated=True)
    panel = SettingsPanel(get_tags_fn=lambda: [], yt_oauth=fake)
    qtbot.addWidget(panel)
    assert "연결됨" in panel._yt_status_lbl.text()

    panel._yt_disconnect_btn.click()

    assert fake.authenticated is False
    assert "연결됨" not in panel._yt_status_lbl.text()
    assert panel._yt_auth_btn.text() == "Google 계정으로 연결"
