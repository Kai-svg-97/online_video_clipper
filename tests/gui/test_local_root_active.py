"""좌측 트리 최상단 "로컬" 선택이 시각적으로 드러나는지 검증한다.

기존 문제: local_hdr 클릭이 category_selected.emit(None)만 호출해 목록은 바뀌지만
직전에 선택된 카테고리 노드의 선택 표시가 남아 어느 것이 활성인지 헷갈렸다.
"""
from __future__ import annotations

from uuid import uuid4

from gui.panels.library_panel import _PlaylistPanel


class TestLocalRootActive:
    def test_starts_inactive(self, qapp_instance):
        panel = _PlaylistPanel()
        assert panel.is_local_root_active() is False

    def test_header_click_activates_and_emits(self, qapp_instance):
        panel = _PlaylistPanel()
        received: list = []
        panel.category_selected.connect(received.append)

        panel._local_hdr.click()

        assert panel.is_local_root_active() is True
        assert received == [None]

    def test_header_click_clears_tree_selection(self, qapp_instance):
        """핵심 회귀 — 이전에 선택한 노드의 선택이 지워져야 한다."""
        panel = _PlaylistPanel()
        tree = panel.trees[0]
        item = tree._make_category("AI Coding", uuid4(), video_count=1)
        tree.addTopLevelItem(item)
        tree.setCurrentItem(item)
        assert tree.selectedItems() != []

        panel._local_hdr.click()

        assert tree.selectedItems() == [], "로컬 클릭 후에도 트리 선택이 남아 있다"

    def test_clearing_selection_does_not_reemit(self, qapp_instance):
        """선택 해제가 시그널을 타 핸들러를 다시 실행하면 안 된다(이중 실행 방지)."""
        panel = _PlaylistPanel()
        tree = panel.trees[0]
        item = tree._make_category("Movies", uuid4(), video_count=1)
        tree.addTopLevelItem(item)
        tree.setCurrentItem(item)

        received: list = []
        panel.category_selected.connect(received.append)
        panel._local_hdr.click()

        assert received == [None], f"category_selected가 중복 방출됨: {received}"

    def test_tree_selection_deactivates_header(self, qapp_instance):
        panel = _PlaylistPanel()
        panel.set_local_root_active(True)
        tree = panel.trees[0]
        item = tree._make_category("Redis", uuid4(), video_count=1)
        tree.addTopLevelItem(item)

        tree.setCurrentItem(item)

        assert panel.is_local_root_active() is False

    def test_checked_state_follows_active(self, qapp_instance):
        """QSS :checked 규칙이 걸리도록 체크 상태가 동기화돼야 한다."""
        panel = _PlaylistPanel()
        panel.set_local_root_active(True)
        assert panel._local_hdr.isChecked() is True
        panel.set_local_root_active(False)
        assert panel._local_hdr.isChecked() is False
