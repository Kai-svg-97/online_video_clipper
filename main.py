import sys

from PyQt6.QtWidgets import QApplication

from config.settings import ensure_data_dirs
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
    DeleteVideoHandler,
    MarkWatchedHandler,
    UpdateVideoHandler,
)
from application.library.queries import (
    GetCategoriesHandler,
    GetTagsHandler,
    GetVideosHandler,
    SearchVideosHandler,
)
from application.download.commands import CancelDownloadHandler, StartDownloadHandler
from application.download.queries import GetDownloadHistoryHandler, GetDownloadQueueHandler

from gui.main_window import MainWindow
from gui.view_models.library_vm import LibraryViewModel
from gui.view_models.download_vm import DownloadViewModel


def main() -> int:
    # 1. Bootstrap data directories
    ensure_data_dirs()

    # 2. Initialize database
    db = Database()
    db.initialize()

    # 3. Repositories
    video_repo     = SqliteVideoRepository(db)
    download_repo  = SqliteDownloadRepository(db)
    clip_repo      = SqliteClipRepository(db)
    channel_repo   = SqliteChannelRepository(db)

    # 4. Infrastructure services
    event_bus = EventBus()
    ytdlp     = YtDlpAdapter()
    ffmpeg    = FfmpegAdapter()

    # 5. Download queue (in-memory aggregate)
    dl_queue = DownloadQueueAggregate()

    # 6. Application handlers — Library
    add_video    = AddVideoHandler(video_repo, event_bus, ytdlp)
    update_video = UpdateVideoHandler(video_repo, event_bus)
    delete_video = DeleteVideoHandler(video_repo, event_bus)
    mark_watched = MarkWatchedHandler(video_repo, event_bus)
    get_videos   = GetVideosHandler(video_repo)
    search_videos = SearchVideosHandler(video_repo)
    get_cats     = GetCategoriesHandler(video_repo)
    get_tags     = GetTagsHandler(video_repo)

    # 7. Application handlers — Download
    start_dl   = StartDownloadHandler(dl_queue, download_repo, ytdlp, event_bus)
    cancel_dl  = CancelDownloadHandler(dl_queue, event_bus)
    get_queue  = GetDownloadQueueHandler(dl_queue)
    get_hist   = GetDownloadHistoryHandler(download_repo)

    # 8. ViewModels
    library_vm = LibraryViewModel(
        get_videos=get_videos,
        search_videos=search_videos,
        get_categories=get_cats,
        get_tags=get_tags,
        add_video=add_video,
        update_video=update_video,
        delete_video=delete_video,
        mark_watched=mark_watched,
    )
    download_vm = DownloadViewModel(
        start_handler=start_dl,
        cancel_handler=cancel_dl,
        queue_handler=get_queue,
        history_handler=get_hist,
        event_bus=event_bus,
    )

    # 9. Launch GUI
    app = QApplication(sys.argv)
    app.setApplicationName("YouTube Content Manager")
    window = MainWindow(library_vm, download_vm)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
