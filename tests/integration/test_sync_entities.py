"""엔티티 확장(Phase D-1) 통합 테스트 — video_tag 링크 + song_info 캡처/적용/수렴."""

from __future__ import annotations

from uuid import UUID

import pytest

from domain.clip.aggregates import ClipAggregate
from domain.clip.value_objects import TimeRange
from domain.download.entities import DownloadJob, JobStatus
from domain.library.aggregates import VideoAggregate
from domain.library.entities import Category, Tag
from domain.library.value_objects import VideoUrl
from domain.song.aggregates import SongInfoAggregate
from infrastructure.sync.recording_repository import (
    RecordingClipRepository,
    RecordingDownloadRepository,
    RecordingSongRepository,
)
from tests.integration.test_sync_flow import _NK, _URL, FakeCloudProvider, Install


@pytest.fixture()
def provider(tmp_path):
    return FakeCloudProvider(tmp_path / "cloud")


def _song_repo(inst: Install) -> RecordingSongRepository:
    return RecordingSongRepository(inst.db, inst.recorder)


def _video_id(inst: Install, nkey: str = _NK) -> UUID:
    with inst.db.connection() as conn:
        row = conn.execute("SELECT id FROM videos WHERE url=?", (nkey,)).fetchone()
    return UUID(row["id"])


def _tags_of(inst: Install, nkey: str = _NK) -> set[str]:
    with inst.db.connection() as conn:
        rows = conn.execute(
            "SELECT t.name FROM video_tags vt "
            "JOIN tags t ON t.id=vt.tag_id JOIN videos v ON v.id=vt.video_id "
            "WHERE v.url=?",
            (nkey,),
        ).fetchall()
    return {r["name"] for r in rows}


def _song_row(inst: Install, nkey: str = _NK) -> dict | None:
    with inst.db.connection() as conn:
        row = conn.execute(
            "SELECT s.* FROM song_info s JOIN videos v ON v.id=s.video_id WHERE v.url=?",
            (nkey,),
        ).fetchone()
    return dict(row) if row else None


def _video_category_name(inst: Install, nkey: str = _NK) -> str | None:
    with inst.db.connection() as conn:
        row = conn.execute(
            "SELECT c.name FROM videos v JOIN categories c ON c.id=v.category_id "
            "WHERE v.url=?",
            (nkey,),
        ).fetchone()
    return row["name"] if row else None


def _category_count(inst: Install) -> int:
    with inst.db.connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]


def _seed_video(a: Install, b: Install) -> None:
    """A가 영상 생성·push, B가 pull해 양쪽에 영상이 존재하게 한다."""
    a.repo.save(VideoAggregate.create(VideoUrl(_URL), "제목"))
    a.push()
    b.pull()


class TestVideoTagLink:
    def test_link_converges(self, tmp_path, provider):
        a = Install(tmp_path, "A", provider)
        b = Install(tmp_path, "B", provider)
        _seed_video(a, b)

        agg = a.repo.get_by_id(_video_id(a))
        tag = Tag.create("rock")
        a.repo.save_tag(tag)
        agg.set_tags([tag.id])
        a.repo.save(agg)
        a.push()
        b.pull()

        assert _tags_of(b) == {"rock"}  # B에 태그가 lazy 생성·연관됨

    def test_unlink_converges(self, tmp_path, provider):
        a = Install(tmp_path, "A", provider)
        b = Install(tmp_path, "B", provider)
        _seed_video(a, b)
        agg = a.repo.get_by_id(_video_id(a))
        tag = Tag.create("jazz")
        a.repo.save_tag(tag)
        agg.set_tags([tag.id])
        a.repo.save(agg)
        a.push()
        b.pull()
        assert _tags_of(b) == {"jazz"}

        # A가 태그 제거 → unlink
        agg2 = a.repo.get_by_id(_video_id(a))
        agg2.set_tags([])
        a.repo.save(agg2)
        a.push()
        b.pull()
        assert _tags_of(b) == set()

    def test_relink_after_unlink(self, tmp_path, provider):
        a = Install(tmp_path, "A", provider)
        b = Install(tmp_path, "B", provider)
        _seed_video(a, b)
        vid = _video_id(a)
        tag = Tag.create("pop")
        a.repo.save_tag(tag)
        for tags in ([tag.id], [], [tag.id]):  # link → unlink → relink
            agg = a.repo.get_by_id(vid)
            agg.set_tags(tags)
            a.repo.save(agg)
        a.push()
        b.pull()
        assert _tags_of(b) == {"pop"}


class TestCategory:
    def test_category_and_assignment_converge(self, tmp_path, provider):
        a = Install(tmp_path, "A", provider)
        b = Install(tmp_path, "B", provider)
        parent = Category.create("음악")
        child = Category.create("가요", parent_id=parent.id)
        a.repo.save_category(parent)
        a.repo.save_category(child)
        agg = VideoAggregate.create(VideoUrl(_URL), "제목", category_id=child.id)
        a.repo.save(agg)
        a.push()
        b.pull()

        assert _video_category_name(b) == "가요"
        # 부모·자식 카테고리가 B에 생성됨(이름 placeholder 잔존 없이 채워짐).
        with b.db.connection() as conn:
            names = {r["name"] for r in conn.execute("SELECT name FROM categories").fetchall()}
        assert names == {"음악", "가요"}

    def test_category_rename_converges(self, tmp_path, provider):
        a = Install(tmp_path, "A", provider)
        b = Install(tmp_path, "B", provider)
        cat = Category.create("음악")
        a.repo.save_category(cat)
        agg = VideoAggregate.create(VideoUrl(_URL), "제목", category_id=cat.id)
        a.repo.save(agg)
        a.push()
        b.pull()
        assert _video_category_name(b) == "음악"

        # A에서 같은 카테고리 rename(같은 id) → 필드 변경으로 전파.
        a.repo.save_category(Category(id=cat.id, name="가요", parent_id=None))
        a.push()
        b.pull()
        assert _video_category_name(b) == "가요"
        assert _category_count(b) == 1  # 중복 카테고리 안 생김


class TestSongInfo:
    def test_song_converges(self, tmp_path, provider):
        a = Install(tmp_path, "A", provider)
        b = Install(tmp_path, "B", provider)
        _seed_video(a, b)

        song = SongInfoAggregate.create(_video_id(a), is_song=True)
        song.edit_field("artist", "아이유")
        song.edit_field("album", "Lilac")
        _song_repo(a).save(song)
        a.push()
        b.pull()

        row = _song_row(b)
        assert row is not None
        assert row["is_song"] == 1
        assert row["artist"] == "아이유"
        assert row["album"] == "Lilac"

    def test_song_field_lww_merges_concurrent_edits(self, tmp_path, provider):
        a = Install(tmp_path, "A", provider)
        b = Install(tmp_path, "B", provider)
        _seed_video(a, b)
        # A가 song 생성·push, B가 받음.
        song_a = SongInfoAggregate.create(_video_id(a), is_song=True)
        _song_repo(a).save(song_a)
        a.push()
        b.pull()

        # 동시 편집: A는 artist, B는 album.
        sa = _song_repo(a).get(_video_id(a))
        sa.edit_field("artist", "가수A")
        _song_repo(a).save(sa)
        sb = _song_repo(b).get(_video_id(b))
        sb.edit_field("album", "앨범B")
        _song_repo(b).save(sb)

        # 교차 동기화.
        a.push()
        b.push()
        a.pull()
        b.pull()

        for inst in (a, b):
            row = _song_row(inst)
            assert row["artist"] == "가수A"
            assert row["album"] == "앨범B"

    def test_song_delete_converges(self, tmp_path, provider):
        a = Install(tmp_path, "A", provider)
        b = Install(tmp_path, "B", provider)
        _seed_video(a, b)
        song = SongInfoAggregate.create(_video_id(a), is_song=True)
        song.edit_field("artist", "삭제될가수")
        _song_repo(a).save(song)
        a.push()
        b.pull()
        assert _song_row(b) is not None

        _song_repo(a).delete(_video_id(a))
        a.push()
        b.pull()
        assert _song_row(b) is None


class TestClip:
    def test_clip_converges(self, tmp_path, provider):
        a = Install(tmp_path, "A", provider)
        b = Install(tmp_path, "B", provider)
        _seed_video(a, b)  # 소스 영상이 양쪽에 존재해야 clip FK 해석 가능

        clip_repo = RecordingClipRepository(a.db, a.recorder)
        agg = ClipAggregate.create(_video_id(a), "내 클립", TimeRange(10.0, 20.0))
        clip_repo.save(agg)
        a.push()
        b.pull()

        with b.db.connection() as conn:
            row = conn.execute(
                "SELECT c.title, c.start_sec, c.end_sec, v.url "
                "FROM clips c JOIN videos v ON v.id=c.source_video_id WHERE c.title=?",
                ("내 클립",),
            ).fetchone()
        assert row is not None
        assert row["url"] == _NK  # B의 로컬 영상에 올바르게 연결
        assert row["start_sec"] == 10.0 and row["end_sec"] == 20.0

    def test_clip_delete_converges(self, tmp_path, provider):
        a = Install(tmp_path, "A", provider)
        b = Install(tmp_path, "B", provider)
        _seed_video(a, b)
        clip_repo = RecordingClipRepository(a.db, a.recorder)
        agg = ClipAggregate.create(_video_id(a), "삭제될 클립", TimeRange(1.0, 2.0))
        clip_repo.save(agg)
        a.push()
        b.pull()
        with b.db.connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0] == 1

        clip_repo.delete(agg.id)
        a.push()
        b.pull()
        with b.db.connection() as conn:
            assert conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0] == 0


class TestDownloadHistory:
    def test_download_converges(self, tmp_path, provider):
        a = Install(tmp_path, "A", provider)
        b = Install(tmp_path, "B", provider)
        dl_repo = RecordingDownloadRepository(a.db, a.recorder)
        job = DownloadJob.create("https://youtu.be/xyz98765432", "다운로드 제목")
        job.status = JobStatus.COMPLETED
        job.file_path = "downloads/xyz.mp4"  # DATA_DIR 상대경로(이식성)
        dl_repo.save(job)
        a.push()
        b.pull()

        with b.db.connection() as conn:
            row = conn.execute(
                "SELECT title, status, file_path FROM download_history WHERE title=?",
                ("다운로드 제목",),
            ).fetchone()
        assert row is not None
        assert row["status"] == JobStatus.COMPLETED.value
        assert row["file_path"] == "downloads/xyz.mp4"

    def test_download_status_update_converges(self, tmp_path, provider):
        a = Install(tmp_path, "A", provider)
        b = Install(tmp_path, "B", provider)
        dl_repo = RecordingDownloadRepository(a.db, a.recorder)
        job = DownloadJob.create("https://youtu.be/xyz98765432", "제목")
        dl_repo.save(job)
        a.push()
        b.pull()

        job.status = JobStatus.COMPLETED
        job.file_path = "downloads/done.mp4"
        dl_repo.save(job)
        a.push()
        b.pull()
        with b.db.connection() as conn:
            row = conn.execute(
                "SELECT status, file_path FROM download_history WHERE title=?", ("제목",)
            ).fetchone()
        assert row["status"] == JobStatus.COMPLETED.value
        assert row["file_path"] == "downloads/done.mp4"
