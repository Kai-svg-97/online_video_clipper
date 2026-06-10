"""Integration tests that hit a real (in-memory) SQLite database."""
import pytest

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

    def test_list_tags_with_counts_scoped(self, repo):
        """인기 태그 스코핑 — 카테고리/영상 범위로 태그 집계가 한정된다."""
        from domain.library.entities import Category

        cat_a = Category.create("A")
        cat_b = Category.create("B")
        repo.save_category(cat_a)
        repo.save_category(cat_b)
        t_news = repo.get_or_create_tag("news")
        t_music = repo.get_or_create_tag("music")

        v1 = _make_agg(url="https://youtu.be/v1", title="V1")  # cat A + news
        v1.assign_category(cat_a.id)
        v1.set_tags([t_news.id])
        repo.save(v1)
        v2 = _make_agg(url="https://youtu.be/v2", title="V2")  # cat B + music
        v2.assign_category(cat_b.id)
        v2.set_tags([t_music.id])
        repo.save(v2)

        # 전역 집계: 두 태그 모두 등장
        all_counts = {t.name: c for t, c in repo.list_tags_with_counts()}
        assert all_counts.get("news") == 1
        assert all_counts.get("music") == 1

        # 카테고리 A 스코프: news만
        a_counts = {t.name: c for t, c in repo.list_tags_with_counts(category_ids=[cat_a.id])}
        assert a_counts == {"news": 1}

        # 영상 스코프: v2만 → music만
        v2_counts = {t.name: c for t, c in repo.list_tags_with_counts(video_ids=[v2.id])}
        assert v2_counts == {"music": 1}

    def test_favorite_filter(self, repo):
        fav = _make_agg(url="https://youtu.be/fav", title="Fav Video")
        fav.update_metadata(favorite=True)
        repo.save(fav)
        repo.save(_make_agg(url="https://youtu.be/nofav", title="No Fav"))
        results = repo.search(SearchQuery(favorite_only=True))
        assert all(a.video.favorite for a in results)
        assert any(a.id == fav.id for a in results)

    def test_categorized_only_excludes_uncategorized(self, repo):
        """\"로컬\" 루트 — categorized_only=True면 카테고리에 속한 영상만 반환한다."""
        from domain.library.entities import Category

        cat = Category.create("Games")
        repo.save_category(cat)
        categorized = _make_agg(url="https://youtu.be/cat1", title="Categorized")
        categorized.assign_category(cat.id)
        repo.save(categorized)
        repo.save(_make_agg(url="https://youtu.be/uncat", title="Uncategorized"))

        # 플래그 ON → 카테고리 영상만
        only = repo.search(SearchQuery(categorized_only=True))
        ids = {a.id for a in only}
        assert categorized.id in ids
        assert all(a.category_id is not None for a in only)

        # 플래그 OFF(기본) → 미분류 포함 전체
        everything = repo.search(SearchQuery())
        assert len(everything) == 2


class TestCategoryOrdering:
    def test_list_categories_sorted_by_name(self, repo):
        """Categories must come back in alphabetical order regardless of insert order."""
        from domain.library.entities import Category
        repo.save_category(Category.create("Zebra"))
        repo.save_category(Category.create("Apple"))
        repo.save_category(Category.create("Mango"))
        cats = repo.list_categories()
        names = [c.name for c in cats]
        assert names == sorted(names)


class TestDeleteZeroCountTags:
    def test_deletes_tags_with_no_videos(self, repo):
        tag_a = repo.get_or_create_tag("used-tag")
        repo.get_or_create_tag("orphan-tag")  # 고아 태그 — delete_zero_count_tags로 삭제되는지 검증용
        # Associate tag_a with a video
        agg = _make_agg(url="https://youtu.be/zzz111", title="Test")
        agg.set_tags([tag_a.id])
        repo.save(agg)
        # orphan-tag has no videos
        deleted = repo.delete_zero_count_tags()
        assert deleted == 1
        remaining = [t.name for t in repo.list_tags()]
        assert "used-tag" in remaining
        assert "orphan-tag" not in remaining
