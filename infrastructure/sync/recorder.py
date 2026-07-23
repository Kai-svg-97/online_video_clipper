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

from domain.sync.services import origin_key
from domain.sync.value_objects import Op, OpKind

logger = logging.getLogger(__name__)

_REF_PREFIX = "__ref__"


class OplogRecorder:
    def __init__(self, db, oplog_store, clock, install_id: str, schema_ids=frozenset()) -> None:
        self._db = db                # infrastructure.persistence.database.Database
        self._oplog = oplog_store    # IOplogStore (로컬)
        self._clock = clock          # LamportClock
        self._install = install_id
        self._schema_ids = frozenset(schema_ids)  # op 기록 시점의 스키마 능력(게이트용)

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
        # present면(그리고 바뀐 필드 없으면) no-op. present=0(tombstone)이면 되살리기 위해
        # 변경이 없어도 진행한다(링크의 remove→재add 등).
        if not changed and self._presence(entity, nkey) == 1:
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
            schema_ids=self._schema_ids,
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
            schema_ids=self._schema_ids,
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

    def record_link(
        self, entity: str, nkey: str, local_uuid: str, refs: dict
    ) -> Op | None:
        """링크(조인 행) 생성을 기록한다. 이미 present면 no-op.

        링크는 자체 필드가 없고 **양 끝점을 refs로** 실어 보낸다(applier가 nkey/ref로 해석).
        refs가 있어야 merge의 writes에 남아 upserts()에 포함된다(presence-only는 미반영).
        """
        if self._presence(entity, nkey) == 1:
            return None
        lam = self._clock.tick()
        op = Op(
            op_id=str(uuid4()),
            install_id=self._install,
            lamport=lam,
            wall_utc=self._now(),
            entity=entity,
            nkey=nkey,
            kind=OpKind.LINK,
            fields={},
            refs=dict(refs),
            schema_ids=self._schema_ids,
        )
        changed_keys = [f"{_REF_PREFIX}{k}" for k in refs]
        self._persist_upsert(entity, nkey, local_uuid, lam, changed_keys, op.op_id)
        self._oplog.append([op])
        return op

    def record_unlink(self, entity: str, nkey: str) -> Op | None:
        """링크 제거(tombstone)를 기록한다. 이미 부재면 no-op."""
        if self._presence(entity, nkey) != 1:
            return None
        lam = self._clock.tick()
        op = Op(
            op_id=str(uuid4()),
            install_id=self._install,
            lamport=lam,
            wall_utc=self._now(),
            entity=entity,
            nkey=nkey,
            kind=OpKind.UNLINK,
            schema_ids=self._schema_ids,
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

    def origin_nkey(self, entity: str, local_uuid: str) -> str:
        """origin-identity 엔티티(카테고리·재생목록 등)의 자연키를 구한다.

        이미 이 로컬 UUID로 등록된 nkey가 있으면(다른 기기가 만든 걸 우리가 받은 경우 포함)
        그것을 재사용하고, 없으면(여기서 처음 생성) origin_key(this_install, local_uuid)를
        만든다. 등록(sync_identity 반영)은 record_change의 _persist_upsert가 담당한다.
        """
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT nkey FROM sync_identity WHERE entity=? AND local_uuid=?",
                (entity, local_uuid),
            ).fetchone()
        return row["nkey"] if row else origin_key(self._install, local_uuid)

    # -- 내부 ------------------------------------------------------------
    def _presence(self, entity: str, nkey: str) -> int | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT present FROM sync_identity WHERE entity=? AND nkey=?", (entity, nkey)
            ).fetchone()
        return row["present"] if row else None

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
