"""Integration tests that hit a real (in-memory) SQLite database."""
import pytest
from pathlib import Path

from domain.library.aggregates import VideoAggregate
from domain.library.repositories import SearchQuery
from domain.library.value_objects import VideoUrl
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository


@pytest.fixture
def repo(tmp_path):
    db = Database(path=tmp_path / "test.db")
    db.initialize()
    return SqliteVideoRepository(db)


def _make_agg(url="https://youtu.be/abc", title="Test Video"):
    return VideoAggregate.create(VideoUrl(url), title)


class TestSqliteVideoRepository:
    def test_save_and_get_by_id(self, repo):
        agg = _make_agg()
        repo.save(agg)
        loaded = repo.get_by_id(agg.id)
        assert loaded is not None
        assert loaded.video.title == "Test Video"

    def test_get_by_id_returns_none_for_unknown(self, repo):
        from uuid import uuid4
        assert repo.get_by_id(uuid4()) is None

    def test_exists_by_url(self, repo):
        agg = _make_agg(url="https://youtu.be/unique123")
        repo.save(agg)
        assert repo.exists_by_url("https://youtu.be/unique123") is True
        assert repo.exists_by_url("https://youtu.be/other") is False

    def test_search_pagination(self, repo):
        for i in range(10):
            repo.save(_make_agg(url=f"https://youtu.be/{i}", title=f"Video {i}"))
        page1 = repo.search(SearchQuery(limit=5, offset=0))
        page2 = repo.search(SearchQuery(limit=5, offset=5))
        assert len(page1) == 5
        assert len(page2) == 5
        ids1 = {a.id for a in page1}
        ids2 = {a.id for a in page2}
        assert ids1.isdisjoint(ids2)

    def test_delete(self, repo):
        agg = _make_agg()
        repo.save(agg)
        repo.delete(agg.id)
        assert repo.get_by_id(agg.id) is None

    def test_tag_association(self, repo):
        tag = repo.get_or_create_tag("python")
        agg = _make_agg()
        agg.set_tags([tag.id])
        repo.save(agg)
        loaded = repo.get_by_id(agg.id)
        assert tag.id in loaded.tag_ids

    def test_favorite_filter(self, repo):
        fav = _make_agg(url="https://youtu.be/fav", title="Fav Video")
        fav.update_metadata(favorite=True)
        repo.save(fav)
        repo.save(_make_agg(url="https://youtu.be/nofav", title="No Fav"))
        results = repo.search(SearchQuery(favorite_only=True))
        assert all(a.video.favorite for a in results)
        assert any(a.id == fav.id for a in results)
