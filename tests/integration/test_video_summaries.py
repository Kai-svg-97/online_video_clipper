"""Gemini 요약의 언어별 저장 — 저장소·마이그레이션·동기화.

요약은 `video_summaries(video_id, lang)` 에 언어마다 한 행으로 산다. Video 엔티티에는
싣지 않는다 — 목록에서 읽은 Video를 저장해도 요약이 지워지지 않아야 하기 때문이다.
"""
from __future__ import annotations

import pytest

from domain.library.aggregates import VideoAggregate
from domain.library.repositories import SearchQuery
from domain.library.value_objects import VideoUrl
from domain.sync.services import link_key, video_key
from domain.sync.value_objects import Op, OpKind
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository
from infrastructure.sync.device import LamportClock
from infrastructure.sync.keyring_secret_store import KeyringSecretStore
from infrastructure.sync.local_oplog_store import LocalOplogStore
from infrastructure.sync.merge_applier import MergeApplier
from infrastructure.sync.recorder import OplogRecorder
from infrastructure.sync.recording_repository import RecordingVideoRepository

_URL = "https://www.youtube.com/watch?v=abc12345678"


@pytest.fixture
def db(tmp_path):
    d = Database(path=tmp_path / "sum.db")
    d.initialize()
    return d


@pytest.fixture
def repo(db):
    return SqliteVideoRepository(db)


def _add(repo, url=_URL, title="제목"):
    agg = VideoAggregate.create(VideoUrl(url), title)
    repo.save(agg)
    return agg


class TestRepository:
    def test_languages_coexist(self, repo):
        agg = _add(repo)
        repo.save_summary(agg.id, "ko", "한국어 요약")
        repo.save_summary(agg.id, "en", "English summary")
        assert repo.get_summaries(agg.id) == {"ko": "한국어 요약", "en": "English summary"}

    def test_overwrite_one_language_only(self, repo):
        agg = _add(repo)
        repo.save_summary(agg.id, "ko", "옛 요약")
        repo.save_summary(agg.id, "en", "English")
        repo.save_summary(agg.id, "ko", "새 요약")
        assert repo.get_summaries(agg.id) == {"ko": "새 요약", "en": "English"}

    def test_empty_text_deletes_that_language(self, repo):
        agg = _add(repo)
        repo.save_summary(agg.id, "ko", "요약")
        repo.save_summary(agg.id, "en", "English")
        repo.save_summary(agg.id, "ko", "")
        assert repo.get_summaries(agg.id) == {"en": "English"}

    def test_deleting_video_cascades(self, repo):
        agg = _add(repo)
        repo.save_summary(agg.id, "ko", "요약")
        repo.delete(agg.id)
        assert repo.get_summaries(agg.id) == {}

    def test_saving_list_loaded_video_keeps_summary(self, repo):
        """목록에서 읽은 Video를 저장해도 요약이 지워지지 않는다(엔티티에 싣지 않은 이유)."""
        agg = _add(repo)
        repo.save_summary(agg.id, "ko", "요약")
        listed = next(v for v in repo.search(SearchQuery()) if v.id == agg.id)
        listed.update_metadata(notes="메모")
        repo.save(listed)
        assert repo.get_summaries(agg.id) == {"ko": "요약"}


class TestMigration:
    def _make_legacy(self, db, agg_id):
        """요약이 videos.gemini_summary 한 칸이던 시절의 DB로 되돌린다."""
        with db.connection() as conn:
            conn.execute("DELETE FROM schema_migrations WHERE id='migrate_video_summaries'")
            conn.execute("DROP TABLE video_summaries")
            conn.execute("DROP TABLE video_summary_status")
            conn.execute(
                "CREATE TABLE video_summary_status ("
                " video_id TEXT PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE,"
                " status TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            conn.execute(
                "UPDATE videos SET gemini_summary='옛 한국어 요약' WHERE id=?", (str(agg_id),)
            )
            conn.execute(
                "INSERT INTO video_summary_status VALUES (?, 'no_button', '2026-01-01')",
                (str(agg_id),),
            )

    def test_backfills_old_summary_as_korean(self, db, repo):
        agg = _add(repo)
        self._make_legacy(db, agg.id)
        db.initialize()
        assert repo.get_summaries(agg.id) == {"ko": "옛 한국어 요약"}
        assert repo.get_summary_statuses(agg.id) == {"ko": "no_button"}

    def test_rerun_is_safe(self, db, repo):
        agg = _add(repo)
        self._make_legacy(db, agg.id)
        db.initialize()
        with db.connection() as conn:
            conn.execute("DELETE FROM schema_migrations WHERE id='migrate_video_summaries'")
        db.initialize()   # 두 번 돌아도 중복·예외 없음
        assert repo.get_summaries(agg.id) == {"ko": "옛 한국어 요약"}
        assert repo.get_summary_statuses(agg.id) == {"ko": "no_button"}


def _recorder(db, tmp_path):
    clk = LamportClock(KeyringSecretStore("s", tmp_path / "s.json", use_file=True))
    oplog = LocalOplogStore(tmp_path / "pending", "A")
    return OplogRecorder(db, oplog, clk, "A"), oplog


class TestSyncCapture:
    def test_save_summary_records_per_language_op(self, db, tmp_path):
        recorder, oplog = _recorder(db, tmp_path)
        repo = RecordingVideoRepository(db, recorder)
        agg = _add(repo)
        before = len(oplog.read_since("A", 0))

        repo.save_summary(agg.id, "en", "English summary")

        ops = oplog.read_since("A", 0)[before:]
        assert len(ops) == 1
        op = ops[0]
        assert op.entity == "video_summary"
        assert op.nkey == link_key(video_key(_URL), "en")
        assert op.fields == {"summary": "English summary"}

    def test_clearing_records_delete(self, db, tmp_path):
        recorder, oplog = _recorder(db, tmp_path)
        repo = RecordingVideoRepository(db, recorder)
        agg = _add(repo)
        repo.save_summary(agg.id, "ko", "요약")
        before = len(oplog.read_since("A", 0))

        repo.save_summary(agg.id, "ko", "")

        ops = oplog.read_since("A", 0)[before:]
        assert [o.kind for o in ops] == [OpKind.DELETE]

    def test_deleting_migrated_summary_still_records_delete(self, db, tmp_path):
        """마이그레이션이 옮긴 요약은 동기화 식별자가 없다 — 지워도 삭제가 전파돼야 한다."""
        recorder, oplog = _recorder(db, tmp_path)
        repo = RecordingVideoRepository(db, recorder)
        agg = _add(repo)
        # 식별자 없이 들어온 요약(마이그레이션 백필과 같은 상태)
        SqliteVideoRepository(db).save_summary(agg.id, "ko", "옮겨 온 요약")
        before = len(oplog.read_since("A", 0))

        repo.save_summary(agg.id, "ko", "")

        ops = oplog.read_since("A", 0)[before:]
        assert ops[-1].kind is OpKind.DELETE
        assert ops[-1].nkey == link_key(video_key(_URL), "ko")

    def test_video_save_no_longer_carries_summary(self, db, tmp_path):
        recorder, oplog = _recorder(db, tmp_path)
        repo = RecordingVideoRepository(db, recorder)
        _add(repo)
        video_op = oplog.read_since("A", 0)[0]
        assert "gemini_summary" not in video_op.fields


def _op(op_id, lamport, entity, nkey, fields=None, kind=OpKind.UPSERT):
    return Op(
        op_id=op_id, install_id="B", lamport=lamport, wall_utc="2026-01-01T00:00:00",
        entity=entity, nkey=nkey, kind=kind, fields=fields or {}, refs={},
    )


class TestSyncApply:
    def _applier(self, db, tmp_path):
        clk = LamportClock(KeyringSecretStore("s", tmp_path / "s2.json", use_file=True))
        return MergeApplier(db, clk)

    def _summaries(self, db):
        with db.connection() as conn:
            return {
                r[0]: r[1]
                for r in conn.execute("SELECT lang, summary FROM video_summaries")
            }

    def test_summary_op_applies_per_language(self, db, tmp_path):
        vnk = video_key(_URL)
        self._applier(db, tmp_path).apply([
            _op("v1", 1, "video", vnk, {"title": "제목"}),
            _op("s1", 2, "video_summary", link_key(vnk, "en"), {"summary": "English"}),
            _op("s2", 3, "video_summary", link_key(vnk, "ko"), {"summary": "한국어"}),
        ])
        assert self._summaries(db) == {"en": "English", "ko": "한국어"}

    def test_delete_op_removes_only_that_language(self, db, tmp_path):
        vnk = video_key(_URL)
        applier = self._applier(db, tmp_path)
        applier.apply([
            _op("v1", 1, "video", vnk, {"title": "제목"}),
            _op("s1", 2, "video_summary", link_key(vnk, "en"), {"summary": "English"}),
            _op("s2", 3, "video_summary", link_key(vnk, "ko"), {"summary": "한국어"}),
        ])
        applier.apply([
            _op("d1", 4, "video_summary", link_key(vnk, "en"), kind=OpKind.DELETE),
        ])
        assert self._summaries(db) == {"ko": "한국어"}

    def test_legacy_video_op_summary_becomes_korean(self, db, tmp_path):
        """업그레이드 전 기기의 op(video.gemini_summary)는 'ko' 행으로 적용된다."""
        vnk = video_key(_URL)
        self._applier(db, tmp_path).apply([
            _op("v1", 1, "video", vnk, {"title": "제목", "gemini_summary": "옛 기기의 요약"}),
        ])
        assert self._summaries(db) == {"ko": "옛 기기의 요약"}
