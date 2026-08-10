"""가져오기 3단계(Preview → 충돌감지 → Import) — 실제 SQLite 리포지토리로 검증."""
from __future__ import annotations

from uuid import uuid4

import pytest

from application.transfer.commands import (
    DetectImportConflictsCommand,
    DetectImportConflictsHandler,
    ImportLibraryCommand,
    ImportLibraryHandler,
    PreviewImportCommand,
    PreviewImportHandler,
)
from domain.library.aggregates import VideoAggregate
from domain.library.entities import Category
from domain.library.value_objects import VideoUrl
from domain.song.aggregates import SongInfoAggregate
from infrastructure.event_bus import EventBus
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_song_repository import SqliteSongRepository
from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository


class FakePackageReader:
    def __init__(self, manifest: dict, data: dict) -> None:
        self._manifest = manifest
        self._data = data
        self.thumbnail_calls: list[tuple] = []

    def read(self, src_path: str) -> tuple[dict, dict]:
        return self._manifest, self._data

    def import_thumbnail(self, src_path, thumbnail_rel, video_id):
        self.thumbnail_calls.append((src_path, thumbnail_rel, video_id))
        return None


def _pkg(categories, videos) -> tuple[dict, dict]:
    return {"format_version": 1}, {"categories": categories, "videos": videos}


def _video(url, title, category_id, **overrides) -> dict:
    base = {
        "id": str(uuid4()), "url": url, "title": title, "category_id": category_id,
        "notes": "", "description": "", "tags": [], "thumbnail_path": "", "song": None,
    }
    base.update(overrides)
    return base


@pytest.fixture
def repos(tmp_path):
    db = Database(tmp_path / "library.db")
    db.initialize()
    return SqliteVideoRepository(db), SqliteSongRepository(db)


class TestPreviewImport:
    def test_카테고리별_영상_수를_보여준다(self, repos):
        video_repo, song_repo = repos
        manifest, data = _pkg(
            [{"id": "c1", "name": "Music", "parent_id": None}],
            [_video("u1", "t1", "c1"), _video("u2", "t2", "c1")],
        )
        reader = FakePackageReader(manifest, data)
        handler = PreviewImportHandler(reader)
        preview = handler.handle(PreviewImportCommand(archive_path="pkg.zip"))

        assert preview.total_video_count == 2
        assert len(preview.categories) == 1
        assert preview.categories[0].name == "Music"
        assert preview.categories[0].video_count == 2


class TestDetectConflicts:
    def test_로컬에_없는_영상은_새_영상으로만_집계된다(self, repos):
        video_repo, song_repo = repos
        manifest, data = _pkg(
            [{"id": "c1", "name": "Music", "parent_id": None}],
            [_video("https://youtu.be/new", "새영상", "c1")],
        )
        reader = FakePackageReader(manifest, data)
        handler = DetectImportConflictsHandler(video_repo, song_repo, reader)
        result = handler.handle(DetectImportConflictsCommand(archive_path="pkg.zip", category_ids=[]))

        assert result.new_video_count == 1
        assert result.conflicts == ()

    def test_제목이_다르면_충돌_필드로_보고된다(self, repos):
        video_repo, song_repo = repos
        agg = VideoAggregate.create(VideoUrl("https://youtu.be/x"), "기존제목")
        video_repo.save(agg)

        manifest, data = _pkg(
            [{"id": "c1", "name": "Music", "parent_id": None}],
            [_video("https://youtu.be/x", "가져올제목", "c1")],
        )
        reader = FakePackageReader(manifest, data)
        handler = DetectImportConflictsHandler(video_repo, song_repo, reader)
        result = handler.handle(DetectImportConflictsCommand(archive_path="pkg.zip", category_ids=[]))

        assert result.new_video_count == 0
        assert len(result.conflicts) == 1
        title_diff = next(f for f in result.conflicts[0].fields if f.field == "title")
        assert title_diff.existing_value == "기존제목"
        assert title_diff.incoming_value == "가져올제목"
        assert title_diff.existing_filled is True
        assert title_diff.incoming_filled is True
        assert title_diff.default_choice == "existing"

    def test_기존값이_비어있으면_가져오기가_기본값이_된다(self, repos):
        video_repo, song_repo = repos
        agg = VideoAggregate.create(VideoUrl("https://youtu.be/x"), "제목")
        video_repo.save(agg)  # notes 비어있음

        manifest, data = _pkg(
            [{"id": "c1", "name": "Music", "parent_id": None}],
            [_video("https://youtu.be/x", "제목", "c1", notes="새 메모")],
        )
        reader = FakePackageReader(manifest, data)
        handler = DetectImportConflictsHandler(video_repo, song_repo, reader)
        result = handler.handle(DetectImportConflictsCommand(archive_path="pkg.zip", category_ids=[]))

        notes_diff = next(f for f in result.conflicts[0].fields if f.field == "notes")
        assert notes_diff.existing_filled is False
        assert notes_diff.incoming_filled is True
        assert notes_diff.default_choice == "incoming"

    def test_완전히_동일하면_충돌로_보고되지_않는다(self, repos):
        video_repo, song_repo = repos
        local_cat = Category.create("Music")
        video_repo.save_category(local_cat)
        agg = VideoAggregate.create(VideoUrl("https://youtu.be/x"), "제목", category_id=local_cat.id)
        video_repo.save(agg)

        manifest, data = _pkg(
            [{"id": "c1", "name": "Music", "parent_id": None}],
            [_video("https://youtu.be/x", "제목", "c1")],
        )
        reader = FakePackageReader(manifest, data)
        handler = DetectImportConflictsHandler(video_repo, song_repo, reader)
        result = handler.handle(DetectImportConflictsCommand(archive_path="pkg.zip", category_ids=[]))

        assert result.conflicts == ()

    def test_가사_오프셋_0은_비어있는_것으로_취급된다(self, repos):
        video_repo, song_repo = repos
        agg = VideoAggregate.create(VideoUrl("https://youtu.be/x"), "노래")
        video_repo.save(agg)
        song = SongInfoAggregate.create(agg.id, is_song=True)
        song_repo.save(song)  # lyrics_offset_ms == 0 (기본값)

        manifest, data = _pkg(
            [{"id": "c1", "name": "Music", "parent_id": None}],
            [_video("https://youtu.be/x", "노래", "c1",
                     song={"is_song": True, "artist": "", "album": "", "song_title": "",
                           "release_year": "", "lyrics_language": "", "lyrics_offset_ms": 800,
                           "lyrics_lines": [], "source_name": "", "source_url": ""})],
        )
        reader = FakePackageReader(manifest, data)
        handler = DetectImportConflictsHandler(video_repo, song_repo, reader)
        result = handler.handle(DetectImportConflictsCommand(archive_path="pkg.zip", category_ids=[]))

        offset_diff = next(f for f in result.conflicts[0].fields if f.field == "lyrics_offset_ms")
        assert offset_diff.existing_filled is False
        assert offset_diff.default_choice == "incoming"


class TestImportLibrary:
    def test_새_카테고리와_영상을_생성한다(self, repos):
        video_repo, song_repo = repos
        bus = EventBus()
        manifest, data = _pkg(
            [{"id": "c1", "name": "Music", "parent_id": None}],
            [_video("https://youtu.be/new", "새영상", "c1", tags=["댄스"])],
        )
        reader = FakePackageReader(manifest, data)
        handler = ImportLibraryHandler(video_repo, song_repo, bus, reader)
        result = handler.handle(ImportLibraryCommand(
            archive_path="pkg.zip", category_ids=[], resolutions={},
        ))

        assert result.created_count == 1
        assert result.category_count == 1
        cats = video_repo.list_categories()
        assert len(cats) == 1 and cats[0].name == "Music"
        created = video_repo.get_by_url("https://youtu.be/new")
        assert created is not None
        assert created.category_id == cats[0].id
        tag_names = {t.name for t in video_repo.list_tags()}
        assert "댄스" in tag_names

    def test_이름이_같은_카테고리는_새로_만들지_않고_합쳐진다(self, repos):
        video_repo, song_repo = repos
        bus = EventBus()
        existing_cat = Category.create("Music")
        video_repo.save_category(existing_cat)

        manifest, data = _pkg(
            [{"id": "c1", "name": "Music", "parent_id": None}],
            [_video("https://youtu.be/new", "새영상", "c1")],
        )
        reader = FakePackageReader(manifest, data)
        handler = ImportLibraryHandler(video_repo, song_repo, bus, reader)
        handler.handle(ImportLibraryCommand(archive_path="pkg.zip", category_ids=[], resolutions={}))

        cats = video_repo.list_categories()
        assert len(cats) == 1   # 중복 생성되지 않음
        created = video_repo.get_by_url("https://youtu.be/new")
        assert created.category_id == existing_cat.id

    def test_충돌_필드는_해결_결과에_따라_적용된다(self, repos):
        video_repo, song_repo = repos
        bus = EventBus()
        existing = VideoAggregate.create(VideoUrl("https://youtu.be/x"), "기존제목")
        video_repo.save(existing)

        manifest, data = _pkg(
            [{"id": "c1", "name": "Music", "parent_id": None}],
            [_video("https://youtu.be/x", "가져올제목", "c1")],
        )
        reader = FakePackageReader(manifest, data)
        handler = ImportLibraryHandler(video_repo, song_repo, bus, reader)
        result = handler.handle(ImportLibraryCommand(
            archive_path="pkg.zip", category_ids=[],
            resolutions={"https://youtu.be/x": {"title": "incoming"}},
        ))

        assert result.merged_count == 1
        assert result.created_count == 0
        merged = video_repo.get_by_url("https://youtu.be/x")
        assert merged.video.title == "가져올제목"

    def test_해결하지_않은_충돌_필드는_기존값을_유지한다(self, repos):
        video_repo, song_repo = repos
        bus = EventBus()
        existing = VideoAggregate.create(VideoUrl("https://youtu.be/x"), "기존제목")
        video_repo.save(existing)

        manifest, data = _pkg(
            [{"id": "c1", "name": "Music", "parent_id": None}],
            [_video("https://youtu.be/x", "가져올제목", "c1")],
        )
        reader = FakePackageReader(manifest, data)
        handler = ImportLibraryHandler(video_repo, song_repo, bus, reader)
        handler.handle(ImportLibraryCommand(archive_path="pkg.zip", category_ids=[], resolutions={}))

        merged = video_repo.get_by_url("https://youtu.be/x")
        assert merged.video.title == "기존제목"

    def test_태그는_해결_없이도_합집합으로_병합된다(self, repos):
        video_repo, song_repo = repos
        bus = EventBus()
        existing = VideoAggregate.create(VideoUrl("https://youtu.be/x"), "제목")
        existing_tag = video_repo.get_or_create_tag("기존태그")
        existing.set_tags([existing_tag.id])
        video_repo.save(existing)

        manifest, data = _pkg(
            [{"id": "c1", "name": "Music", "parent_id": None}],
            [_video("https://youtu.be/x", "제목", "c1", tags=["새태그"])],
        )
        reader = FakePackageReader(manifest, data)
        handler = ImportLibraryHandler(video_repo, song_repo, bus, reader)
        handler.handle(ImportLibraryCommand(archive_path="pkg.zip", category_ids=[], resolutions={}))

        merged = video_repo.get_by_url("https://youtu.be/x")
        tag_names = {t.name for t in video_repo.list_tags() if t.id in merged.tag_ids}
        assert tag_names == {"기존태그", "새태그"}

    def test_카테고리가_없던_영상은_가져온_카테고리로_채워진다(self, repos):
        video_repo, song_repo = repos
        bus = EventBus()
        existing = VideoAggregate.create(VideoUrl("https://youtu.be/x"), "제목")  # category_id=None
        video_repo.save(existing)

        manifest, data = _pkg(
            [{"id": "c1", "name": "Music", "parent_id": None}],
            [_video("https://youtu.be/x", "제목", "c1")],
        )
        reader = FakePackageReader(manifest, data)
        handler = ImportLibraryHandler(video_repo, song_repo, bus, reader)
        handler.handle(ImportLibraryCommand(archive_path="pkg.zip", category_ids=[], resolutions={}))

        merged = video_repo.get_by_url("https://youtu.be/x")
        music_cat = next(c for c in video_repo.list_categories() if c.name == "Music")
        assert merged.category_id == music_cat.id

    def test_노래_정보가_없던_영상에_가사가_추가된다(self, repos):
        video_repo, song_repo = repos
        bus = EventBus()
        existing = VideoAggregate.create(VideoUrl("https://youtu.be/x"), "노래")
        video_repo.save(existing)

        manifest, data = _pkg(
            [{"id": "c1", "name": "Music", "parent_id": None}],
            [_video("https://youtu.be/x", "노래", "c1", song={
                "is_song": True, "artist": "가수", "album": "", "song_title": "",
                "release_year": "", "lyrics_language": "", "lyrics_offset_ms": 300,
                "lyrics_lines": [{"original": "가사", "translation": "", "start_ms": None}],
                "source_name": "가져오기", "source_url": "",
            })],
        )
        reader = FakePackageReader(manifest, data)
        handler = ImportLibraryHandler(video_repo, song_repo, bus, reader)
        handler.handle(ImportLibraryCommand(archive_path="pkg.zip", category_ids=[], resolutions={}))

        song = song_repo.get(existing.id)
        assert song is not None
        assert song.info.artist == "가수"
        assert song.info.lyrics_lines[0].original == "가사"
        assert song.info.lyrics_offset_ms == 300

    def test_노래_아티스트_충돌은_해결결과대로_적용된다(self, repos):
        video_repo, song_repo = repos
        bus = EventBus()
        existing = VideoAggregate.create(VideoUrl("https://youtu.be/x"), "노래")
        video_repo.save(existing)
        song = SongInfoAggregate.create(existing.id, is_song=True)
        song.edit_field("artist", "기존가수")
        song_repo.save(song)

        manifest, data = _pkg(
            [{"id": "c1", "name": "Music", "parent_id": None}],
            [_video("https://youtu.be/x", "노래", "c1", song={
                "is_song": True, "artist": "새가수", "album": "", "song_title": "",
                "release_year": "", "lyrics_language": "", "lyrics_offset_ms": 0,
                "lyrics_lines": [], "source_name": "", "source_url": "",
            })],
        )
        reader = FakePackageReader(manifest, data)
        handler = ImportLibraryHandler(video_repo, song_repo, bus, reader)
        handler.handle(ImportLibraryCommand(
            archive_path="pkg.zip", category_ids=[],
            resolutions={"https://youtu.be/x": {"artist": "incoming"}},
        ))

        merged_song = song_repo.get(existing.id)
        assert merged_song.info.artist == "새가수"

    def test_이미_동일한_영상은_병합되어도_변경이_없다(self, repos):
        video_repo, song_repo = repos
        bus = EventBus()
        existing = VideoAggregate.create(VideoUrl("https://youtu.be/x"), "제목")
        video_repo.save(existing)

        manifest, data = _pkg(
            [{"id": "c1", "name": "Music", "parent_id": None}],
            [_video("https://youtu.be/x", "제목", "c1")],
        )
        reader = FakePackageReader(manifest, data)
        handler = ImportLibraryHandler(video_repo, song_repo, bus, reader)
        result = handler.handle(ImportLibraryCommand(archive_path="pkg.zip", category_ids=[], resolutions={}))

        assert result.merged_count == 1
        assert result.created_count == 0
