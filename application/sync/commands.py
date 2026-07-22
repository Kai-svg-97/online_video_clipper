"""sync 유스케이스 핸들러 (Push/Pull/SyncNow/Connect/Disconnect).

의존성(로컬 oplog store, cloud oplog store, applier, state store, provider 등)은 생성자
주입으로 받는다(구조적 타이핑). composition root(main.py)가 구체 구현을 배선한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from domain.sync.services import SyncSchemaError, schema_ids_supported

logger = logging.getLogger(__name__)


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
