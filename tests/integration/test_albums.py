"""앨범 보기 유스케이스 — 실제 SQLite로 그루핑·매핑·자동 채우기를 검증한다.

여기서 지키는 계약:
* 앨범 목록 조회는 **네트워크를 쓰지 않는다**(카테고리를 옮길 때마다 외부 API를 때리면 안 된다).
* 외부 수록곡 목록에 내 라이브러리 곡이 정확히 매핑되고, 못 찾은 곡은 'missing'으로 남는다.
* 내가 가진 곡은 외부 목록에 없어도 **화면에서 사라지지 않는다**(보너스 트랙·라이브 버전).
* 외부 조회가 실패해도 내 곡만으로 앨범이 구성된다(폴백).
* 자동으로 붙인 곡은 DB에 남아 다시 열 때 재검색하지 않는다.
"""
from __future__ import annotations

import pytest

from application.song.album_dtos import (
    TRACK_ORIGIN_AUTO,
    TRACK_ORIGIN_LIBRARY,
    TRACK_ORIGIN_MISSING,
)
from application.song.album_queries import (
    FillAlbumTracksCommand,
    FillAlbumTracksHandler,
    GetAlbumDetailHandler,
    GetAlbumDetailQuery,
    GetAlbumsHandler,
    GetAlbumsQuery,
    ResolveUnknownAlbumsCommand,
    ResolveUnknownAlbumsHandler,
)
from domain.library.aggregates import VideoAggregate
from domain.library.entities import Category
from domain.library.value_objects import VideoUrl
from domain.song.aggregates import SongInfoAggregate
from domain.song.album import make_album_key
from domain.song.ports import AlbumMetadata, AlbumTrackInfo
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_album_repository import SqliteAlbumRepository
from infrastructure.persistence.sqlite_song_repository import SqliteSongRepository
from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository


@pytest.fixture
def db(tmp_path):
    d = Database(path=tmp_path / "albums.db")
    d.initialize()
    return d


@pytest.fixture
def repos(db):
    return (
        SqliteVideoRepository(db),
        SqliteSongRepository(db),
        SqliteAlbumRepository(db),
    )


def _add_song(videos, songs, url, title, *, artist="", album="", song_title="", category_id=None):
    agg = VideoAggregate.create(VideoUrl(url), title)
    if category_id is not None:
        agg.assign_category(category_id)
    videos.save(agg)
    info = SongInfoAggregate.create(agg.id, is_song=True)
    info.apply_fetched(artist=artist or None, album=album or None,
                       song_title=song_title or None)
    songs.save(info)
    return agg.id


class _StubProvider:
    """외부 앨범 출처 스텁 — 호출 횟수까지 세어 '조회하지 않는다'를 검증한다."""

    key = "stub"

    def __init__(self, album=None, track_album=None):
        self._album = album
        self._track_album = track_album
        self.album_calls = 0
        self.track_calls = 0

    def fetch_album(self, artist, album):
        self.album_calls += 1
        return self._album

    def find_album_of_track(self, artist, title):
        self.track_calls += 1
        return self._track_album


def _palette_meta():
    return AlbumMetadata(
        album_title="Palette",
        artist="IU",
        artwork_url="https://art/600x600bb.jpg",
        release_date="2017-04-21",
        genre="K-Pop",
        track_count=3,
        tracks=[
            AlbumTrackInfo(track_no=1, title="Palette", artist="IU", duration_sec=217),
            AlbumTrackInfo(track_no=2, title="밤편지", artist="IU", duration_sec=254),
            AlbumTrackInfo(track_no=3, title="이런 엔딩", artist="IU", duration_sec=200),
        ],
        source_name="iTunes",
    )


class TestAlbumList:
    def test_같은_앨범_노래가_한_카드로_묶인다(self, repos):
        videos, songs, albums = repos
        cat = Category.create("Music")
        videos.save_category(cat)
        _add_song(videos, songs, "https://youtu.be/a1", "IU - Palette",
                  artist="IU", album="Palette", category_id=cat.id)
        _add_song(videos, songs, "https://youtu.be/a2", "IU - 밤편지",
                  artist="IU", album="palette", category_id=cat.id)
        _add_song(videos, songs, "https://youtu.be/b1", "다른 노래",
                  artist="다른가수", album="다른앨범", category_id=cat.id)

        cards = GetAlbumsHandler(videos, songs, albums).handle(
            GetAlbumsQuery(category_id=cat.id)
        )

        assert len(cards) == 2
        palette = next(c for c in cards if c.album_title.lower() == "palette")
        assert palette.library_count == 2

    def test_앨범이_없는_노래는_미상_카드로_모인다(self, repos):
        videos, songs, albums = repos
        cat = Category.create("Music")
        videos.save_category(cat)
        _add_song(videos, songs, "https://youtu.be/u1", "무제1", artist="가수", category_id=cat.id)
        _add_song(videos, songs, "https://youtu.be/u2", "무제2", artist="가수", category_id=cat.id)

        cards = GetAlbumsHandler(videos, songs, albums).handle(
            GetAlbumsQuery(category_id=cat.id)
        )

        assert len(cards) == 1
        assert cards[0].key == ""
        assert cards[0].library_count == 2

    def test_목록_조회는_외부를_호출하지_않는다(self, repos):
        videos, songs, albums = repos
        cat = Category.create("Music")
        videos.save_category(cat)
        _add_song(videos, songs, "https://youtu.be/a1", "곡", artist="IU", album="Palette",
                  category_id=cat.id)

        # GetAlbumsHandler는 provider를 아예 받지 않는다 — 시그니처로 계약을 고정한다.
        cards = GetAlbumsHandler(videos, songs, albums).handle(GetAlbumsQuery(category_id=cat.id))

        assert cards and cards[0].artwork_url == ""


class TestAlbumDetail:
    def _setup(self, repos, provider):
        videos, songs, albums = repos
        cat = Category.create("Music")
        videos.save_category(cat)
        _add_song(videos, songs, "https://youtu.be/p1", "아이유 - 팔레트 (Official Audio)",
                  artist="IU", album="Palette", song_title="Palette", category_id=cat.id)
        _add_song(videos, songs, "https://youtu.be/p2", "IU - 밤편지 [MV]",
                  artist="IU", album="Palette", song_title="밤편지", category_id=cat.id)
        handler = GetAlbumDetailHandler(videos, songs, albums, provider)
        return cat, handler

    def test_외부_수록곡에_내_곡이_매핑되고_나머지는_missing이다(self, repos):
        provider = _StubProvider(album=_palette_meta())
        cat, handler = self._setup(repos, provider)

        detail = handler.handle(
            GetAlbumDetailQuery(album_key=make_album_key("IU", "Palette"), category_id=cat.id)
        )

        assert detail is not None
        assert [t.track_no for t in detail.tracks] == [1, 2, 3]
        assert detail.tracks[0].origin == TRACK_ORIGIN_LIBRARY
        assert detail.tracks[1].origin == TRACK_ORIGIN_LIBRARY
        assert detail.tracks[2].origin == TRACK_ORIGIN_MISSING
        assert detail.library_count == 2
        assert detail.missing_count == 1

    def test_두번째_조회는_캐시를_쓴다(self, repos):
        provider = _StubProvider(album=_palette_meta())
        cat, handler = self._setup(repos, provider)
        key = make_album_key("IU", "Palette")

        handler.handle(GetAlbumDetailQuery(album_key=key, category_id=cat.id))
        handler.handle(GetAlbumDetailQuery(album_key=key, category_id=cat.id))

        assert provider.album_calls == 1

    def test_refresh는_다시_받아온다(self, repos):
        provider = _StubProvider(album=_palette_meta())
        cat, handler = self._setup(repos, provider)
        key = make_album_key("IU", "Palette")

        handler.handle(GetAlbumDetailQuery(album_key=key, category_id=cat.id))
        handler.handle(GetAlbumDetailQuery(album_key=key, category_id=cat.id, refresh=True))

        assert provider.album_calls == 2

    def test_외부_조회가_실패해도_내_곡으로_구성한다(self, repos):
        provider = _StubProvider(album=None)
        cat, handler = self._setup(repos, provider)

        detail = handler.handle(
            GetAlbumDetailQuery(album_key=make_album_key("IU", "Palette"), category_id=cat.id)
        )

        assert detail is not None
        assert detail.library_count == 2
        assert all(t.origin == TRACK_ORIGIN_LIBRARY for t in detail.tracks)

    def test_외부_목록에_없는_내_곡도_뒤에_남는다(self, repos):
        videos, songs, albums = repos
        provider = _StubProvider(album=_palette_meta())
        cat, handler = self._setup(repos, provider)
        _add_song(videos, songs, "https://youtu.be/p9", "IU - 보너스 트랙",
                  artist="IU", album="Palette", song_title="보너스 트랙", category_id=cat.id)

        detail = handler.handle(
            GetAlbumDetailQuery(album_key=make_album_key("IU", "Palette"), category_id=cat.id)
        )

        titles = [t.title for t in detail.tracks]
        assert "보너스 트랙" in titles
        assert detail.tracks[-1].origin == TRACK_ORIGIN_LIBRARY

    def test_설명은_장르_발매일_수록곡수로_조립된다(self, repos):
        provider = _StubProvider(album=_palette_meta())
        cat, handler = self._setup(repos, provider)

        detail = handler.handle(
            GetAlbumDetailQuery(album_key=make_album_key("IU", "Palette"), category_id=cat.id)
        )

        assert "K-Pop" in detail.description
        assert "2017-04-21" in detail.description


class _StubMedia:
    def __init__(self, results=None):
        self._results = results or []
        self.queries: list[str] = []

    def fetch_search_videos(self, query, limit=12, cookie_opts=None):
        self.queries.append(query)
        return self._results


class TestFillTracks:
    def test_빠진_곡에_official_음원을_붙이고_저장한다(self, repos):
        videos, songs, albums = repos
        provider = _StubProvider(album=_palette_meta())
        cat = Category.create("Music")
        videos.save_category(cat)
        _add_song(videos, songs, "https://youtu.be/p1", "IU - Palette",
                  artist="IU", album="Palette", song_title="Palette", category_id=cat.id)
        detail_handler = GetAlbumDetailHandler(videos, songs, albums, provider)
        media = _StubMedia([{
            "url": "https://youtu.be/auto1", "title": "IU - 밤편지 (Official Audio)",
            "channel_name": "1theK", "yt_video_id": "auto1", "duration_sec": 254,
        }])
        key = make_album_key("IU", "Palette")

        filled = FillAlbumTracksHandler(detail_handler, albums, media).handle(
            FillAlbumTracksCommand(album_key=key, category_id=cat.id)
        )

        assert filled == 2                       # 밤편지 + 이런 엔딩
        assert "official audio" in media.queries[0]
        detail = detail_handler.handle(GetAlbumDetailQuery(album_key=key, category_id=cat.id))
        autos = [t for t in detail.tracks if t.origin == TRACK_ORIGIN_AUTO]
        assert len(autos) == 2
        assert autos[0].stream_url == "https://youtu.be/auto1"

    def test_이미_붙은_곡은_다시_검색하지_않는다(self, repos):
        videos, songs, albums = repos
        provider = _StubProvider(album=_palette_meta())
        cat = Category.create("Music")
        videos.save_category(cat)
        _add_song(videos, songs, "https://youtu.be/p1", "IU - Palette",
                  artist="IU", album="Palette", song_title="Palette", category_id=cat.id)
        detail_handler = GetAlbumDetailHandler(videos, songs, albums, provider)
        media = _StubMedia([{"url": "https://youtu.be/auto1", "title": "auto"}])
        cmd = FillAlbumTracksCommand(album_key=make_album_key("IU", "Palette"), category_id=cat.id)
        handler = FillAlbumTracksHandler(detail_handler, albums, media)

        handler.handle(cmd)
        first_round = len(media.queries)
        handler.handle(cmd)

        assert len(media.queries) == first_round   # 두 번째 호출은 검색이 없다

    def test_취소하면_중간에_멈춘다(self, repos):
        videos, songs, albums = repos
        provider = _StubProvider(album=_palette_meta())
        cat = Category.create("Music")
        videos.save_category(cat)
        _add_song(videos, songs, "https://youtu.be/p1", "IU - Palette",
                  artist="IU", album="Palette", song_title="Palette", category_id=cat.id)
        detail_handler = GetAlbumDetailHandler(videos, songs, albums, provider)
        media = _StubMedia([{"url": "https://youtu.be/auto1", "title": "auto"}])

        filled = FillAlbumTracksHandler(detail_handler, albums, media).handle(
            FillAlbumTracksCommand(album_key=make_album_key("IU", "Palette"), category_id=cat.id),
            should_cancel=lambda: True,
        )

        assert filled == 0
        assert media.queries == []


class TestResolveUnknownAlbums:
    def test_앨범을_추정해_노래정보에_채운다(self, repos):
        videos, songs, albums = repos
        cat = Category.create("Music")
        videos.save_category(cat)
        vid = _add_song(videos, songs, "https://youtu.be/u1", "IU - 밤편지",
                        artist="IU", song_title="밤편지", category_id=cat.id)
        provider = _StubProvider(track_album=_palette_meta())

        resolved = ResolveUnknownAlbumsHandler(videos, songs, albums, provider).handle(
            ResolveUnknownAlbumsCommand(category_id=cat.id)
        )

        assert resolved == 1
        assert songs.get(vid).info.album == "Palette"

    def test_못_찾은_곡은_다시_조회하지_않는다(self, repos):
        videos, songs, albums = repos
        cat = Category.create("Music")
        videos.save_category(cat)
        _add_song(videos, songs, "https://youtu.be/u1", "무명곡", artist="무명",
                  song_title="무명곡", category_id=cat.id)
        provider = _StubProvider(track_album=None)
        handler = ResolveUnknownAlbumsHandler(videos, songs, albums, provider)

        handler.handle(ResolveUnknownAlbumsCommand(category_id=cat.id))
        handler.handle(ResolveUnknownAlbumsCommand(category_id=cat.id))

        assert provider.track_calls == 1
