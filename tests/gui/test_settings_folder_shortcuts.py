"""설정 패널 — 폴더 바로 열기 + 쿠키 파일 등록 방법 안내.

"이건 컴퓨터 전문가용 앱이 아니다"는 사용자 신고에 따라, 경로를 직접 찾아
입력하지 않고도 버튼 클릭만으로 폴더를 열거나 쿠키 파일 등록 절차를 안내받을
수 있도록 한다.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from PyQt6.QtWidgets import QDialog, QLabel, QPushButton


class TestOpenFolder:
    def test_QDesktopServices_openUrl을_호출한다(self, monkeypatch):
        # open_folder는 부품 모듈로 옮겨졌다 — **쓰는 쪽 모듈**을 패치한다.
        import gui.panels.settings.helpers as sp

        called = MagicMock()
        monkeypatch.setattr(sp.QDesktopServices, "openUrl", called)

        sp.open_folder("/some/path")

        assert called.called
        url = called.call_args[0][0]
        assert url.toLocalFile() == "/some/path"


class TestPathRowOpenButtons:
    def test_각_저장_경로_행에_열기_버튼이_있다(self, qtbot):
        from gui.panels.settings_panel import SettingsPanel

        panel = SettingsPanel(get_tags_fn=lambda: [])
        qtbot.addWidget(panel)

        open_buttons = [
            b for b in panel.findChildren(QPushButton) if b.text() == "열기"
        ]
        # 데이터베이스·다운로드·썸네일·로그 4개 경로 행
        assert len(open_buttons) == 4

    def test_열기_버튼_클릭시_해당_경로로_open_folder가_호출된다(self, qtbot, monkeypatch):
        import gui.panels.settings_panel as sp
        from gui.panels.settings_panel import SettingsPanel

        called = MagicMock()
        monkeypatch.setattr(sp, "open_folder", called)

        panel = SettingsPanel(get_tags_fn=lambda: [])
        qtbot.addWidget(panel)

        open_buttons = [
            b for b in panel.findChildren(QPushButton) if b.text() == "열기"
        ]
        open_buttons[0].click()

        assert called.called


class TestOpenLogDir:
    def test_로그_폴더_열기_버튼이_LOG_DIR로_open_folder를_호출한다(self, qtbot, monkeypatch):
        import gui.panels.settings_panel as sp
        from gui.panels.settings_panel import SettingsPanel

        called = MagicMock()
        monkeypatch.setattr(sp, "open_folder", called)

        panel = SettingsPanel(get_tags_fn=lambda: [])
        qtbot.addWidget(panel)

        panel._open_log_dir_btn.click()

        assert called.called
        from config import settings as s

        assert called.call_args[0][0] == s.LOG_DIR


class TestCookieHelpDialog:
    def test_다이얼로그가_안내_문구를_보여준다(self, qtbot, monkeypatch):
        from gui.panels.settings_panel import COOKIE_HELP_TEXT, SettingsPanel

        captured: list[QDialog] = []
        monkeypatch.setattr(QDialog, "exec", lambda self: captured.append(self))

        panel = SettingsPanel(get_tags_fn=lambda: [])
        qtbot.addWidget(panel)

        panel._cookie_help_btn.click()

        assert captured
        dialog = captured[0]
        labels = dialog.findChildren(QLabel)
        assert any(lbl.text() == COOKIE_HELP_TEXT for lbl in labels)

    def test_다운로드_폴더_열기_버튼이_홈_다운로드로_연다(self, qtbot, monkeypatch):
        import gui.panels.settings_panel as sp
        from gui.panels.settings_panel import SettingsPanel

        captured: list[QDialog] = []
        monkeypatch.setattr(QDialog, "exec", lambda self: captured.append(self))
        called = MagicMock()
        monkeypatch.setattr(sp, "open_folder", called)

        panel = SettingsPanel(get_tags_fn=lambda: [])
        qtbot.addWidget(panel)
        panel._cookie_help_btn.click()

        dialog = captured[0]
        dl_btn = next(
            b for b in dialog.findChildren(QPushButton) if b.text() == "다운로드 폴더 열기"
        )
        dl_btn.click()

        called.assert_called_with(Path.home() / "Downloads")
