from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from config.settings import DOWNLOAD_DIR
from domain.clip.aggregates import ClipAggregate
from domain.clip.repositories import IClipRepository
from domain.clip.value_objects import TimeRange
from domain.shared.ports import IClipExtractor, IEventBus


@dataclass
class ExtractClipCommand:
    source_video_id: UUID
    source_file_path: str
    title: str
    start_sec: float
    end_sec: float
    output_path: str | None = None


@dataclass
class DeleteClipCommand:
    clip_id: UUID
    delete_file: bool = False


class ExtractClipHandler:
    def __init__(
        self,
        repo: IClipRepository,
        ffmpeg: IClipExtractor,
        event_bus: IEventBus,
    ) -> None:
        self._repo = repo
        self._ffmpeg = ffmpeg
        self._bus = event_bus

    def handle(self, cmd: ExtractClipCommand) -> ClipAggregate:
        """Run in a background QThread — ffmpeg I/O blocks."""
        time_range = TimeRange(cmd.start_sec, cmd.end_sec)
        agg = ClipAggregate.create(cmd.source_video_id, cmd.title, time_range)

        out_path = (
            Path(cmd.output_path)
            if cmd.output_path
            else DOWNLOAD_DIR / "clips" / f"{agg.id}.mp4"
        )
        result_path = self._ffmpeg.extract_clip(
            Path(cmd.source_file_path), time_range, out_path
        )
        agg.set_file_path(str(result_path))
        self._repo.save(agg)
        self._bus.publish_all(agg.pull_events())
        return agg


class DeleteClipHandler:
    def __init__(self, repo: IClipRepository, event_bus: IEventBus) -> None:
        self._repo = repo
        self._bus = event_bus

    def handle(self, cmd: DeleteClipCommand) -> None:
        agg = self._repo.get_by_id(cmd.clip_id)
        if agg is None:
            return
        if cmd.delete_file and agg.clip.file_path:
            Path(agg.clip.file_path).unlink(missing_ok=True)
        agg.delete()
        self._repo.delete(cmd.clip_id)
        self._bus.publish_all(agg.pull_events())
