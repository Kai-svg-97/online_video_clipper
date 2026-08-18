"""라이브러리 화면 키보드 단축키 — 없던 기능이라 동작과 충돌 규칙을 함께 고정한다.

플레이어는 수정키 없는 단일 키(Space·J·K·L·방향키…)를 쓰므로, 여기 조합(Ctrl/Alt/F5/Esc)과
겹치지 않아야 한다. Esc는 '덮여 있는 화면부터 걷어내기'이고 창을 닫지 않는다.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence

from gui.panels.library_panel import _VIEW_ALBUMS, _VIEW_LIST, LibraryPanel


@pytest.fixture
def panel(qtbot, library_vm, download_vm, clip_vm, monkeypatch):
    import config.settings as settings
    monkeypatch.setattr(settings, "save_setting", lambda *a, **k: None)
    monkeypatch.setattr(library_vm, "load", lambda *a, **k: None)
    album_vm = MagicMock()
    for sig in ("albums_changed", "detail_ready", "track_filled", "fill_finished",
                "unknown_resolved", "error_occurred", "add_progress", "tracks_added"):
        getattr(album_vm, sig).connect = MagicMock()
    p = LibraryPanel(vm=library_vm, clip_vm=clip_vm, download_vm=download_vm,
                     album_vm=album_vm)
    qtbot.addWidget(p)
    yield p
    for worker in list(library_vm._list_workers):
        worker.wait(3000)
    library_vm.shutdown()


def _keys(panel) -> set[str]:
    return {sc.key().toString() for sc in panel._shortcuts}


class TestBindings:
    def test_기본_조작_단축키가_모두_걸려_있다(self, panel):
        assert _keys(panel) >= {
            QKeySequence("Ctrl+F").toString(), QKeySequence("Esc").toString(),
            QKeySequence("Alt+Left").toString(), QKeySequence("Alt+Right").toString(),
            QKeySequence("F5").toString(),
            QKeySequence("Ctrl+1").toString(), QKeySequence("Ctrl+4").toString(),
        }

    def test_플레이어_단일키와_겹치지_않는다(self, panel):
        """Space·J·K·L·화살표는 재생 조작이다 — 여기서 가로채면 재생이 죽는다."""
        player_keys = {"Space", "J", "K", "L", "M", "F", "P", "C", "Left", "Right",
                       "Up", "Down"}
        assert not (_keys(panel) & player_keys)

    def test_다른_페이지에서는_발동하지_않는다(self, panel):
        # WidgetWithChildrenShortcut — 포커스가 패널 밖이면 Qt가 무시한다.
        for sc in panel._shortcuts:
            assert sc.context() == Qt.ShortcutContext.WidgetWithChildrenShortcut


class TestActions:
    def test_검색_단축키가_포커스와_전체선택을_한다(self, panel, qtbot):
        panel.show()
        qtbot.waitExposed(panel)
        panel._search_box.setText("파이썬")

        panel._shortcut_focus_search()

        # 오프스크린 테스트에서는 창 활성화가 없어 hasFocus()가 아니라
        # 창 안의 포커스 위젯으로 확인한다.
        assert panel.focusWidget() is panel._search_box
        assert panel._search_box.selectedText() == "파이썬"

    def test_Esc는_상세를_먼저_닫는다(self, panel, monkeypatch):
        closed: list = []
        monkeypatch.setattr(panel, "_on_detail_back_requested", lambda: closed.append(1))
        panel._nav_stack.setCurrentIndex(1)

        panel._shortcut_escape()

        assert closed == [1]

    def test_Esc는_앨범_상세도_닫는다(self, panel, monkeypatch):
        closed: list = []
        monkeypatch.setattr(panel, "_on_album_back", lambda: closed.append(1))
        panel._nav_stack.setCurrentIndex(2)

        panel._shortcut_escape()

        assert closed == [1]

    def test_목록에서_Esc는_검색어를_지운다(self, panel):
        panel._nav_stack.setCurrentIndex(0)
        panel._search_box.setText("검색어")

        panel._shortcut_escape()

        assert panel._search_box.text() == ""

    def test_뷰_전환_단축키가_보기를_바꾼다(self, panel):
        panel._shortcut_view(_VIEW_LIST)

        assert panel._view_stack.currentIndex() == _VIEW_LIST

    def test_앨범_단축키는_음악_카테고리에서만_동작한다(self, panel, monkeypatch):
        monkeypatch.setattr(panel, "album_view_available", lambda: False)
        entered: list = []
        monkeypatch.setattr(panel, "_on_view_button_clicked", lambda v: entered.append(v))

        panel._shortcut_view(_VIEW_ALBUMS)

        assert entered == []

    def test_F5는_목록을_다시_읽는다(self, panel, library_vm, monkeypatch):
        loaded: list = []
        monkeypatch.setattr(library_vm, "load", lambda: loaded.append(1))

        panel._shortcut_reload()

        assert loaded == [1]

    def test_Alt_방향키는_히스토리를_되짚는다(self, panel, monkeypatch):
        moves: list = []
        monkeypatch.setattr(panel, "_go_back", lambda: moves.append("back"))
        monkeypatch.setattr(panel, "_go_forward", lambda: moves.append("forward"))

        panel._shortcut_back()
        panel._shortcut_forward()

        assert moves == ["back", "forward"]
