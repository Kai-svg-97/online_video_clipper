"""sync 컨텍스트 값 객체 (순수 — I/O 없음).

레코드 단위 병합(oplog CRDT)의 기본 타입을 정의한다:
- `Op` — 한 건의 변경 연산(NDJSON 한 줄로 직렬화됨).
- `EntityKey` — (엔티티, 자연키) 식별자. 로컬 UUID가 아니라 머신 독립 자연키를 쓴다.
- `ClockEntry` — Lamport 논리시계 + install_id. 필드/존재 레지스터의 승자 판정 기준.
- `SnapshotManifest` — 컴팩션 스냅샷 메타(어느 install의 어느 seq까지 덮었는지).

병합 규칙: 전순서 = (lamport, install_id). 필드 LWW = 더 큰 ClockEntry가 승자.
동시 다중 쓰기에도 적용 순서와 무관하게 결정적으로 수렴한다(LWW register CRDT).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class OpKind(str, Enum):
    """연산 종류.

    UPSERT/LINK  → 대상 존재(present) + 필드 반영.
    DELETE/UNLINK → 대상 부재(absent) — tombstone.
    """

    UPSERT = "upsert"
    DELETE = "delete"
    LINK = "link"
    UNLINK = "unlink"

    @property
    def is_present(self) -> bool:
        return self in (OpKind.UPSERT, OpKind.LINK)


@dataclass(frozen=True, slots=True, order=True)
class ClockEntry:
    """(lamport, install_id) 논리시계 값. 사전식 비교로 전순서를 이룬다.

    order=True라 정의 순서(lamport → install_id)대로 비교된다. 같은 install은
    lamport가 단조 증가하므로 (lamport, install_id)는 유일하다.
    """

    lamport: int
    install_id: str


@dataclass(frozen=True, slots=True)
class EntityKey:
    """(엔티티 종류, 자연키) — 머신 독립 식별자."""

    entity: str
    nkey: str


@dataclass(frozen=True, slots=True)
class Op:
    """한 건의 변경 연산.

    fields/refs 는 이 연산이 설정하는 컬럼 값과 FK(자연키로 표현)이다.
    field_lamport 는 필드별 개별 lamport(필드 단위 LWW용) — 없으면 op.lamport 사용.
    """

    op_id: str
    install_id: str
    lamport: int
    wall_utc: str
    entity: str
    nkey: str
    kind: OpKind
    fields: dict[str, Any] = field(default_factory=dict)
    field_lamport: dict[str, int] = field(default_factory=dict)
    refs: dict[str, str] = field(default_factory=dict)
    schema_ids: frozenset[str] = field(default_factory=frozenset)

    @property
    def entity_key(self) -> EntityKey:
        return EntityKey(self.entity, self.nkey)

    @property
    def order_key(self) -> tuple[int, str, str]:
        """전순서 정렬 키. op_id는 최종 타이브레이크(안전용)."""
        return (self.lamport, self.install_id, self.op_id)

    def clock_for(self, field_name: str | None = None) -> ClockEntry:
        """전체 op 또는 특정 필드의 ClockEntry."""
        lam = self.field_lamport.get(field_name, self.lamport) if field_name else self.lamport
        return ClockEntry(lam, self.install_id)

    # -- 직렬화 (NDJSON 한 줄) -------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "op_id": self.op_id,
            "install_id": self.install_id,
            "lamport": self.lamport,
            "wall_utc": self.wall_utc,
            "entity": self.entity,
            "nkey": self.nkey,
            "kind": self.kind.value,
            "fields": dict(self.fields),
            "field_lamport": dict(self.field_lamport),
            "refs": dict(self.refs),
            "schema_ids": sorted(self.schema_ids),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Op:
        return cls(
            op_id=d["op_id"],
            install_id=d["install_id"],
            lamport=int(d["lamport"]),
            wall_utc=d.get("wall_utc", ""),
            entity=d["entity"],
            nkey=d["nkey"],
            kind=OpKind(d["kind"]),
            fields=dict(d.get("fields", {})),
            field_lamport=dict(d.get("field_lamport", {})),
            refs=dict(d.get("refs", {})),
            schema_ids=frozenset(d.get("schema_ids", ())),
        )


@dataclass(frozen=True, slots=True)
class SnapshotManifest:
    """컴팩션 스냅샷 메타.

    covered[install_id] = 이 스냅샷이 반영한 해당 install의 마지막 seq.
    """

    covered: dict[str, int]
    schema_ids: frozenset[str]
    db_sha256: str
    utc: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "covered": dict(self.covered),
            "schema_ids": sorted(self.schema_ids),
            "db_sha256": self.db_sha256,
            "utc": self.utc,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SnapshotManifest:
        return cls(
            covered={k: int(v) for k, v in d.get("covered", {}).items()},
            schema_ids=frozenset(d.get("schema_ids", ())),
            db_sha256=d.get("db_sha256", ""),
            utc=d.get("utc", ""),
        )
