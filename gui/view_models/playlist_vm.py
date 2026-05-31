from __future__ import annotations

from uuid import UUID

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from application.library.dtos import PlaylistDTO, PlaylistFolderDTO
from application.library.playlist_commands import (
    AddUrlToPlaylistCommand,
    AddUrlToPlaylistHandler,
    MoveVideoToPlaylistCommand,
    MoveVideoToPlaylistHandler,
    AddVideoToPlaylistCommand,
    AddVideoToPlaylistHandler,
    CopyYouTubePlaylistToLocalCommand,
    CopyYouTubePlaylistToLocalHandler,
    CreatePlaylistCommand,
    CreatePlaylistFolderCommand,
    CreatePlaylistFolderHandler,
    CreatePlaylistHandler,
    DeletePlaylistCommand,
    PushPlaylistToYouTubeCommand,
    PushPlaylistToYouTubeHandler,
    DeletePlaylistFolderCommand,
    DeletePlaylistFolderHandler,
    DeletePlaylistHandler,
    ImportYouTubePlaylistCommand,
    ImportYouTubePlaylistHandler,
    MovePlaylistToFolderCommand,
    MovePlaylistToFolderHandler,
    RemoveVideoFromPlaylistCommand,
    RemoveVideoFromPlaylistHandler,
    RenamePlaylistCommand,
    RenamePlaylistHandler,
    RenamePlaylistFolderCommand,
    RenamePlaylistFolderHandler,
    ReorderPlaylistCommand,
    ReorderPlaylistHandler,
)
from application.library.playlist_queries import (
    GetPlaylistFoldersHandler,
    GetPlaylistFoldersQuery,
    GetPlaylistsHandler,
    GetPlaylistsQuery,
    GetYouTubePlaylistsHandler,
    GetYouTubePlaylistsQuery,
)

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from infrastructure.auth.youtube_auth import YouTubeAuthService


class _AddUrlWorker(QThread):
    finished_ok = pyqtSignal()
    finished_err = pyqtSignal(str)

    def __init__(
        self,
        handler: AddUrlToPlaylistHandler,
        url: str,
        playlist_id: UUID,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._handler = handler
        self._url = url
        self._playlist_id = playlist_id

    def run(self) -> None:
        try:
            self._handler.handle(
                AddUrlToPlaylistCommand(url=self._url, playlist_id=self._playlist_id)
            )
            self.finished_ok.emit()
        except Exception as exc:
            self.finished_err.emit(str(exc))


class _FetchYTPlaylistsWorker(QThread):
    finished_ok  = pyqtSignal(list)   # list[dict]
    finished_err = pyqtSignal(str)

    def __init__(
        self,
        handler: GetYouTubePlaylistsHandler,
        cookie_opts: dict,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._handler = handler
        self._cookie_opts = cookie_opts

    def run(self) -> None:
        try:
            result = self._handler.handle(GetYouTubePlaylistsQuery(cookie_opts=self._cookie_opts))
            self.finished_ok.emit(result)
        except Exception as exc:
            self.finished_err.emit(str(exc))


class _ImportWorker(QThread):
    progress = pyqtSignal(int, int)
    finished_ok = pyqtSignal(object)   # PlaylistDTO
    finished_err = pyqtSignal(str)

    def __init__(
        self,
        handler: ImportYouTubePlaylistHandler,
        yt_playlist_id: str,
        cookie_opts: dict,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._handler = handler
        self._yt_playlist_id = yt_playlist_id
        self._cookie_opts = cookie_opts

    def run(self) -> None:
        try:
            dto = self._handler.handle(
                ImportYouTubePlaylistCommand(
                    yt_playlist_id=self._yt_playlist_id,
                    cookie_opts=self._cookie_opts,
                    on_progress=lambda cur, tot: self.progress.emit(cur, tot),
                )
            )
            self.finished_ok.emit(dto)
        except Exception as exc:
            self.finished_err.emit(str(exc))


class _PushToYTWorker(QThread):
    finished_ok  = pyqtSignal(object)   # PlaylistDTO
    finished_err = pyqtSignal(str)

    def __init__(
        self,
        handler: PushPlaylistToYouTubeHandler,
        playlist_id: "UUID",
        move: bool,
        privacy: str,
        parent: "QObject | None" = None,
    ) -> None:
        super().__init__(parent)
        self._handler = handler
        self._playlist_id = playlist_id
        self._move = move
        self._privacy = privacy

    def run(self) -> None:
        try:
            dto = self._handler.handle(
                PushPlaylistToYouTubeCommand(
                    playlist_id=self._playlist_id,
                    move=self._move,
                    privacy_status=self._privacy,
                )
            )
            self.finished_ok.emit(dto)
        except Exception as exc:
            self.finished_err.emit(str(exc))


class _CopyYTWorker(QThread):
    finished_ok  = pyqtSignal(object)   # PlaylistDTO
    finished_err = pyqtSignal(str)

    def __init__(
        self,
        handler: CopyYouTubePlaylistToLocalHandler,
        yt_playlist_id: str,
        folder_id: "UUID | None",
        cookie_opts: dict,
        parent: "QObject | None" = None,
    ) -> None:
        super().__init__(parent)
        self._handler = handler
        self._yt_playlist_id = yt_playlist_id
        self._folder_id = folder_id
        self._cookie_opts = cookie_opts

    def run(self) -> None:
        try:
            dto = self._handler.handle(
                CopyYouTubePlaylistToLocalCommand(
                    yt_playlist_id=self._yt_playlist_id,
                    folder_id=self._folder_id,
                    cookie_opts=self._cookie_opts,
                )
            )
            self.finished_ok.emit(dto)
        except Exception as exc:
            self.finished_err.emit(str(exc))


class PlaylistViewModel(QObject):
    playlists_changed = pyqtSignal()
    folders_changed   = pyqtSignal()
    error_occurred    = pyqtSignal(str)
    import_progress   = pyqtSignal(int, int)
    import_finished   = pyqtSignal()
    yt_playlists_ready = pyqtSignal(list)   # list[dict] — YouTube 계정 재생목록

    def __init__(
        self,
        get_playlists: GetPlaylistsHandler,
        create_playlist: CreatePlaylistHandler,
        delete_playlist: DeletePlaylistHandler,
        add_video: AddVideoToPlaylistHandler,
        remove_video: RemoveVideoFromPlaylistHandler,
        reorder: ReorderPlaylistHandler,
        import_yt: ImportYouTubePlaylistHandler,
        add_url_to_playlist: AddUrlToPlaylistHandler | None = None,
        get_yt_playlists: GetYouTubePlaylistsHandler | None = None,
        get_folders: GetPlaylistFoldersHandler | None = None,
        create_folder: CreatePlaylistFolderHandler | None = None,
        rename_playlist: RenamePlaylistHandler | None = None,
        rename_folder: RenamePlaylistFolderHandler | None = None,
        delete_folder: DeletePlaylistFolderHandler | None = None,
        move_to_folder: MovePlaylistToFolderHandler | None = None,
        copy_yt_to_local: CopyYouTubePlaylistToLocalHandler | None = None,
        push_to_yt: PushPlaylistToYouTubeHandler | None = None,
        move_video: MoveVideoToPlaylistHandler | None = None,
        auth_service: "YouTubeAuthService | None" = None,
        parent: "QObject | None" = None,
    ) -> None:
        super().__init__(parent)
        self._get_playlists    = get_playlists
        self._create_playlist  = create_playlist
        self._delete_playlist  = delete_playlist
        self._add_video        = add_video
        self._remove_video     = remove_video
        self._reorder          = reorder
        self._import_yt        = import_yt
        self._add_url_handler  = add_url_to_playlist
        self._get_yt_playlists = get_yt_playlists
        self._get_folders       = get_folders
        self._rename_playlist_h = rename_playlist
        self._create_folder_h  = create_folder
        self._rename_folder_h  = rename_folder
        self._delete_folder_h  = delete_folder
        self._move_to_folder_h = move_to_folder
        self._copy_yt_h        = copy_yt_to_local
        self._push_yt_h        = push_to_yt
        self._move_video_h     = move_video
        self._auth             = auth_service
        self._playlists:  list[PlaylistDTO]       = []
        self._folders:    list[PlaylistFolderDTO] = []
        self._import_workers:    list[_ImportWorker]          = []
        self._add_url_workers:   list[_AddUrlWorker]          = []
        self._fetch_yt_workers:  list[_FetchYTPlaylistsWorker] = []
        self._copy_yt_workers:   list[_CopyYTWorker]          = []
        self._push_yt_workers:   list[_PushToYTWorker]        = []

    @property
    def playlists(self) -> list[PlaylistDTO]:
        return self._playlists

    @property
    def folders(self) -> list[PlaylistFolderDTO]:
        return self._folders

    def load(self) -> None:
        self._refresh_playlists()
        self._refresh_folders()

    def create_playlist(self, title: str, folder_id: "UUID | None" = None) -> None:
        try:
            self._create_playlist.handle(CreatePlaylistCommand(title=title, folder_id=folder_id))
            self._refresh_playlists()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def delete_playlist(self, playlist_id: UUID) -> None:
        try:
            self._delete_playlist.handle(DeletePlaylistCommand(playlist_id=playlist_id))
            self._refresh_playlists()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def add_video_to_playlist(
        self, playlist_id: UUID, video_id: UUID, position: int | None = None
    ) -> None:
        try:
            self._add_video.handle(
                AddVideoToPlaylistCommand(
                    playlist_id=playlist_id,
                    video_id=video_id,
                    position=position,
                )
            )
            self._refresh_playlists()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def remove_video_from_playlist(self, playlist_id: UUID, video_id: UUID) -> None:
        try:
            self._remove_video.handle(
                RemoveVideoFromPlaylistCommand(
                    playlist_id=playlist_id, video_id=video_id
                )
            )
            self._refresh_playlists()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def reorder_playlist(self, playlist_id: UUID, ordered_video_ids: list[UUID]) -> None:
        try:
            self._reorder.handle(
                ReorderPlaylistCommand(
                    playlist_id=playlist_id,
                    ordered_video_ids=ordered_video_ids,
                )
            )
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def import_youtube_playlist(self, yt_playlist_id: str) -> None:
        cookie_opts = self._auth.get_ytdlp_opts() if self._auth else {}
        worker = _ImportWorker(self._import_yt, yt_playlist_id, cookie_opts, self)
        worker.progress.connect(self.import_progress)
        worker.finished_ok.connect(self._on_import_ok)
        worker.finished_err.connect(lambda err: self.error_occurred.emit(err))
        worker.finished.connect(lambda: self._import_workers.remove(worker))
        self._import_workers.append(worker)
        worker.start()

    def add_url_to_playlist(self, url: str, playlist_id: UUID) -> None:
        """피드에서 URL + 재생목록 ID로 영상을 추가 (라이브러리 upsert 후 연결)."""
        if self._add_url_handler is None:
            self.error_occurred.emit("AddUrlToPlaylistHandler가 주입되지 않았습니다.")
            return
        worker = _AddUrlWorker(self._add_url_handler, url, playlist_id, self)
        worker.finished_ok.connect(self._refresh_playlists)
        worker.finished_err.connect(self.error_occurred)
        worker.finished.connect(lambda: self._add_url_workers.remove(worker))
        self._add_url_workers.append(worker)
        worker.start()

    def get_ytdlp_cookie_opts(self) -> dict:
        """저장된 yt-dlp 쿠키 옵션 반환 (인증 미설정 시 빈 dict)."""
        return self._auth.get_ytdlp_opts() if self._auth else {}

    def fetch_youtube_playlists(self) -> None:
        """YouTube 계정 재생목록 목록을 비동기로 가져온다."""
        if self._get_yt_playlists is None:
            self.error_occurred.emit("YouTube 재생목록 핸들러가 초기화되지 않았습니다.")
            return
        cookie_opts = self._auth.get_ytdlp_opts() if self._auth else {}
        worker = _FetchYTPlaylistsWorker(self._get_yt_playlists, cookie_opts, self)
        worker.finished_ok.connect(self.yt_playlists_ready)
        worker.finished_ok.connect(lambda _: self._fetch_yt_workers.remove(worker))
        worker.finished_err.connect(self.error_occurred)
        worker.finished_err.connect(lambda _: self._fetch_yt_workers.remove(worker))
        self._fetch_yt_workers.append(worker)
        worker.start()

    # ── 폴더 관리 ──────────────────────────────────────────────────────────────

    def create_folder(self, name: str, source: str = "local") -> None:
        if self._create_folder_h is None:
            return
        try:
            self._create_folder_h.handle(CreatePlaylistFolderCommand(name=name, source=source))
            self._refresh_folders()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def rename_playlist(self, playlist_id: UUID, new_title: str) -> None:
        if self._rename_playlist_h is None:
            return
        try:
            self._rename_playlist_h.handle(RenamePlaylistCommand(playlist_id=playlist_id, new_title=new_title))
            self._refresh_playlists()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def rename_folder(self, folder_id: UUID, new_name: str) -> None:
        if self._rename_folder_h is None:
            return
        try:
            self._rename_folder_h.handle(RenamePlaylistFolderCommand(folder_id=folder_id, new_name=new_name))
            self._refresh_folders()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def delete_folder(self, folder_id: UUID) -> None:
        if self._delete_folder_h is None:
            return
        try:
            self._delete_folder_h.handle(DeletePlaylistFolderCommand(folder_id=folder_id))
            self._refresh_folders()
            self._refresh_playlists()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def move_playlist_to_folder(self, playlist_id: UUID, folder_id: UUID | None) -> None:
        if self._move_to_folder_h is None:
            return
        try:
            self._move_to_folder_h.handle(MovePlaylistToFolderCommand(
                playlist_id=playlist_id, folder_id=folder_id
            ))
            self._refresh_playlists()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def push_to_youtube(
        self,
        playlist_id: UUID,
        move: bool = False,
        privacy: str = "private",
    ) -> None:
        """로컬 재생목록을 YouTube에 생성한다. YouTube API 인증 필요."""
        if self._push_yt_h is None:
            self.error_occurred.emit("YouTube API가 연결되지 않았습니다.\n설정 > YouTube API 연동에서 인증하세요.")
            return
        worker = _PushToYTWorker(self._push_yt_h, playlist_id, move, privacy, self)
        worker.finished_ok.connect(lambda _: self._refresh_playlists())
        worker.finished_err.connect(self.error_occurred)
        worker.finished.connect(lambda: self._push_yt_workers.remove(worker))
        self._push_yt_workers.append(worker)
        worker.start()

    def move_video_to_playlist(
        self,
        video_id: UUID,
        source_playlist_id: UUID | None,
        target_playlist_id: UUID,
    ) -> None:
        """영상을 소스 재생목록에서 대상 재생목록으로 이전한다."""
        if self._move_video_h is None:
            self.error_occurred.emit("MoveVideoToPlaylistHandler가 초기화되지 않았습니다.")
            return
        try:
            self._move_video_h.handle(
                MoveVideoToPlaylistCommand(
                    video_id=video_id,
                    source_playlist_id=source_playlist_id,
                    target_playlist_id=target_playlist_id,
                )
            )
            self._refresh_playlists()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def copy_youtube_to_local(
        self,
        yt_playlist_id: str,
        folder_id: UUID | None = None,
    ) -> None:
        if self._copy_yt_h is None:
            self.error_occurred.emit("CopyYouTubePlaylistToLocalHandler가 초기화되지 않았습니다.")
            return
        cookie_opts = self._auth.get_ytdlp_opts() if self._auth else {}
        worker = _CopyYTWorker(self._copy_yt_h, yt_playlist_id, folder_id, cookie_opts, self)
        worker.finished_ok.connect(lambda _: self._refresh_playlists())
        worker.finished_err.connect(self.error_occurred)
        worker.finished.connect(lambda: self._copy_yt_workers.remove(worker))
        self._copy_yt_workers.append(worker)
        worker.start()

    # ── 내부 갱신 ──────────────────────────────────────────────────────────────

    def _on_import_ok(self, _dto: PlaylistDTO) -> None:
        self._refresh_playlists()
        self.import_finished.emit()

    def _refresh_playlists(self) -> None:
        try:
            self._playlists = self._get_playlists.handle(GetPlaylistsQuery())
            self.playlists_changed.emit()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def _refresh_folders(self) -> None:
        if self._get_folders is None:
            return
        try:
            self._folders = self._get_folders.handle(GetPlaylistFoldersQuery())
            self.folders_changed.emit()
        except Exception as exc:
            self.error_occurred.emit(str(exc))
