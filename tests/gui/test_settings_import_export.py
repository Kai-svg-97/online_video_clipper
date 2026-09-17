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


# ----------------------------------------------------------------------
# 미디어 서버용 사이드카(.nfo/.m3u)
# ----------------------------------------------------------------------

from application.transfer.media_server import MediaServerExportResult  # noqa: E402


def _section(qtbot, categories=()):
    from gui.panels.settings_panel import SettingsPanel

    vm = _transfer_vm()
    panel = SettingsPanel(
        get_tags_fn=lambda: [], transfer_vm=vm, get_categories_fn=lambda: list(categories),
    )
    qtbot.addWidget(panel)
    section = panel._import_export_section
    # 섹션만 돌려주면 패널이 GC돼 자식 위젯이 파괴된다("wrapped C/C++ object has
    # been deleted"). 파이썬 쪽 참조를 섹션에 붙여 수명을 맞춘다.
    section._owner_panel = panel
    return section


class TestMediaServerExport:
    def test_버튼이_노출된다(self, qtbot):
        section = _section(qtbot)
        assert section._media_btn.text() == "미디어 서버용 내보내기…"

    def test_카테고리가_없으면_안내만_한다(self, qtbot):
        section = _section(qtbot)
        section._on_media_server_clicked()
        assert "카테고리가 없습니다" in section._status_lbl.text()

    def test_결과를_한_줄로_알린다(self, qtbot):
        section = _section(qtbot)
        section._on_media_server_finished(
            MediaServerExportResult(nfo_written=12, m3u_entries=12, m3u_path="C:/a.m3u")
        )
        text = section._status_lbl.text()
        assert "정보 파일 12개" in text
        assert "재생목록 12곡" in text

    def test_건너뛴_영상_수를_반드시_알린다(self, qtbot):
        """'왜 적게 나왔지?'의 답이라 빠뜨리면 사용자가 원인을 못 찾는다."""
        section = _section(qtbot)
        section._on_media_server_finished(
            MediaServerExportResult(nfo_written=3, skipped_no_file=9)
        )
        assert "9개는 받아 둔 파일이 없어 건너뜀" in section._status_lbl.text()

    def test_쓰기_실패도_알린다(self, qtbot):
        section = _section(qtbot)
        section._on_media_server_finished(
            MediaServerExportResult(nfo_written=1, failed=["C:/x.nfo"])
        )
        assert "1개 쓰기 실패" in section._status_lbl.text()

    def test_재생목록을_만들지_않았으면_언급하지_않는다(self, qtbot):
        section = _section(qtbot)
        section._on_media_server_finished(MediaServerExportResult(nfo_written=5))
        assert "재생목록" not in section._status_lbl.text()
