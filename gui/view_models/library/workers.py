"""LibraryViewModel이 띄우는 QThread 워커 7종.

전부 **부모 없이** 만든다 — 붙드는 일은 `WorkerOwnerMixin._start_worker`(→
`gui/workers.py:track_thread`)가 한다. 결과·오류는 신호로만 알리고 뷰모델 상태를
직접 건드리지 않는다(워커 스레드에서 실행되므로).
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QThread, pyqtSignal

from gui.text.messages import describe_error, render

from application.library.commands import (
    AddVideoCommand,
    AddVideoHandler,
    ImportYouTubePlaylistToCategoryCommand,
    ImportYouTubePlaylistToCategoryHandler,
    RefreshCategoryMetadataCommand,
    RefreshCategoryMetadataHandler,
    RefreshVideoMetadataCommand,
    RefreshVideoMetadataHandler,
    RefreshVideoThumbnailCommand,
    RefreshVideoThumbnailHandler,
)

logger = logging.getLogger(__name__)


class _AddVideoWorker(QThread):
    finished_ok = pyqtSignal(object)   # video_id: UUID — 등록 후 보강에 사용
    finished_err = pyqtSignal(str)

    def __init__(
        self,
        handler: AddVideoHandler,
        cmd: AddVideoCommand,
    ) -> None:
        # 부모를 주지 않는다 — 붙드는 일은 track_thread가 한다(gui/workers.py).
        super().__init__(None)
        self._handler = handler
        self._cmd = cmd

    def run(self) -> None:
        try:
            agg = self._handler.handle(self._cmd)
            self.finished_ok.emit(agg.id)
        except Exception as exc:
            self.finished_err.emit(describe_error(exc))


class _EnrichWorker(QThread):
    """등록 직후 요약/가사 자동 보강을 백그라운드에서 실행한다.

    Gemini 요약 추출은 Playwright 브라우저를 띄워 수십 초가 걸리므로
    ViewModel이 동시 1건으로 직렬화한다.
    """
    finished_result = pyqtSignal(str, str, bool, str)   # url, kind, ok, detail

    def __init__(self, handler, cmd, url: str) -> None:
        # 부모를 주지 않는다 — 붙드는 일은 track_thread가 한다(gui/workers.py).
        super().__init__(None)
        self._handler = handler
        self._cmd = cmd
        self._url = url

    def run(self) -> None:
        try:
            result = self._handler.handle(self._cmd)
            # 사유는 `Message`로 온다 — 신호는 문자열이라 여기서 문장으로 만든다.
            self.finished_result.emit(self._url, result.kind, result.ok, render(result.detail))
        except Exception as exc:
            logger.exception("영상 보강 워커 실패: %s", self._url)
            self.finished_result.emit(self._url, "skipped", False, describe_error(exc))


class _ImportYTToCatWorker(QThread):
    progress    = pyqtSignal(int, int)  # current, total
    finished_ok = pyqtSignal(int)       # 처리된 영상 수
    finished_err = pyqtSignal(str)

    def __init__(
        self,
        handler: ImportYouTubePlaylistToCategoryHandler,
        cmd: ImportYouTubePlaylistToCategoryCommand,
    ) -> None:
        # 부모를 주지 않는다 — 붙드는 일은 track_thread가 한다(gui/workers.py).
        super().__init__(None)
        self._handler = handler
        self._cmd = cmd

    def run(self) -> None:
        try:
            self._cmd.on_progress = lambda cur, tot: self.progress.emit(cur, tot)
            count = self._handler.handle(self._cmd)
            self.finished_ok.emit(count)
        except Exception as exc:
            self.finished_err.emit(describe_error(exc))


class _ListVideosWorker(QThread):
    """_refresh_videos()를 백그라운드 스레드에서 실행한다."""
    finished_ok  = pyqtSignal(list, bool)   # (videos, append)
    finished_err = pyqtSignal(str)

    def __init__(self, fetch_fn, append: bool) -> None:
        # 부모를 주지 않는다 — 붙드는 일은 track_thread가 한다(gui/workers.py).
        super().__init__(None)
        self._fetch = fetch_fn
        self._append = append

    def run(self) -> None:
        try:
            results = self._fetch()
            self.finished_ok.emit(results, self._append)
        except Exception as exc:
            self.finished_err.emit(describe_error(exc))


class _RefreshThumbnailWorker(QThread):
    """단일 영상의 썸네일을 백그라운드에서 갱신한다."""
    finished_ok  = pyqtSignal(object, str)   # (video_id: UUID, new_path: str)
    finished_err = pyqtSignal(str)

    def __init__(
        self,
        handler: RefreshVideoThumbnailHandler,
        cmd: RefreshVideoThumbnailCommand,
    ) -> None:
        # 부모를 주지 않는다 — 붙드는 일은 track_thread가 한다(gui/workers.py).
        super().__init__(None)
        self._handler = handler
        self._cmd = cmd

    def run(self) -> None:
        try:
            new_path = self._handler.handle(self._cmd)
            if new_path:
                self.finished_ok.emit(self._cmd.video_id, new_path)
        except Exception as exc:
            self.finished_err.emit(describe_error(exc))


class _RefreshMetadataWorker(QThread):
    progress = pyqtSignal(int, int)   # current, total
    finished_ok = pyqtSignal(int)     # count of refreshed videos
    finished_err = pyqtSignal(str)

    def __init__(
        self,
        handler: RefreshCategoryMetadataHandler,
        cmd: RefreshCategoryMetadataCommand,
    ) -> None:
        # 부모를 주지 않는다 — 붙드는 일은 track_thread가 한다(gui/workers.py).
        super().__init__(None)
        self._handler = handler
        self._cmd = cmd

    def run(self) -> None:
        try:
            count = self._handler.handle(
                self._cmd,
                on_progress=lambda cur, total: self.progress.emit(cur, total),
            )
            self.finished_ok.emit(count)
        except Exception as exc:
            self.finished_err.emit(describe_error(exc))


class _RefreshVideoMetaWorker(QThread):
    """단일 영상 메타데이터를 YouTube(yt-dlp)에서 재수집한다(상세화면 ⟳)."""
    finished_ok  = pyqtSignal(object, bool)   # (video_id: UUID, updated: bool)
    finished_err = pyqtSignal(object, str)    # (video_id: UUID, error)

    def __init__(
        self,
        handler: RefreshVideoMetadataHandler,
        cmd: RefreshVideoMetadataCommand,
    ) -> None:
        # 부모를 주지 않는다 — 붙드는 일은 track_thread가 한다(gui/workers.py).
        super().__init__(None)
        self._handler = handler
        self._cmd = cmd

    def run(self) -> None:
        try:
            updated = self._handler.handle(self._cmd)
            self.finished_ok.emit(self._cmd.video_id, bool(updated))
        except Exception as exc:
            logger.exception("영상 메타데이터 갱신 실패: %s", self._cmd.video_id)
            self.finished_err.emit(self._cmd.video_id, describe_error(exc))
