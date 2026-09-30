"""네트워크를 타는 갱신 — 카테고리 메타데이터·YouTube 재생목록 가져오기·썸네일·단일 영상 메타.

전부 워커 스레드에서 돌리고, 끝나면 목록 캐시를 비워 다시 읽는다.
"""
from __future__ import annotations

import logging
from uuid import UUID

from application.library.commands import (
    ImportYouTubePlaylistToCategoryCommand,
    RefreshCategoryMetadataCommand,
    RefreshVideoMetadataCommand,
    RefreshVideoThumbnailCommand,
)
from gui.text import tr
from gui.view_models.library.workers import (
    _ImportYTToCatWorker,
    _RefreshMetadataWorker,
    _RefreshThumbnailWorker,
    _RefreshVideoMetaWorker,
)

logger = logging.getLogger(__name__)


class RefreshMixin:
    """메타데이터·썸네일·재생목록을 원격에서 다시 받아 DB를 갱신한다."""

    def refresh_category_metadata(self, category_id: UUID | None) -> None:
        if self._refresh_metadata_workers:  # already running
            return
        category_ids = (
            self._resolve_category_ids(category_id)
            if category_id is not None
            else []
        )
        cmd = RefreshCategoryMetadataCommand(category_ids=category_ids)
        worker = _RefreshMetadataWorker(self._refresh_metadata, cmd)
        worker.progress.connect(self.metadata_refresh_progress)
        worker.finished_ok.connect(self._on_refresh_metadata_ok)
        worker.finished_err.connect(self._on_refresh_metadata_err)
        worker.finished.connect(lambda: self._refresh_metadata_workers.remove(worker))
        self._refresh_metadata_workers.append(worker)
        self._start_worker(worker)

    def _on_refresh_metadata_ok(self, count: int) -> None:
        self._refresh_videos(bust_cache=True)
        self._refresh_tags()
        self.metadata_refresh_finished.emit(count)

    def _on_refresh_metadata_err(self, err: str) -> None:
        self.error_occurred.emit(err)
        self.metadata_refresh_finished.emit(0)

    def import_youtube_to_category(
        self,
        yt_playlist_id: str,
        category_id: UUID | None,
        cookie_opts: dict,
    ) -> None:
        """YouTube 재생목록의 영상들을 지정 카테고리로 가져온다 (비동기)."""
        if self._import_yt_to_category is None:
            self.error_occurred.emit(
                tr("ImportYouTubePlaylistToCategoryHandler가 초기화되지 않았습니다.")
            )
            return
        cmd = ImportYouTubePlaylistToCategoryCommand(
            yt_playlist_id=yt_playlist_id,
            category_id=category_id,
            cookie_opts=cookie_opts,
        )
        worker = _ImportYTToCatWorker(self._import_yt_to_category, cmd)
        worker.progress.connect(self.yt_import_progress)
        worker.finished_ok.connect(self._on_yt_import_ok)
        worker.finished_err.connect(self._on_yt_import_err)
        worker.finished.connect(lambda: self._yt_import_workers.remove(worker))
        self._yt_import_workers.append(worker)
        self._start_worker(worker)

    def _on_yt_import_ok(self, count: int) -> None:
        self._refresh_videos(bust_cache=True)
        self._refresh_categories()  # _refresh_categories()가 캐시 무효화 포함
        self._refresh_tags()
        self.yt_import_finished.emit(count)

    def _on_yt_import_err(self, err: str) -> None:
        self.error_occurred.emit(err)
        self.yt_import_finished.emit(0)

    def request_thumbnail_refresh(self, video_id: UUID, video_url: str) -> None:
        """상세화면 진입 시 1주일 경과 썸네일을 백그라운드에서 갱신한다.

        YouTube 영상이 아니거나 handler가 미설정이면 무시한다.
        """
        if self._refresh_thumbnail_handler is None:
            return
        cmd = RefreshVideoThumbnailCommand(video_id=video_id, video_url=video_url)
        worker = _RefreshThumbnailWorker(self._refresh_thumbnail_handler, cmd)

        def _on_ok(vid_id: object, new_path: str) -> None:
            self.thumbnail_refreshed.emit(vid_id, new_path)
            self._refresh_videos(bust_cache=True)  # 그리드 썸네일 갱신

        worker.finished_ok.connect(_on_ok)
        worker.finished_err.connect(lambda err: logger.debug("썸네일 갱신 실패(무시): %s", err))
        worker.finished.connect(lambda: self._thumb_workers.remove(worker) if worker in self._thumb_workers else None)
        self._thumb_workers.append(worker)
        self._start_worker(worker)

    def refresh_video_metadata(self, video_id: UUID) -> None:
        """상세화면 ⟳ — 단일 영상 메타데이터를 YouTube에서 재수집해 DB를 갱신한다.

        네트워크 I/O이므로 백그라운드 워커에서 실행하고, 완료 시
        `video_metadata_refreshed(video_id, ok)`를 방출한다(ok=True면 갱신됨).
        handler 미설정이면 무시한다.
        """
        if self._refresh_video_meta is None:
            self.video_metadata_refreshed.emit(video_id, False)
            return
        cmd = RefreshVideoMetadataCommand(video_id=video_id)
        worker = _RefreshVideoMetaWorker(self._refresh_video_meta, cmd)

        def _on_ok(vid_id: object, updated: bool) -> None:
            if updated:
                self._refresh_videos(bust_cache=True)  # 그리드/목록도 갱신
            self.video_metadata_refreshed.emit(vid_id, updated)

        def _on_err(vid_id: object, err: str) -> None:
            self.error_occurred.emit(err)
            self.video_metadata_refreshed.emit(vid_id, False)

        worker.finished_ok.connect(_on_ok)
        worker.finished_err.connect(_on_err)
        worker.finished.connect(
            lambda: self._video_meta_workers.remove(worker)
            if worker in self._video_meta_workers else None
        )
        self._video_meta_workers.append(worker)
        self._start_worker(worker)
