"""재생목록·폴더·구독 피드·추천 유스케이스 조립.

피드·채널·추천이 여기 함께 있는 이유는 셋 다 **YouTube API lazy provider**를
공유하기 때문이다(`Services.youtube_api`). 인증 규약을 바꿀 때 한 파일만 보면 된다.
"""

from __future__ import annotations

from application.library.playlist_commands import (
    AddUrlToPlaylistHandler,
    AddVideoToPlaylistHandler,
    CopyYouTubePlaylistToLocalHandler,
    CreatePlaylistFolderHandler,
    CreatePlaylistHandler,
    DeletePlaylistFolderHandler,
    DeletePlaylistHandler,
    ImportYouTubePlaylistHandler,
    MovePlaylistToFolderHandler,
    MoveVideoToPlaylistHandler,
    PushPlaylistToYouTubeHandler,
    RemoveVideoFromPlaylistHandler,
    RenamePlaylistFolderHandler,
    RenamePlaylistHandler,
    ReorderPlaylistHandler,
)
from application.library.playlist_queries import (
    GetChannelVideosHandler,
    GetPlaylistFoldersHandler,
    GetPlaylistItemsHandler,
    GetPlaylistsHandler,
    GetRecommendationsHandler,
    GetSubscribedChannelInfosHandler,
    GetSubscriptionFeedHandler,
    GetYouTubePlaylistsHandler,
)
from infrastructure.youtube.youtube_api_adapter import YouTubeApiAdapter

from bootstrap.context import LibraryHandlers, PlaylistHandlers, Repositories, Services


def build(
    repos: Repositories,
    services: Services,
    library: LibraryHandlers,
) -> PlaylistHandlers:
    playlist, folder, video, channel = (
        repos.playlist,
        repos.folder,
        repos.video,
        repos.channel,
    )
    media = services.media_source
    yt_api = services.youtube_api

    return PlaylistHandlers(
        create=CreatePlaylistHandler(playlist),
        delete=DeletePlaylistHandler(playlist),
        rename=RenamePlaylistHandler(playlist, yt_api_provider=yt_api),
        add_video=AddVideoToPlaylistHandler(playlist, video, yt_api_provider=yt_api),
        remove_video=RemoveVideoFromPlaylistHandler(playlist, yt_api_provider=yt_api),
        reorder=ReorderPlaylistHandler(playlist, video, yt_api_provider=yt_api),
        move_video=MoveVideoToPlaylistHandler(playlist, video, yt_api_provider=yt_api),
        add_url=AddUrlToPlaylistHandler(library.add_video, playlist),
        import_youtube=ImportYouTubePlaylistHandler(
            playlist,
            video,
            media,
            add_video_handler=library.add_video,
            yt_oauth=services.youtube_oauth,
            yt_api_factory=lambda creds: YouTubeApiAdapter(creds),
        ),
        copy_youtube_to_local=CopyYouTubePlaylistToLocalHandler(playlist, video, media),
        # 인증 여부와 무관하게 항상 만든다 — 미인증이면 `handle()` 호출 시점에
        # RuntimeError로 알려 주므로(뷰모델 워커가 error_occurred로 표출) 시작
        # 시점에 인증 유무를 미리 알 필요가 없다(lazy binding).
        push_to_youtube=PushPlaylistToYouTubeHandler(playlist, video, yt_api_provider=yt_api),
        get_playlists=GetPlaylistsHandler(playlist),
        get_items=GetPlaylistItemsHandler(playlist, video),
        get_youtube_playlists=GetYouTubePlaylistsHandler(media, yt_api_provider=yt_api),
        create_folder=CreatePlaylistFolderHandler(folder),
        rename_folder=RenamePlaylistFolderHandler(folder),
        delete_folder=DeletePlaylistFolderHandler(folder),
        move_to_folder=MovePlaylistToFolderHandler(playlist),
        get_folders=GetPlaylistFoldersHandler(folder),
        get_feed=GetSubscriptionFeedHandler(media, video, channel, yt_api_provider=yt_api),
        get_channel_videos=GetChannelVideosHandler(media, video, yt_api_provider=yt_api),
        get_channel_infos=GetSubscribedChannelInfosHandler(yt_api_provider=yt_api),
        get_recommendations=GetRecommendationsHandler(media, video, yt_api_provider=yt_api),
    )
