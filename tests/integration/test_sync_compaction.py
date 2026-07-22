"""컴팩션 + 스냅샷 부트스트랩 통합 테스트 (fake provider)."""

from __future__ import annotations

from pathlib import Path

import pytest

from application.sync.commands import (
    CompactHandler,
    PullHandler,
)
from domain.library.aggregates import VideoAggregate
from domain.library.value_objects import VideoUrl
from domain.sync.services import SyncSchemaError
from infrastructure.persistence.database import MIGRATION_IDS, Database
from infrastructure.sync.bootstrap import bootstrap_if_fresh
from infrastructure.sync.snapshot_store import SnapshotStore
from infrastructure.sync.sync_state import SyncStateStore
from tests.integration.test_sync_flow import FakeCloudProvider, Install

_URL2 = "https://www.youtube.com/watch?v=def45678901"
_URL3 = "https://www.youtube.com/watch?v=ghi78901234"


@pytest.fixture()
def provider(tmp_path):
    return FakeCloudProvider(tmp_path / "cloud")


def _compact(inst: Install, provider, tmp_path: Path, gc: bool = False):
    snap = SnapshotStore(inst.db._path, MIGRATION_IDS)
    return CompactHandler(
        install_id=inst.name,
        snapshot_store=snap,
        provider=provider,
        state_store=inst.state,
        tmp_dir=tmp_path / f"{inst.name}_tmp",
        gc=gc,
    ).handle()


def _bootstrap(name: str, tmp_path: Path, provider) -> tuple[bool, Path, SyncStateStore]:
    """이름만 가진 신규 install 을 부트스트랩한다(DB 미존재 상태)."""
    db_path = tmp_path / f"{name}.db"
    state = SyncStateStore(tmp_path / f"{name}_state.json")
    snap = SnapshotStore(db_path, MIGRATION_IDS)
    ok = bootstrap_if_fresh(
        provider, snap, state, db_path,
        backup_dir=tmp_path / f"{name}_backup",
        tmp_dir=tmp_path / f"{name}_dl",
    )
    return ok, db_path, state


def _titles(db_path: Path) -> set[str]:
    db = Database(db_path)
    with db.connection() as conn:
        return {r["title"] for r in conn.execute("SELECT title FROM videos").fetchall()}


class TestCompactAndBootstrap:
    def test_fresh_install_bootstraps_from_snapshot(self, tmp_path, provider):
        a = Install(tmp_path, "A", provider)
        a.repo.save(VideoAggregate.create(VideoUrl("https://www.youtube.com/watch?v=abc12345678"), "영상1"))
        a.repo.save(VideoAggregate.create(VideoUrl(_URL2), "영상2"))
        a.push()
        manifest = _compact(a, provider, tmp_path)
        assert manifest.covered["A"] == a.state.load().pushed_head

        ok, db_b, state_b = _bootstrap("B", tmp_path, provider)
        assert ok is True
        assert db_b.exists()
        assert _titles(db_b) == {"영상1", "영상2"}
        assert state_b.load().consumed == manifest.covered

    def test_bootstrap_then_incremental_pull(self, tmp_path, provider):
        a = Install(tmp_path, "A", provider)
        a.repo.save(VideoAggregate.create(VideoUrl("https://www.youtube.com/watch?v=abc12345678"), "영상1"))
        a.push()
        _compact(a, provider, tmp_path)

        ok, db_b, state_b = _bootstrap("B", tmp_path, provider)
        assert ok

        # A 가 스냅샷 이후 새 영상 추가·push.
        a.repo.save(VideoAggregate.create(VideoUrl(_URL2), "영상2"))
        a.push()

        # B 를 로드해 증분 pull.
        b_db = Database(db_b)
        b_state = SyncStateStore(tmp_path / "B_state.json")
        from infrastructure.sync.device import LamportClock
        from infrastructure.sync.keyring_secret_store import KeyringSecretStore
        from infrastructure.sync.merge_applier import MergeApplier
        from infrastructure.sync.cloud_oplog_store import CloudOplogStore
        secret = KeyringSecretStore("s", tmp_path / "B_secret.json", use_file=True)
        applier = MergeApplier(b_db, LamportClock(secret))
        pulled = PullHandler(
            "B", CloudOplogStore(provider), applier, b_state, frozenset(MIGRATION_IDS)
        ).handle()
        assert pulled > 0
        assert _titles(db_b) == {"영상1", "영상2"}

    def test_no_bootstrap_when_db_exists(self, tmp_path, provider):
        a = Install(tmp_path, "A", provider)
        a.repo.save(VideoAggregate.create(VideoUrl("https://www.youtube.com/watch?v=abc12345678"), "t"))
        a.push()
        _compact(a, provider, tmp_path)
        # A 는 이미 DB 가 있으므로 부트스트랩 안 함.
        snap = SnapshotStore(a.db._path, MIGRATION_IDS)
        ok = bootstrap_if_fresh(
            provider, snap, a.state, a.db._path,
            backup_dir=tmp_path / "bk", tmp_dir=tmp_path / "dl",
        )
        assert ok is False

    def test_no_snapshot_returns_false(self, tmp_path, provider):
        ok, _, _ = _bootstrap("B", tmp_path, provider)
        assert ok is False

    def test_sha_mismatch_raises(self, tmp_path, provider):
        a = Install(tmp_path, "A", provider)
        a.repo.save(VideoAggregate.create(VideoUrl("https://www.youtube.com/watch?v=abc12345678"), "t"))
        a.push()
        _compact(a, provider, tmp_path)
        # 업로드된 스냅샷 DB 를 손상시킨다(manifest sha 와 불일치).
        provider.write_text("snapshot/library.db", "corrupted-not-a-db")
        with pytest.raises(SyncSchemaError):
            _bootstrap("B", tmp_path, provider)


class TestGarbageCollection:
    def test_gc_deletes_covered_segments(self, tmp_path, provider):
        a = Install(tmp_path, "A", provider)
        a.repo.save(VideoAggregate.create(VideoUrl("https://www.youtube.com/watch?v=abc12345678"), "영상1"))
        a.repo.save(VideoAggregate.create(VideoUrl(_URL2), "영상2"))
        head = a.push()
        assert head == 2

        # gc=True 컴팩션 → oplog/A 세그먼트(<= head) 삭제.
        _compact(a, provider, tmp_path, gc=True)
        remaining = [rf.path for rf in provider.list_files("oplog/A/")]
        assert remaining == []

        # 스냅샷 이후 새 op.
        a.repo.save(VideoAggregate.create(VideoUrl(_URL3), "영상3"))
        a.push()  # seq 3

        # 신규 C: 스냅샷 부트스트랩(영상1·2) + 증분 pull(영상3).
        ok, db_c, state_c = _bootstrap("C", tmp_path, provider)
        assert ok
        assert _titles(db_c) == {"영상1", "영상2"}

        c_db = Database(db_c)
        c_state = SyncStateStore(tmp_path / "C_state.json")
        from infrastructure.sync.cloud_oplog_store import CloudOplogStore
        from infrastructure.sync.device import LamportClock
        from infrastructure.sync.keyring_secret_store import KeyringSecretStore
        from infrastructure.sync.merge_applier import MergeApplier
        secret = KeyringSecretStore("s", tmp_path / "C_secret.json", use_file=True)
        applier = MergeApplier(c_db, LamportClock(secret))
        PullHandler(
            "C", CloudOplogStore(provider), applier, c_state, frozenset(MIGRATION_IDS)
        ).handle()
        assert _titles(db_c) == {"영상1", "영상2", "영상3"}
