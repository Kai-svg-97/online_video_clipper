"""즐겨찾기 바 클릭이 좌측 트리 노드 선택·스크롤까지 동기화하는지 검증한다.

기존 문제: 상단 즐겨찾기 바 항목을 누르면 영상 목록만 바뀌고 좌측 트리는 아무
반응이 없었다. 트리 노드를 직접 클릭했을 때와 달리 선택 표시가 붙지 않아 지금
어느 카테고리를 보고 있는지 트리에서 알 수 없었고, 트리가 길면 해당 노드가 화면
밖에 남아 "아무 일도 안 일어난 것"처럼 보였다.

`_on_favorite_clicked`가 기존 `select_snapshot` 경로를 재사용하고,
`select_for_snapshot`이 선택 후 `scrollToItem`까지 하도록 고쳤다.
"""
from __future__ import annotations

from uuid import uuid4

from PyQt6.QtWidgets import QLabel, QPushButton

from gui.panels.library_panel import _PlaylistPanel


class TestSmartFolderRemoved:
    """스마트 폴더 기능은 쓰이지 않아 UI·코드 모두 제거했다(되살아나지 않게 고정)."""

    def test_module_is_gone(self):
        import importlib

        try:
            importlib.import_module("application.library.smart_folders")
        except ModuleNotFoundError:
            return
        raise AssertionError("application.library.smart_folders가 아직 남아 있다")

    def test_panel_has_no_smart_folder_state(self, library_vm, clip_vm, download_vm):
        from gui.panels.library_panel import LibraryPanel

        panel = LibraryPanel(vm=library_vm, clip_vm=clip_vm, download_vm=download_vm)
        for attr in ("_sf_list", "_smart_folders", "_load_smart_folders_ui", "_on_save_smart_folder"):
            assert not hasattr(panel, attr), f"스마트 폴더 잔재: {attr}"

    def test_no_smart_folder_text_in_ui(self, library_vm, clip_vm, download_vm):
        from gui.panels.library_panel import LibraryPanel

        panel = LibraryPanel(vm=library_vm, clip_vm=clip_vm, download_vm=download_vm)
        hits = [
            w.text()
            for w in panel.findChildren((QLabel, QPushButton))
            if "스마트" in (w.text() or "")
        ]
        assert hits == [], f"화면에 스마트 폴더 문구가 남아 있다: {hits}"


class TestSelectSnapshotHighlights:
    """select_snapshot이 스냅샷에 해당하는 노드를 선택 표시한다."""

    def test_category_snapshot_selects_node(self, qapp_instance):
        panel = _PlaylistPanel()
        tree = panel.trees[0]
        cat_id = uuid4()
        other = tree._make_category("다른 카테고리", uuid4(), video_count=2)
        target = tree._make_category("음악", cat_id, video_count=5)
        tree.addTopLevelItem(other)
        tree.addTopLevelItem(target)

        panel.select_snapshot({"kind": "category", "cat_id": cat_id})

        assert tree.currentItem() is target, "즐겨찾기한 카테고리 노드가 선택되지 않았다"

    def test_playlist_snapshot_selects_node(self, qapp_instance):
        panel = _PlaylistPanel()
        tree = panel.trees[0]
        pl_id = uuid4()
        target = tree._make_playlist("내 재생목록", 3, pl_id, None)
        tree.addTopLevelItem(tree._make_playlist("다른 목록", 1, uuid4(), None))
        tree.addTopLevelItem(target)

        panel.select_snapshot({"kind": "playlist", "playlist_id": pl_id})

        assert tree.currentItem() is target, "즐겨찾기한 재생목록 노드가 선택되지 않았다"

    def test_nested_category_ancestors_expanded(self, qapp_instance):
        """하위 카테고리는 조상이 접혀 있으면 보이지 않으므로 펼쳐져야 한다."""
        panel = _PlaylistPanel()
        tree = panel.trees[0]
        child_id = uuid4()
        parent = tree._make_category("Music", uuid4(), video_count=0)
        child = tree._make_category("Rock", child_id, video_count=4)
        parent.addChild(child)
        tree.addTopLevelItem(parent)
        parent.setExpanded(False)

        panel.select_snapshot({"kind": "category", "cat_id": child_id})

        assert parent.isExpanded() is True, "부모 카테고리가 펼쳐지지 않아 자식이 가려진다"
        assert tree.currentItem() is child

    def test_selection_does_not_reemit(self, qapp_instance):
        """선택 변경이 핸들러를 다시 실행하면 목록 조회가 두 번 돈다(이중 실행 방지)."""
        panel = _PlaylistPanel()
        tree = panel.trees[0]
        cat_id = uuid4()
        tree.addTopLevelItem(tree._make_category("음악", cat_id, video_count=5))

        received: list = []
        panel.category_selected.connect(received.append)
        panel.select_snapshot({"kind": "category", "cat_id": cat_id})

        assert received == [], f"select_snapshot이 category_selected를 방출했다: {received}"

    def test_unmatched_snapshot_activates_local_root(self, qapp_instance):
        """어떤 노드와도 일치하지 않으면 '로컬' 루트 화면으로 본다."""
        panel = _PlaylistPanel()
        panel.select_snapshot({"kind": "category", "cat_id": uuid4()})
        assert panel.is_local_root_active() is True


class TestSelectSnapshotScrolls:
    """핵심 회귀 — 선택한 노드가 화면 밖이면 보이는 위치까지 스크롤해야 한다.

    `setCurrentItem` 자체도 `EnsureVisible`로 스크롤은 하지만, 그것은 노드를
    뷰포트 *경계까지만* 밀어 넣어 아래쪽 끝에 걸치게 둔다(실측: 340px 뷰포트에서
    중심으로부터 145px 아래). 그래서 `PositionAtCenter`로 명시적으로 한 번 더
    스크롤해 노드를 화면 가운데에 놓는다 — 즐겨찾기 바에서 눌렀을 때 트리의 어디로
    갔는지 한눈에 보이게 하려는 것이 목적이다.
    """

    def _build_long_tree(self, panel, target_index: int = 60):
        tree = panel.trees[0]
        target_id = None
        for i in range(80):
            cat_id = uuid4()
            if i == target_index:
                target_id = cat_id
            tree.addTopLevelItem(tree._make_category(f"카테고리 {i:02d}", cat_id, video_count=1))
        return tree, target_id

    def test_offscreen_node_scrolled_into_view(self, qapp_instance):
        panel = _PlaylistPanel()
        tree, target_id = self._build_long_tree(panel)
        panel.resize(240, 400)
        panel.show()
        tree.scrollToTop()

        target = tree.find_item_by_cat_id(str(target_id))
        assert target is not None
        # 전제 확인 — 목록 아래쪽 노드라 스크롤 전에는 뷰포트 밖이어야 한다.
        assert not tree.viewport().rect().intersects(tree.visualItemRect(target)), (
            "전제 실패 — 대상 노드가 스크롤 전에 이미 보인다(트리를 더 길게 만들 것)"
        )

        panel.select_snapshot({"kind": "category", "cat_id": target_id})

        rect = tree.visualItemRect(target)
        assert tree.viewport().rect().intersects(rect), (
            "선택 후에도 노드가 뷰포트 밖에 있다 — 스크롤이 전혀 되지 않았다"
        )
        panel.hide()

    def test_node_is_centred_not_merely_visible(self, qapp_instance):
        """EnsureVisible(경계까지만 밀기)로 되돌아가면 이 테스트가 실패한다."""
        panel = _PlaylistPanel()
        tree, target_id = self._build_long_tree(panel)
        panel.resize(240, 400)
        panel.show()
        tree.scrollToTop()

        panel.select_snapshot({"kind": "category", "cat_id": target_id})

        target = tree.find_item_by_cat_id(str(target_id))
        rect = tree.visualItemRect(target)
        offset = abs(rect.center().y() - tree.viewport().rect().center().y())
        assert offset <= rect.height(), (
            f"노드가 뷰포트 중앙에서 {offset}px 떨어져 있다 — 한 행 높이"
            f"({rect.height()}px) 안으로 들어와야 한다"
        )
        panel.hide()
