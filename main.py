import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Qt6 DirectWrite가 구형 비트맵 폰트(MS Sans Serif)를 처리하지 못해 발생하는
# 무해한 경고를 억제한다. 앱 동작에는 영향 없음.
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.fonts=false")

# Qt multimedia 내장 FFmpeg가 av_log로 직접 stderr에 출력하는
# INFO·WARNING 메시지([h264] Late SEI, Input #0, Stream # 등)를 억제한다.
# PyQt6 번들 avutil DLL을 찾아 av_log_set_level(AV_LOG_ERROR=16)을 호출.
import ctypes as _ct
import importlib.util as _ilu

def _suppress_av_log() -> None:
    spec = _ilu.find_spec("PyQt6")
    qt_bin = ""
    if spec and spec.submodule_search_locations:
        qt_bin = os.path.join(list(spec.submodule_search_locations)[0], "Qt6", "bin")
    for _name in ("avutil-59.dll", "avutil-58.dll", "avutil-57.dll", "avutil-56.dll"):
        for _base in ([qt_bin] if qt_bin else []) + [""]:
            _path = os.path.join(_base, _name) if _base else _name
            try:
                _ct.CDLL(_path).av_log_set_level(-8)  # AV_LOG_QUIET = -8
                return
            except OSError:
                pass

_suppress_av_log()
del _ct, _ilu, _suppress_av_log

from PyQt6.QtCore import Qt, QRect, QtMsgType, qInstallMessageHandler
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QPixmapCache
from PyQt6.QtWidgets import QApplication, QSplashScreen

# Qt 내부 QFFmpeg 객체 소멸 시 발생하는 무해한 QObject::disconnect 경고를 필터링한다.
_MUTED_QT = ("wildcard call disconnects from destroyed signal",)

def _qt_msg_handler(msg_type: QtMsgType, _ctx, message: str) -> None:
    if any(p in message for p in _MUTED_QT):
        return
    if msg_type in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
        print(f"[Qt] {message}", file=sys.stderr)

qInstallMessageHandler(_qt_msg_handler)

from config.settings import ensure_data_dirs
from utils.logging_config import setup_logging
from utils.resources import get_resource_path


def _build_youtube_oauth(db):
    """YouTubeOAuthAdapter를 keyring 우선 저장소 + 번들 Desktop 클라이언트로 구성한다.

    클라이언트 설정이 없어도(개발/미배포 빌드) None을 반환하지 않고 예외를
    던지지 않는다 — `has_client_config() == False`인 어댑터를 돌려줘
    앱 시작을 막지 않는다(YouTube API 의존 기능만 비활성).
    """
    from config.settings import DATA_DIR  # noqa: PLC0415
    from infrastructure.sync.keyring_secret_store import KeyringSecretStore  # noqa: PLC0415
    from infrastructure.youtube.oauth_adapter import YouTubeOAuthAdapter  # noqa: PLC0415
    from infrastructure.youtube.oauth_client_config import find_youtube_oauth_config  # noqa: PLC0415

    yt_secret_store = KeyringSecretStore(
        "online-video-clipper.youtube-oauth",
        Path(DATA_DIR) / "secrets" / "youtube_oauth.json",
    )
    return YouTubeOAuthAdapter(
        db,
        yt_secret_store,
        client_config_path=find_youtube_oauth_config(),
    )


def _build_splash_pixmap() -> QPixmap:
    W, H = 480, 240
    pix = QPixmap(W, H)
    pix.fill(QColor("#242424"))

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    icon_path = get_resource_path("assets/icon.ico")
    if icon_path.exists():
        icon_pix = QPixmap(str(icon_path)).scaled(
            80, 80,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawPixmap((W - icon_pix.width()) // 2, 28, icon_pix)

    painter.setPen(QColor("#ffffff"))
    painter.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
    painter.drawText(QRect(0, 122, W, 36), Qt.AlignmentFlag.AlignHCenter, "YouTube Content Manager")

    painter.setPen(QColor("#888888"))
    painter.setFont(QFont("Segoe UI", 9))
    painter.drawText(QRect(0, 172, W, 26), Qt.AlignmentFlag.AlignHCenter, "로딩 중…")

    painter.end()
    return pix


def main() -> int:
    # 1. QApplication 가장 먼저 생성 — 스플래시 화면 즉시 표시를 위해 초기화 전에 배치
    app = QApplication(sys.argv)
    app.setApplicationName("YouTube Content Manager")
    app.setFont(QFont("Segoe UI", 9))
    QPixmapCache.setCacheLimit(30720)  # 30 MB

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "YTContentManager.App.1.0"
            )
        except Exception:
            logger.debug("AppUserModelID 설정 실패 — 작업표시줄 아이콘 그룹화만 영향 받음")

    _icon_path = get_resource_path("assets/icon.ico")
    if _icon_path.exists():
        app.setWindowIcon(QIcon(str(_icon_path)))

    # 2. 스플래시 화면 즉시 표시 (무거운 임포트 전)
    _splash = QSplashScreen(_build_splash_pixmap())
    _splash.show()
    app.processEvents()

    # 3. Bootstrap
    ensure_data_dirs()
    setup_logging()

    # 3-1. 단일 인스턴스 가드 — 업데이트 직후 인스톨러/배치가 겹쳐 실행되거나 사용자가
    # 아이콘을 연달아 눌러도 하나만 살아남게 한다. **DB를 열기 전에** 판단해야
    # 두 프로세스가 같은 DB를 동시에 건드리지 않는다.
    from gui.single_instance import SingleInstanceGuard  # noqa: PLC0415

    _guard = SingleInstanceGuard()
    if not _guard.try_acquire():
        logger.info("이미 실행 중인 인스턴스가 있어 종료한다")
        _splash.close()
        return 0

    # 4. 무거운 임포트 — 스플래시가 보이는 동안 수행
    from infrastructure.event_bus import EventBus
    from infrastructure.persistence.database import Database
    from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository
    from infrastructure.persistence.sqlite_download_repository import SqliteDownloadRepository
    from infrastructure.persistence.sqlite_clip_repository import SqliteClipRepository
    from infrastructure.persistence.sqlite_channel_repository import SqliteChannelRepository
    from infrastructure.downloader.ytdlp_adapter import YtDlpAdapter
    from infrastructure.ffmpeg.ffmpeg_adapter import FfmpegAdapter
    from infrastructure.persistence.sqlite_album_repository import SqliteAlbumRepository
    from infrastructure.persistence.sqlite_song_repository import SqliteSongRepository
    from infrastructure.song.lyrics_providers import build_default_providers
    from infrastructure.song.translator import DeepTranslatorAdapter

    from domain.download.aggregates import DownloadQueueAggregate

    from application.library.commands import (
    UpdatePlaybackPositionHandler,
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
        UpdateVideoHandler,
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
    from application.song.commands import (
        AddLyricsSourceHandler,
        ApplyLyricsCandidateHandler,
        DeleteLyricsSourceHandler,
        FetchSongInfoHandler,
        ReorderLyricsSourcesHandler,
        SearchLyricsCandidatesHandler,
        SetLyricsOffsetHandler,
        SetSongFlagHandler,
        TranslateSongLyricsHandler,
        UpdateLyricsSourceHandler,
        UpdateSongFieldHandler,
        UpdateSongLyricsHandler,
    )
    from application.song.queries import (
        FindSongVideoIdsHandler,
        GetSongInfoHandler,
        ListLyricsSourcesHandler,
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
    from infrastructure.youtube.youtube_api_adapter import YouTubeApiAdapter
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
    from infrastructure.persistence.sqlite_playlist_repository import (
        SqlitePlaylistFolderRepository,
        SqlitePlaylistRepository,
    )
    from infrastructure.auth.youtube_auth import YouTubeAuthService

    from version import __version__
    from infrastructure.updater.update_checker import GithubUpdateChecker
    from application.updater.queries import CheckForUpdateHandler
    from application.updater.commands import DownloadUpdateHandler

    from gui.main_window import MainWindow
    from gui.view_models.clip_vm import ClipViewModel
    from gui.view_models.download_vm import DownloadViewModel
    from gui.view_models.feed_vm import FeedViewModel
    from gui.view_models.library_vm import LibraryViewModel
    from gui.view_models.monitoring_vm import MonitoringViewModel
    from gui.view_models.playlist_vm import PlaylistViewModel
    from gui.view_models.recommend_vm import RecommendViewModel
    from gui.view_models.song_vm import SongViewModel

    # 5. Initialize database — DB 열기 전 클라우드 스냅샷 부트스트랩(신규 기기만)
    from infrastructure.sync.sync_service import SyncService, pre_db_bootstrap
    if pre_db_bootstrap():
        logger.info("클라우드 스냅샷에서 로컬 DB 부트스트랩 완료")
    db = Database()
    db.initialize()

    # 6. Repositories
    video_repo    = SqliteVideoRepository(db)
    download_repo = SqliteDownloadRepository(db)
    clip_repo     = SqliteClipRepository(db)
    channel_repo  = SqliteChannelRepository(db)
    playlist_repo  = SqlitePlaylistRepository(db)
    folder_repo    = SqlitePlaylistFolderRepository(db)
    song_repo      = SqliteSongRepository(db)
    # 앨범 캐시는 파생 데이터라 동기화 캡처 대상이 아니다(Recording*로 감싸지 않는다).
    album_repo     = SqliteAlbumRepository(db)

    # 6b. 클라우드 동기화 — 연결돼 있으면 repo를 캡처(Recording*)로 교체(미연결이면 무변경).
    sync_service = SyncService(db)
    _rec_repos = sync_service.make_recording_repos(db)
    if _rec_repos is not None:
        video_repo    = _rec_repos["video"]
        song_repo     = _rec_repos["song"]
        clip_repo     = _rec_repos["clip"]
        download_repo = _rec_repos["download"]
        playlist_repo = _rec_repos["playlist"]
        folder_repo   = _rec_repos["folder"]
        logger.info("클라우드 동기화 연결됨 — 변경 캡처 활성화")

    # 7. Infrastructure services
    event_bus    = EventBus()
    ytdlp        = YtDlpAdapter()
    yt_oauth     = _build_youtube_oauth(db)
    ffmpeg       = FfmpegAdapter()
    auth_service = YouTubeAuthService()
    lyrics_providers = build_default_providers()
    translator       = DeepTranslatorAdapter()

    # 8. Download queue (in-memory aggregate)
    dl_queue = DownloadQueueAggregate()

    # 9. Application handlers — Library
    # Gemini 요약 추출기 — 등록 후 자동 보강(EnrichVideoHandler)과 다운로드 완료 캡처가 공유
    from infrastructure.browser.gemini_extractor import GeminiExtractor
    _gemini_extractor = GeminiExtractor()

    # 노래 정보 조회 핸들러 — AddVideoHandler가 등록 시 노래 감지·메타데이터 기록에 사용.
    fetch_song = FetchSongInfoHandler(
        song_repo, video_repo, event_bus,
        lyrics_providers=lyrics_providers,
        translator=translator,
        media_source=ytdlp,
    )
    add_video           = AddVideoHandler(video_repo, event_bus, ytdlp, song_fetch=fetch_song)
    # 이어보기 — 재생 위치 기록(가벼운 UPDATE 전용 경로를 쓴다).
    update_position     = UpdatePlaybackPositionHandler(video_repo)

    # 라이브러리 정리 — 찾아 주기만 하고 삭제는 사용자가 고른 것만 수행한다.
    from application.library.maintenance import (  # noqa: PLC0415
        FindBrokenDownloadsHandler,
        FindDuplicatesQuery,
        FindDuplicateVideosHandler,
    )

    _find_dups_h   = FindDuplicateVideosHandler(video_repo)
    _find_broken_h = FindBrokenDownloadsHandler(download_repo)

    def _delete_videos_bulk(video_ids) -> None:
        for vid in video_ids:
            delete_video.handle(DeleteVideoCommand(video_id=vid))

    cleanup_fns = (
        lambda: _find_dups_h.handle(FindDuplicatesQuery()),
        _find_broken_h.handle,
        _delete_videos_bulk,
    )
    # 단건 등록 직후 요약(비노래)·가사(노래) 자동 보강 — GUI 워커가 백그라운드에서 호출
    enrich_video        = EnrichVideoHandler(
        video_repo, song_repo,
        song_fetch=fetch_song,
        summary_source=_gemini_extractor,
        event_bus=event_bus,
    )
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
    refresh_video_meta  = RefreshVideoMetadataHandler(video_repo, event_bus, ytdlp)
    get_videos          = GetVideosHandler(video_repo)
    search_videos       = SearchVideosHandler(video_repo)
    get_cats            = GetCategoriesHandler(video_repo)
    get_tags            = GetTagsHandler(video_repo)
    get_video_detail    = GetVideoDetailHandler(video_repo, download_repo)
    get_dl_formats      = GetDownloadedFormatsHandler(download_repo)
    get_video_id_by_url = GetVideoIdByUrlHandler(video_repo)
    stats_handler       = LibraryStatsHandler(video_repo, download_repo)
    get_cat_order_h        = GetCategoryVideoOrderHandler(video_repo)
    set_cat_order_h        = SetCategoryVideoOrderHandler(video_repo)
    refresh_thumbnail_h    = RefreshVideoThumbnailHandler(video_repo, ytdlp)
    import_yt_to_cat_h = ImportYouTubePlaylistToCategoryHandler(
        video_repo, event_bus, ytdlp, add_video_handler=add_video
    )

    # 10. Application handlers — Download
    start_dl  = StartDownloadHandler(
        dl_queue, download_repo, ytdlp, event_bus,
        make_downloader=lambda cb: YtDlpAdapter(on_progress=cb),
        add_video_handler=add_video,
        gemini_extractor=_gemini_extractor,
    )
    cancel_dl = CancelDownloadHandler(dl_queue, event_bus)
    get_queue = GetDownloadQueueHandler(dl_queue)
    get_hist  = GetDownloadHistoryHandler(download_repo)

    # 11. Application handlers — Clip
    extract_clip = ExtractClipHandler(clip_repo, ffmpeg, event_bus)
    delete_clip  = DeleteClipHandler(clip_repo, event_bus)
    get_clips    = GetClipsHandler(clip_repo)

    # 12. Application handlers — Monitoring
    subscribe_ch   = SubscribeChannelHandler(channel_repo, event_bus, ytdlp)
    unsubscribe_ch = UnsubscribeChannelHandler(channel_repo, event_bus)
    set_rule       = SetMonitoringRuleHandler(channel_repo)
    get_subs       = GetSubscriptionsHandler(channel_repo)

    # 13. Application handlers — Playlist & YouTube API
    # YouTube 인증(keyring 접근)은 시작 시 미루고, 실제로 YouTube 기능을 쓰는
    # 시점(피드/채널 클릭, 재생목록 push 등)에만 수행한다(lazy binding, 200~300ms
    # 단축). 한 번 해석되면(성공/실패 모두) 세션 내에서 재사용한다 — 기존에도
    # 인증은 재시작 후에만 전 핸들러에 반영됐으므로(위 "번들 YouTube OAuth 로그인"
    # 항목) 이 캐싱은 기존 동작과 동일하다.
    _yt_api = None
    _yt_api_resolved = False

    def _get_youtube_api():
        """필요할 때만 YouTube 인증·API를 초기화한다(lazy binding)."""
        nonlocal _yt_api, _yt_api_resolved
        if not _yt_api_resolved:
            _creds = yt_oauth.get_credentials()
            if _creds is not None:
                _yt_api = YouTubeApiAdapter(_creds)
            _yt_api_resolved = True
        return _yt_api

    create_playlist_h  = CreatePlaylistHandler(playlist_repo)
    delete_playlist_h  = DeletePlaylistHandler(playlist_repo)
    add_to_playlist_h  = AddVideoToPlaylistHandler(
        playlist_repo, video_repo, yt_api_provider=_get_youtube_api
    )
    remove_from_pl_h   = RemoveVideoFromPlaylistHandler(
        playlist_repo, yt_api_provider=_get_youtube_api
    )
    reorder_pl_h       = ReorderPlaylistHandler(
        playlist_repo, video_repo, yt_api_provider=_get_youtube_api
    )
    import_yt_pl_h     = ImportYouTubePlaylistHandler(
        playlist_repo, video_repo, ytdlp,
        add_video_handler=add_video,
        yt_oauth=yt_oauth,
        yt_api_factory=lambda creds: YouTubeApiAdapter(creds),
    )
    get_playlists_h    = GetPlaylistsHandler(playlist_repo)
    get_pl_items_h     = GetPlaylistItemsHandler(playlist_repo, video_repo)
    get_feed_h         = GetSubscriptionFeedHandler(
        ytdlp, video_repo, channel_repo, yt_api_provider=_get_youtube_api
    )
    get_channel_vids_h = GetChannelVideosHandler(
        ytdlp, video_repo, yt_api_provider=_get_youtube_api
    )
    get_ch_infos_h     = GetSubscribedChannelInfosHandler(yt_api_provider=_get_youtube_api)
    get_recommend_h    = GetRecommendationsHandler(
        ytdlp, video_repo, yt_api_provider=_get_youtube_api
    )

    # 앨범 보기 — 외부 앨범 정보(iTunes, 무키)는 실패해도 라이브러리 곡으로 폴백한다.
    from application.song.album_queries import (  # noqa: PLC0415
        AddAlbumTracksHandler,
        FillAlbumTracksHandler,
        GetAlbumDetailHandler,
        GetAlbumsHandler,
        RemoveAlbumTrackLinkHandler,
        ResolveUnknownAlbumsHandler,
    )
    from infrastructure.song.album_providers import build_default_album_provider  # noqa: PLC0415

    _album_provider    = build_default_album_provider()
    get_albums_h       = GetAlbumsHandler(video_repo, song_repo, album_repo)
    get_album_detail_h = GetAlbumDetailHandler(video_repo, song_repo, album_repo, _album_provider)
    fill_album_h       = FillAlbumTracksHandler(get_album_detail_h, album_repo, ytdlp)
    resolve_albums_h   = ResolveUnknownAlbumsHandler(
        video_repo, song_repo, album_repo, _album_provider
    )
    # 앨범 수록곡을 현재 카테고리에 담기 — 등록(AddVideoHandler)에 노래 정보 기록을 얹는다.
    add_album_tracks_h = AddAlbumTracksHandler(add_video, song_repo)
    remove_album_link_h = RemoveAlbumTrackLinkHandler(album_repo)
    add_url_to_pl_h    = AddUrlToPlaylistHandler(add_video, playlist_repo)

    rename_playlist_h  = RenamePlaylistHandler(playlist_repo, yt_api_provider=_get_youtube_api)
    create_folder_h    = CreatePlaylistFolderHandler(folder_repo)
    rename_folder_h    = RenamePlaylistFolderHandler(folder_repo)
    delete_folder_h    = DeletePlaylistFolderHandler(folder_repo)
    move_to_folder_h   = MovePlaylistToFolderHandler(playlist_repo)
    copy_yt_to_local_h = CopyYouTubePlaylistToLocalHandler(playlist_repo, video_repo, ytdlp)
    get_folders_h      = GetPlaylistFoldersHandler(folder_repo)
    # 인증 여부와 무관하게 항상 생성한다 — 미인증이면 handle() 호출 시점에
    # RuntimeError로 알려주고(push_to_youtube() 워커가 error_occurred로 표출),
    # 시작 시점에 인증 유무를 미리 알 필요가 없다(lazy binding).
    push_to_yt_h       = PushPlaylistToYouTubeHandler(
        playlist_repo, video_repo, yt_api_provider=_get_youtube_api
    )
    move_video_pl_h    = MoveVideoToPlaylistHandler(
        playlist_repo, video_repo, yt_api_provider=_get_youtube_api
    )

    import_yt_subs_h   = ImportYouTubeSubscriptionsHandler(
        subscribe_ch, ytdlp, yt_api_provider=_get_youtube_api
    )

    # 14. Event bridge (translates domain events → application-level callbacks)
    dl_bridge = DownloadEventBridge(event_bus)

    # 15. ViewModels
    library_vm = LibraryViewModel(
        get_videos=get_videos,
        search_videos=search_videos,
        get_categories=get_cats,
        get_tags=get_tags,
        add_video=add_video,
        update_video=update_video,
        update_position=update_position,
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
        refresh_thumbnail=refresh_thumbnail_h,
        get_video_id_by_url=get_video_id_by_url,
        refresh_video_metadata=refresh_video_meta,
        find_song_videos=FindSongVideoIdsHandler(song_repo),
        enrich_video=enrich_video,
        get_downloaded_formats=get_dl_formats,
    )
    get_yt_playlists_h = GetYouTubePlaylistsHandler(ytdlp, yt_api_provider=_get_youtube_api)
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
    recommend_vm = RecommendViewModel(
        handler=get_recommend_h,
        auth_service=auth_service,
    )
    from gui.view_models.album_vm import AlbumViewModel  # noqa: PLC0415
    album_vm = AlbumViewModel(
        get_albums=get_albums_h,
        get_detail=get_album_detail_h,
        fill_tracks=fill_album_h,
        resolve_unknown=resolve_albums_h,
        add_tracks=add_album_tracks_h,
        remove_track_link=remove_album_link_h,
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
    # 노래 정보 뷰모델 (상세화면 '노래' 탭 + 가사 출처 관리)
    song_vm = SongViewModel(
        get_song_info=GetSongInfoHandler(song_repo),
        fetch_song=fetch_song,
        search_candidates=SearchLyricsCandidatesHandler(
            song_repo, video_repo, lyrics_providers=lyrics_providers
        ),
        apply_candidate=ApplyLyricsCandidateHandler(song_repo, event_bus, translator),
        set_flag=SetSongFlagHandler(song_repo, event_bus),
        update_field=UpdateSongFieldHandler(song_repo, event_bus),
        update_lyrics=UpdateSongLyricsHandler(song_repo, event_bus),
        translate_lyrics=TranslateSongLyricsHandler(song_repo, translator, event_bus),
        set_lyrics_offset=SetLyricsOffsetHandler(song_repo, event_bus),
        list_sources=ListLyricsSourcesHandler(song_repo),
        add_source=AddLyricsSourceHandler(song_repo),
        update_source=UpdateLyricsSourceHandler(song_repo),
        delete_source=DeleteLyricsSourceHandler(song_repo),
        reorder_sources=ReorderLyricsSourcesHandler(song_repo),
    )
    # 클라우드 동기화 뷰모델 (설정 패널 연결/해제·상태·지금 동기화)
    from gui.view_models.sync_vm import SyncViewModel  # noqa: PLC0415
    sync_vm = SyncViewModel(sync_service)

    # 라이브러리 가져오기/내보내기 뷰모델 (설정 패널)
    from application.transfer.commands import (  # noqa: PLC0415
        DetectImportConflictsHandler,
        ExportLibraryHandler,
        ImportLibraryHandler,
        PreviewImportHandler,
    )
    from infrastructure.transfer.portable_package import (  # noqa: PLC0415
        ZipLibraryPackageReader,
        ZipLibraryPackageWriter,
    )
    from gui.view_models.transfer_vm import LibraryTransferViewModel  # noqa: PLC0415
    _pkg_writer = ZipLibraryPackageWriter()
    _pkg_reader = ZipLibraryPackageReader()
    transfer_vm = LibraryTransferViewModel(
        export_handler=ExportLibraryHandler(video_repo, song_repo, _pkg_writer),
        preview_handler=PreviewImportHandler(_pkg_reader),
        conflicts_handler=DetectImportConflictsHandler(video_repo, song_repo, _pkg_reader),
        import_handler=ImportLibraryHandler(video_repo, song_repo, event_bus, _pkg_reader),
    )

    # 16. Launch GUI
    window = MainWindow(
        library_vm, download_vm, clip_vm, monitoring_vm,
        stats_handler,
        playlist_vm=playlist_vm,
        feed_vm=feed_vm,
        recommend_vm=recommend_vm,
        album_vm=album_vm,
        auth_service=auth_service,
        yt_oauth=yt_oauth,
        song_vm=song_vm,
        sync_vm=sync_vm,
        transfer_vm=transfer_vm,
        cleanup_fns=cleanup_fns,
    )

    # 자동 업데이트 — composition root에서 조립
    from gui.updater.update_controller import UpdateController  # noqa: PLC0415
    _update_checker  = GithubUpdateChecker(__version__)
    _check_update_h  = CheckForUpdateHandler(_update_checker)
    _dl_update_h     = DownloadUpdateHandler(_update_checker)
    _update_ctrl     = UpdateController(_check_update_h, _dl_update_h, window)
    window.set_update_controller(_update_ctrl)

    # 17. 스플래시 닫기 + 메인 창 표시
    _splash.finish(window)
    window.show()

    # 두 번째 인스턴스가 실행되면 이 창을 앞으로 불러온다(그쪽은 즉시 종료된다).
    def _activate_existing() -> None:
        window.showNormal()
        window.raise_()
        window.activateWindow()

    _guard.set_activate_callback(_activate_existing)
    # 연결돼 있으면 기동 후 1회 동기화 + 주기 자동 동기화 시작.
    sync_vm.start_auto_sync()
    exit_code = app.exec()
    _guard.release()

    # 앱 완전 종료 후 pending 업데이트 installer 실행 (파일 잠금 방지)
    # batch 파일로 지연 실행: 5초 대기 후 설치 → 설치 완료 후 앱 자동 재실행
    if sys.platform == "win32":
        _pending = Path(tempfile.gettempdir()) / "ovc_pending_update.txt"
        if _pending.exists():
            try:
                _lines = _pending.read_text(encoding="utf-8").splitlines()
                _inst = _lines[0].strip() if _lines else ""
                _exe = _lines[1].strip() if len(_lines) > 1 else ""
            except OSError:
                logger.exception("pending 업데이트 파일 읽기 실패")
                _inst = _exe = ""
            _pending.unlink(missing_ok=True)
            if _inst and Path(_inst).exists():
                try:
                    _bat = Path(tempfile.gettempdir()) / "ovc_update_launcher.bat"
                    _bat_content = (
                        "@echo off\r\n"
                        "timeout /t 5 /nobreak >nul\r\n"
                        f"\"{_inst}\" /VERYSILENT /NORESTART\r\n"
                    )
                    if _exe:
                        _bat_content += f"start \"\" \"{_exe}\"\r\n"
                    _bat_content += "del \"%~f0\"\r\n"
                    _bat.write_text(_bat_content, encoding="mbcs")
                    subprocess.Popen(
                        ["cmd", "/c", str(_bat)],
                        creationflags=subprocess.DETACHED_PROCESS
                        | subprocess.CREATE_NEW_PROCESS_GROUP,
                        close_fds=True,
                    )
                except (OSError, IOError):
                    logger.exception("업데이트 launcher 실행 실패")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
