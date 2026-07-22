"""sync 유스케이스 핸들러 (Push/Pull/SyncNow/Connect/Disconnect).

의존성(로컬 oplog store, cloud oplog store, applier, state store, provider 등)은 생성자
주입으로 받는다(구조적 타이핑). composition root(main.py)가 구체 구현을 배선한다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from domain.sync.services import SyncSchemaError, schema_ids_supported
from domain.sync.value_objects import SnapshotManifest

logger = logging.getLogger(__name__)

# 컴팩션 스냅샷의 원격 경로.
_SNAPSHOT_DB = "snapshot/library.db"
_SNAPSHOT_MANIFEST = "snapshot/snapshot.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PushHandler:
    """우리 install의 아직 안 올린 로컬 세그먼트를 클라우드로 업로드한다."""

    install_id: str
    local_store: object   # LocalOplogStore
    cloud_store: object   # CloudOplogStore
    state_store: object   # SyncStateStore

    def handle(self) -> int:
        state = self.state_store.load()
        head = self.local_store.head_seq(self.install_id)
        for seq in range(state.pushed_head + 1, head + 1):
            ops = self.local_store.read_segment(self.install_id, seq)
            if ops:
                self.cloud_store.put_ops(self.install_id, seq, ops)
        if head > state.pushed_head:
            reg = self.cloud_store.read_registry()
            reg[self.install_id] = head
            self.cloud_store.write_registry(reg)
            state.pushed_head = head
        state.last_push_utc = _now()
        self.state_store.save(state)
        return head


@dataclass
class PullHandler:
    """다른 install들의 새 op를 받아 병합·적용한다."""

    install_id: str
    cloud_store: object   # CloudOplogStore
    applier: object       # MergeApplier
    state_store: object   # SyncStateStore
    local_migration_ids: frozenset

    def handle(self) -> int:
        state = self.state_store.load()
        installs = self.cloud_store.list_installs()

        all_ops = []
        new_heads: dict[str, int] = {}
        for install, head in installs.items():
            if install == self.install_id:
                continue
            after = state.consumed.get(install, 0)
            if head <= after:
                continue
            all_ops.extend(self.cloud_store.read_since(install, after))
            new_heads[install] = head

        # 스키마 게이트: 로컬이 모르는 스키마의 op가 있으면 차단(앱 업데이트 필요)
        for op in all_ops:
            if not schema_ids_supported(op.schema_ids, self.local_migration_ids):
                raise SyncSchemaError(
                    "원격 변경이 더 최신 스키마를 요구합니다 — 앱 업데이트가 필요합니다."
                )

        if all_ops:
            self.applier.apply(all_ops)

        for install, head in new_heads.items():
            state.consumed[install] = head
        state.last_pull_utc = _now()
        self.state_store.save(state)
        return len(all_ops)


@dataclass
class SyncNowHandler:
    """수동 '지금 동기화' — push 후 pull(양방향 수렴)."""

    push: PushHandler
    pull: PullHandler

    def handle(self) -> tuple[int, int]:
        pushed = self.push.handle()
        pulled = self.pull.handle()
        return pushed, pulled


@dataclass
class ConnectProviderHandler:
    """provider 연결 표시(실제 OAuth는 provider 어댑터가 수행). state에 provider_key 기록."""

    state_store: object

    def handle(self, provider_key: str) -> None:
        state = self.state_store.load()
        state.provider_key = provider_key
        self.state_store.save(state)


@dataclass
class CompactHandler:
    """현재 DB를 스냅샷으로 export → provider에 업로드(+manifest 발행) → (선택) 덮인 세그먼트 GC.

    covered[install] = 이 스냅샷이 반영한 해당 install의 마지막 seq. 우리 install은 로컬에서
    작성돼 DB에 이미 있으므로 pushed_head, 다른 install은 우리가 병합한 consumed[install].

    GC는 **기본 비활성**(gc=False). 스냅샷이 덮은 세그먼트를 지우면 그 seq를 아직 소비하지
    못한(뒤처진/휴면) install은 증분 pull로 회수할 수 없고 스냅샷 부트스트랩에 의존하게 된다.
    완전 안전 GC는 활성 install들의 consumed 워터마크 공유가 필요하므로(열린 결정) 명시적으로
    켤 때만 수행한다.
    """

    install_id: str
    snapshot_store: object   # ISnapshotStore
    provider: object         # ICloudSyncProvider
    state_store: object      # SyncStateStore
    tmp_dir: object          # Path — 스냅샷 export 임시 위치
    gc: bool = False

    def handle(self) -> SnapshotManifest:
        state = self.state_store.load()
        covered = dict(state.consumed)
        covered[self.install_id] = max(covered.get(self.install_id, 0), state.pushed_head)

        tmp = Path(self.tmp_dir) / "snapshot_export.db"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        sha = self.snapshot_store.export_snapshot(tmp)
        manifest = SnapshotManifest(
            covered=covered,
            schema_ids=self.snapshot_store.local_migration_ids(),
            db_sha256=sha,
            utc=_now(),
        )
        self.provider.ensure_root()
        self.provider.upload_file(tmp, _SNAPSHOT_DB)
        self.provider.write_text(
            _SNAPSHOT_MANIFEST, json.dumps(manifest.to_dict(), ensure_ascii=False)
        )
        if self.gc:
            self._gc_segments(covered)
        tmp.unlink(missing_ok=True)
        logger.info("컴팩션 스냅샷 발행: covered=%s gc=%s", covered, self.gc)
        return manifest

    def _gc_segments(self, covered: dict[str, int]) -> None:
        for install, upto in covered.items():
            for rf in self.provider.list_files(f"oplog/{install}/"):
                stem = rf.path.split("/")[-1]
                if stem.endswith(".ndjson"):
                    s = stem[: -len(".ndjson")]
                    if s.isdigit() and int(s) <= upto:
                        self.provider.delete_file(rf.path)


@dataclass
class DisconnectProviderHandler:
    state_store: object
    secret_store: object | None = None
    token_keys: tuple[str, ...] = ()

    def handle(self) -> None:
        state = self.state_store.load()
        state.provider_key = ""
        self.state_store.save(state)
        if self.secret_store is not None:
            for key in self.token_keys:
                try:
                    self.secret_store.delete(key)
                except Exception:
                    logger.exception("토큰 삭제 실패: %s", key)
