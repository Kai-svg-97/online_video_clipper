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
        # DownloadPanel은 자체 QTabWidget이 없고 상세 페이지로 VideoDetailWidget을
        # 임베드하므로, findChild(QTabWidget)는 상세 화면의 탭을 찾는다:
        # 설명 / 요약 / 다운로드·클립 = 3개.
        tabs = panel.findChild(QTabWidget)
        assert tabs is not None
        assert tabs.count() == 3


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

    def test_category_select_leaves_folder_view(self, qtbot, library_vm, download_vm, clip_vm):
        """폴더 카드 뷰(경로바 'YouTube' 클릭 상태)에서 카테고리를 고르면
        영상 리스트 뷰로 복귀해야 한다 (폴더 카드가 그대로 남으면 버그)."""
        from gui.panels.library_panel import _VIEW_FOLDER, LibraryPanel

        panel = LibraryPanel(vm=library_vm, clip_vm=clip_vm, download_vm=download_vm)
        qtbot.addWidget(panel)
        # 폴더 카드 뷰 상태를 강제 (섹션 루트 'YouTube' 클릭과 동일한 스택 상태)
        panel._view_stack.setCurrentIndex(_VIEW_FOLDER)
        assert panel._view_stack.currentIndex() == _VIEW_FOLDER

        panel._on_cat_filter_changed(None)  # 카테고리 선택

        assert panel._view_stack.currentIndex() != _VIEW_FOLDER


class TestLibraryCategorizedOnly:
    """\"로컬\" 루트 선택 시 카테고리 영상만(category_id IS NOT NULL) 조회하는지 검증."""

    def _last_query(self, library_vm):
        return library_vm._get_videos.handle.call_args.args[0]

    def test_local_root_requests_categorized_only(self, library_vm):
        from uuid import uuid4

        # 특정 카테고리 선택 → categorized_only=False
        library_vm.set_category_filter(uuid4())
        assert self._last_query(library_vm).categorized_only is False

        # "로컬"/전체(None) 선택 → categorized_only=True
        library_vm.set_category_filter(None)
        assert self._last_query(library_vm).categorized_only is True

    def test_playlist_view_not_categorized_only(self, library_vm):
        from uuid import uuid4

        library_vm.set_playlist_filter(uuid4())
        assert self._last_query(library_vm).categorized_only is False


class TestPlaylistTreeCategorySelection:
    """하위 카테고리 추가로 트리가 재구성돼도 부모 카테고리 선택이 유지돼야 한다."""

    def test_load_preserves_category_selection(self, qtbot, qapp_instance):
        from types import SimpleNamespace
        from uuid import uuid4

        from gui.panels.library_panel import _CAT_ID_ROLE, _PlaylistTree

        parent_id = uuid4()
        cats = [SimpleNamespace(id=parent_id, name="Games", parent_id=None, video_count=0)]
        tree = _PlaylistTree(section="local")
        qtbot.addWidget(tree)
        tree.load(playlists=[], folders=[], categories=cats)

        # 부모 카테고리 선택
        tree.setCurrentItem(tree.topLevelItem(0))
        assert tree.currentItem().data(0, _CAT_ID_ROLE) == parent_id

        # 하위 카테고리 추가 → 트리 재구성(refresh와 동일)
        child_id = uuid4()
        cats2 = cats + [SimpleNamespace(id=child_id, name="PS5", parent_id=parent_id, video_count=0)]
        tree.load(playlists=[], folders=[], categories=cats2)

        # 부모 카테고리가 여전히 선택돼 있어야 한다
        cur = tree.currentItem()
        assert cur is not None
        assert cur.data(0, _CAT_ID_ROLE) == parent_id


class TestMonitoringPanel:
    def test_widget_creates_without_error(self, qtbot, monitoring_vm):
        from gui.panels.monitoring_panel import MonitoringPanel

        panel = MonitoringPanel(vm=monitoring_vm)
        qtbot.addWidget(panel)
        panel.show()


class TestSettingsPanelCloudSync:
    """클라우드 동기화 섹션이 미연결 상태로 오류 없이 렌더되는지 + 미주입 시 무변경."""

    def _sync_vm(self, tmp_path):
        from gui.view_models.sync_vm import SyncViewModel
        from infrastructure.persistence.database import Database
        from infrastructure.sync.sync_service import SyncService

        db = Database(tmp_path / "lib.db")
        db.initialize()
        svc = SyncService(db, data_dir=tmp_path / "data", provider=None)
        return SyncViewModel(svc)

    def test_sync_section_renders_disconnected(self, qtbot, tmp_path):
        from gui.panels.settings_panel import SettingsPanel

        vm = self._sync_vm(tmp_path)
        panel = SettingsPanel(get_tags_fn=lambda: [], sync_vm=vm)
        qtbot.addWidget(panel)
        panel.show()
        assert panel._cloud_sync_section is not None
        # 미연결 → 상태 라벨에 "연결 안" 문구, 연결 버튼 활성/동기화 버튼 비활성
        assert "연결 안" in panel._cloud_sync_section._status_lbl.text()
        assert panel._cloud_sync_section._connect_btn.isEnabled()
        assert not panel._cloud_sync_section._sync_btn.isEnabled()
        vm.shutdown()

    def test_no_sync_vm_omits_section(self, qtbot):
        from gui.panels.settings_panel import SettingsPanel

        panel = SettingsPanel(get_tags_fn=lambda: [])
        qtbot.addWidget(panel)
        panel.show()
        assert getattr(panel, "_cloud_sync_section", None) is None
