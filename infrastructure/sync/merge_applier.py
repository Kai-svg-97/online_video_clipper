"""MergeApplier — 병합된 op를 라이브 DB에 반영한다.

OpLogMerger(순수)로 승자를 계산한 뒤, 자연키→로컬 UUID를 해석하고 FK를 재작성해
엔티티 타입 위상 순서로 라이브 테이블에 직접 적용한다. 적용은 **plain 리포지토리/직접
SQL**로 하므로 RecordingRepository가 개입하지 않는다 → 원격 op를 다시 op로 기록하는
루프가 생기지 않는다. FTS 트리거는 테이블에 걸려 있어 직접 write에도 정상 발화하고,
rowid는 로컬에서 재할당된다(이식성 문제 없음).

Phase 3에서는 video upsert/delete + category 참조 해석을 구현한다. 다른 엔티티 핸들러는
후속 Phase에서 registry에 추가한다.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from uuid import uuid4

from domain.sync.services import (
    OpLogMerger,
    category_key,
    split_category_key,
    topo_order,
)
from domain.sync.value_objects import (
    ClockEntry,
    EntityKey,
    Op,
)
from domain.sync.services import FieldEntry, MergeResult, MergeState, PresenceEntry

logger = logging.getLogger(__name__)

_REF = "__ref__"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MergeApplier:
    def __init__(self, db, clock, handlers: dict | None = None) -> None:
        self._db = db
        self._clock = clock
        self._handlers = handlers or {"video": VideoApplyHandler()}
        self._merger = OpLogMerger()

    def apply(self, ops: list[Op]) -> MergeResult:
        ops = list(ops)
        keys = {op.entity_key for op in ops}
        op_ids = {op.op_id for op in ops}

        with self._db.connection() as conn:
            state = self._load_state(conn, keys, op_ids)

        result = self._merger.merge(ops, state)
        if not result.newly_applied:
            return result

        with self._db.connection() as conn:
            uuid_map = self._resolve_uuids(conn, result.changed)
            self._apply_changes(conn, result, uuid_map)
            self._persist_state(conn, result, uuid_map)

        max_lam = max((op.lamport for op in ops), default=0)
        self._clock.observe(max_lam)
        return result

    # -- 상태 로드 --------------------------------------------------------
    def _load_state(self, conn, keys, op_ids) -> MergeState:
        presence: dict = {}
        fields: dict = {}
        refs: dict = {}
        for ek in keys:
            row = conn.execute(
                "SELECT present, pres_lamport, pres_install FROM sync_identity "
                "WHERE entity=? AND nkey=?",
                (ek.entity, ek.nkey),
            ).fetchone()
            if row is not None:
                presence[ek] = PresenceEntry(
                    ClockEntry(row["pres_lamport"], row["pres_install"]),
                    bool(row["present"]),
                )
            for fc in conn.execute(
                "SELECT field, lamport, install FROM sync_field_clock "
                "WHERE entity=? AND nkey=?",
                (ek.entity, ek.nkey),
            ).fetchall():
                ce = ClockEntry(fc["lamport"], fc["install"])
                name = fc["field"]
                # 값은 clock 테이블에 없음(None) — LWW 판정엔 clock만 필요.
                if name.startswith(_REF):
                    refs.setdefault(ek, {})[name[len(_REF):]] = FieldEntry(ce, None)
                else:
                    fields.setdefault(ek, {})[name] = FieldEntry(ce, None)

        applied = set()
        for oid in op_ids:
            if conn.execute(
                "SELECT 1 FROM sync_applied_ops WHERE op_id=?", (oid,)
            ).fetchone():
                applied.add(oid)
        return MergeState(presence=presence, fields=fields, refs=refs, applied_op_ids=applied)

    def _resolve_uuids(self, conn, changed) -> dict[EntityKey, str]:
        out: dict[EntityKey, str] = {}
        for ek in changed:
            row = conn.execute(
                "SELECT local_uuid FROM sync_identity WHERE entity=? AND nkey=?",
                (ek.entity, ek.nkey),
            ).fetchone()
            out[ek] = row["local_uuid"] if row else str(uuid4())
        return out

    # -- 적용 -------------------------------------------------------------
    def _apply_changes(self, conn, result: MergeResult, uuid_map) -> None:
        upserts = result.upserts()
        deletions = result.deletions()
        by_entity: dict[str, list[EntityKey]] = defaultdict(list)
        for ek in result.changed:
            by_entity[ek.entity].append(ek)

        for entity in topo_order(by_entity.keys()):
            handler = self._handlers.get(entity)
            if handler is None:
                logger.warning("적용 핸들러 없는 엔티티 건너뜀: %s", entity)
                continue
            for ek in by_entity[entity]:
                luuid = uuid_map[ek]
                if ek in deletions:
                    handler.delete(conn, luuid, ek.nkey)
                elif ek in upserts:
                    w = upserts[ek]
                    field_vals = {k: v for k, v in w.items() if not k.startswith(_REF)}
                    ref_vals = {
                        k[len(_REF):]: v for k, v in w.items() if k.startswith(_REF)
                    }
                    handler.upsert(conn, luuid, ek.nkey, field_vals, ref_vals, self)

    def _persist_state(self, conn, result: MergeResult, uuid_map) -> None:
        for ek in result.changed:
            pe = result.state.presence.get(ek)
            if pe is not None:
                conn.execute(
                    """
                    INSERT INTO sync_identity(entity, nkey, local_uuid, present, pres_lamport, pres_install)
                    VALUES (?,?,?,?,?,?)
                    ON CONFLICT(entity, nkey) DO UPDATE SET
                        present=excluded.present,
                        pres_lamport=excluded.pres_lamport,
                        pres_install=excluded.pres_install
                    """,
                    (
                        ek.entity, ek.nkey, uuid_map[ek],
                        1 if pe.present else 0, pe.clock.lamport, pe.clock.install_id,
                    ),
                )
            for name, fe in result.state.fields.get(ek, {}).items():
                self._upsert_clock(conn, ek, name, fe.clock)
            for name, fe in result.state.refs.get(ek, {}).items():
                self._upsert_clock(conn, ek, _REF + name, fe.clock)

        now = _now_iso()
        for op_id in result.newly_applied:
            conn.execute(
                "INSERT OR IGNORE INTO sync_applied_ops(op_id, applied_at) VALUES (?, ?)",
                (op_id, now),
            )

    @staticmethod
    def _upsert_clock(conn, ek: EntityKey, field_name: str, clk: ClockEntry) -> None:
        conn.execute(
            """
            INSERT INTO sync_field_clock(entity, nkey, field, lamport, install)
            VALUES (?,?,?,?,?)
            ON CONFLICT(entity, nkey, field) DO UPDATE SET
                lamport=excluded.lamport, install=excluded.install
            """,
            (ek.entity, ek.nkey, field_name, clk.lamport, clk.install_id),
        )

    # -- 참조 해석 (핸들러가 호출) ---------------------------------------
    def resolve_category(self, conn, cat_nkey: str | None) -> str | None:
        """카테고리 자연키(이름 경로) → 로컬 UUID. 없으면 경로를 따라 생성."""
        if not cat_nkey:
            return None
        row = conn.execute(
            "SELECT local_uuid FROM sync_identity WHERE entity='category' AND nkey=?",
            (cat_nkey,),
        ).fetchone()
        if row:
            return row["local_uuid"]
        # 경로를 따라 카테고리를 생성하며 내려간다.
        names = split_category_key(cat_nkey)
        parent_id: str | None = None
        for depth in range(len(names)):
            sub_nkey = category_key(names[: depth + 1])
            existing = conn.execute(
                "SELECT local_uuid FROM sync_identity WHERE entity='category' AND nkey=?",
                (sub_nkey,),
            ).fetchone()
            if existing:
                parent_id = existing["local_uuid"]
                continue
            new_uuid = str(uuid4())
            conn.execute(
                "INSERT INTO categories(id, name, parent_id) VALUES (?,?,?)",
                (new_uuid, names[depth], parent_id),
            )
            conn.execute(
                "INSERT OR IGNORE INTO sync_identity(entity, nkey, local_uuid, present, pres_lamport, pres_install) "
                "VALUES ('category', ?, ?, 1, 0, '')",
                (sub_nkey, new_uuid),
            )
            parent_id = new_uuid
        return parent_id


class VideoApplyHandler:
    """video 엔티티의 라이브 테이블 반영(직접 SQL, 부분 컬럼 갱신)."""

    _COLS = (
        "title",
        "notes",
        "favorite",
        "watched",
        "thumbnail_path",
        "gemini_summary",
        "channel_name",
        "channel_url",
        "channel_id",
        "duration_sec",
        "published_at",
    )

    def upsert(self, conn, local_uuid, nkey, fields, refs, applier) -> None:
        exists = conn.execute(
            "SELECT 1 FROM videos WHERE id=?", (local_uuid,)
        ).fetchone()
        cat_id = None
        if "category" in refs:
            cat_id = applier.resolve_category(conn, refs["category"])

        if exists:
            sets, vals = [], []
            for col in self._COLS:
                if col in fields:
                    sets.append(f"{col}=?")
                    vals.append(fields[col])
            if "category" in refs:
                sets.append("category_id=?")
                vals.append(cat_id)
            if sets:
                sets.append("updated_at=?")
                vals.append(_now_iso())
                conn.execute(
                    f"UPDATE videos SET {', '.join(sets)} WHERE id=?", (*vals, local_uuid)
                )
        else:
            now = _now_iso()
            conn.execute(
                """
                INSERT INTO videos
                    (id, url, title, channel_name, channel_url, channel_id,
                     duration_sec, published_at, view_count, favorite, watched,
                     notes, gemini_summary, thumbnail_path, category_id, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    local_uuid, nkey, fields.get("title", ""),
                    fields.get("channel_name"), fields.get("channel_url"),
                    fields.get("channel_id"), fields.get("duration_sec"),
                    fields.get("published_at"), None,
                    int(fields.get("favorite", 0)), int(fields.get("watched", 0)),
                    fields.get("notes", ""), fields.get("gemini_summary", ""),
                    fields.get("thumbnail_path", ""), cat_id, now, now,
                ),
            )

    def delete(self, conn, local_uuid, nkey) -> None:
        conn.execute("DELETE FROM videos WHERE id=?", (local_uuid,))
