"""OplogRecorder — 로컬 변경을 op 로그로 캡처하고 병합 레지스터(sync_* 테이블)를 갱신한다.

RecordingRepository 데코레이터가 엔티티별 (old_values, new_values)를 계산해 넘기면,
여기서 일반적인 diff → 필드별 clock 갱신 → op append 를 수행한다.

참조(FK)는 old/new dict에서 "__ref__" 접두 키로 표현한다 — op.refs로 분리되어 저장되고
applier(Phase 3)가 자연키→로컬 UUID로 해석한다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from domain.sync.value_objects import Op, OpKind

logger = logging.getLogger(__name__)

_REF_PREFIX = "__ref__"


class OplogRecorder:
    def __init__(self, db, oplog_store, clock, install_id: str) -> None:
        self._db = db                # infrastructure.persistence.database.Database
        self._oplog = oplog_store    # IOplogStore (로컬)
        self._clock = clock          # LamportClock
        self._install = install_id

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def record_change(
        self,
        entity: str,
        nkey: str,
        local_uuid: str,
        old_values: dict,
        new_values: dict,
    ) -> Op | None:
        """upsert 변경을 기록한다. 바뀐 필드가 없고 이미 존재하면 no-op(None)."""
        changed = {k: v for k, v in new_values.items() if old_values.get(k) != v}
        exists = self._identity_exists(entity, nkey)
        if not changed and exists:
            return None

        lam = self._clock.tick()
        fields: dict = {}
        refs: dict = {}
        for k, v in changed.items():
            if k.startswith(_REF_PREFIX):
                refs[k[len(_REF_PREFIX):]] = v
            else:
                fields[k] = v

        op = Op(
            op_id=str(uuid4()),
            install_id=self._install,
            lamport=lam,
            wall_utc=self._now(),
            entity=entity,
            nkey=nkey,
            kind=OpKind.UPSERT,
            fields=fields,
            refs=refs,
        )
        self._persist_upsert(entity, nkey, local_uuid, lam, changed.keys(), op.op_id)
        self._oplog.append([op])
        return op

    def record_delete(self, entity: str, nkey: str) -> Op | None:
        """삭제(tombstone)를 기록한다. 로컬에 식별자가 없으면 no-op."""
        if not self._identity_exists(entity, nkey):
            return None
        lam = self._clock.tick()
        op = Op(
            op_id=str(uuid4()),
            install_id=self._install,
            lamport=lam,
            wall_utc=self._now(),
            entity=entity,
            nkey=nkey,
            kind=OpKind.DELETE,
        )
        with self._db.connection() as conn:
            conn.execute(
                "UPDATE sync_identity SET present=0, pres_lamport=?, pres_install=? "
                "WHERE entity=? AND nkey=?",
                (lam, self._install, entity, nkey),
            )
            conn.execute(
                "INSERT OR IGNORE INTO sync_applied_ops(op_id, applied_at) VALUES (?, ?)",
                (op.op_id, self._now()),
            )
        self._oplog.append([op])
        return op

    # -- 내부 ------------------------------------------------------------
    def _identity_exists(self, entity: str, nkey: str) -> bool:
        with self._db.connection() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM sync_identity WHERE entity=? AND nkey=?", (entity, nkey)
                ).fetchone()
                is not None
            )

    def _persist_upsert(self, entity, nkey, local_uuid, lam, changed_keys, op_id) -> None:
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO sync_identity(entity, nkey, local_uuid, present, pres_lamport, pres_install)
                VALUES (?,?,?,1,?,?)
                ON CONFLICT(entity, nkey) DO UPDATE SET
                    present=1, pres_lamport=excluded.pres_lamport, pres_install=excluded.pres_install
                """,
                (entity, nkey, local_uuid, lam, self._install),
            )
            for field_name in changed_keys:
                conn.execute(
                    """
                    INSERT INTO sync_field_clock(entity, nkey, field, lamport, install)
                    VALUES (?,?,?,?,?)
                    ON CONFLICT(entity, nkey, field) DO UPDATE SET
                        lamport=excluded.lamport, install=excluded.install
                    """,
                    (entity, nkey, field_name, lam, self._install),
                )
            conn.execute(
                "INSERT OR IGNORE INTO sync_applied_ops(op_id, applied_at) VALUES (?, ?)",
                (op_id, self._now()),
            )
