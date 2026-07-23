"""SyncService 조립·오케스트레이션 통합 테스트 (fake provider)."""

from __future__ import annotations

import pytest

from domain.library.aggregates import VideoAggregate
from domain.library.value_objects import VideoUrl
from infrastructure.persistence.database import Database
from infrastructure.sync.sync_service import SyncService
from tests.integration.test_sync_flow import _NK, _URL, FakeCloudProvider


@pytest.fixture()
def provider(tmp_path):
    return FakeCloudProvider(tmp_path / "cloud")


def _service(tmp_path, name, provider):
    db = Database(tmp_path / f"{name}.db")
    db.initialize()
    svc = SyncService(db, data_dir=tmp_path / name, provider=provider)
    return db, svc


class TestSyncService:
    def test_sync_now_round_trip(self, tmp_path, provider):
        dba, a = _service(tmp_path, "A", provider)
        dbb, b = _service(tmp_path, "B", provider)
        assert a.is_connected() and b.is_connected()
        assert a.install_id != b.install_id  # 데이터 디렉터리 분리 → install 분리

        repos = a.make_recording_repos(dba)
        assert repos is not None
        repos["video"].save(VideoAggregate.create(VideoUrl(_URL), "제목"))

        pushed, _ = a.sync_now()
        assert pushed > 0
        _, pulled = b.sync_now()
        assert pulled > 0

        with dbb.connection() as conn:
            row = conn.execute("SELECT title FROM videos WHERE url=?", (_NK,)).fetchone()
        assert row is not None and row["title"] == "제목"

    def test_not_connected_is_inert(self, tmp_path):
        db = Database(tmp_path / "x.db")
        db.initialize()
        svc = SyncService(db, data_dir=tmp_path / "x", provider=None)
        assert svc.is_connected() is False
        assert svc.make_recording_repos(db) is None  # 캡처 래핑 안 함
        assert svc.sync_now() == (0, 0)
        assert svc.sync_media() is None
        assert svc.compact() is None

    def test_status_reports_connection(self, tmp_path, provider):
        _, svc = _service(tmp_path, "A", provider)
        st = svc.status()
        assert st.connected is True
        assert st.account_name == "tester@example.com"

    def test_disconnect_clears_provider(self, tmp_path, provider):
        _, svc = _service(tmp_path, "A", provider)
        assert svc.is_connected()
        svc.disconnect()
        assert svc.is_connected() is False
        assert svc.sync_now() == (0, 0)
