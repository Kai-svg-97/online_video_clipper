"""설정 패널의 '라이브러리 가져오기/내보내기' 섹션 — 미주입 시 숨김, 주입 시 노출·배선."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from gui.view_models.transfer_vm import LibraryTransferViewModel


def _transfer_vm() -> LibraryTransferViewModel:
    return LibraryTransferViewModel(
        export_handler=MagicMock(),
        preview_handler=MagicMock(),
        conflicts_handler=MagicMock(),
        import_handler=MagicMock(),
    )


class TestImportExportSection:
    def test_transfer_vm_미주입시_섹션이_없다(self, qtbot):
        from gui.panels.settings_panel import SettingsPanel

        panel = SettingsPanel(get_tags_fn=lambda: [])
        qtbot.addWidget(panel)
        assert getattr(panel, "_import_export_section", None) is None

    def test_transfer_vm_주입시_섹션이_노출된다(self, qtbot):
        from gui.panels.settings_panel import SettingsPanel

        vm = _transfer_vm()
        panel = SettingsPanel(
            get_tags_fn=lambda: [], transfer_vm=vm, get_categories_fn=lambda: [],
        )
        qtbot.addWidget(panel)
        assert panel._import_export_section is not None
        assert panel._import_export_section._export_btn.text() == "내보내기…"
        assert panel._import_export_section._import_btn.text() == "가져오기…"

    def test_내보낼_카테고리가_없으면_안내문구를_보여준다(self, qtbot):
        from gui.panels.settings_panel import SettingsPanel

        vm = _transfer_vm()
        panel = SettingsPanel(
            get_tags_fn=lambda: [], transfer_vm=vm, get_categories_fn=lambda: [],
        )
        qtbot.addWidget(panel)
        panel._import_export_section._export_btn.click()
        assert "없습니다" in panel._import_export_section._status_lbl.text()

    def test_내보내기_완료_신호가_상태에_반영된다(self, qtbot):
        from gui.panels.settings_panel import SettingsPanel

        vm = _transfer_vm()
        panel = SettingsPanel(
            get_tags_fn=lambda: [], transfer_vm=vm, get_categories_fn=lambda: [],
        )
        qtbot.addWidget(panel)
        result = SimpleNamespace(category_count=2, video_count=5, path="out.ovcpkg")
        vm.export_finished.emit(result)
        status = panel._import_export_section._status_lbl.text()
        assert "완료" in status and "5" in status

    def test_가져오기_완료_신호가_상태에_반영된다(self, qtbot):
        from gui.panels.settings_panel import SettingsPanel

        vm = _transfer_vm()
        panel = SettingsPanel(
            get_tags_fn=lambda: [], transfer_vm=vm, get_categories_fn=lambda: [],
        )
        qtbot.addWidget(panel)
        result = SimpleNamespace(created_count=3, merged_count=1, category_count=2)
        vm.import_finished.emit(result)
        status = panel._import_export_section._status_lbl.text()
        assert "완료" in status and "3" in status

    def test_바쁨_상태에서_버튼이_비활성화된다(self, qtbot):
        from gui.panels.settings_panel import SettingsPanel

        vm = _transfer_vm()
        panel = SettingsPanel(
            get_tags_fn=lambda: [], transfer_vm=vm, get_categories_fn=lambda: [],
        )
        qtbot.addWidget(panel)
        vm.busy_changed.emit(True)
        assert not panel._import_export_section._export_btn.isEnabled()
        assert not panel._import_export_section._import_btn.isEnabled()
        vm.busy_changed.emit(False)
        assert panel._import_export_section._export_btn.isEnabled()

    def test_오류_신호가_상태에_표시된다(self, qtbot):
        from gui.panels.settings_panel import SettingsPanel

        vm = _transfer_vm()
        panel = SettingsPanel(
            get_tags_fn=lambda: [], transfer_vm=vm, get_categories_fn=lambda: [],
        )
        qtbot.addWidget(panel)
        vm.error_occurred.emit("문제가 발생했습니다")
        assert "문제가 발생했습니다" in panel._import_export_section._status_lbl.text()
