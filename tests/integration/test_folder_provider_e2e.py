"""FolderProvider 계약 + 실 스택 end-to-end 테스트.

로컬 폴더를 클라우드 백엔드로 삼아(OneDrive/Drive 동기화 폴더 시뮬레이션) **실제 스택 전체**를
검증한다: 진짜 SQLite DB(실 스키마)·Recording* repo(실 도메인 저장 캡처)·oplog NDJSON 파일·
스냅샷 부트스트랩·실제 미디어 파일 바이트. 유일하게 가짜인 건 "클라우드가 로컬 폴더"라는 점뿐
이며, 그건 실제 지원 기능(OS 동기화 클라이언트가 왕복 담당)이라 사실상 진짜 사용자 환경이다.
"""

from __future__ import annotations

from domain.clip.aggregates import ClipAggregate
from domain.clip.value_objects import TimeRange
from domain.library.aggregates import VideoAggregate
from domain.library.entities import Category, Tag
from domain.library.value_objects import VideoUrl
from domain.song.aggregates import SongInfoAggregate
from infrastructure.persistence.database import MIGRATION_IDS, Database
from infrastructure.sync.bootstrap import bootstrap_if_fresh
from infrastructure.sync.file_syncer import FileSyncer
from infrastructure.sync.folder_provider import FolderProvider
from infrastructure.sync.snapshot_store import SnapshotStore
from infrastructure.sync.sync_service import SyncService
from infrastructure.sync.sync_state import SyncStateStore
from tests.integration.test_sync_flow import _NK, _URL

_URL2 = "https://www.youtube.com/watch?v=def45678901"


# ---------------------------------------------------------------------------
# 계약
# ---------------------------------------------------------------------------


class TestFolderProviderContract:
    def test_text_round_trip_and_atomic(self, tmp_path):
        p = FolderProvider(tmp_path / "cloud")
        assert p.is_authenticated()
        assert p.read_text("oplog/installs.json") is None
        p.write_text("oplog/installs.json", '{"A": 3}')
        assert p.read_text("oplog/installs.json") == '{"A": 3}'
        # 원자적 확정 — .ovctmp 잔여물 없음
        assert list((tmp_path / "cloud").rglob("*.ovctmp")) == []

    def test_file_upload_download_and_list(self, tmp_path):
        p = FolderProvider(tmp_path / "cloud")
        src = tmp_path / "src.bin"
        src.write_bytes(b"x" * (3 * 1024 * 1024 + 7))  # 청크 경계 넘김
        seen: list[tuple[int, int]] = []
        p.upload_file(src, "media/files/downloads/a.bin", on_progress=lambda d, t: seen.append((d, t)))
        assert seen and seen[-1][0] == seen[-1][1] == src.stat().st_size
        rels = [rf.path for rf in p.list_files("media/")]
        assert rels == ["media/files/downloads/a.bin"]
        assert p.stat("media/files/downloads/a.bin").size == src.stat().st_size
        dest = tmp_path / "out.bin"
        p.download_file("media/files/downloads/a.bin", dest)
        assert dest.read_bytes() == src.read_bytes()
        p.delete_file("media/files/downloads/a.bin")
        assert p.stat("media/files/downloads/a.bin") is None


# ---------------------------------------------------------------------------
# 실 스택 end-to-end
# ---------------------------------------------------------------------------


def _service(tmp_path, name, cloud):
    db = Database(tmp_path / f"{name}.db")
    db.initialize()
    svc = SyncService(db, data_dir=tmp_path / f"{name}_data", provider=FolderProvider(cloud))
    return db, svc


def _titles(db_or_path) -> set[str]:
    db = db_or_path if isinstance(db_or_path, Database) else Database(db_or_path)
    with db.connection() as conn:
        return {r["title"] for r in conn.execute("SELECT title FROM videos").fetchall()}


class TestFolderE2E:
    def test_metadata_converges_via_shared_folder(self, tmp_path):
        cloud = tmp_path / "cloud"
        dba, a = _service(tmp_path, "A", cloud)
        dbb, b = _service(tmp_path, "B", cloud)

        # A: 실제 도메인 저장(카테고리·태그·노래까지) — Recording* repo가 캡처.
        repos = a.make_recording_repos(dba)
        cat = Category.create("음악")
        repos["video"].save_category(cat)
        tag = Tag.create("rock")
        repos["video"].save_tag(tag)
        agg = VideoAggregate.create(VideoUrl(_URL), "첫 영상", category_id=cat.id)
        agg.set_tags([tag.id])
        repos["video"].save(agg)
        song = SongInfoAggregate.create(agg.id, is_song=True)
        song.edit_field("artist", "아이유")
        repos["song"].save(song)

        pushed, _ = a.sync_now()
        assert pushed > 0
        _, pulled = b.sync_now()
        assert pulled > 0

        # B에 전부 수렴했는지 — 제목·카테고리·태그·노래.
        with dbb.connection() as conn:
            row = conn.execute(
                "SELECT v.title, c.name AS cat FROM videos v "
                "LEFT JOIN categories c ON c.id=v.category_id WHERE v.url=?",
                (_NK,),
            ).fetchone()
            assert row["title"] == "첫 영상" and row["cat"] == "음악"
            tags = {
                r["name"]
                for r in conn.execute(
                    "SELECT t.name FROM video_tags vt JOIN tags t ON t.id=vt.tag_id "
                    "JOIN videos v ON v.id=vt.video_id WHERE v.url=?",
                    (_NK,),
                ).fetchall()
            }
            assert tags == {"rock"}
            srow = conn.execute(
                "SELECT s.artist FROM song_info s JOIN videos v ON v.id=s.video_id WHERE v.url=?",
                (_NK,),
            ).fetchone()
            assert srow["artist"] == "아이유"

        # 실제로 클라우드 폴더에 oplog NDJSON 세그먼트가 생겼는지 확인.
        segs = list((cloud / "oplog").rglob("*.ndjson"))
        assert segs, "oplog 세그먼트가 폴더에 기록돼야 한다"

    def test_bidirectional_convergence(self, tmp_path):
        cloud = tmp_path / "cloud"
        dba, a = _service(tmp_path, "A", cloud)
        dbb, b = _service(tmp_path, "B", cloud)
        ra = a.make_recording_repos(dba)
        rb = b.make_recording_repos(dbb)

        ra["video"].save(VideoAggregate.create(VideoUrl(_URL), "A영상"))
        a.sync_now()
        b.sync_now()
        rb["video"].save(VideoAggregate.create(VideoUrl(_URL2), "B영상"))
        b.sync_now()
        a.sync_now()

        assert _titles(dba) == {"A영상", "B영상"}
        assert _titles(dbb) == {"A영상", "B영상"}

    def test_connect_folder_persists_and_restores(self, tmp_path):
        cloud = tmp_path / "cloud"
        db = Database(tmp_path / "x.db")
        db.initialize()
        data_dir = tmp_path / "x_data"
        # 미설정으로 시작 → 폴더 연결.
        svc = SyncService(db, data_dir=data_dir)
        assert svc.is_connected() is False
        assert svc.connect_folder(str(cloud)) is True
        assert svc.is_connected() is True

        # 상태 파일에 폴더 경로·provider_key 영속.
        st = SyncStateStore(data_dir / "sync" / "sync_state.json").load()
        assert st.provider_key == "folder"
        assert st.folder_path == str(cloud)

        # 새 SyncService(재시작)가 상태에서 provider를 복원한다.
        svc2 = SyncService(db, data_dir=data_dir)
        assert svc2.is_connected() is True

    def test_fresh_machine_bootstraps_from_folder_snapshot(self, tmp_path):
        cloud = tmp_path / "cloud"
        dba, a = _service(tmp_path, "A", cloud)
        ra = a.make_recording_repos(dba)
        ra["video"].save(VideoAggregate.create(VideoUrl(_URL), "스냅샷영상"))
        a.sync_now()
        a.compact()  # 스냅샷 발행

        # 신규 기기 C: 로컬 DB 없음 → 스냅샷 부트스트랩.
        db_c = tmp_path / "C.db"
        state_c = SyncStateStore(tmp_path / "C_data" / "sync_state.json")
        snap = SnapshotStore(db_c, MIGRATION_IDS)
        ok = bootstrap_if_fresh(
            FolderProvider(cloud), snap, state_c, db_c,
            backup_dir=tmp_path / "C_backup", tmp_dir=tmp_path / "C_tmp",
        )
        assert ok is True
        assert _titles(db_c) == {"스냅샷영상"}

    def test_clip_and_media_files_sync(self, tmp_path):
        """clip 메타데이터 + 실제 미디어 파일 바이트가 폴더를 통해 왕복하는지."""
        cloud = tmp_path / "cloud"
        dba, a = _service(tmp_path, "A", cloud)
        dbb, b = _service(tmp_path, "B", cloud)
        ra = a.make_recording_repos(dba)

        # 소스 영상 양쪽에 존재하도록.
        ra["video"].save(VideoAggregate.create(VideoUrl(_URL), "원본"))
        a.sync_now()
        b.sync_now()
        # A에서 clip 생성.
        clip = ClipAggregate.create(_video_id(dba), "클립1", TimeRange(5.0, 12.0))
        ra["clip"].save(clip)
        a.sync_now()
        b.sync_now()
        with dbb.connection() as conn:
            row = conn.execute(
                "SELECT title, start_sec, end_sec FROM clips WHERE title=?", ("클립1",)
            ).fetchone()
        assert row is not None and row["start_sec"] == 5.0 and row["end_sec"] == 12.0

        # 실제 미디어 파일 바이트 동기화(FileSyncer + FolderProvider, 실 파일).
        a_dl = tmp_path / "A_data" / "downloads"
        a_dl.mkdir(parents=True, exist_ok=True)
        (a_dl / "clip1.mp4").write_bytes(b"real-video-bytes-0123456789")
        syncer_a = FileSyncer(FolderProvider(cloud), tmp_path / "A_data", [a_dl],
                              tmp_path / "A_data" / "sync")
        rep = syncer_a.sync()
        assert rep.uploaded == 1

        b_dir = tmp_path / "B_data"
        (b_dir / "downloads").mkdir(parents=True, exist_ok=True)
        syncer_b = FileSyncer(FolderProvider(cloud), b_dir, [b_dir / "downloads"],
                              b_dir / "sync")
        rep_b = syncer_b.sync()
        assert rep_b.downloaded == 1
        assert (b_dir / "downloads" / "clip1.mp4").read_bytes() == b"real-video-bytes-0123456789"


def _video_id(db):
    from uuid import UUID
    with db.connection() as conn:
        row = conn.execute("SELECT id FROM videos WHERE url=?", (_NK,)).fetchone()
    return UUID(row["id"])
