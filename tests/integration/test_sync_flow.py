"""sync 흐름 통합 테스트 — fake provider로 두 install 왕복(push/pull/merge)."""

from __future__ import annotations

import shutil
from pathlib import Path
from uuid import UUID

import pytest

from application.sync.commands import (
    PullHandler,
    PushHandler,
    SyncNowHandler,
)
from application.sync.ports import RemoteFile
from application.sync.queries import GetSyncStatusHandler
from domain.library.aggregates import VideoAggregate
from domain.library.value_objects import ChannelInfo, VideoUrl
from domain.sync.services import SyncSchemaError, video_key
from domain.sync.value_objects import Op, OpKind
from infrastructure.persistence.database import MIGRATION_IDS, Database
from infrastructure.sync.cloud_oplog_store import CloudOplogStore
from infrastructure.sync.device import LamportClock
from infrastructure.sync.keyring_secret_store import KeyringSecretStore
from infrastructure.sync.local_oplog_store import LocalOplogStore
from infrastructure.sync.merge_applier import MergeApplier
from infrastructure.sync.recorder import OplogRecorder
from infrastructure.sync.recording_repository import RecordingVideoRepository
from infrastructure.sync.sync_state import SyncStateStore

_URL = "https://www.youtube.com/watch?v=abc12345678"
_NK = video_key(_URL)


class FakeCloudProvider:
    """temp 디렉터리 기반 ICloudSyncProvider 테스트 더블."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def provider_key(self) -> str:
        return "fake"

    def is_authenticated(self) -> bool:
        return True

    def account_name(self) -> str | None:
        return "tester@example.com"

    def ensure_root(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

    def _abs(self, remote_path: str) -> Path:
        return self._root / remote_path

    def list_files(self, prefix: str = "") -> list[RemoteFile]:
        out: list[RemoteFile] = []
        for p in self._root.rglob("*"):
            if p.is_file():
                rel = p.relative_to(self._root).as_posix()
                if rel.startswith(prefix):
                    out.append(RemoteFile(path=rel, size=p.stat().st_size, modified=""))
        return out

    def stat(self, remote_path: str) -> RemoteFile | None:
        p = self._abs(remote_path)
        if not p.is_file():
            return None
        return RemoteFile(path=remote_path, size=p.stat().st_size, modified="")

    def upload_file(self, local_path, remote_path, on_progress=None) -> RemoteFile:
        dest = self._abs(remote_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_path, dest)
        return RemoteFile(path=remote_path, size=dest.stat().st_size, modified="")

    def download_file(self, remote_path, local_path, on_progress=None) -> None:
        shutil.copyfile(self._abs(remote_path), local_path)

    def delete_file(self, remote_path: str) -> None:
        self._abs(remote_path).unlink(missing_ok=True)

    def read_text(self, remote_path: str) -> str | None:
        p = self._abs(remote_path)
        return p.read_text(encoding="utf-8") if p.is_file() else None

    def write_text(self, remote_path: str, content: str) -> None:
        dest = self._abs(remote_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")


class Install:
    """한 기기의 sync 스택 묶음(테스트 편의)."""

    def __init__(self, tmp_path: Path, name: str, provider: FakeCloudProvider) -> None:
        self.name = name
        self.db = Database(tmp_path / f"{name}.db")
        self.db.initialize()
        secret = KeyringSecretStore("s", tmp_path / f"{name}_secret.json", use_file=True)
        self.clock = LamportClock(secret)
        self.local = LocalOplogStore(tmp_path / f"{name}_pending", name)
        self.recorder = OplogRecorder(
            self.db, self.local, self.clock, name, schema_ids=frozenset(MIGRATION_IDS)
        )
        self.repo = RecordingVideoRepository(self.db, self.recorder)
        self.cloud = CloudOplogStore(provider)
        self.state = SyncStateStore(tmp_path / f"{name}_state.json")
        self.applier = MergeApplier(self.db, self.clock)

    def push(self) -> int:
        return PushHandler(self.name, self.local, self.cloud, self.state).handle()

    def pull(self) -> int:
        return PullHandler(
            self.name, self.cloud, self.applier, self.state, frozenset(MIGRATION_IDS)
        ).handle()

    def video(self, nkey=_NK):
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT title, notes, favorite, channel_id FROM videos WHERE url=?", (nkey,)
            ).fetchone()
            return dict(row) if row else None


@pytest.fixture()
def provider(tmp_path):
    return FakeCloudProvider(tmp_path / "cloud")


class TestRoundTrip:
    def test_a_push_b_pull(self, tmp_path, provider):
        a = Install(tmp_path, "A", provider)
        b = Install(tmp_path, "B", provider)

        # A: 영상 생성 + 메모 편집
        agg = VideoAggregate.create(
            VideoUrl(_URL), "제목", channel=ChannelInfo("Ch", "http://c", "UC1")
        )
        a.repo.save(agg)
        agg.update_metadata(notes="A의 메모")
        a.repo.save(agg)

        assert a.push() == 2                 # 세그먼트 2개(생성+편집)
        assert b.video() is None             # 아직 pull 안 함
        assert b.pull() > 0                  # A의 op 적용

        v = b.video()
        assert v is not None
        assert v["title"] == "제목"
        assert v["notes"] == "A의 메모"
        assert v["channel_id"] == "UC1"

    def test_idempotent_pull(self, tmp_path, provider):
        a = Install(tmp_path, "A", provider)
        b = Install(tmp_path, "B", provider)
        a.repo.save(VideoAggregate.create(VideoUrl(_URL), "t"))
        a.push()
        assert b.pull() > 0
        assert b.pull() == 0                 # consumed 최신 → 재적용 없음

    def test_bidirectional_convergence(self, tmp_path, provider):
        a = Install(tmp_path, "A", provider)
        b = Install(tmp_path, "B", provider)
        # A가 생성·push, B가 받음
        agg_a = VideoAggregate.create(VideoUrl(_URL), "제목")
        a.repo.save(agg_a)
        a.push()
        b.pull()
        # B에서 nkey로 로드해 편집(B의 로컬 uuid 사용 — A와 uuid는 달라도 nkey는 동일)
        with b.db.connection() as conn:
            row = conn.execute("SELECT id FROM videos WHERE url=?", (_NK,)).fetchone()
        b_agg = b.repo.get_by_id(UUID(row["id"]))
        b_agg.update_metadata(notes="B의 메모", favorite=True)
        b.repo.save(b_agg)
        b.push()
        a.pull()
        va = a.video()
        assert va["notes"] == "B의 메모"
        assert va["favorite"] == 1


class TestSchemaGate:
    def test_pull_blocks_unknown_schema(self, tmp_path, provider):
        b = Install(tmp_path, "B", provider)
        future_op = Op(
            op_id="fx", install_id="C", lamport=1, wall_utc="2099",
            entity="video", nkey=_NK, kind=OpKind.UPSERT,
            fields={"title": "future"},
            schema_ids=frozenset({"migrate_from_the_future"}),
        )
        b.cloud.put_ops("C", 1, [future_op])
        with pytest.raises(SyncSchemaError):
            b.pull()


class TestStatus:
    def test_status_dto(self, tmp_path, provider):
        a = Install(tmp_path, "A", provider)
        a.repo.save(VideoAggregate.create(VideoUrl(_URL), "t"))
        a.push()
        dto = GetSyncStatusHandler(a.state, provider).handle()
        assert dto.connected is True
        assert dto.account_name == "tester@example.com"
        assert dto.pushed_head == 1
        assert dto.last_push_utc

    def test_sync_now(self, tmp_path, provider):
        a = Install(tmp_path, "A", provider)
        b = Install(tmp_path, "B", provider)
        a.repo.save(VideoAggregate.create(VideoUrl(_URL), "t"))
        a.push()
        # B의 SyncNow = push(없음) + pull(A의 op)
        push_pull = SyncNowHandler(
            PushHandler("B", b.local, b.cloud, b.state),
            PullHandler("B", b.cloud, b.applier, b.state, frozenset(MIGRATION_IDS)),
        ).handle()
        assert push_pull[1] > 0
        assert b.video() is not None
