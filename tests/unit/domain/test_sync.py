"""sync 도메인 순수 로직 테스트 (I/O 없음)."""

from __future__ import annotations

import itertools

from domain.sync.services import (
    ENTITY_ORDER,
    MergeState,
    OpLogMerger,
    category_key,
    link_key,
    origin_key,
    topo_order,
    video_key,
)
from domain.sync.value_objects import (
    ClockEntry,
    EntityKey,
    Op,
    OpKind,
    SnapshotManifest,
)


def make_op(
    op_id, install, lamport, entity, nkey, kind=OpKind.UPSERT,
    fields=None, field_lamport=None, refs=None,
):
    return Op(
        op_id=op_id,
        install_id=install,
        lamport=lamport,
        wall_utc="2026-01-01T00:00:00",
        entity=entity,
        nkey=nkey,
        kind=kind,
        fields=fields or {},
        field_lamport=field_lamport or {},
        refs=refs or {},
        schema_ids=frozenset({"m1"}),
    )


class TestClockEntry:
    def test_lamport_dominates(self):
        assert ClockEntry(2, "a") > ClockEntry(1, "z")

    def test_install_id_tiebreak(self):
        assert ClockEntry(5, "b") > ClockEntry(5, "a")

    def test_equality(self):
        assert ClockEntry(3, "x") == ClockEntry(3, "x")


class TestNaturalKey:
    def test_video_key_normalizes(self):
        assert video_key("https://youtu.be/abc12345678") == video_key(
            "https://www.youtube.com/watch?v=abc12345678&list=xyz"
        )

    def test_category_path(self):
        assert category_key(["IT", "News"]) == category_key(("IT", "News"))
        assert category_key(["IT", "News"]) != category_key(["IT", "Newz"])

    def test_link_and_origin_distinct(self):
        assert link_key("p", "c") != link_key("c", "p")
        assert origin_key("A", "u1") != origin_key("B", "u1")


class TestTopoOrder:
    def test_parents_before_children(self):
        order = topo_order(["video_tag", "video", "tag", "category"])
        assert order.index("category") < order.index("video")
        assert order.index("tag") < order.index("video_tag")
        assert order.index("video") < order.index("video_tag")

    def test_unknown_entity_last(self):
        order = topo_order(["mystery", "video"])
        assert order[-1] == "mystery"

    def test_all_known_entities_ranked(self):
        assert topo_order(ENTITY_ORDER) == list(ENTITY_ORDER)


class TestSerialization:
    def test_op_round_trip(self):
        op = make_op("o1", "A", 7, "video", "vk",
                     fields={"notes": "hi", "favorite": 1},
                     field_lamport={"notes": 7, "favorite": 5},
                     refs={"category": "IT"})
        back = Op.from_dict(op.to_dict())
        assert back == op

    def test_manifest_round_trip(self):
        m = SnapshotManifest(covered={"A": 3, "B": 9},
                             schema_ids=frozenset({"m1", "m2"}),
                             db_sha256="deadbeef", utc="2026-01-01")
        assert SnapshotManifest.from_dict(m.to_dict()) == m


class TestMergeDeterminism:
    def _ops(self):
        return [
            make_op("o1", "A", 1, "video", "vk", fields={"notes": "a", "title": "T"}),
            make_op("o2", "B", 2, "video", "vk", fields={"notes": "b"}),
            make_op("o3", "A", 3, "video", "vk", fields={"favorite": 1}),
            make_op("o4", "B", 4, "tag", "rock"),
        ]

    def test_order_independent(self):
        merger = OpLogMerger()
        ops = self._ops()
        baseline = merger.merge(ops).state
        for perm in itertools.permutations(ops):
            res = merger.merge(list(perm)).state
            assert res.presence == baseline.presence
            assert res.fields == baseline.fields

    def test_higher_lamport_wins_same_field(self):
        merger = OpLogMerger()
        res = merger.merge(self._ops())
        vk = EntityKey("video", "vk")
        # notes: o1(lamport1,A)="a" vs o2(lamport2,B)="b" → b wins
        assert res.state.fields[vk]["notes"].value == "b"
        # 서로 다른 필드는 모두 보존
        assert res.state.fields[vk]["title"].value == "T"
        assert res.state.fields[vk]["favorite"].value == 1


class TestFieldLevelLWW:
    def test_concurrent_different_fields_both_survive(self):
        merger = OpLogMerger()
        ops = [
            make_op("o1", "A", 5, "video", "vk",
                    fields={"notes": "memoA"}, field_lamport={"notes": 5}),
            make_op("o2", "B", 5, "video", "vk",
                    refs={"category": "Jazz"}),
        ]
        res = merger.merge(ops)
        vk = EntityKey("video", "vk")
        assert res.state.fields[vk]["notes"].value == "memoA"
        assert res.state.refs[vk]["category"].value == "Jazz"
        up = res.upserts()[vk]
        assert up["notes"] == "memoA"
        assert up["__ref__category"] == "Jazz"

    def test_field_lamport_beats_op_lamport(self):
        merger = OpLogMerger()
        ops = [
            make_op("o1", "A", 10, "video", "vk",
                    fields={"notes": "new"}, field_lamport={"notes": 10}),
            make_op("o2", "B", 20, "video", "vk",
                    fields={"notes": "stale"}, field_lamport={"notes": 3}),
        ]
        res = merger.merge(ops)
        vk = EntityKey("video", "vk")
        # o2 op.lamport(20)이 더 크지만 notes의 field_lamport(3)은 작아 o1(10)이 승리
        assert res.state.fields[vk]["notes"].value == "new"


class TestTombstone:
    def test_delete_wins_over_lower_upsert(self):
        merger = OpLogMerger()
        ops = [
            make_op("o1", "A", 1, "video", "vk", fields={"notes": "x"}),
            make_op("o2", "B", 2, "video", "vk", kind=OpKind.DELETE),
        ]
        res = merger.merge(ops)
        vk = EntityKey("video", "vk")
        assert not res.state.presence[vk].present
        assert vk in res.deletions()
        assert vk not in res.upserts()

    def test_higher_readd_resurrects(self):
        merger = OpLogMerger()
        ops = [
            make_op("o1", "A", 1, "video", "vk", fields={"notes": "x"}),
            make_op("o2", "B", 2, "video", "vk", kind=OpKind.DELETE),
            make_op("o3", "A", 3, "video", "vk", fields={"notes": "again"}),
        ]
        res = merger.merge(ops)
        vk = EntityKey("video", "vk")
        assert res.state.presence[vk].present
        assert res.upserts()[vk]["notes"] == "again"

    def test_delete_order_independent(self):
        merger = OpLogMerger()
        ops = [
            make_op("o1", "A", 1, "video", "vk", fields={"notes": "x"}),
            make_op("o2", "B", 2, "video", "vk", kind=OpKind.DELETE),
            make_op("o3", "A", 3, "video", "vk", fields={"notes": "again"}),
        ]
        baseline = merger.merge(ops).state.presence
        for perm in itertools.permutations(ops):
            assert merger.merge(list(perm)).state.presence == baseline


class TestIdempotency:
    def test_already_applied_ops_skipped(self):
        merger = OpLogMerger()
        first = merger.merge([make_op("o1", "A", 1, "tag", "rock")])
        assert first.newly_applied == {"o1"}
        # 같은 op을 이미 적용된 상태로 다시 병합 → 무시
        second = merger.merge(
            [make_op("o1", "A", 1, "tag", "rock")], first.state
        )
        assert second.newly_applied == set()
        assert second.changed == set()

    def test_merge_does_not_mutate_input_state(self):
        merger = OpLogMerger()
        base = MergeState()
        merger.merge([make_op("o1", "A", 1, "tag", "rock")], base)
        assert base.presence == {}
        assert base.applied_op_ids == set()
