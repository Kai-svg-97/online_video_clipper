"""MergeApplier 통합 테스트 — 병합 op를 라이브 DB에 반영, 결정적 수렴 검증."""

from __future__ import annotations

import itertools

from domain.sync.services import category_key, video_key
from domain.sync.value_objects import Op, OpKind
from infrastructure.persistence.database import Database
from infrastructure.sync.device import LamportClock
from infrastructure.sync.keyring_secret_store import KeyringSecretStore
from infrastructure.sync.merge_applier import MergeApplier

_URL = "https://www.youtube.com/watch?v=abc12345678"
_NK = video_key(_URL)


def _applier(tmp_path, db):
    clk = LamportClock(KeyringSecretStore("s", tmp_path / "s.json", use_file=True))
    return MergeApplier(db, clk)


def _op(op_id, install, lamport, kind=OpKind.UPSERT, fields=None, refs=None, nkey=_NK):
    return Op(
        op_id=op_id, install_id=install, lamport=lamport, wall_utc="2026-01-01T00:00:00",
        entity="video", nkey=nkey, kind=kind, fields=fields or {}, refs=refs or {},
    )


def _fresh_db(tmp_path, name):
    d = Database(tmp_path / name)
    d.initialize()
    return d


def _video_content(db, nkey=_NK):
    """비교용 — id/타임스탬프 제외한 내용 컬럼."""
    with db.connection() as conn:
        row = conn.execute(
            "SELECT url, title, notes, favorite, watched, channel_id, duration_sec, "
            "published_at, category_id FROM videos WHERE url=?",
            (nkey,),
        ).fetchone()
        return dict(row) if row else None


class TestApplyBasics:
    def test_create_op_inserts_row(self, tmp_path):
        db = _fresh_db(tmp_path, "a.db")
        applier = _applier(tmp_path, db)
        res = applier.apply([
            _op("o1", "A", 1, fields={"title": "제목", "notes": "메모", "channel_id": "UC1"})
        ])
        assert res.newly_applied == {"o1"}
        c = _video_content(db)
        assert c["title"] == "제목" and c["notes"] == "메모" and c["channel_id"] == "UC1"
        assert c["url"] == _NK
        # 레지스터·applied 기록 확인
        with db.connection() as conn:
            assert conn.execute(
                "SELECT present FROM sync_identity WHERE entity='video' AND nkey=?", (_NK,)
            ).fetchone()[0] == 1
            assert conn.execute(
                "SELECT 1 FROM sync_applied_ops WHERE op_id='o1'"
            ).fetchone()

    def test_idempotent_reapply(self, tmp_path):
        db = _fresh_db(tmp_path, "a.db")
        applier = _applier(tmp_path, db)
        ops = [_op("o1", "A", 1, fields={"title": "t"})]
        applier.apply(ops)
        res2 = applier.apply(ops)  # 같은 op 재적용
        assert res2.newly_applied == set()
        with db.connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM videos WHERE url=?", (_NK,)).fetchone()[0] == 1

    def test_duplicate_url_from_two_installs_single_row(self, tmp_path):
        db = _fresh_db(tmp_path, "a.db")
        applier = _applier(tmp_path, db)
        applier.apply([
            _op("o1", "A", 1, fields={"title": "A제목"}),
            _op("o2", "B", 2, fields={"title": "B제목"}),  # 더 높은 lamport → 승
        ])
        with db.connection() as conn:
            rows = conn.execute("SELECT title FROM videos WHERE url=?", (_NK,)).fetchall()
        assert len(rows) == 1
        assert rows[0]["title"] == "B제목"


class TestDeterministicConvergence:
    def _ops(self):
        return [
            _op("o1", "A", 1, fields={"title": "T", "notes": "a", "channel_id": "UC1"}),
            _op("o2", "B", 2, fields={"notes": "b"}),           # notes 덮어씀
            _op("o3", "A", 3, fields={"favorite": 1}),
            _op("o4", "B", 4, fields={"watched": 1, "duration_sec": 100}),
        ]

    def test_order_independent_final_row(self, tmp_path):
        # 기준 결과
        base_db = _fresh_db(tmp_path, "base.db")
        _applier(tmp_path, base_db).apply(self._ops())
        baseline = _video_content(base_db)
        assert baseline["notes"] == "b" and baseline["title"] == "T"
        assert baseline["favorite"] == 1 and baseline["watched"] == 1
        assert baseline["duration_sec"] == 100

        # 모든 순열로 적용해도 내용 컬럼 동일
        for i, perm in enumerate(itertools.permutations(self._ops())):
            d = _fresh_db(tmp_path, f"perm{i}.db")
            _applier(tmp_path, d).apply(list(perm))
            assert _video_content(d) == baseline

    def test_split_across_two_apply_calls(self, tmp_path):
        """두 번에 나눠 pull해도 필드 단위로 모두 보존."""
        db = _fresh_db(tmp_path, "a.db")
        applier = _applier(tmp_path, db)
        applier.apply([_op("o1", "A", 5, fields={"title": "T", "notes": "memoA"})])
        applier.apply([_op("o2", "B", 6, fields={"favorite": 1})])
        c = _video_content(db)
        assert c["notes"] == "memoA" and c["favorite"] == 1 and c["title"] == "T"


class TestTombstone:
    def test_delete_removes_row(self, tmp_path):
        db = _fresh_db(tmp_path, "a.db")
        applier = _applier(tmp_path, db)
        applier.apply([
            _op("o1", "A", 1, fields={"title": "t"}),
            _op("o2", "B", 2, kind=OpKind.DELETE),
        ])
        assert _video_content(db) is None
        with db.connection() as conn:
            assert conn.execute(
                "SELECT present FROM sync_identity WHERE entity='video' AND nkey=?", (_NK,)
            ).fetchone()[0] == 0

    def test_higher_readd_resurrects(self, tmp_path):
        db = _fresh_db(tmp_path, "a.db")
        applier = _applier(tmp_path, db)
        applier.apply([
            _op("o1", "A", 1, fields={"title": "t"}),
            _op("o2", "B", 2, kind=OpKind.DELETE),
            _op("o3", "A", 3, fields={"title": "다시"}),
        ])
        c = _video_content(db)
        assert c is not None and c["title"] == "다시"

    def test_delete_order_independent(self, tmp_path):
        ops = [
            _op("o1", "A", 1, fields={"title": "t"}),
            _op("o2", "B", 2, kind=OpKind.DELETE),
            _op("o3", "A", 3, fields={"title": "다시"}),
        ]
        results = []
        for i, perm in enumerate(itertools.permutations(ops)):
            d = _fresh_db(tmp_path, f"t{i}.db")
            _applier(tmp_path, d).apply(list(perm))
            results.append(_video_content(d))
        # 모든 순열이 동일 결과(부활, title="다시")
        assert all(r == results[0] for r in results)
        assert results[0]["title"] == "다시"


class TestFtsConsistency:
    def test_fts_index_updated_on_apply(self, tmp_path):
        db = _fresh_db(tmp_path, "a.db")
        applier = _applier(tmp_path, db)
        applier.apply([_op("o1", "A", 1, fields={"title": "Python 강좌", "notes": "n"})])
        with db.connection() as conn:
            # videos_ai 트리거가 직접 INSERT에도 발화 → FTS로 검색됨
            hit = conn.execute(
                "SELECT v.title FROM videos_fts f JOIN videos v ON v.rowid=f.rowid "
                "WHERE videos_fts MATCH 'Python'"
            ).fetchone()
            assert hit is not None and hit["title"] == "Python 강좌"
        # 삭제 후 FTS에서도 사라짐(videos_ad 트리거)
        applier.apply([_op("o2", "B", 2, kind=OpKind.DELETE)])
        with db.connection() as conn:
            assert conn.execute(
                "SELECT COUNT(*) FROM videos_fts WHERE videos_fts MATCH 'Python'"
            ).fetchone()[0] == 0


class TestCategoryRef:
    def test_category_path_created_and_linked(self, tmp_path):
        db = _fresh_db(tmp_path, "a.db")
        applier = _applier(tmp_path, db)
        applier.apply([
            _op("o1", "A", 1, fields={"title": "t"}, refs={"category": category_key(["IT", "News"])})
        ])
        with db.connection() as conn:
            # 카테고리 경로 IT > News 가 생성되고 video.category_id가 News를 가리킨다
            vid = conn.execute("SELECT category_id FROM videos WHERE url=?", (_NK,)).fetchone()
            assert vid["category_id"]
            news = conn.execute(
                "SELECT id, name, parent_id FROM categories WHERE id=?", (vid["category_id"],)
            ).fetchone()
            assert news["name"] == "News"
            parent = conn.execute(
                "SELECT name, parent_id FROM categories WHERE id=?", (news["parent_id"],)
            ).fetchone()
            assert parent["name"] == "IT" and parent["parent_id"] is None
