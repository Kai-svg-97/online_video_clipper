"""앨범 보기 유스케이스 조립(노래 정보에서 파생된 그룹).

외부 앨범 정보(iTunes, 무키)가 실패해도 라이브러리에 있는 곡만으로 앨범을 구성한다
— 화면이 통째로 비지 않게 하는 폴백이 핸들러 안에 있다.
"""

from __future__ import annotations

from application.song.album_queries import (
    AddAlbumTracksHandler,
    FillAlbumTracksHandler,
    GetAlbumDetailHandler,
    GetAlbumsHandler,
    RemoveAlbumTrackLinkHandler,
    ResolveUnknownAlbumsHandler,
)

from bootstrap.context import AlbumHandlers, LibraryHandlers, Repositories, Services


def build(
    repos: Repositories,
    services: Services,
    library: LibraryHandlers,
) -> AlbumHandlers:
    video, song, album = repos.video, repos.song, repos.album
    provider = services.album_provider

    get_detail = GetAlbumDetailHandler(video, song, album, provider)
    return AlbumHandlers(
        # 목록 조회는 **네트워크를 쓰지 않는다** — 카테고리를 옮길 때마다 외부 API를
        # 때리지 않기 위해 캐시된 자켓만 붙인다.
        get_albums=GetAlbumsHandler(video, song, album),
        get_detail=get_detail,
        fill_tracks=FillAlbumTracksHandler(get_detail, album, services.media_source),
        resolve_unknown=ResolveUnknownAlbumsHandler(video, song, album, provider),
        # 수록곡 담기는 등록(AddVideoHandler)에 노래 정보 기록을 얹는다 — 그냥
        # 등록하면 앨범 값이 없어 '앨범 미상'으로 떨어진다(담았는데 안 보인다).
        add_tracks=AddAlbumTracksHandler(library.add_video, song),
        remove_track_link=RemoveAlbumTrackLinkHandler(album),
    )
