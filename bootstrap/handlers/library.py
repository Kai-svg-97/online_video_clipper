"""라이브러리(영상·카테고리·태그) 유스케이스 조립.

`SongHandlers`를 인자로 받는다 — 등록 경로가 노래 감지·가사 보강에 쓰기 때문에
song 컨텍스트가 **먼저** 조립돼 있어야 한다.
"""

from __future__ import annotations

from application.library.saved_search_commands import (
    DeleteSavedSearchHandler,
    ListSavedSearchesHandler,
    RenameSavedSearchHandler,
    SaveSearchHandler,
)
from application.library.commands import (
    AddVideoHandler,
    AssignCategoryHandler,
    CreateCategoryHandler,
    DeleteCategoryHandler,
    DeleteTagHandler,
    DeleteVideoCommand,
    DeleteVideoHandler,
    EnrichVideoHandler,
    ImportYouTubePlaylistToCategoryHandler,
    MarkWatchedHandler,
    MoveCategoryHandler,
    RefreshCategoryMetadataHandler,
    RefreshVideoMetadataHandler,
    RefreshVideoThumbnailHandler,
    RenameCategoryHandler,
    SetCategoryVideoOrderHandler,
    UpdatePlaybackPositionHandler,
    UpdateVideoHandler,
)
from application.library.subtitle_commands import (
    BulkIndexSubtitlesHandler,
    TranscribeVideoHandler,
    FetchAndIndexSubtitlesHandler,
    IndexSubtitleCuesHandler,
)
from application.library.subtitle_queries import (
    GetSubtitleCoverageHandler,
    GetSubtitleIndexesHandler,
    GetSubtitleLinesHandler,
)
from infrastructure.subtitle.youtube_subtitles import (
    fetch_cues,
    fetch_tracks_for_url,
)

from application.library.maintenance import (
    FindBrokenDownloadsHandler,
    FindMissingSourcesHandler,
    FindDuplicatesQuery,
    FindDuplicateVideosHandler,
)
from application.library.queries import (
    GetCategoriesHandler,
    GetCategoryVideoOrderHandler,
    GetDownloadedFormatsHandler,
    GetTagsHandler,
    GetVideoDetailHandler,
    GetVideoIdByUrlHandler,
    GetVideosHandler,
    LibraryStatsHandler,
    SearchVideosHandler,
)

from bootstrap.context import LibraryHandlers, Repositories, Services, SongHandlers


def _build_cleanup_fns(video_repo, download_repo, delete_video, availability) -> tuple:
    """라이브러리 정리 콜백 4종 — (중복 찾기, 끊긴 파일 찾기, 일괄 삭제, 원본 소실 찾기).

    **찾아 주기만 하고 삭제는 사용자가 고른 것만 한다** — 자동 삭제 경로는 없다.
    """
    find_dups = FindDuplicateVideosHandler(video_repo)
    find_broken = FindBrokenDownloadsHandler(download_repo)

    def delete_bulk(video_ids) -> None:
        for vid in video_ids:
            delete_video.handle(DeleteVideoCommand(video_id=vid))

    find_missing = FindMissingSourcesHandler(video_repo, availability)

    return (
        lambda: find_dups.handle(FindDuplicatesQuery()),
        find_broken.handle,
        delete_bulk,
        find_missing.handle,
    )


def build(
    repos: Repositories,
    services: Services,
    song: SongHandlers,
) -> LibraryHandlers:
    video, download = repos.video, repos.download
    bus = services.event_bus
    media = services.media_source

    # 자막 조회·다운로드 함수를 **여기서 꽂는다** — 핸들러가
    # `infrastructure/subtitle/`를 직접 import 하면 application → infrastructure
    # 의존이 생긴다(DDD 의존 규칙). 단건·일괄이 같은 인스턴스를 공유한다.
    fetch_subtitles = FetchAndIndexSubtitlesHandler(
        repos.subtitle, track_lister=fetch_tracks_for_url, cue_fetcher=fetch_cues
    )

    # 등록은 노래 감지에 song 체인을 쓴다(등록 시 메타데이터만, 가사는 보강 단계에서).
    add_video = AddVideoHandler(video, bus, media, song_fetch=song.fetch)
    delete_video = DeleteVideoHandler(video, bus)

    return LibraryHandlers(
        add_video=add_video,
        update_video=UpdateVideoHandler(video, bus),
        delete_video=delete_video,
        mark_watched=MarkWatchedHandler(video, bus),
        # 이어보기 — 재생 중 5초마다 불리므로 아그리게이트 전체 저장이 아니라
        # 가벼운 UPDATE 전용 경로를 쓴다.
        update_position=UpdatePlaybackPositionHandler(video),
        # 등록 직후 요약(비노래)·가사(노래) 자동 보강.
        list_saved_searches=ListSavedSearchesHandler(repos.saved_search),
        save_search=SaveSearchHandler(repos.saved_search),
        delete_saved_search=DeleteSavedSearchHandler(repos.saved_search),
        rename_saved_search=RenameSavedSearchHandler(repos.saved_search),
        enrich_video=EnrichVideoHandler(
            video,
            repos.song,
            song_fetch=song.fetch,
            summary_source=services.summary_source,
            event_bus=bus,
        ),
        assign_category=AssignCategoryHandler(video, bus),
        create_category=CreateCategoryHandler(video),
        rename_category=RenameCategoryHandler(video),
        delete_category=DeleteCategoryHandler(video),
        move_category=MoveCategoryHandler(video),
        delete_tag=DeleteTagHandler(video),
        refresh_category_metadata=RefreshCategoryMetadataHandler(video, bus, media),
        refresh_video_metadata=RefreshVideoMetadataHandler(video, bus, media),
        refresh_thumbnail=RefreshVideoThumbnailHandler(video, media),
        import_youtube_playlist_to_category=ImportYouTubePlaylistToCategoryHandler(
            video, bus, media, add_video_handler=add_video
        ),
        get_videos=GetVideosHandler(video),
        search_videos=SearchVideosHandler(video),
        get_categories=GetCategoriesHandler(video),
        get_tags=GetTagsHandler(video),
        get_video_detail=GetVideoDetailHandler(video, download),
        get_downloaded_formats=GetDownloadedFormatsHandler(download),
        get_video_id_by_url=GetVideoIdByUrlHandler(video),
        get_category_order=GetCategoryVideoOrderHandler(video),
        set_category_order=SetCategoryVideoOrderHandler(video),
        stats=LibraryStatsHandler(video, download),
        cleanup_fns=_build_cleanup_fns(
            video, download, delete_video, services.availability_source
        ),
        index_subtitle_cues=IndexSubtitleCuesHandler(repos.subtitle),
        # 자막 조회·다운로드 함수를 **여기서 꽂는다** — 핸들러가
        # `infrastructure/subtitle/`를 직접 import 하면 application → infrastructure
        # 의존이 생긴다(DDD 의존 규칙).
        fetch_and_index_subtitles=fetch_subtitles,
        bulk_index_subtitles=BulkIndexSubtitlesHandler(
            video, repos.subtitle, fetch_subtitles
        ),
        get_subtitle_lines=GetSubtitleLinesHandler(repos.subtitle),
        get_subtitle_indexes=GetSubtitleIndexesHandler(repos.subtitle),
        subtitle_coverage=GetSubtitleCoverageHandler(video, repos.subtitle),
        transcribe_video=TranscribeVideoHandler(repos.subtitle, services.transcriber),
    )
