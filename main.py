import os
import sys

# Qt6 DirectWrite가 구형 비트맵 폰트(MS Sans Serif)를 처리하지 못해 발생하는
# 무해한 경고를 억제한다. 앱 동작에는 영향 없음.
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.fonts=false")

from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import QApplication

from config.settings import ensure_data_dirs
from utils.logging_config import setup_logging
from utils.resources import get_resource_path
from infrastructure.event_bus import EventBus
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository
from infrastructure.persistence.sqlite_download_repository import SqliteDownloadRepository
from infrastructure.persistence.sqlite_clip_repository import SqliteClipRepository
from infrastructure.persistence.sqlite_channel_repository import SqliteChannelRepository
from infrastructure.downloader.ytdlp_adapter import YtDlpAdapter
from infrastructure.ffmpeg.ffmpeg_adapter import FfmpegAdapter

from domain.download.aggregates import DownloadQueueAggregate

from application.library.commands import (
    AddVideoHandler,
    AssignCategoryHandler,
    CreateCategoryHandler,
    DeleteCategoryHandler,
    DeleteTagHandler,
    DeleteVideoHandler,
    ImportYouTubePlaylistToCategoryHandler,
    MarkWatchedHandler,
    MoveCategoryHandler,
    RefreshCategoryMetadataHandler,
    RenameCategoryHandler,
    SetCategoryVideoOrderHandler,
    UpdateVideoHandler,
)
from application.library.queries import (
    GetCategoriesHandler,
    GetCategoryVideoOrderHandler,
    GetTagsHandler,
    GetVideoDetailHandler,
    GetVideosHandler,
    LibraryStatsHandler,
    SearchVideosHandler,
)
from application.download.commands import CancelDownloadHandler, StartDownloadHandler
from application.download.event_bridge import DownloadEventBridge
from application.download.queries import GetDownloadHistoryHandler, GetDownloadQueueHandler
from application.clip.commands import DeleteClipHandler, ExtractClipHandler
from application.clip.queries import GetClipsHandler
from application.monitoring.commands import (
    SetMonitoringRuleHandler,
    SubscribeChannelHandler,
    UnsubscribeChannelHandler,
)
from application.monitoring.queries import GetSubscriptionsHandler
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
    RenamePlaylistHandler,
    RenamePlaylistFolderHandler,
    ReorderPlaylistHandler,
)
from application.monitoring.commands import ImportYouTubeSubscriptionsHandler
from infrastructure.youtube.oauth_adapter import YouTubeOAuthAdapter
from infrastructure.youtube.youtube_api_adapter import YouTubeApiAdapter
from application.library.playlist_queries import (
    GetChannelVideosHandler,
    GetPlaylistFoldersHandler,
    GetPlaylistItemsHandler,
    GetPlaylistsHandler,
    GetSubscribedChannelInfosHandler,
    GetSubscriptionFeedHandler,
    GetYouTubePlaylistsHandler,
)
from infrastructure.persistence.sqlite_playlist_repository import (
    SqlitePlaylistFolderRepository,
    SqlitePlaylistRepository,
)
from infrastructure.auth.youtube_auth import YouTubeAuthService

from gui.main_window import MainWindow
from gui.view_models.clip_vm import ClipViewModel
from gui.view_models.download_vm import DownloadViewModel
from gui.view_models.feed_vm import FeedViewModel
from gui.view_models.library_vm import LibraryViewModel
from gui.view_models.monitoring_vm import MonitoringViewModel
from gui.view_models.playlist_vm import PlaylistViewModel


def main() -> int:
    # 1. Bootstrap data directories
    ensure_data_dirs()
    setup_logging()

    # 2. Initialize database
    db = Database()
    db.initialize()

    # 3. Repositories
    video_repo    = SqliteVideoRepository(db)
    download_repo = SqliteDownloadRepository(db)
    clip_repo     = SqliteClipRepository(db)
    channel_repo  = SqliteChannelRepository(db)
    playlist_repo  = SqlitePlaylistRepository(db)
    folder_repo    = SqlitePlaylistFolderRepository(db)

    # 4. Infrastructure services
    event_bus    = EventBus()
    ytdlp        = YtDlpAdapter()
    yt_oauth     = YouTubeOAuthAdapter(db)
    ffmpeg       = FfmpegAdapter()
    auth_service = YouTubeAuthService()

    # 5. Download queue (in-memory aggregate)
    dl_queue = DownloadQueueAggregate()

    # 6. Application handlers — Library
    add_video           = AddVideoHandler(video_repo, event_bus, ytdlp)
    update_video        = UpdateVideoHandler(video_repo, event_bus)
    delete_video        = DeleteVideoHandler(video_repo, event_bus)
    mark_watched        = MarkWatchedHandler(video_repo, event_bus)
    assign_category     = AssignCategoryHandler(video_repo, event_bus)
    create_category     = CreateCategoryHandler(video_repo)
    rename_category     = RenameCategoryHandler(video_repo)
    delete_category     = DeleteCategoryHandler(video_repo)
    move_category       = MoveCategoryHandler(video_repo)
    delete_tag_h        = DeleteTagHandler(video_repo)
    refresh_metadata    = RefreshCategoryMetadataHandler(video_repo, event_bus, ytdlp)
    get_videos          = GetVideosHandler(video_repo)
    search_videos       = SearchVideosHandler(video_repo)
    get_cats            = GetCategoriesHandler(video_repo)
    get_tags            = GetTagsHandler(video_repo)
    get_video_detail    = GetVideoDetailHandler(video_repo, download_repo)
    stats_handler       = LibraryStatsHandler(video_repo, download_repo)
    get_cat_order_h     = GetCategoryVideoOrderHandler(video_repo)
    set_cat_order_h     = SetCategoryVideoOrderHandler(video_repo)
    import_yt_to_cat_h = ImportYouTubePlaylistToCategoryHandler(
        video_repo, event_bus, ytdlp, add_video_handler=add_video
    )

    # 7. Application handlers — Download
    start_dl  = StartDownloadHandler(
        dl_queue, download_repo, ytdlp, event_bus,
        make_downloader=lambda cb: YtDlpAdapter(on_progress=cb),
    )
    cancel_dl = CancelDownloadHandler(dl_queue, event_bus)
    get_queue = GetDownloadQueueHandler(dl_queue)
    get_hist  = GetDownloadHistoryHandler(download_repo)

    # 8. Application handlers — Clip
    extract_clip = ExtractClipHandler(clip_repo, ffmpeg, event_bus)
    delete_clip  = DeleteClipHandler(clip_repo, event_bus)
    get_clips    = GetClipsHandler(clip_repo)

    # 9. Application handlers — Monitoring
    subscribe_ch   = SubscribeChannelHandler(channel_repo, event_bus, ytdlp)
    unsubscribe_ch = UnsubscribeChannelHandler(channel_repo, event_bus)
    set_rule       = SetMonitoringRuleHandler(channel_repo)
    get_subs       = GetSubscriptionsHandler(channel_repo)

    # 9b. Application handlers — Playlist
    # YouTube API 어댑터 (인증되어 있으면 활성화)
    _yt_creds      = yt_oauth.get_credentials()
    _yt_api        = None
    if _yt_creds is not None:
        _yt_api = YouTubeApiAdapter(_yt_creds)

    create_playlist_h  = CreatePlaylistHandler(playlist_repo)
    delete_playlist_h  = DeletePlaylistHandler(playlist_repo)
    add_to_playlist_h  = AddVideoToPlaylistHandler(playlist_repo, video_repo, _yt_api)
    remove_from_pl_h   = RemoveVideoFromPlaylistHandler(playlist_repo, _yt_api)
    reorder_pl_h       = ReorderPlaylistHandler(playlist_repo, video_repo, _yt_api)
    import_yt_pl_h     = ImportYouTubePlaylistHandler(
        playlist_repo, video_repo, ytdlp,
        add_video_handler=add_video,
        yt_api=_yt_api,
        yt_oauth=yt_oauth,
        yt_api_factory=lambda creds: YouTubeApiAdapter(creds),
    )
    get_playlists_h    = GetPlaylistsHandler(playlist_repo)
    get_pl_items_h     = GetPlaylistItemsHandler(playlist_repo, video_repo)
    get_feed_h         = GetSubscriptionFeedHandler(ytdlp, video_repo, channel_repo, _yt_api)
    get_channel_vids_h = GetChannelVideosHandler(ytdlp, video_repo, _yt_api)
    get_ch_infos_h     = GetSubscribedChannelInfosHandler(_yt_api)
    add_url_to_pl_h    = AddUrlToPlaylistHandler(add_video, playlist_repo)

    # 9c. Playlist folder + YouTube API handlers
    rename_playlist_h  = RenamePlaylistHandler(playlist_repo, yt_api=_yt_api)
    create_folder_h    = CreatePlaylistFolderHandler(folder_repo)
    rename_folder_h    = RenamePlaylistFolderHandler(folder_repo)
    delete_folder_h    = DeletePlaylistFolderHandler(folder_repo)
    move_to_folder_h   = MovePlaylistToFolderHandler(playlist_repo)
    copy_yt_to_local_h = CopyYouTubePlaylistToLocalHandler(playlist_repo, video_repo, ytdlp)
    get_folders_h      = GetPlaylistFoldersHandler(folder_repo)
    push_to_yt_h       = PushPlaylistToYouTubeHandler(playlist_repo, video_repo, _yt_api) if _yt_api else None
    move_video_pl_h    = MoveVideoToPlaylistHandler(playlist_repo, video_repo, _yt_api)

    # 9d. YouTube 구독 채널 일괄 가져오기 (OAuth 우선, fallback: yt-dlp)
    import_yt_subs_h   = ImportYouTubeSubscriptionsHandler(subscribe_ch, ytdlp, _yt_api)

    # 10. Event bridge (translates domain events → application-level callbacks)
    dl_bridge = DownloadEventBridge(event_bus)

    # 11. ViewModels
    library_vm = LibraryViewModel(
        get_videos=get_videos,
        search_videos=search_videos,
        get_categories=get_cats,
        get_tags=get_tags,
        add_video=add_video,
        update_video=update_video,
        delete_video=delete_video,
        mark_watched=mark_watched,
        create_category=create_category,
        rename_category=rename_category,
        delete_category=delete_category,
        move_category=move_category,
        delete_tag=delete_tag_h,
        assign_category=assign_category,
        get_video_detail=get_video_detail,
        refresh_metadata=refresh_metadata,
        get_playlist_items=get_pl_items_h,
        get_category_order=get_cat_order_h,
        set_category_order=set_cat_order_h,
        import_yt_to_category=import_yt_to_cat_h,
    )
    get_yt_playlists_h = GetYouTubePlaylistsHandler(ytdlp, _yt_api)
    playlist_vm = PlaylistViewModel(
        get_playlists=get_playlists_h,
        create_playlist=create_playlist_h,
        delete_playlist=delete_playlist_h,
        add_video=add_to_playlist_h,
        remove_video=remove_from_pl_h,
        reorder=reorder_pl_h,
        import_yt=import_yt_pl_h,
        add_url_to_playlist=add_url_to_pl_h,
        get_yt_playlists=get_yt_playlists_h,
        get_folders=get_folders_h,
        rename_playlist=rename_playlist_h,
        create_folder=create_folder_h,
        rename_folder=rename_folder_h,
        delete_folder=delete_folder_h,
        move_to_folder=move_to_folder_h,
        copy_yt_to_local=copy_yt_to_local_h,
        push_to_yt=push_to_yt_h,
        move_video=move_video_pl_h,
        auth_service=auth_service,
    )
    feed_vm = FeedViewModel(
        handler=get_feed_h,
        channel_handler=get_channel_vids_h,
        channel_infos_handler=get_ch_infos_h,
        auth_service=auth_service,
    )
    download_vm = DownloadViewModel(
        start_handler=start_dl,
        cancel_handler=cancel_dl,
        queue_handler=get_queue,
        history_handler=get_hist,
        event_bridge=dl_bridge,
    )
    clip_vm = ClipViewModel(
        extract_handler=extract_clip,
        delete_handler=delete_clip,
        get_clips_handler=get_clips,
    )
    monitoring_vm = MonitoringViewModel(
        subscribe_handler=subscribe_ch,
        unsubscribe_handler=unsubscribe_ch,
        set_rule_handler=set_rule,
        get_subs_handler=get_subs,
        import_yt_handler=import_yt_subs_h,
        auth_service=auth_service,
    )

    # 12. Launch GUI
    app = QApplication(sys.argv)
    app.setApplicationName("YouTube Content Manager")
    # 앱 기본 폰트를 Windows 표준 폰트로 설정 — MS Sans Serif fallback 방지
    _default_font = QFont("Segoe UI", 9)
    app.setFont(_default_font)

    # 태스크바·윈도우 아이콘 설정
    _icon_path = get_resource_path("assets/icon.ico")
    if _icon_path.exists():
        _app_icon = QIcon(str(_icon_path))
        app.setWindowIcon(_app_icon)
    # Windows: 태스크바 그룹핑 AppUserModelID 설정
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "YTContentManager.App.1.0"
            )
        except Exception:
            pass

    window = MainWindow(
        library_vm, download_vm, clip_vm, monitoring_vm,
        stats_handler,
        playlist_vm=playlist_vm,
        feed_vm=feed_vm,
        auth_service=auth_service,
        yt_oauth=yt_oauth,
    )
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
