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
    AddAlbumTracksCommand,
    AddAlbumTracksHandler,
    FillAlbumTracksCommand,
    FillAlbumTracksHandler,
    GetAlbumDetailHandler,
    GetAlbumDetailQuery,
    GetAlbumsHandler,
    GetAlbumsQuery,
    RemoveAlbumTrackLinkCommand,
    RemoveAlbumTrackLinkHandler,
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

    def test_먼저_등록한_곡의_가수_제목으로_앨범을_확정한다(self, repos):
        """앨범명 텍스트 검색(fetch_album)보다 정확한 곡 기준 조회(find_album_of_track)를
        먼저 시도한다 — 표기 차이·동명 앨범으로 엉뚱한 앨범을 고르는 사고를 줄인다."""
        provider = _StubProvider(album=_wrong_album_meta(), track_album=_palette_meta())
        cat, handler = self._setup(repos, provider)

        detail = handler.handle(
            GetAlbumDetailQuery(album_key=make_album_key("IU", "Palette"), category_id=cat.id)
        )

        assert [t.track_no for t in detail.tracks] == [1, 2, 3]
        assert detail.tracks[0].title == "Palette"
        assert detail.tracks[0].origin == TRACK_ORIGIN_LIBRARY
        assert provider.album_calls == 0    # 앨범명 검색은 시도조차 하지 않았다
        assert provider.track_calls == 1

    def test_곡_기준_조회가_엉뚱한_앨범이면_앨범명_검색으로_되돌아간다(self, repos):
        """잘못된 collectionId 방어 — 찾은 앨범이 실제로 그 곡을 담고 있지 않으면
        무시하고 앨범명 검색으로 폴백한다."""
        provider = _StubProvider(album=_palette_meta(), track_album=_wrong_album_meta())
        cat, handler = self._setup(repos, provider)

        detail = handler.handle(
            GetAlbumDetailQuery(album_key=make_album_key("IU", "Palette"), category_id=cat.id)
        )

        assert [t.track_no for t in detail.tracks] == [1, 2, 3]
        assert detail.tracks[0].title == "Palette"
        assert provider.album_calls == 1
        assert provider.track_calls == 1


def _wrong_album_meta():
    """앵커 곡("Palette")을 담고 있지 않은 앨범 — 동명 앨범 오매칭 시나리오."""
    return AlbumMetadata(
        album_title="Palette",
        artist="다른가수",
        track_count=2,
        tracks=[
            AlbumTrackInfo(track_no=1, title="딴 노래1", artist="다른가수"),
            AlbumTrackInfo(track_no=2, title="딴 노래2", artist="다른가수"),
        ],
        source_name="iTunes",
    )


class _StubMedia:
    def __init__(self, results=None, unique=False):
        self._results = results or []
        self._unique = unique          # 곡마다 다른 영상을 주는 실제 검색과 같게
        self.queries: list[str] = []

    def fetch_search_videos(self, query, limit=12, cookie_opts=None):
        self.queries.append(query)
        if self._unique:
            n = len(self.queries)
            return [{"url": f"https://youtu.be/auto{n}", "title": query,
                     "channel_name": "official", "yt_video_id": f"auto{n}"}]
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
        # 곡마다 검색 결과가 다른 실제 검색과 같게(unique) — 각 후보 제목은 검색어를
        # 그대로 담고 있어 그 트랙의 검증(제목 일치)을 통과한다.
        media = _StubMedia(unique=True)
        key = make_album_key("IU", "Palette")

        filled = FillAlbumTracksHandler(detail_handler, albums, media).handle(
            FillAlbumTracksCommand(album_key=key, category_id=cat.id)
        )

        assert filled == 2                       # 밤편지 + 이런 엔딩
        assert "official audio" in media.queries[0]
        detail = detail_handler.handle(GetAlbumDetailQuery(album_key=key, category_id=cat.id))
        autos = [t for t in detail.tracks if t.origin == TRACK_ORIGIN_AUTO]
        assert len(autos) == 2
        # 서로 다른 곡이니 서로 다른 영상이 붙어야 한다 — 같은 URL이면 검증 없이
        # 아무 후보나 붙이던 예전 버그가 되살아난 것이다.
        assert len({t.stream_url for t in autos}) == 2

    def test_제목이_다른_곡의_음원은_붙이지_않는다(self, repos):
        """동명이곡·엉뚱한 검색 결과를 걸러 낸다 — 실제 신고된 문제(자신의 음원이
        아닌 경우가 붙는다)의 회귀 테스트."""
        videos, songs, albums = repos
        provider = _StubProvider(album=_palette_meta())
        cat = Category.create("Music")
        videos.save_category(cat)
        _add_song(videos, songs, "https://youtu.be/p1", "IU - Palette",
                  artist="IU", album="Palette", song_title="Palette", category_id=cat.id)
        detail_handler = GetAlbumDetailHandler(videos, songs, albums, provider)
        # 검색 결과가 "밤편지" 하나뿐이라 "이런 엔딩" 검색에도 같은 후보가 온다 —
        # 제목이 다르므로 "이런 엔딩"에는 붙으면 안 된다.
        media = _StubMedia([{
            "url": "https://youtu.be/auto1", "title": "IU - 밤편지 (Official Audio)",
            "channel_name": "1theK", "duration_sec": 254,
        }])
        key = make_album_key("IU", "Palette")

        filled = FillAlbumTracksHandler(detail_handler, albums, media).handle(
            FillAlbumTracksCommand(album_key=key, category_id=cat.id)
        )

        assert filled == 1                       # 밤편지만 (제목이 일치)
        detail = detail_handler.handle(GetAlbumDetailQuery(album_key=key, category_id=cat.id))
        by_title = {t.title: t.origin for t in detail.tracks}
        assert by_title["밤편지"] == TRACK_ORIGIN_AUTO
        assert by_title["이런 엔딩"] == TRACK_ORIGIN_MISSING   # 붙이지 않고 '없음'으로 남는다

    def test_이미_붙은_곡은_다시_검색하지_않는다(self, repos):
        videos, songs, albums = repos
        provider = _StubProvider(album=_palette_meta())
        cat = Category.create("Music")
        videos.save_category(cat)
        _add_song(videos, songs, "https://youtu.be/p1", "IU - Palette",
                  artist="IU", album="Palette", song_title="Palette", category_id=cat.id)
        detail_handler = GetAlbumDetailHandler(videos, songs, albums, provider)
        media = _StubMedia(unique=True)   # 곡마다 제목이 일치하는 후보 — 검증을 통과한다
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


def _two_disc_meta():
    """2장짜리 앨범 — 디스크마다 트랙 번호가 1번부터 다시 시작한다(iTunes 실제 형식)."""
    return AlbumMetadata(
        album_title="Mercury - Acts 1 & 2",
        artist="Imagine Dragons",
        track_count=4,
        tracks=[
            AlbumTrackInfo(track_no=1, title="Enemy", artist="Imagine Dragons", disc_no=1),
            AlbumTrackInfo(track_no=2, title="My Life", artist="Imagine Dragons", disc_no=1),
            AlbumTrackInfo(track_no=1, title="Bones", artist="Imagine Dragons", disc_no=2),
            AlbumTrackInfo(track_no=2, title="Symphony", artist="Imagine Dragons", disc_no=2),
        ],
        source_name="iTunes",
    )


class TestTwoDiscAlbum:
    """2장짜리 앨범에서 번호가 겹쳐 서로 다른 곡이 한 곡으로 뭉개지던 회귀.

    실제 증상: 'Mercury - Acts 1 & 2'(32곡)를 열면 같은 제목·같은 영상이 두 줄씩 뜨고,
    자동 매핑이 disc1/disc2의 같은 번호를 서로 덮어썼다.
    """

    def _setup(self, repos):
        videos, songs, albums = repos
        cat = Category.create("Music")
        videos.save_category(cat)
        _add_song(videos, songs, "https://youtu.be/d1t1", "Imagine Dragons - Enemy",
                  artist="Imagine Dragons", album="Mercury - Acts 1 & 2",
                  song_title="Enemy", category_id=cat.id)
        provider = _StubProvider(album=_two_disc_meta())
        handler = GetAlbumDetailHandler(videos, songs, albums, provider)
        key = make_album_key("Imagine Dragons", "Mercury - Acts 1 & 2")
        return cat, handler, key, albums

    def test_같은_번호라도_디스크가_다르면_다른_곡이다(self, repos):
        cat, handler, key, _albums = self._setup(repos)

        detail = handler.handle(GetAlbumDetailQuery(album_key=key, category_id=cat.id))

        slots = [(t.disc_no, t.track_no) for t in detail.tracks]
        assert slots == [(1, 1), (1, 2), (2, 1), (2, 2)]
        assert [t.title for t in detail.tracks] == ["Enemy", "My Life", "Bones", "Symphony"]

    def test_자동_매핑이_디스크별로_따로_저장된다(self, repos):
        videos, songs, albums = repos
        cat, handler, key, _ = self._setup(repos)
        media = _StubMedia(unique=True)   # 곡마다 제목이 일치하는 후보 — 검증을 통과한다

        FillAlbumTracksHandler(handler, albums, media).handle(
            FillAlbumTracksCommand(album_key=key, category_id=cat.id)
        )

        links = albums.get_track_links(key)
        # disc1-t2, disc2-t1, disc2-t2 — 번호만 키로 쓰면 2건으로 뭉개진다.
        assert set(links) == {(1, 2), (2, 1), (2, 2)}
        assert links[(2, 1)].track_title == "Bones"
        assert links[(1, 2)].track_title == "My Life"

    def test_검색어도_곡마다_다르다(self, repos):
        cat, handler, key, albums = self._setup(repos)
        media = _StubMedia([{"url": "https://youtu.be/auto", "title": "auto"}])

        FillAlbumTracksHandler(handler, albums, media).handle(
            FillAlbumTracksCommand(album_key=key, category_id=cat.id)
        )

        assert len(media.queries) == 3
        assert len(set(media.queries)) == 3   # 같은 검색이 반복되면 같은 곡을 붙인 것


class _StubAddVideo:
    """AddVideoHandler 스텁 — 등록된 URL을 기록하고 애그리게이트를 돌려준다."""

    def __init__(self, videos):
        self._videos = videos
        self.calls: list[tuple] = []

    def handle(self, cmd):
        # 실제 AddVideoHandler는 같은 URL이면 갱신만 한다(upsert) — 스텁도 그렇게 둔다.
        self.calls.append((cmd.url, cmd.category_id))
        existing = self._videos.get_by_url(cmd.url)
        if existing is not None:
            if cmd.category_id is not None:
                existing.assign_category(cmd.category_id)
            self._videos.save(existing)
            return existing
        agg = VideoAggregate.create(VideoUrl(cmd.url), cmd.url)
        if cmd.category_id is not None:
            agg.assign_category(cmd.category_id)
        self._videos.save(agg)
        return agg


class TestRemoveTrackLink:
    """잘못 붙은 자동 매핑을 사용자가 직접 지운다(앨범 수정 모드의 삭제 버튼)."""

    def test_지우면_다시_없음으로_돌아간다(self, repos):
        videos, songs, albums = repos
        cat = Category.create("Music")
        videos.save_category(cat)
        _add_song(videos, songs, "https://youtu.be/p1", "IU - Palette",
                  artist="IU", album="Palette", song_title="Palette", category_id=cat.id)
        detail_handler = GetAlbumDetailHandler(
            videos, songs, albums, _StubProvider(album=_palette_meta())
        )
        key = make_album_key("IU", "Palette")
        media = _StubMedia(unique=True)
        FillAlbumTracksHandler(detail_handler, albums, media).handle(
            FillAlbumTracksCommand(album_key=key, category_id=cat.id)
        )
        detail = detail_handler.handle(GetAlbumDetailQuery(album_key=key, category_id=cat.id))
        auto_track = next(t for t in detail.tracks if t.origin == TRACK_ORIGIN_AUTO)

        RemoveAlbumTrackLinkHandler(albums).handle(
            RemoveAlbumTrackLinkCommand(
                album_key=key, disc_no=auto_track.disc_no, track_no=auto_track.track_no
            )
        )

        reloaded = detail_handler.handle(GetAlbumDetailQuery(album_key=key, category_id=cat.id))
        by_slot = {t.slot: t for t in reloaded.tracks}
        assert by_slot[auto_track.slot].origin == TRACK_ORIGIN_MISSING

    def test_다른_슬롯은_건드리지_않는다(self, repos):
        videos, songs, albums = repos
        cat = Category.create("Music")
        videos.save_category(cat)
        _add_song(videos, songs, "https://youtu.be/p1", "IU - Palette",
                  artist="IU", album="Palette", song_title="Palette", category_id=cat.id)
        detail_handler = GetAlbumDetailHandler(
            videos, songs, albums, _StubProvider(album=_palette_meta())
        )
        key = make_album_key("IU", "Palette")
        media = _StubMedia(unique=True)
        FillAlbumTracksHandler(detail_handler, albums, media).handle(
            FillAlbumTracksCommand(album_key=key, category_id=cat.id)
        )

        RemoveAlbumTrackLinkHandler(albums).handle(
            RemoveAlbumTrackLinkCommand(album_key=key, disc_no=1, track_no=2)
        )

        remaining = albums.get_track_links(key)
        assert (1, 2) not in remaining
        assert (1, 3) in remaining   # "이런 엔딩"은 그대로 남아 있다


class TestAddAlbumTracks:
    """앨범 수록곡을 현재 카테고리에 한꺼번에 담기."""

    def _detail_with_auto(self, repos):
        videos, songs, albums = repos
        cat = Category.create("Music")
        videos.save_category(cat)
        _add_song(videos, songs, "https://youtu.be/p1", "IU - Palette",
                  artist="IU", album="Palette", song_title="Palette", category_id=cat.id)
        handler = GetAlbumDetailHandler(videos, songs, albums, _StubProvider(album=_palette_meta()))
        key = make_album_key("IU", "Palette")
        media = _StubMedia(unique=True)
        FillAlbumTracksHandler(handler, albums, media).handle(
            FillAlbumTracksCommand(album_key=key, category_id=cat.id)
        )
        detail = handler.handle(GetAlbumDetailQuery(album_key=key, category_id=cat.id))
        return cat, handler, key, detail

    def test_자동_매핑_곡만_카테고리에_등록한다(self, repos):
        videos, songs, albums = repos
        cat, _handler, _key, detail = self._detail_with_auto(repos)
        adder = _StubAddVideo(videos)

        count = AddAlbumTracksHandler(adder, songs).handle(
            AddAlbumTracksCommand(
                album_title=detail.album_title, artist=detail.artist,
                category_id=cat.id, tracks=detail.tracks,
            )
        )

        assert count == 2                                   # 자동 매핑 2곡
        assert all(c[1] == cat.id for c in adder.calls)     # 현재 카테고리로 들어간다
        assert all(url.startswith("https://youtu.be/auto") for url, _ in adder.calls)

    def test_담은_곡은_그_앨범으로_묶이도록_노래정보를_쓴다(self, repos):
        # 앨범 값을 안 쓰면 새 영상이 '앨범 미상'으로 떨어져 방금 담은 앨범에 안 보인다.
        videos, songs, albums = repos
        cat, handler, key, detail = self._detail_with_auto(repos)
        adder = _StubAddVideo(videos)

        AddAlbumTracksHandler(adder, songs).handle(
            AddAlbumTracksCommand(
                album_title=detail.album_title, artist=detail.artist,
                category_id=cat.id, tracks=detail.tracks,
            )
        )

        after = handler.handle(GetAlbumDetailQuery(album_key=key, category_id=cat.id))
        assert after.library_count == 3       # 원래 1곡 + 담은 2곡
        assert after.auto_count == 0

    def test_담을_곡이_없으면_아무_일도_하지_않는다(self, repos):
        videos, songs, _albums = repos
        adder = _StubAddVideo(videos)

        count = AddAlbumTracksHandler(adder, songs).handle(
            AddAlbumTracksCommand(album_title="X", tracks=[])
        )

        assert count == 0
        assert adder.calls == []

    def test_한_곡이_실패해도_나머지는_담는다(self, repos):
        videos, songs, _albums = repos
        cat, _handler, _key, detail = self._detail_with_auto(repos)

        class _Flaky(_StubAddVideo):
            def handle(self, cmd):
                if len(self.calls) == 0:
                    self.calls.append((cmd.url, cmd.category_id))
                    raise RuntimeError("등록 실패")
                return super().handle(cmd)

        adder = _Flaky(videos)
        count = AddAlbumTracksHandler(adder, songs).handle(
            AddAlbumTracksCommand(
                album_title=detail.album_title, category_id=cat.id, tracks=detail.tracks,
            )
        )

        assert count == 1     # 두 곡 중 하나만 실패
