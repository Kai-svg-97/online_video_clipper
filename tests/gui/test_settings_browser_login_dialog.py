"""설정 화면 — 브라우저 열어서 로그인 버튼.

"쿠키를 왜 찾아야 하냐, 그냥 브라우저를 띄워서 로그인시키면 안 되냐"는 사용자
질문에 따라, 이미 구현돼 있었지만 어디에서도 열리지 않던 `YouTubeAuthDialog`
(Playwright로 자체 브라우저 창을 띄워 로그인 후 쿠키를 직접 캡처)를 설정 화면에
연결한다. 이 방식은 사용자의 기존 브라우저 쿠키 DB를 건드리지 않아 Chrome
잠금·App-Bound Encryption 문제를 완전히 피한다.
"""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal


class _FakeAuthDialog(QObject):
    auth_changed = pyqtSignal()
    instances: list["_FakeAuthDialog"] = []

    def __init__(self, auth_service, parent=None):
        super().__init__(parent)
        self.auth_service = auth_service
        self.exec_called = False
        _FakeAuthDialog.instances.append(self)

    def exec(self):
        self.exec_called = True


class TestBrowserLoginButton:
    def test_로그인_버튼이_있다(self, qtbot):
        from gui.panels.settings_panel import SettingsPanel

        panel = SettingsPanel(get_tags_fn=lambda: [])
        qtbot.addWidget(panel)

        assert panel._browser_login_btn is not None

    def test_클릭시_다이얼로그를_열고_로그인_후_상태를_갱신한다(self, qtbot, monkeypatch):
        import gui.dialogs.youtube_auth_dialog as yad
        import gui.panels.settings_panel as sp
        from gui.panels.settings_panel import SettingsPanel

        _FakeAuthDialog.instances.clear()
        monkeypatch.setattr(yad, "YouTubeAuthDialog", _FakeAuthDialog)

        panel = SettingsPanel(get_tags_fn=lambda: [])
        qtbot.addWidget(panel)

        refreshed = []
        monkeypatch.setattr(
            sp.SettingsPanel, "_refresh_feed_auth_ui", lambda self: refreshed.append(True)
        )

        panel._browser_login_btn.click()

        assert len(_FakeAuthDialog.instances) == 1
        dialog = _FakeAuthDialog.instances[0]
        assert dialog.exec_called

        dialog.auth_changed.emit()
        assert refreshed == [True]


class TestRealDialogConstructs:
    """실제 YouTubeAuthDialog가 크래시 없이 뜨는지 검증 — 지금까지 앱 어디에서도
    열리지 않아 한 번도 실행된 적 없는 코드였다."""

    def test_실제_다이얼로그가_예외없이_생성된다(self, qtbot, monkeypatch):
        import config.settings as s
        import gui.dialogs.youtube_auth_dialog as yad
        from infrastructure.auth.youtube_auth import YouTubeAuthService

        # 실사용 config.yaml에 저장된 프로필이 있으면 백그라운드 상태 확인
        # 워커가 실제 네트워크 요청(yt-dlp)을 시도한다 — 테스트에서는 비워둔다.
        monkeypatch.setattr(s, "YT_AUTH_PROFILE", None, raising=False)
        monkeypatch.setattr(s, "YT_AUTH_COOKIEFILE", None, raising=False)
        # 위젯이 테스트 종료와 함께 즉시 파괴되므로, 생성자가 띄우는 백그라운드
        # QThread(_LoginStatusWorker)를 실제로 돌리지 않는다 — 안 그러면
        # "스레드 실행 중 QObject 파괴" 충돌로 프로세스가 죽을 수 있다.
        monkeypatch.setattr(yad._LoginStatusWorker, "start", lambda self: None)

        dialog = yad.YouTubeAuthDialog(YouTubeAuthService())
        qtbot.addWidget(dialog)

        assert dialog._login_btn is not None
        assert dialog._profile_list is not None
        dialog.close()
