"""sync 인프라 통합 테스트 (실제 SQLite·파일 I/O)."""

from __future__ import annotations

import pytest

from domain.library.aggregates import VideoAggregate
from domain.library.entities import Category
from domain.library.value_objects import ChannelInfo, VideoUrl
from domain.sync.services import category_key, video_key
from domain.sync.value_objects import Op, OpKind
from infrastructure.persistence.database import MIGRATION_IDS, Database
from infrastructure.sync.device import Device, LamportClock
from infrastructure.sync.keyring_secret_store import KeyringSecretStore
from infrastructure.sync.local_oplog_store import LocalOplogStore
from infrastructure.sync.recorder import OplogRecorder
from infrastructure.sync.recording_repository import RecordingVideoRepository
from infrastructure.sync.snapshot_store import SnapshotStore, SyncSchemaError


@pytest.fixture()
def db(tmp_path):
    d = Database(tmp_path / "library.db")
    d.initialize()
    return d


def _op(op_id, lam, entity="video", nkey="vk", kind=OpKind.UPSERT, fields=None):
    return Op(
        op_id=op_id, install_id="A", lamport=lam, wall_utc="2026-01-01T00:00:00",
        entity=entity, nkey=nkey, kind=kind, fields=fields or {},
    )


class TestKeyringSecretStore:
    def test_file_fallback_round_trip(self, tmp_path):
        s = KeyringSecretStore("test.svc", tmp_path / "secrets.json", use_file=True)
        assert s.get("k") is None
        s.set("k", "v1")
        assert s.get("k") == "v1"
        s.set("k", "v2")
        assert s.get("k") == "v2"
        s.delete("k")
        assert s.get("k") is None

    def test_persists_to_disk(self, tmp_path):
        p = tmp_path / "secrets.json"
        KeyringSecretStore("svc", p, use_file=True).set("token", "abc")
        assert "abc" in p.read_text()
        assert KeyringSecretStore("svc", p, use_file=True).get("token") == "abc"


class TestDeviceAndClock:
    def test_install_id_stable(self, tmp_path):
        s = KeyringSecretStore("svc", tmp_path / "s.json", use_file=True)
        dev = Device(s)
        first = dev.install_id()
        assert first
        assert dev.install_id() == first
        assert Device(s).install_id() == first  # 재구성해도 동일(영속)

    def test_lamport_monotonic(self, tmp_path):
        s = KeyringSecretStore("svc", tmp_path / "s.json", use_file=True)
        clk = LamportClock(s)
        assert clk.current() == 0
        assert clk.tick() == 1
        assert clk.tick() == 2
        clk.observe(10)
        assert clk.tick() == 11
        clk.observe(5)  # 더 작은 값은 무시
        assert clk.tick() == 12


class TestLocalOplogStore:
    def test_append_read_roundtrip(self, tmp_path):
        store = LocalOplogStore(tmp_path / "pending", "A")
        assert store.head_seq("A") == 0
        assert store.append([_op("o1", 1)]) == 1
        assert store.append([_op("o2", 2), _op("o3", 3)]) == 2
        assert store.head_seq("A") == 2
        got = store.read_since("A", 0)
        assert [o.op_id for o in got] == ["o1", "o2", "o3"]
        assert store.read_since("A", 1) == store.read_since("A", 1)
        assert [o.op_id for o in store.read_since("A", 1)] == ["o2", "o3"]

    def test_list_installs(self, tmp_path):
        base = tmp_path / "pending"
        LocalOplogStore(base, "A").append([_op("o1", 1)])
        LocalOplogStore(base, "B").append([_op("o2", 1)])
        assert LocalOplogStore(base, "A").list_installs() == {"A": 1, "B": 1}


class TestSnapshotStore:
    def test_export_import_roundtrip(self, tmp_path, db):
        # seed a row
        with db.connection() as conn:
            conn.execute(
                "INSERT INTO tags(id, name) VALUES ('t1', 'rock')"
            )
        store = SnapshotStore(db._path, MIGRATION_IDS)
        snap = tmp_path / "snap.db"
        sha = store.export_snapshot(snap)
        assert snap.exists() and len(sha) == 64

        # import into a fresh target db path
        target = tmp_path / "target.db"
        tstore = SnapshotStore(target, MIGRATION_IDS)
        # 재-export한 사본을 import (import는 src를 소비/rename하므로 별도 파일 사용)
        src_copy = tmp_path / "src.db"
        store.export_snapshot(src_copy)
        tstore.import_snapshot(src_copy, tmp_path / "backups")
        assert target.exists()
        import sqlite3
        with sqlite3.connect(target) as c:
            assert c.execute("SELECT name FROM tags WHERE id='t1'").fetchone()[0] == "rock"

    def test_import_backs_up_current(self, tmp_path, db):
        store = SnapshotStore(db._path, MIGRATION_IDS)
        src = tmp_path / "src.db"
        store.export_snapshot(src)
        backups = tmp_path / "backups"
        store.import_snapshot(src, backups)  # db already exists → should back up
        conflict = list((backups / "sync-conflict").glob("library-*.db"))
        assert len(conflict) == 1

    def test_schema_gate_blocks_newer(self, tmp_path, db):
        store = SnapshotStore(db._path, MIGRATION_IDS)
        src = tmp_path / "src.db"
        store.export_snapshot(src)
        # inject an unknown (future) migration id into the snapshot
        import sqlite3
        with sqlite3.connect(src) as c:
            c.execute(
                "INSERT INTO schema_migrations(id, applied_at) VALUES ('migrate_from_future', '2099')"
            )
        with pytest.raises(SyncSchemaError):
            store.import_snapshot(src, tmp_path / "backups")


class TestRecordingVideoRepository:
    def _recorder(self, db, tmp_path):
        clk = LamportClock(KeyringSecretStore("s", tmp_path / "s.json", use_file=True))
        return OplogRecorder(db, LocalOplogStore(tmp_path / "pending", "A"), clk, "A"), \
            LocalOplogStore(tmp_path / "pending", "A")

    def test_create_edit_delete_capture(self, tmp_path, db):
        recorder, oplog = self._recorder(db, tmp_path)
        repo = RecordingVideoRepository(db, recorder)

        # create
        url = VideoUrl("https://www.youtube.com/watch?v=abc12345678")
        agg = VideoAggregate.create(url, "제목", channel=ChannelInfo("Ch", "http://c", "UC1"))
        repo.save(agg)
        nkey = video_key(str(url))
        ops = oplog.read_since("A", 0)
        assert len(ops) == 1
        create_op = ops[0]
        assert create_op.kind is OpKind.UPSERT
        assert create_op.nkey == nkey
        assert create_op.fields["title"] == "제목"
        assert create_op.fields["channel_id"] == "UC1"
        # None 필드(예: gemini_summary="")는 값이 있으니 포함되지만 view_count는 캡처 안 함
        assert "view_count" not in create_op.fields

        # edit only notes → op with ONLY notes changed
        agg.update_metadata(notes="메모")
        repo.save(agg)
        ops = oplog.read_since("A", 0)
        assert len(ops) == 2
        edit_op = ops[1]
        assert set(edit_op.fields.keys()) == {"notes"}
        assert edit_op.fields["notes"] == "메모"
        assert edit_op.lamport > create_op.lamport

        # no-op save (아무 변경 없음) → op 추가 안 됨
        repo.save(agg)
        assert len(oplog.read_since("A", 0)) == 2

        # field clock reflects latest lamport for notes
        with db.connection() as conn:
            row = conn.execute(
                "SELECT lamport FROM sync_field_clock WHERE entity='video' AND field='notes'"
            ).fetchone()
            assert row[0] == edit_op.lamport

        # delete → tombstone op + present=0
        repo.delete(agg.id)
        ops = oplog.read_since("A", 0)
        assert ops[-1].kind is OpKind.DELETE
        with db.connection() as conn:
            pres = conn.execute(
                "SELECT present FROM sync_identity WHERE entity='video' AND nkey=?", (nkey,)
            ).fetchone()
            assert pres[0] == 0

    def test_category_ref_captured(self, tmp_path, db):
        recorder, oplog = self._recorder(db, tmp_path)
        repo = RecordingVideoRepository(db, recorder)
        parent = Category.create("IT")
        child = Category.create("News", parent_id=parent.id)
        repo.save_category(parent)
        repo.save_category(child)

        url = VideoUrl("https://www.youtube.com/watch?v=xyz98765432")
        agg = VideoAggregate.create(url, "t", category_id=child.id)
        repo.save(agg)
        op = oplog.read_since("A", 0)[0]
        assert op.refs.get("category") == category_key(["IT", "News"])
