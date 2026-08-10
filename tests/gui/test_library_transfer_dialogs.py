"""가져오기/내보내기 다이얼로그 — 카테고리 체크트리 + 충돌 해결 화면."""
from __future__ import annotations

from PyQt6.QtCore import Qt

from application.transfer.dtos import ImportConflictDTO, ImportFieldDiffDTO
from gui.dialogs.library_transfer_dialogs import (
    CategorySelectDialog,
    ImportConflictResolutionDialog,
)


class _Cat:
    def __init__(self, id, name, parent_id, video_count=0):
        self.id = id
        self.name = name
        self.parent_id = parent_id
        self.video_count = video_count


class TestCategorySelectDialog:
    def _cats(self):
        return [
            _Cat("root", "Music", None, video_count=3),
            _Cat("child", "OST", "root", video_count=1),
            _Cat("other", "Movies", None, video_count=2),
        ]

    def test_모든_카테고리가_트리에_들어간다(self, qapp_instance):
        dlg = CategorySelectDialog(self._cats(), "내보내기")
        assert set(dlg._items_by_id.keys()) == {"root", "child", "other"}

    def test_기본은_전부_해제된_상태다(self, qapp_instance):
        dlg = CategorySelectDialog(self._cats(), "내보내기")
        assert dlg.selected_category_ids() == []

    def test_부모를_체크하면_자식도_체크된다(self, qapp_instance):
        dlg = CategorySelectDialog(self._cats(), "내보내기")
        dlg._items_by_id["root"].setCheckState(0, Qt.CheckState.Checked)
        assert set(dlg.selected_category_ids()) == {"root", "child"}
        assert "other" not in dlg.selected_category_ids()

    def test_부모를_해제하면_자식도_해제된다(self, qapp_instance):
        dlg = CategorySelectDialog(self._cats(), "내보내기")
        dlg._items_by_id["root"].setCheckState(0, Qt.CheckState.Checked)
        dlg._items_by_id["root"].setCheckState(0, Qt.CheckState.Unchecked)
        assert dlg.selected_category_ids() == []

    def test_전체_선택_버튼(self, qapp_instance):
        dlg = CategorySelectDialog(self._cats(), "내보내기")
        dlg._select_all_btn.click()
        assert set(dlg.selected_category_ids()) == {"root", "child", "other"}

    def test_전체_해제_버튼(self, qapp_instance):
        dlg = CategorySelectDialog(self._cats(), "내보내기")
        dlg._select_all_btn.click()
        dlg._select_none_btn.click()
        assert dlg.selected_category_ids() == []

    def test_리프_카테고리만_체크해도_결과에_포함된다(self, qapp_instance):
        dlg = CategorySelectDialog(self._cats(), "내보내기")
        dlg._items_by_id["child"].setCheckState(0, Qt.CheckState.Checked)
        assert dlg.selected_category_ids() == ["child"]


def _diff(field, label, ex, inc, ex_filled, inc_filled, default) -> ImportFieldDiffDTO:
    return ImportFieldDiffDTO(
        field=field, label=label, existing_value=ex, incoming_value=inc,
        existing_filled=ex_filled, incoming_filled=inc_filled, default_choice=default,
    )


class TestImportConflictResolutionDialog:
    def _conflicts(self):
        return (
            ImportConflictDTO(
                url="u1", title="영상1",
                fields=(
                    _diff("title", "제목", "기존제목", "새제목", True, True, "existing"),
                    _diff("notes", "메모", "", "새메모", False, True, "incoming"),
                ),
            ),
            ImportConflictDTO(
                url="u2", title="영상2",
                fields=(_diff("artist", "가수", "가수A", "가수B", True, True, "existing"),),
            ),
        )

    def test_초기_선택값은_필드의_기본값을_따른다(self, qapp_instance):
        dlg = ImportConflictResolutionDialog(self._conflicts())
        res = dlg.resolutions()
        assert res["u1"]["title"] == "existing"
        assert res["u1"]["notes"] == "incoming"
        assert res["u2"]["artist"] == "existing"

    def test_라디오를_바꾸면_resolutions에_반영된다(self, qapp_instance):
        dlg = ImportConflictResolutionDialog(self._conflicts())
        dlg._list.setCurrentRow(0)
        row = dlg._field_rows["title"]
        row._incoming_radio.setChecked(True)
        assert dlg.resolutions()["u1"]["title"] == "incoming"

    def test_다른_영상을_선택하면_필드목록이_바뀐다(self, qapp_instance):
        dlg = ImportConflictResolutionDialog(self._conflicts())
        dlg._list.setCurrentRow(0)
        assert set(dlg._field_rows.keys()) == {"title", "notes"}
        dlg._list.setCurrentRow(1)
        assert set(dlg._field_rows.keys()) == {"artist"}

    def test_전체_가져오기값_사용_버튼(self, qapp_instance):
        dlg = ImportConflictResolutionDialog(self._conflicts())
        dlg._all_incoming_btn.click()
        res = dlg.resolutions()
        assert res["u1"]["title"] == "incoming"
        assert res["u1"]["notes"] == "incoming"
        assert res["u2"]["artist"] == "incoming"

    def test_전체_기존값_유지_버튼(self, qapp_instance):
        dlg = ImportConflictResolutionDialog(self._conflicts())
        dlg._all_incoming_btn.click()
        dlg._all_existing_btn.click()
        res = dlg.resolutions()
        assert all(choice == "existing" for fields in res.values() for choice in fields.values())

    def test_충돌이_없으면_빈_resolutions를_반환한다(self, qapp_instance):
        dlg = ImportConflictResolutionDialog(())
        assert dlg.resolutions() == {}
