"""트리 항목의 데이터 롤과 델리게이트를 검증한다.

시각 정보가 한 문자열("🏷  이름  (3)")에 뭉쳐 있으면 델리게이트가 파싱해야 하는데,
로딩 스피너가 텍스트 뒤에 ⠋를 덧붙이고 카테고리 이름에 괄호가 들어갈 수도 있어
파싱은 깨진다. 그래서 팩토리가 롤을 따로 심고 델리게이트는 롤만 읽는다.
"""
from __future__ import annotations

from uuid import uuid4

from gui.panels.library_panel import (
    _COLOR_ROLE,
    _COUNT_ROLE,
    _GLYPH_ROLE,
    _ITEM_TYPE_ROLE,
    _ITYPE_CATEGORY,
    _NAME_ROLE,
    _STAR_ROLE,
    _PlaylistTree,
    _TreeRowDelegate,
)


class TestCategoryItemRoles:
    def test_name_and_count_stored_separately(self, qapp_instance):
        tree = _PlaylistTree(section="local")
        cid = uuid4()
        item = tree._make_category("AI Coding", cid, video_count=3)

        assert item.data(0, _NAME_ROLE) == "AI Coding"
        assert item.data(0, _COUNT_ROLE) == 3
        assert item.data(0, _GLYPH_ROLE) == "category"
        assert item.data(0, _ITEM_TYPE_ROLE) == _ITYPE_CATEGORY

    def test_zero_count_is_none(self, qapp_instance):
        tree = _PlaylistTree(section="local")
        item = tree._make_category("Servers", uuid4(), video_count=0)
        assert item.data(0, _COUNT_ROLE) is None

    def test_color_role_is_stable_palette_color(self, qapp_instance):
        """같은 이름은 항상 같은 색 — 색상 점이 의미를 가지려면 필수."""
        tree = _PlaylistTree(section="local")
        a = tree._make_category("Music", uuid4(), video_count=1)
        b = tree._make_category("Music", uuid4(), video_count=9)
        assert a.data(0, _COLOR_ROLE) == b.data(0, _COLOR_ROLE)
        assert a.data(0, _COLOR_ROLE).startswith("#")

    def test_name_role_excludes_parenthesis_in_name(self, qapp_instance):
        """이름에 괄호가 있어도 개수와 섞이지 않는다 — 문자열 파싱 방식이 깨지던 경우."""
        tree = _PlaylistTree(section="local")
        item = tree._make_category("Movies (2024)", uuid4(), video_count=5)
        assert item.data(0, _NAME_ROLE) == "Movies (2024)"
        assert item.data(0, _COUNT_ROLE) == 5

    def test_display_text_still_set(self, qapp_instance):
        """스피너·툴팁·find_item_by_* 가 계속 동작하려면 텍스트가 남아야 한다."""
        tree = _PlaylistTree(section="local")
        item = tree._make_category("Redis", uuid4(), video_count=1)
        assert "Redis" in item.text(0)


class TestFavoriteStar:
    def test_star_role_false_by_default(self, qapp_instance):
        tree = _PlaylistTree(section="local")
        item = tree._make_category("Redis", uuid4(), video_count=1)
        assert item.data(0, _STAR_ROLE) is False

    def test_star_role_true_when_favorited(self, qapp_instance):
        tree = _PlaylistTree(section="local")
        cid = uuid4()
        tree._favs.add(("category", str(cid)))
        item = tree._make_category("Music", cid, video_count=1)
        assert item.data(0, _STAR_ROLE) is True


class TestFolderItemRoles:
    def test_folder_roles(self, qapp_instance):
        tree = _PlaylistTree(section="local")
        item = tree._make_folder("보관함", uuid4(), "local")
        assert item.data(0, _NAME_ROLE) == "보관함"
        assert item.data(0, _GLYPH_ROLE) == "folder"

    def test_unfiled_roles(self, qapp_instance):
        tree = _PlaylistTree(section="local")
        item = tree._make_unfiled("local")
        assert item.data(0, _NAME_ROLE) == "미분류"
        assert item.data(0, _GLYPH_ROLE) == "folder"


class TestDelegate:
    def test_row_height_increased(self, qapp_instance):
        """행 높이 30px — 기존 약 22px보다 여유를 준다."""
        from PyQt6.QtWidgets import QStyleOptionViewItem

        tree = _PlaylistTree(section="local")
        item = tree._make_category("AI Coding", uuid4(), video_count=3)
        tree.addTopLevelItem(item)
        delegate = _TreeRowDelegate(tree)
        hint = delegate.sizeHint(QStyleOptionViewItem(), tree.indexFromItem(item, 0))
        assert hint.height() == 30

    def test_tree_installs_delegate(self, qapp_instance):
        tree = _PlaylistTree(section="local")
        assert isinstance(tree.itemDelegate(), _TreeRowDelegate)


class TestBranchClickStillExpands:
    """drawBranches() 오버라이드가 네이티브 펼침 히트테스트를 깨지 않았는지 검증한다.

    셰브론을 델리게이트(아이템 영역)에 그리면 클릭이 확장으로 처리되지 않는다.
    그래서 branch 영역에 그렸고, 이 테스트가 그 판단을 실제로 확인한다.
    """

    def test_click_on_branch_area_toggles_expansion(self, qapp_instance):
        from PyQt6.QtCore import QPoint, Qt
        from PyQt6.QtTest import QTest

        tree = _PlaylistTree(section="local")
        parent = tree._make_category("AI Coding", uuid4(), video_count=3)
        parent.addChild(tree._make_category("자식", uuid4(), video_count=1))
        tree.addTopLevelItem(parent)
        tree.collapseAll()
        tree.resize(240, 200)
        tree.show()
        QTest.qWaitForWindowExposed(tree)

        assert parent.isExpanded() is False

        rect = tree.visualItemRect(parent)
        # branch 영역 = 아이템 rect 왼쪽의 들여쓰기 폭. 셰브론은 그 중앙에 그린다.
        branch_x = rect.left() - tree.indentation() // 2
        QTest.mouseClick(
            tree.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(max(2, branch_x), rect.center().y()),
        )
        qapp_instance.processEvents()

        assert parent.isExpanded() is True, "branch 클릭으로 펼쳐지지 않았다"

        QTest.mouseClick(
            tree.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(max(2, branch_x), rect.center().y()),
        )
        qapp_instance.processEvents()
        assert parent.isExpanded() is False, "branch 재클릭으로 접히지 않았다"

    def test_selection_still_emits_category_signal(self, qapp_instance):
        """행 선택 시그널 경로가 그리기 변경에 영향받지 않았는지 확인한다.

        합성 마우스 클릭은 뷰포트 좌표·윈도우 활성화에 민감해 불안정하므로
        선택 자체를 트리거해 시그널 경로를 검증한다(마우스 처리 코드는 미수정).
        """
        tree = _PlaylistTree(section="local")
        cid = uuid4()
        item = tree._make_category("Movies", cid, video_count=2)
        tree.addTopLevelItem(item)

        received: list = []
        tree.category_selected.connect(received.append)

        tree.setCurrentItem(item)
        qapp_instance.processEvents()

        assert received == [cid]


class TestSpinnerStillWorks:
    def test_spinner_preserves_roles(self, qapp_instance):
        """스피너가 텍스트를 바꿔도 롤은 그대로여야 한다(델리게이트가 롤을 읽으므로)."""
        tree = _PlaylistTree(section="local")
        item = tree._make_category("AI Coding", uuid4(), video_count=3)
        tree.addTopLevelItem(item)

        tree.set_node_loading("k", item, True)
        assert item.data(0, _NAME_ROLE) == "AI Coding"
        assert item.data(0, _COUNT_ROLE) == 3

        tree.set_node_loading("k", None, False)
        assert item.data(0, _NAME_ROLE) == "AI Coding"
