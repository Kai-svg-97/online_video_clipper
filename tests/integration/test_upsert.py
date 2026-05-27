"""Integration tests: upsert behaviour and tag extraction.

All tests use an in-memory SQLite DB (tmp_path fixture) and a stub YtDlpAdapter
so there is no real network I/O.
"""
import pytest
from unittest.mock import MagicMock
from uuid import uuid4

from domain.library.value_objects import VideoUrl
from infrastructure.event_bus import EventBus
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository
from application.library.commands import AddVideoHandler, AddVideoCommand


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    _db = Database(path=tmp_path / "test.db")
    _db.initialize()
    return _db


@pytest.fixture
def repo(db):
    return SqliteVideoRepository(db)


@pytest.fixture
def bus():
    return EventBus()


def _make_stub_ytdlp(*, title="Test Title", tags=None, categories=None, description=""):
    """Return a stub YtDlpAdapter that returns fixed metadata."""
    stub = MagicMock()
    stub.fetch_metadata.return_value = {
        "title": title,
        "uploader": "TestChannel",
        "uploader_url": "https://www.youtube.com/@TestChannel",
        "channel_id": "UC_test",
        "duration": 300,
        "upload_date": "20240101",
        "view_count": 1000,
        "thumbnail": "https://i.ytimg.com/vi/abc/hq720.jpg",
        "tags": tags or [],
        "categories": categories or [],
        "description": description,
    }
    stub.download_thumbnail.return_value = None
    return stub


URL_CANONICAL = "https://www.youtube.com/watch?v=TestVideoId1"
URL_WITH_LIST  = "https://www.youtube.com/watch?v=TestVideoId1&list=RD&start_radio=1"
URL_YOUTU_BE   = "https://youtu.be/TestVideoId1?si=tracking123"


# ---------------------------------------------------------------------------
# Upsert: same video ID, different URL forms
# ---------------------------------------------------------------------------

class TestUpsertUrlVariants:
    def test_canonical_then_canonical(self, repo, bus):
        handler = AddVideoHandler(repo, bus, ytdlp=_make_stub_ytdlp(title="First"))
        handler.handle(AddVideoCommand(url=URL_CANONICAL))
        assert repo.count(__import__("domain.library.repositories", fromlist=["SearchQuery"]).SearchQuery()) == 1

        handler.handle(AddVideoCommand(url=URL_CANONICAL))
        assert repo.count(__import__("domain.library.repositories", fromlist=["SearchQuery"]).SearchQuery()) == 1

    def test_list_url_upserts_existing(self, repo, bus):
        """Register with ?v=ID, re-register with &list= variant → still 1 video."""
        handler = AddVideoHandler(repo, bus, ytdlp=_make_stub_ytdlp())
        handler.handle(AddVideoCommand(url=URL_CANONICAL))
        handler.handle(AddVideoCommand(url=URL_WITH_LIST))
        from domain.library.repositories import SearchQuery
        assert repo.count(SearchQuery()) == 1

    def test_youtu_be_upserts_existing(self, repo, bus):
        """Register with canonical URL, re-register with youtu.be short link → still 1 video."""
        handler = AddVideoHandler(repo, bus, ytdlp=_make_stub_ytdlp())
        handler.handle(AddVideoCommand(url=URL_CANONICAL))
        handler.handle(AddVideoCommand(url=URL_YOUTU_BE))
        from domain.library.repositories import SearchQuery
        assert repo.count(SearchQuery()) == 1

    def test_si_param_upserts_existing(self, repo, bus):
        url_si = URL_CANONICAL + "&si=AAABBBCCC"
        handler = AddVideoHandler(repo, bus, ytdlp=_make_stub_ytdlp())
        handler.handle(AddVideoCommand(url=URL_CANONICAL))
        handler.handle(AddVideoCommand(url=url_si))
        from domain.library.repositories import SearchQuery
        assert repo.count(SearchQuery()) == 1


# ---------------------------------------------------------------------------
# Upsert: metadata updated correctly
# ---------------------------------------------------------------------------

class TestUpsertMetadataUpdate:
    def test_title_updated_on_re_register(self, repo, bus):
        AddVideoHandler(repo, bus, ytdlp=_make_stub_ytdlp(title="Old Title")).handle(
            AddVideoCommand(url=URL_CANONICAL)
        )
        AddVideoHandler(repo, bus, ytdlp=_make_stub_ytdlp(title="New Title")).handle(
            AddVideoCommand(url=URL_CANONICAL)
        )
        agg = repo.get_by_url(URL_CANONICAL)
        assert agg.video.title == "New Title"

    def test_channel_added_on_re_register(self, repo, bus):
        # First: no ytdlp → title=URL, no channel
        AddVideoHandler(repo, bus, ytdlp=None).handle(
            AddVideoCommand(url=URL_CANONICAL, fetch_metadata=False)
        )
        agg = repo.get_by_url(URL_CANONICAL)
        assert agg.video.channel is None

        # Second: with metadata → channel populated
        AddVideoHandler(repo, bus, ytdlp=_make_stub_ytdlp()).handle(
            AddVideoCommand(url=URL_CANONICAL)
        )
        agg = repo.get_by_url(URL_CANONICAL)
        assert agg.video.channel is not None
        assert agg.video.channel.name == "TestChannel"


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

class TestTagExtraction:
    def test_yt_tags_saved(self, repo, bus):
        handler = AddVideoHandler(
            repo, bus,
            ytdlp=_make_stub_ytdlp(tags=["python", "tutorial"])
        )
        handler.handle(AddVideoCommand(url=URL_CANONICAL))
        agg = repo.get_by_url(URL_CANONICAL)
        all_tags = {t.id: t.name for t in repo.list_tags()}
        names = {all_tags[tid] for tid in agg.tag_ids}
        assert "python" in names
        assert "tutorial" in names

    def test_categories_saved_as_tags(self, repo, bus):
        handler = AddVideoHandler(
            repo, bus,
            ytdlp=_make_stub_ytdlp(categories=["Music"])
        )
        handler.handle(AddVideoCommand(url=URL_CANONICAL))
        agg = repo.get_by_url(URL_CANONICAL)
        all_tags = {t.id: t.name for t in repo.list_tags()}
        names = {all_tags[tid] for tid in agg.tag_ids}
        assert "music" in names  # lowercased

    def test_tags_updated_on_re_register(self, repo, bus):
        """First register with no tags, re-register with tags → tags added."""
        AddVideoHandler(repo, bus, ytdlp=None).handle(
            AddVideoCommand(url=URL_CANONICAL, fetch_metadata=False)
        )
        assert len(repo.get_by_url(URL_CANONICAL).tag_ids) == 0

        AddVideoHandler(
            repo, bus,
            ytdlp=_make_stub_ytdlp(tags=["kpop"], categories=["Music"])
        ).handle(AddVideoCommand(url=URL_CANONICAL))

        agg = repo.get_by_url(URL_CANONICAL)
        assert len(agg.tag_ids) == 2

    def test_re_register_with_list_url_updates_tags(self, repo, bus):
        """Core regression: re-register via browser URL (with &list=) adds tags to existing video."""
        AddVideoHandler(repo, bus, ytdlp=None).handle(
            AddVideoCommand(url=URL_CANONICAL, fetch_metadata=False)
        )

        AddVideoHandler(
            repo, bus,
            ytdlp=_make_stub_ytdlp(tags=["kpop", "mv"], categories=["Music"])
        ).handle(AddVideoCommand(url=URL_WITH_LIST))

        from domain.library.repositories import SearchQuery
        assert repo.count(SearchQuery()) == 1          # no duplicate
        agg = repo.get_by_url(URL_CANONICAL)
        assert len(agg.tag_ids) == 3                   # kpop, mv, music

    def test_tag_counts_reflect_video_count(self, repo, bus):
        from application.library.queries import GetTagsHandler
        for i in range(3):
            AddVideoHandler(
                repo, bus,
                ytdlp=_make_stub_ytdlp(tags=["shared"], categories=[])
            ).handle(AddVideoCommand(url=f"https://www.youtube.com/watch?v=vid{i}"))

        tags = GetTagsHandler(repo).handle()
        shared = next(t for t in tags if t.name == "shared")
        assert shared.count == 3

    def test_description_hashtags_extracted(self, repo, bus):
        desc = "Official MV\n#더리슨 #TheListen\n#이예준 #나얼\n#music"
        handler = AddVideoHandler(
            repo, bus,
            ytdlp=_make_stub_ytdlp(description=desc)
        )
        handler.handle(AddVideoCommand(url=URL_CANONICAL))
        agg = repo.get_by_url(URL_CANONICAL)
        all_tags = {t.id: t.name for t in repo.list_tags()}
        names = {all_tags[tid] for tid in agg.tag_ids}
        assert "더리슨" in names
        assert "thelisten" in names    # lowercased
        assert "이예준" in names
        assert "나얼" in names
        assert "music" in names

    def test_description_hashtags_updated_on_upsert(self, repo, bus):
        """Re-register adds description hashtags that were missing from first registration."""
        AddVideoHandler(repo, bus, ytdlp=None).handle(
            AddVideoCommand(url=URL_CANONICAL, fetch_metadata=False)
        )
        assert len(repo.get_by_url(URL_CANONICAL).tag_ids) == 0

        desc = "#kpop #mv #official"
        AddVideoHandler(
            repo, bus,
            ytdlp=_make_stub_ytdlp(description=desc)
        ).handle(AddVideoCommand(url=URL_CANONICAL))

        agg = repo.get_by_url(URL_CANONICAL)
        all_tags = {t.id: t.name for t in repo.list_tags()}
        names = {all_tags[tid] for tid in agg.tag_ids}
        assert "kpop" in names
        assert "mv" in names
        assert "official" in names
