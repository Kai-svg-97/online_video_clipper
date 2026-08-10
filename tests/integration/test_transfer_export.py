"""ExportLibraryHandler — 실제 SQLite 리포지토리로 카테고리·영상·노래 정보 내보내기 검증."""
from __future__ import annotations

import pytest

from application.transfer.commands import ExportLibraryCommand, ExportLibraryHandler
from domain.library.aggregates import VideoAggregate
from domain.library.entities import Category
from domain.library.value_objects import VideoUrl
from domain.song.aggregates import SongInfoAggregate
from domain.song.value_objects import LyricsLine
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_song_repository import SqliteSongRepository
from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository


class FakePackageWriter:
    """실제 zip 대신 write() 호출 인자를 그대로 보관한다."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def write(self, dest_path: str, manifest: dict, data: dict) -> None:
        self.calls.append((dest_path, manifest, data))


@pytest.fixture
def repos(tmp_path):
    db = Database(tmp_path / "library.db")
    db.initialize()
    return SqliteVideoRepository(db), SqliteSongRepository(db)


def _make_video(video_repo, url: str, title: str, category_id=None, tags=None) -> VideoAggregate:
    agg = VideoAggregate.create(VideoUrl(url), title, category_id=category_id)
    if tags:
        tag_ids = [video_repo.get_or_create_tag(t).id for t in tags]
        agg.set_tags(tag_ids)
    video_repo.save(agg)
    return agg


class TestExportLibrary:
    def test_선택한_카테고리의_영상만_내보낸다(self, repos):
        video_repo, song_repo = repos
        music = Category.create("Music")
        movies = Category.create("Movies")
        video_repo.save_category(music)
        video_repo.save_category(movies)
        _make_video(video_repo, "https://youtu.be/a", "노래영상", category_id=music.id)
        _make_video(video_repo, "https://youtu.be/b", "영화영상", category_id=movies.id)

        writer = FakePackageWriter()
        handler = ExportLibraryHandler(video_repo, song_repo, writer)
        result = handler.handle(ExportLibraryCommand(category_ids=[music.id], dest_path="out.zip"))

        assert result.video_count == 1
        assert result.category_count == 1
        _dest, _manifest, data = writer.calls[0]
        assert len(data["videos"]) == 1
        assert data["videos"][0]["title"] == "노래영상"

    def test_하위_카테고리도_함께_내보낸다(self, repos):
        video_repo, song_repo = repos
        parent = Category.create("Music")
        video_repo.save_category(parent)
        child = Category.create("OST", parent_id=parent.id)
        video_repo.save_category(child)
        _make_video(video_repo, "https://youtu.be/a", "부모영상", category_id=parent.id)
        _make_video(video_repo, "https://youtu.be/b", "자식영상", category_id=child.id)

        writer = FakePackageWriter()
        handler = ExportLibraryHandler(video_repo, song_repo, writer)
        result = handler.handle(ExportLibraryCommand(category_ids=[parent.id], dest_path="out.zip"))

        assert result.video_count == 2
        assert result.category_count == 2
        _dest, _manifest, data = writer.calls[0]
        titles = {v["title"] for v in data["videos"]}
        assert titles == {"부모영상", "자식영상"}

    def test_선택되지_않은_조상은_패키지에서_부모가_없는_것으로_표시된다(self, repos):
        video_repo, song_repo = repos
        parent = Category.create("Music")
        video_repo.save_category(parent)
        child = Category.create("OST", parent_id=parent.id)
        video_repo.save_category(child)

        writer = FakePackageWriter()
        handler = ExportLibraryHandler(video_repo, song_repo, writer)
        handler.handle(ExportLibraryCommand(category_ids=[child.id], dest_path="out.zip"))

        _dest, _manifest, data = writer.calls[0]
        assert len(data["categories"]) == 1
        assert data["categories"][0]["name"] == "OST"
        assert data["categories"][0]["parent_id"] is None

    def test_태그와_노트_설명이_함께_내보내진다(self, repos):
        video_repo, song_repo = repos
        cat = Category.create("Music")
        video_repo.save_category(cat)
        agg = _make_video(video_repo, "https://youtu.be/a", "제목", category_id=cat.id, tags=["신남", "댄스"])
        agg.update_metadata(description="설명입니다", notes="메모입니다")
        video_repo.save(agg)

        writer = FakePackageWriter()
        handler = ExportLibraryHandler(video_repo, song_repo, writer)
        handler.handle(ExportLibraryCommand(category_ids=[cat.id], dest_path="out.zip"))

        _dest, _manifest, data = writer.calls[0]
        v = data["videos"][0]
        assert set(v["tags"]) == {"신남", "댄스"}
        assert v["description"] == "설명입니다"
        assert v["notes"] == "메모입니다"

    def test_노래_가사_싱크_정보가_함께_내보내진다(self, repos):
        video_repo, song_repo = repos
        cat = Category.create("Music")
        video_repo.save_category(cat)
        agg = _make_video(video_repo, "https://youtu.be/a", "노래", category_id=cat.id)
        song = SongInfoAggregate.create(agg.id, is_song=True)
        song.edit_field("artist", "가수이름")
        # edit_lyrics는 수동 재입력용이라 시각을 버린다 — 실제 싱크 가사처럼
        # apply_fetched로 시각 있는 줄을 반영한다(LRCLIB 등 조회 결과와 동일 경로).
        song.apply_fetched(lyrics_lines=[LyricsLine("가사한줄", "번역한줄", start_ms=1000)])
        song.set_lyrics_offset(500)
        song_repo.save(song)

        writer = FakePackageWriter()
        handler = ExportLibraryHandler(video_repo, song_repo, writer)
        handler.handle(ExportLibraryCommand(category_ids=[cat.id], dest_path="out.zip"))

        _dest, _manifest, data = writer.calls[0]
        song_payload = data["videos"][0]["song"]
        assert song_payload["artist"] == "가수이름"
        assert song_payload["lyrics_offset_ms"] == 500
        assert song_payload["lyrics_lines"][0]["original"] == "가사한줄"
        assert song_payload["lyrics_lines"][0]["start_ms"] == 1000

    def test_노래가_아닌_영상은_song이_None이다(self, repos):
        video_repo, song_repo = repos
        cat = Category.create("Music")
        video_repo.save_category(cat)
        _make_video(video_repo, "https://youtu.be/a", "일반영상", category_id=cat.id)

        writer = FakePackageWriter()
        handler = ExportLibraryHandler(video_repo, song_repo, writer)
        handler.handle(ExportLibraryCommand(category_ids=[cat.id], dest_path="out.zip"))

        _dest, _manifest, data = writer.calls[0]
        assert data["videos"][0]["song"] is None

    def test_빈_카테고리를_내보내도_예외가_없다(self, repos):
        video_repo, song_repo = repos
        cat = Category.create("Empty")
        video_repo.save_category(cat)

        writer = FakePackageWriter()
        handler = ExportLibraryHandler(video_repo, song_repo, writer)
        result = handler.handle(ExportLibraryCommand(category_ids=[cat.id], dest_path="out.zip"))

        assert result.video_count == 0
        assert result.category_count == 1

    def test_내보내기_완료가_카운트와_함께_로그에_남는다(self, repos, caplog):
        video_repo, song_repo = repos
        cat = Category.create("Music")
        video_repo.save_category(cat)
        _make_video(video_repo, "https://youtu.be/a", "영상", category_id=cat.id)

        writer = FakePackageWriter()
        handler = ExportLibraryHandler(video_repo, song_repo, writer)
        with caplog.at_level("INFO"):
            handler.handle(ExportLibraryCommand(category_ids=[cat.id], dest_path="out.zip"))

        msg = next(r.message for r in caplog.records if "내보내기 완료" in r.message)
        assert "영상 1개" in msg
        assert "out.zip" in msg
