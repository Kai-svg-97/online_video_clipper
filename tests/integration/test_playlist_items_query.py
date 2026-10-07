"""재생목록 항목 조회 — N+1 제거(성능 배치 7, A5).

회귀 배경: `GetPlaylistItemsHandler`가 재생목록 **전체** 항목을 읽은 뒤 쪽을 자르고,
남은 항목마다 `video_repo.get_by_id`(연결 여러 개)를 불렀다 — 119개 재생목록에서
연결 수백 회, 280ms. 이제 조회 전용 포트가 JOIN 한 번으로 LIMIT/OFFSET 한 쪽만 읽는다.

핸들러는 **조립 루트가 만든 것**을 쓴다(`bootstrap`이 포트를 주입하므로 생성자
시그니처에 시험이 묶이지 않는다). 연결 수는 `Database.connection` 진입 횟수로 센다.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from application.library.playlist_queries import GetPlaylistItemsQuery
from domain.library.aggregates import VideoAggregate
from domain.library.entities import Playlist
from domain.library.value_objects import ChannelInfo, Duration, VideoUrl
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository


@pytest.fixture(scope="module")
def qapp_instance():
    from PyQt6.QtWidgets import QApplication

    yield QApplication.instance() or QApplication([])


@pytest.fixture
def db(tmp_path):
    d = Database(path=tmp_path / "playlist_items.db")
    d.initialize()
    return d


@pytest.fixture
def graph(db, qapp_instance):
    from bootstrap import build_app_graph

    g = build_app_graph(db)
    yield g
    lib = g.view_models.library
    for worker in list(getattr(lib, "_list_workers", [])):
        worker.wait(3000)
    for name in ("library",):
        shutdown = getattr(getattr(g.view_models, name), "shutdown", None)
        if callable(shutdown):
            shutdown()


@pytest.fixture
def handler(graph):
    return graph.handlers.playlist.get_items


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


def _make_videos(repo: SqliteVideoRepository, n: int) -> list[VideoAggregate]:
    vids = []
    for i in range(n):
        agg = VideoAggregate.create(
            VideoUrl(f"https://www.youtube.com/watch?v=plitem{i:05d}"), f"영상 {i}"
        )
        agg.update_metadata(
            thumbnail_path=f"thumb_{i}.jpg",
            channel=ChannelInfo(f"채널{i}", f"https://www.youtube.com/@c{i}", f"UCpl{i:06d}"),
            duration=Duration(60 + i),
        )
        repo.save(agg)
        vids.append(agg)
    return vids


@pytest.fixture
def world(graph):
    """영상 6개를 position 순서 [v3, v0, v5, v1, v4, v2]로 재생목록 P에 넣는다."""
    video_repo = graph.repositories.video
    playlist_repo = graph.repositories.playlist
    vids = _make_videos(video_repo, 6)
    pl = Playlist.create("P")
    playlist_repo.save(pl)
    order = [vids[3], vids[0], vids[5], vids[1], vids[4], vids[2]]
    playlist_repo.set_items(pl.id, [v.video.id for v in order])
    return pl, order


class TestPlaylistItemsContent:
    def test_position_오름차순으로_모든_필드가_저장값과_같다(self, handler, world):
        pl, order = world

        items = handler.handle(GetPlaylistItemsQuery(pl.id, limit=50, offset=0))

        assert [i.video_id for i in items] == [v.video.id for v in order]
        assert [i.position for i in items] == sorted(i.position for i in items)
        for dto, agg in zip(items, order, strict=True):
            v = agg.video
            assert dto.playlist_id == pl.id
            assert dto.video_title == v.title
            assert dto.thumbnail_path == v.thumbnail_path
            assert dto.channel_name == v.channel.name
            assert dto.duration_sec == v.duration.seconds

    def test_limit_offset_쪽을_자른다(self, handler, world):
        pl, order = world
        ids = [v.video.id for v in order]

        page = handler.handle(GetPlaylistItemsQuery(pl.id, limit=2, offset=2))
        assert [i.video_id for i in page] == ids[2:4]

        assert handler.handle(GetPlaylistItemsQuery(pl.id, limit=2, offset=6)) == []
        assert handler.handle(GetPlaylistItemsQuery(pl.id, limit=0, offset=0)) == []

    def test_삭제된_영상은_빠지고_남은_순서는_유지된다(self, handler, graph, world):
        pl, order = world
        graph.repositories.video.delete(order[2].video.id)

        items = handler.handle(GetPlaylistItemsQuery(pl.id, limit=50, offset=0))

        expected = [v.video.id for i, v in enumerate(order) if i != 2]
        assert [i.video_id for i in items] == expected

    def test_빈_재생목록과_없는_재생목록은_빈_목록이다(self, handler, graph):
        from uuid import uuid4

        empty = Playlist.create("빈 목록")
        graph.repositories.playlist.save(empty)

        assert handler.handle(GetPlaylistItemsQuery(empty.id, limit=50, offset=0)) == []
        assert handler.handle(GetPlaylistItemsQuery(uuid4(), limit=50, offset=0)) == []


class TestPlaylistItemsNoNPlusOne:
    def test_119개_재생목록_조회는_연결이_2개_이하다(self, handler, graph, connections):
        vids = _make_videos(graph.repositories.video, 119)
        pl = Playlist.create("큰 목록")
        graph.repositories.playlist.save(pl)
        graph.repositories.playlist.set_items(pl.id, [v.video.id for v in vids])
        connections.clear()

        items = handler.handle(GetPlaylistItemsQuery(pl.id, limit=500, offset=0))

        assert len(items) == 119
        assert 0 < len(connections) <= 2, f"연결 {len(connections)}회 — N+1이다"

    def test_video_repo_get_by_id를_부르지_않는다(self, handler, world, monkeypatch):
        pl, order = world

        def boom(self, *a, **k):
            raise AssertionError("항목마다 get_by_id를 부르면 N+1이다")

        monkeypatch.setattr(SqliteVideoRepository, "get_by_id", boom)

        items = handler.handle(GetPlaylistItemsQuery(pl.id, limit=50, offset=0))

        assert len(items) == len(order)


class TestFirstItem:
    def test_get_playlist_first_item은_최소_position_항목을_연결_1회로_읽는다(
        self, graph, world, connections
    ):
        pl, order = world
        vm = graph.view_models.library
        connections.clear()

        first = vm.get_playlist_first_item(pl.id)

        assert first is not None
        assert first.video_id == order[0].video.id
        assert 0 < len(connections) <= 1, f"연결 {len(connections)}회"
