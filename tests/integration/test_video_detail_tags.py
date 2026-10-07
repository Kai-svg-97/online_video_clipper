"""`GetVideoDetailHandler` 가 태그를 읽는 방식 (성능 배치 4, A4 상세).

회귀 배경: 상세를 열 때마다 `list_tags()`(라이브러리 **전체** 태그)를 읽어 영상 한 건의
태그명을 풀었다. 이제 그 영상의 태그명만 `video_tags JOIN tags`로 읽는다.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from application.library.queries import GetVideoDetailHandler
from domain.library.aggregates import VideoAggregate
from domain.library.entities import Tag
from domain.library.value_objects import VideoUrl
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository


@pytest.fixture
def db(tmp_path):
    d = Database(path=tmp_path / "detail_tags.db")
    d.initialize()
    return d


@pytest.fixture
def repo(db):
    return SqliteVideoRepository(db)


@pytest.fixture
def dl_repo():
    m = MagicMock()
    m.find_completed_by_url.return_value = []
    m.find_failed_by_url.return_value = []
    return m


@pytest.fixture
def world(repo):
    """태그 100개 중 영상 V 에는 2개('록', '재즈')만 붙인다."""
    tags = [Tag.create(f"태그{i:03d}") for i in range(98)]
    rock, jazz = Tag.create("록"), Tag.create("재즈")
    for t in [*tags, rock, jazz]:
        repo.save_tag(t)
    v = VideoAggregate.create(VideoUrl("https://www.youtube.com/watch?v=tagvideo001"), "V")
    v.set_tags([rock.id, jazz.id])
    repo.save(v)
    bare = VideoAggregate.create(VideoUrl("https://www.youtube.com/watch?v=tagvideo002"), "태그 없음")
    repo.save(bare)
    return v, bare


@pytest.fixture
def connections(monkeypatch):
    calls: list[int] = []
    original = Database.connection

    @contextmanager
    def counting(self):
        calls.append(1)
        with original(self) as conn:
            yield conn

    monkeypatch.setattr(Database, "connection", counting)
    return calls


class TestDetailTagNames:
    def test_그_영상의_태그명만_돌려준다(self, repo, dl_repo, world):
        v, _ = world
        dto = GetVideoDetailHandler(repo, dl_repo).handle(v.id)

        assert dto is not None
        # 순서는 원래도 정의되지 않았다 — 집합으로 비교한다.
        assert set(dto.tags) == {"록", "재즈"}
        assert len(dto.tags) == 2

    def test_전체_태그_목록을_읽지_않는다(self, repo, dl_repo, world, monkeypatch):
        """구조 고정 — 줄 237 의 `list_tags()` 가 남아 있으면 여기서 터진다."""
        v, _ = world

        def boom(*_a, **_k):
            raise AssertionError("list_tags() 를 부르면 안 된다 — 영상 한 건의 태그만 읽는다")

        monkeypatch.setattr(repo, "list_tags", boom)

        dto = GetVideoDetailHandler(repo, dl_repo).handle(v.id)

        assert dto is not None
        assert set(dto.tags) == {"록", "재즈"}

    def test_태그가_없는_영상은_빈_목록이다(self, repo, dl_repo, world):
        _, bare = world
        dto = GetVideoDetailHandler(repo, dl_repo).handle(bare.id)

        assert dto is not None
        assert list(dto.tags) == []

    def test_저장소_메서드_tag_names_for(self, repo, world):
        v, bare = world

        assert set(repo.tag_names_for(v.id)) == {"록", "재즈"}
        assert list(repo.tag_names_for(bare.id)) == []
        assert list(repo.tag_names_for(uuid4())) == []

    def test_상세_조회의_연결_수가_늘지_않는다(self, repo, dl_repo, world, connections):
        """현재 6개. 8ms 수용 기준은 측정(`dl_tags.py`)으로 넘기고, 구조만 고정한다."""
        v, _ = world
        connections.clear()

        dto = GetVideoDetailHandler(repo, dl_repo).handle(v.id)

        assert dto is not None
        assert 0 < len(connections) <= 6
