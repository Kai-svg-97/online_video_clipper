import sys

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from config.settings import ensure_data_dirs
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
    MarkWatchedHandler,
    MoveCategoryHandler,
    RefreshCategoryMetadataHandler,
    RenameCategoryHandler,
    UpdateVideoHandler,
)
from application.library.queries import (
    GetCategoriesHandler,
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

from gui.main_window import MainWindow
from gui.view_models.clip_vm import ClipViewModel
from gui.view_models.download_vm import DownloadViewModel
from gui.view_models.library_vm import LibraryViewModel
from gui.view_models.monitoring_vm import MonitoringViewModel


def main() -> int:
    # 1. Bootstrap data directories
    ensure_data_dirs()

    # 2. Initialize database
    db = Database()
    db.initialize()

    # 3. Repositories
    video_repo   = SqliteVideoRepository(db)
    download_repo = SqliteDownloadRepository(db)
    clip_repo    = SqliteClipRepository(db)
    channel_repo = SqliteChannelRepository(db)

    # 4. Infrastructure services
    event_bus = EventBus()
    ytdlp     = YtDlpAdapter()
    ffmpeg    = FfmpegAdapter()

    # 5. Download queue (in-memory aggregate)
    dl_queue = DownloadQueueAggregate()

    # 6. Application handlers — Library
    add_video        = AddVideoHandler(video_repo, event_bus, ytdlp)
    update_video     = UpdateVideoHandler(video_repo, event_bus)
    delete_video     = DeleteVideoHandler(video_repo, event_bus)
    mark_watched     = MarkWatchedHandler(video_repo, event_bus)
    assign_category  = AssignCategoryHandler(video_repo, event_bus)
    create_category  = CreateCategoryHandler(video_repo)
    rename_category  = RenameCategoryHandler(video_repo)
    delete_category  = DeleteCategoryHandler(video_repo)
    move_category    = MoveCategoryHandler(video_repo)
    delete_tag_h     = DeleteTagHandler(video_repo)
    refresh_metadata = RefreshCategoryMetadataHandler(video_repo, event_bus, ytdlp)
    get_videos       = GetVideosHandler(video_repo)
    search_videos    = SearchVideosHandler(video_repo)
    get_cats         = GetCategoriesHandler(video_repo)
    get_tags         = GetTagsHandler(video_repo)
    get_video_detail = GetVideoDetailHandler(video_repo, download_repo)
    stats_handler    = LibraryStatsHandler(video_repo, download_repo)

    # 7. Application handlers — Download
    start_dl  = StartDownloadHandler(dl_queue, download_repo, ytdlp, event_bus)
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
    )

    # 12. Launch GUI
    app = QApplication(sys.argv)
    app.setApplicationName("YouTube Content Manager")

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

    window = MainWindow(library_vm, download_vm, clip_vm, monitoring_vm, stats_handler)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
