"""sync 도메인 서비스 (순수 — I/O 없음).

- `OpLogMerger` — op 배치를 현재 레지스터 상태에 병합하는 결정적 reducer.
  적용 순서와 무관하게 같은 결과로 수렴한다(LWW register CRDT).
- `NaturalKey` — 엔티티별 자연키 계산(머신 독립 식별).
- `topo_order` — FK 안전 적용을 위한 엔티티 위상 순서.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from domain.library.value_objects import normalize_video_url
from domain.sync.value_objects import ClockEntry, EntityKey, Op


# ---------------------------------------------------------------------------
# 자연키 (NaturalKey)
# ---------------------------------------------------------------------------

# 경로/링크 조합에 쓰는 구분자 — 일반 텍스트에 등장하지 않는 제어문자.
_SEP = "\x1f"


def video_key(url: str) -> str:
    """영상 자연키 = 정규화 URL (기존 normalize_video_url 재사용)."""
    return normalize_video_url(url)


def tag_key(name: str) -> str:
    return name


def category_key(path: Iterable[str]) -> str:
    """카테고리 자연키 = 루트→리프 이름 경로."""
    return _SEP.join(path)


def split_category_key(nkey: str) -> list[str]:
    """category_key의 역 — 자연키를 루트→리프 이름 리스트로 분해."""
    return nkey.split(_SEP) if nkey else []


def channel_key(channel_id: str) -> str:
    return channel_id


def link_key(parent_nkey: str, child_nkey: str) -> str:
    """조인 테이블(video_tag/playlist_item/category_video_order)의 링크 자연키."""
    return f"{parent_nkey}{_SEP}{child_nkey}"


def origin_key(install_id: str, local_uuid: str) -> str:
    """자연키가 없는 엔티티(로컬 재생목록·폴더·클립·다운로드 이력)의 origin-identity.

    생성한 기기 + 로컬 UUID 조합 — 기기 간 union(중복 허용이 올바른 의미).
    """
    return f"{install_id}{_SEP}{local_uuid}"


# ---------------------------------------------------------------------------
# 위상 순서 (topo_order)
# ---------------------------------------------------------------------------

# FK 의존 순서: 부모가 먼저 적용돼야 자식의 참조가 해석된다.
ENTITY_ORDER: tuple[str, ...] = (
    "category",
    "tag",
    "channel_subscription",
    "video",
    "video_description",
    "song_info",
    "playlist",
    "playlist_folder",
    "video_tag",
    "playlist_item",
    "category_video_order",
    "clip",
    "download_history",
)


def topo_order(entities: Iterable[str]) -> list[str]:
    """엔티티 종류를 FK 안전 적용 순서로 정렬한다. 미등록 종류는 뒤로."""
    rank = {name: i for i, name in enumerate(ENTITY_ORDER)}
    fallback = len(ENTITY_ORDER)
    return sorted(set(entities), key=lambda e: rank.get(e, fallback))


# ---------------------------------------------------------------------------
# 병합 (OpLogMerger)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class PresenceEntry:
    """엔티티 존재 레지스터 — present=False면 tombstone."""

    clock: ClockEntry
    present: bool


@dataclass(frozen=True, slots=True)
class FieldEntry:
    """필드/참조 값 레지스터 — 승자 clock과 값."""

    clock: ClockEntry
    value: Any


@dataclass(slots=True)
class MergeState:
    """현재 materialized 레지스터 상태.

    applier가 로컬 sync_* 테이블에서 로드해 주입한다. 테스트에서는 직접 구성한다.
    (dict는 호출자 소유 — merge()는 복사본을 만들어 원본을 변형하지 않는다.)
    """

    presence: dict[EntityKey, PresenceEntry] = field(default_factory=dict)
    fields: dict[EntityKey, dict[str, FieldEntry]] = field(default_factory=dict)
    refs: dict[EntityKey, dict[str, FieldEntry]] = field(default_factory=dict)
    applied_op_ids: set[str] = field(default_factory=set)


@dataclass(slots=True)
class MergeResult:
    """병합 결과.

    - state: 갱신된 레지스터 상태(persist 대상 — 필드/참조 clock, presence).
    - changed: 이번 배치의 op가 건드린 엔티티(상태 persist 범위).
    - newly_applied: 이번에 처음 적용된 op_id.
    - writes: 이번 배치에서 **실제로 값이 갱신된** 필드/참조만(엔티티→{키:값}).
      로컬이 이긴 필드(값 미상)는 여기 없으므로 applier가 라이브 DB를 덮지 않는다.
      참조는 "__ref__" 접두 키로 담긴다.
    """

    state: MergeState
    changed: set[EntityKey]
    newly_applied: set[str]
    writes: dict[EntityKey, dict[str, Any]]

    def upserts(self) -> dict[EntityKey, dict[str, Any]]:
        """존재(present)하며 이번 배치에서 값이 갱신된 엔티티의 갱신 필드/참조."""
        out: dict[EntityKey, dict[str, Any]] = {}
        for ek, w in self.writes.items():
            pe = self.state.presence.get(ek)
            if pe is not None and pe.present and w:
                out[ek] = dict(w)
        return out

    def deletions(self) -> set[EntityKey]:
        """이번 배치에서 tombstone(부재)으로 확정된 엔티티."""
        return {
            ek
            for ek in self.changed
            if (pe := self.state.presence.get(ek)) is not None and not pe.present
        }


class OpLogMerger:
    """op 배치를 결정적으로 병합한다.

    같은 op 집합이면 적용 순서(셔플)와 무관하게 동일한 MergeState로 수렴한다.
    """

    def merge(self, ops: Iterable[Op], state: MergeState | None = None) -> MergeResult:
        base = state or MergeState()
        # 원본 불변 — 얕은 복사 후 필드/참조 버킷도 복사.
        presence = dict(base.presence)
        fields = {k: dict(v) for k, v in base.fields.items()}
        refs = {k: dict(v) for k, v in base.refs.items()}
        applied = set(base.applied_op_ids)

        newly_applied: set[str] = set()
        changed: set[EntityKey] = set()
        writes: dict[EntityKey, dict[str, Any]] = {}

        # 전순서 정렬 — LWW 특성상 결과값은 순서 무관하나, 안정성을 위해 정렬 적용.
        for op in sorted(ops, key=lambda o: o.order_key):
            if op.op_id in applied:
                continue
            applied.add(op.op_id)
            newly_applied.add(op.op_id)
            ek = op.entity_key
            changed.add(ek)

            clk = op.clock_for()
            cur = presence.get(ek)
            if cur is None or clk > cur.clock:
                presence[ek] = PresenceEntry(clk, op.kind.is_present)

            if op.kind.is_present:
                self._fold(fields, writes, ek, op.fields, op.clock_for, ref=False)
                self._fold(refs, writes, ek, op.refs, op.clock_for, ref=True)

        new_state = MergeState(
            presence=presence, fields=fields, refs=refs, applied_op_ids=applied
        )
        return MergeResult(
            state=new_state, changed=changed, newly_applied=newly_applied, writes=writes
        )

    @staticmethod
    def _fold(register, writes, ek, values, clock_for, ref: bool) -> None:
        """values의 각 항목을 더 큰 clock일 때만 레지스터에 반영하고, 그때만 writes에 기록."""
        bucket = register.setdefault(ek, {})
        for name, val in values.items():
            clk = clock_for(name)
            cur = bucket.get(name)
            if cur is None or clk > cur.clock:
                bucket[name] = FieldEntry(clk, val)
                wkey = f"__ref__{name}" if ref else name
                writes.setdefault(ek, {})[wkey] = val
