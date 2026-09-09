"""뷰모델 조립 — 유스케이스를 UI 상태 계층에 배선한다."""

from __future__ import annotations

from gui.view_models.album_vm import AlbumViewModel
from gui.view_models.clip_vm import ClipViewModel
from gui.view_models.download_vm import DownloadViewModel
from gui.view_models.feed_vm import FeedViewModel
from gui.view_models.library_vm import LibraryViewModel
from gui.view_models.monitoring_vm import MonitoringViewModel
from gui.view_models.playlist_vm import PlaylistViewModel
from gui.view_models.recommend_vm import RecommendViewModel
from gui.view_models.song_vm import SongViewModel
from gui.view_models.sync_vm import SyncViewModel
from gui.view_models.transfer_vm import LibraryTransferViewModel

from bootstrap.context import Handlers, Services, ViewModels


def build_view_models(handlers: Handlers, services: Services) -> ViewModels:
    lib, pl, song = handlers.library, handlers.playlist, handlers.song
    auth = services.auth_service

    return ViewModels(
        library=LibraryViewModel(
            get_videos=lib.get_videos,
            search_videos=lib.search_videos,
            get_categories=lib.get_categories,
            get_tags=lib.get_tags,
            add_video=lib.add_video,
            update_video=lib.update_video,
            update_position=lib.update_position,
            delete_video=lib.delete_video,
            mark_watched=lib.mark_watched,
            create_category=lib.create_category,
            rename_category=lib.rename_category,
            delete_category=lib.delete_category,
            move_category=lib.move_category,
            delete_tag=lib.delete_tag,
            assign_category=lib.assign_category,
            get_video_detail=lib.get_video_detail,
            refresh_metadata=lib.refresh_category_metadata,
            get_playlist_items=pl.get_items,
            get_category_order=lib.get_category_order,
            set_category_order=lib.set_category_order,
            import_yt_to_category=lib.import_youtube_playlist_to_category,
            refresh_thumbnail=lib.refresh_thumbnail,
            get_video_id_by_url=lib.get_video_id_by_url,
            refresh_video_metadata=lib.refresh_video_metadata,
            find_song_videos=song.find_video_ids,
            enrich_video=lib.enrich_video,
            get_downloaded_formats=lib.get_downloaded_formats,
        ),
        playlist=PlaylistViewModel(
            get_playlists=pl.get_playlists,
            create_playlist=pl.create,
            delete_playlist=pl.delete,
            add_video=pl.add_video,
            remove_video=pl.remove_video,
            reorder=pl.reorder,
            import_yt=pl.import_youtube,
            add_url_to_playlist=pl.add_url,
            get_yt_playlists=pl.get_youtube_playlists,
            get_folders=pl.get_folders,
            rename_playlist=pl.rename,
            create_folder=pl.create_folder,
            rename_folder=pl.rename_folder,
            delete_folder=pl.delete_folder,
            move_to_folder=pl.move_to_folder,
            copy_yt_to_local=pl.copy_youtube_to_local,
            push_to_yt=pl.push_to_youtube,
            move_video=pl.move_video,
            auth_service=auth,
        ),
        feed=FeedViewModel(
            handler=pl.get_feed,
            channel_handler=pl.get_channel_videos,
            channel_infos_handler=pl.get_channel_infos,
            auth_service=auth,
        ),
        recommend=RecommendViewModel(
            handler=pl.get_recommendations,
            auth_service=auth,
        ),
        album=AlbumViewModel(
            get_albums=handlers.album.get_albums,
            get_detail=handlers.album.get_detail,
            fill_tracks=handlers.album.fill_tracks,
            resolve_unknown=handlers.album.resolve_unknown,
            add_tracks=handlers.album.add_tracks,
            remove_track_link=handlers.album.remove_track_link,
        ),
        download=DownloadViewModel(
            start_handler=handlers.download.start,
            cancel_handler=handlers.download.cancel,
            queue_handler=handlers.download.get_queue,
            history_handler=handlers.download.get_history,
            event_bridge=handlers.download.event_bridge,
        ),
        clip=ClipViewModel(
            extract_handler=handlers.clip.extract,
            delete_handler=handlers.clip.delete,
            get_clips_handler=handlers.clip.get_clips,
        ),
        monitoring=MonitoringViewModel(
            subscribe_handler=handlers.monitoring.subscribe,
            unsubscribe_handler=handlers.monitoring.unsubscribe,
            set_rule_handler=handlers.monitoring.set_rule,
            get_subs_handler=handlers.monitoring.get_subscriptions,
            import_yt_handler=handlers.monitoring.import_youtube_subscriptions,
            auth_service=auth,
        ),
        song=SongViewModel(
            get_song_info=song.get_info,
            fetch_song=song.fetch,
            search_candidates=song.search_candidates,
            apply_candidate=song.apply_candidate,
            set_flag=song.set_flag,
            update_field=song.update_field,
            update_lyrics=song.update_lyrics,
            translate_lyrics=song.translate_lyrics,
            set_lyrics_offset=song.set_lyrics_offset,
            list_sources=song.list_sources,
            add_source=song.add_source,
            update_source=song.update_source,
            delete_source=song.delete_source,
            reorder_sources=song.reorder_sources,
        ),
        sync=SyncViewModel(services.sync_service),
        transfer=LibraryTransferViewModel(
            export_handler=handlers.transfer.export,
            preview_handler=handlers.transfer.preview,
            conflicts_handler=handlers.transfer.detect_conflicts,
            import_handler=handlers.transfer.do_import,
        ),
    )
