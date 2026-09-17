from __future__ import annotations

from uuid import UUID

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from application.clip.commands import (
    DeleteClipCommand,
    DeleteClipHandler,
    ExtractClipCommand,
    ExtractClipHandler,
    ExtractClipsCommand,
    ExtractClipsHandler,
)
from application.clip.dtos import ChapterDTO, ClipDTO
from application.clip.queries import (
    GetChaptersHandler,
    GetChaptersQuery,
    GetClipsHandler,
    GetClipsQuery,
)
from gui.view_models.base import WorkerOwnerMixin


def _clip_to_dto(agg) -> ClipDTO:
    c = agg.clip
    return ClipDTO(
        id=agg.id,
        source_video_id=c.source_video_id,
        title=c.title,
        file_path=c.file_path,
        thumbnail_path=c.thumbnail_path,
        start_sec=c.time_range.start_sec,
        end_sec=c.time_range.end_sec,
    )


class _ExtractWorker(QThread):
    """Runs ffmpeg clip extraction on a background thread."""

    finished_ok = pyqtSignal(object)   # ClipDTO
    finished_err = pyqtSignal(str)

    def __init__(
        self,
        handler: ExtractClipHandler,
        cmd: ExtractClipCommand,
    ) -> None:
        # 부모를 주지 않는다 — 소유 뷰모델이 사라질 때 실행 중 스레드가 파괴되면
        # Qt가 프로세스를 죽인다(gui/workers.py). 붙드는 일은 track_thread가 한다.
        super().__init__(None)
        self._handler = handler
        self._cmd = cmd

    def run(self) -> None:
        try:
            self.finished_ok.emit(_clip_to_dto(self._handler.handle(self._cmd)))
        except Exception as exc:
            self.finished_err.emit(str(exc))


class _ChapterExtractWorker(QThread):
    """챕터 여러 개를 순차 추출한다 (ffmpeg는 한 번에 하나)."""

    progress = pyqtSignal(int, int, str)     # 현재, 전체, 제목
    finished_all = pyqtSignal(object, object)  # list[ClipDTO], list[(제목, 오류)]

    def __init__(self, handler: ExtractClipsHandler, cmd: ExtractClipsCommand) -> None:
        # 부모를 주지 않는다 — `_ExtractWorker`와 같은 이유(gui/workers.py).
        super().__init__(None)
        self._handler = handler
        self._cmd = cmd

    def run(self) -> None:
        try:
            done, failed = self._handler.handle(self._cmd, on_progress=self._emit_progress)
            self.finished_all.emit([_clip_to_dto(agg) for agg in done], failed)
        except Exception as exc:
            self.finished_all.emit([], [("", str(exc))])

    def _emit_progress(self, current: int, total: int, title: str) -> None:
        self.progress.emit(current, total, title)


class ClipViewModel(WorkerOwnerMixin, QObject):
    clips_changed = pyqtSignal()
    error_occurred = pyqtSignal(str)
    chapters_loaded = pyqtSignal(object)        # list[ChapterDTO]
    chapter_progress = pyqtSignal(int, int, str)
    chapter_finished = pyqtSignal(int, int)     # 성공 수, 실패 수

    def __init__(
        self,
        extract_handler: ExtractClipHandler,
        delete_handler: DeleteClipHandler,
        get_clips_handler: GetClipsHandler,
        get_chapters_handler: GetChaptersHandler | None = None,
        extract_many_handler: ExtractClipsHandler | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._extract = extract_handler
        self._delete = delete_handler
        self._get_clips = get_clips_handler
        self._get_chapters = get_chapters_handler
        self._extract_many = extract_many_handler
        self._clips: list[ClipDTO] = []
        self._chapters: list[ChapterDTO] = []
        self._worker: _ExtractWorker | None = None

    @property
    def clips(self) -> list[ClipDTO]:
        return self._clips

    @property
    def chapters(self) -> list[ChapterDTO]:
        return self._chapters

    # ── 챕터 ──────────────────────────────────────────────────────

    def load_chapters(self, video_id: UUID) -> None:
        """설명에서 챕터를 뽑는다. DB 읽기 + 정규식이라 동기로 충분하다."""
        self._chapters = []
        if self._get_chapters is not None:
            try:
                self._chapters = self._get_chapters.handle(GetChaptersQuery(video_id=video_id))
            except Exception as exc:
                self.error_occurred.emit(str(exc))
        self.chapters_loaded.emit(self._chapters)

    def extract_chapters(
        self,
        source_video_id: UUID,
        source_file_path: str,
        chapters: list[ChapterDTO],
    ) -> None:
        if self._extract_many is None or not chapters:
            return
        cmd = ExtractClipsCommand(
            source_video_id=source_video_id,
            source_file_path=source_file_path,
            ranges=[(c.title, c.start_sec, c.end_sec) for c in chapters],
        )
        worker = _ChapterExtractWorker(self._extract_many, cmd)
        worker.progress.connect(self._on_chapter_progress)
        worker.finished_all.connect(self._on_chapters_done)
        self._start_worker(worker)

    def _on_chapter_progress(self, current: int, total: int, title: str) -> None:
        self.chapter_progress.emit(current, total, title)

    def _on_chapters_done(self, clips: object, failed: object) -> None:
        self._clips.extend(clips or [])
        self.clips_changed.emit()
        self.chapter_finished.emit(len(clips or []), len(failed or []))
        for title, error in (failed or []):
            self.error_occurred.emit(f"'{title}' 추출 실패: {error}")

    def load_clips(self, video_id: UUID) -> None:
        try:
            self._clips = self._get_clips.handle(GetClipsQuery(source_video_id=video_id))
            self.clips_changed.emit()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def extract_clip(
        self,
        source_video_id: UUID,
        source_file_path: str,
        title: str,
        start_sec: float,
        end_sec: float,
    ) -> None:
        cmd = ExtractClipCommand(
            source_video_id=source_video_id,
            source_file_path=source_file_path,
            title=title,
            start_sec=start_sec,
            end_sec=end_sec,
        )
        worker = _ExtractWorker(self._extract, cmd)
        worker.finished_ok.connect(self._on_extract_ok)
        worker.finished_err.connect(self._on_extract_err)
        self._worker = worker
        self._adopt_worker(worker)
        worker.start()

    def delete_clip(self, clip_id: UUID, delete_file: bool = False) -> None:
        try:
            self._delete.handle(DeleteClipCommand(clip_id=clip_id, delete_file=delete_file))
            self._clips = [c for c in self._clips if c.id != clip_id]
            self.clips_changed.emit()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    def _on_extract_ok(self, dto: ClipDTO) -> None:
        self._clips.append(dto)
        self.clips_changed.emit()

    def _on_extract_err(self, error: str) -> None:
        self.error_occurred.emit(f"Clip extraction failed: {error}")
