"""엔티티 확장(Phase D-1) 통합 테스트 — video_tag 링크 + song_info 캡처/적용/수렴."""

from __future__ import annotations

from uuid import UUID

import pytest

from domain.library.aggregates import VideoAggregate
from domain.library.entities import Tag
from domain.library.value_objects import VideoUrl
from domain.song.aggregates import SongInfoAggregate
from infrastructure.sync.recording_repository import RecordingSongRepository
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
