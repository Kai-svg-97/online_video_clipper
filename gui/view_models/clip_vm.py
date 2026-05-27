from __future__ import annotations

from uuid import UUID

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from application.clip.commands import DeleteClipCommand, DeleteClipHandler, ExtractClipCommand, ExtractClipHandler
from application.clip.dtos import ClipDTO
from application.clip.queries import GetClipsHandler, GetClipsQuery


class _ExtractWorker(QThread):
    """Runs ffmpeg clip extraction on a background thread."""

    finished_ok = pyqtSignal(object)   # ClipDTO
    finished_err = pyqtSignal(str)

    def __init__(
        self,
        handler: ExtractClipHandler,
        cmd: ExtractClipCommand,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._handler = handler
        self._cmd = cmd

    def run(self) -> None:
        try:
            agg = self._handler.handle(self._cmd)
            c = agg.clip
            dto = ClipDTO(
                id=agg.id,
                source_video_id=c.source_video_id,
                title=c.title,
                file_path=c.file_path,
                thumbnail_path=c.thumbnail_path,
                start_sec=c.time_range.start_sec,
                end_sec=c.time_range.end_sec,
            )
            self.finished_ok.emit(dto)
        except Exception as exc:
            self.finished_err.emit(str(exc))


class ClipViewModel(QObject):
    clips_changed = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        extract_handler: ExtractClipHandler,
        delete_handler: DeleteClipHandler,
        get_clips_handler: GetClipsHandler,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._extract = extract_handler
        self._delete = delete_handler
        self._get_clips = get_clips_handler
        self._clips: list[ClipDTO] = []
        self._worker: _ExtractWorker | None = None

    @property
    def clips(self) -> list[ClipDTO]:
        return self._clips

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
        self._worker = _ExtractWorker(self._extract, cmd, self)
        self._worker.finished_ok.connect(self._on_extract_ok)
        self._worker.finished_err.connect(self._on_extract_err)
        self._worker.start()

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
