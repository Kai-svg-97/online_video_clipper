"""GUI 구동 end-to-end — 실제 설정 패널 UI로 폴더 연결·동기화를 클릭 흐름으로 검증.

SettingsPanel의 _CloudSyncSection을 실제로 조작(제공자 선택·경로 입력·연결/동기화 버튼 클릭)해
SyncViewModel(QThread) → SyncService → FolderProvider 경로가 UI에서 끝까지 동작하는지 본다.
실계정 OAuth가 필요 없는 폴더 provider라 CI/헤드리스에서도 진짜로 돌릴 수 있다.
"""

from __future__ import annotations

from tests.integration.test_sync_flow import _NK, _URL


class TestCloudSyncGuiFlow:
    def test_connect_folder_and_sync_through_ui(self, qtbot, tmp_path, monkeypatch):
        from config import settings
        from domain.library.aggregates import VideoAggregate
        from domain.library.value_objects import VideoUrl
        from gui.panels.settings_panel import SettingsPanel
        from gui.view_models.sync_vm import SyncViewModel
        from infrastructure.persistence.database import Database
        from infrastructure.sync.folder_provider import FolderProvider
        from infrastructure.sync.sync_service import SyncService

        # 미디어 동기화가 실제 앱 다운로드 폴더를 건드리지 않도록 빈 임시 경로로 대체.
        monkeypatch.setattr(settings, "DOWNLOAD_DIR", tmp_path / "empty_dl")
        monkeypatch.setattr(settings, "THUMBNAIL_DIR", tmp_path / "empty_thumb")

        cloud = tmp_path / "cloud"
        dba = Database(tmp_path / "A.db")
        dba.initialize()
        svc_a = SyncService(dba, data_dir=tmp_path / "A_data")  # 미설정으로 시작
        vm_a = SyncViewModel(svc_a)

        panel = SettingsPanel(get_tags_fn=lambda: [], sync_vm=vm_a)
        qtbot.addWidget(panel)
        sec = panel._cloud_sync_section
        assert "연결 안" in sec._status_lbl.text()

        # 1) UI로 '로컬 폴더' 선택 + 경로 입력 + 연결 버튼 클릭.
        idx = sec._provider_combo.findData("folder")
        sec._provider_combo.setCurrentIndex(idx)
        assert not sec._folder_row_widget.isHidden()  # 폴더 경로 행 노출됨
        sec._folder_path.setText(str(cloud))
        with qtbot.waitSignal(vm_a.connection_changed, timeout=20000) as sig:
            sec._connect_btn.click()
        assert sig.args == [True]
        assert svc_a.is_connected()
        assert "연결됨" in sec._status_lbl.text()

        # 2) A에 영상 저장(캡처 repo) 후 UI '지금 동기화' 클릭.
        repos = svc_a.make_recording_repos(dba)
        repos["video"].save(VideoAggregate.create(VideoUrl(_URL), "GUI영상"))
        with qtbot.waitSignal(vm_a.sync_finished, timeout=20000):
            sec._sync_btn.click()

        # 3) 같은 폴더를 공유하는 B(실 스택)가 받아오는지.
        dbb = Database(tmp_path / "B.db")
        dbb.initialize()
        svc_b = SyncService(dbb, data_dir=tmp_path / "B_data", provider=FolderProvider(cloud))
        svc_b.sync_now()
        with dbb.connection() as conn:
            row = conn.execute("SELECT title FROM videos WHERE url=?", (_NK,)).fetchone()
        assert row is not None and row["title"] == "GUI영상"

        vm_a.shutdown()
