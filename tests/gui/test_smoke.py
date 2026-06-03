"""GUI 스모크 테스트 — 각 패널이 오류 없이 초기화되는지 확인.

세부 동작이 아닌 "앱이 죽지 않고 위젯이 뜨는가"를 검증한다.
pytest-qt의 qtbot 픽스처로 위젯 생명주기를 관리한다.
"""
from __future__ import annotations



class TestThemeManager:
    def test_initialize_does_not_raise(self, qapp_instance):
        from gui.themes.manager import ThemeManager

        ThemeManager._instance = None
        mgr = ThemeManager.instance()
        mgr.initialize()

    def test_apply_valid_preset(self, qapp_instance):
        from gui.themes.manager import ThemeManager
        from gui.themes.tokens import PRESETS

        mgr = ThemeManager.instance()
        for name in list(PRESETS.keys())[:2]:
            mgr.apply(name)

    def test_apply_unknown_preset_is_noop(self, qapp_instance):
        from gui.themes.manager import ThemeManager

        mgr = ThemeManager.instance()
        mgr.apply("__no_such_preset__")


class TestDownloadPanel:
    def test_widget_creates_without_error(self, qtbot, download_vm):
        from gui.panels.download_panel import DownloadPanel

        panel = DownloadPanel(vm=download_vm)
        qtbot.addWidget(panel)
        panel.show()

    def test_widget_has_expected_tabs(self, qtbot, download_vm):
        from PyQt6.QtWidgets import QTabWidget

        from gui.panels.download_panel import DownloadPanel

        panel = DownloadPanel(vm=download_vm)
        qtbot.addWidget(panel)
        tabs = panel.findChild(QTabWidget)
        assert tabs is not None
        assert tabs.count() == 2


class TestFeedPanel:
    def test_widget_creates_without_error(self, qtbot, feed_vm):
        from gui.panels.feed_panel import FeedPanel

        panel = FeedPanel(vm=feed_vm)
        qtbot.addWidget(panel)
        panel.show()


class TestLibraryPanel:
    def test_widget_creates_without_error(self, qtbot, library_vm, download_vm, clip_vm):
        from gui.panels.library_panel import LibraryPanel

        panel = LibraryPanel(vm=library_vm, clip_vm=clip_vm, download_vm=download_vm)
        qtbot.addWidget(panel)
        panel.show()


class TestMonitoringPanel:
    def test_widget_creates_without_error(self, qtbot, monitoring_vm):
        from gui.panels.monitoring_panel import MonitoringPanel

        panel = MonitoringPanel(vm=monitoring_vm)
        qtbot.addWidget(panel)
        panel.show()
