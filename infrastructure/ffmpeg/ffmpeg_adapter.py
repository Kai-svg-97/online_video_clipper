from __future__ import annotations

from pathlib import Path

import ffmpeg

from domain.clip.value_objects import TimeRange
from utils.resources import get_ffmpeg_path


class FfmpegAdapter:
    """Wraps ffmpeg-python for clip extraction.

    All I/O runs in a background QThread — never call from the GUI thread.
    """

    def extract_clip(
        self,
        source_path: Path,
        time_range: TimeRange,
        output_path: Path,
    ) -> Path:
        """Extract *time_range* from *source_path* into *output_path*."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        (
            ffmpeg
            .input(str(source_path), ss=time_range.start_sec, to=time_range.end_sec)
            .output(str(output_path), c="copy")
            .overwrite_output()
            .run(cmd=get_ffmpeg_path(), quiet=True)
        )
        return output_path

    def extract_thumbnail(
        self,
        source_path: Path,
        timestamp_sec: float,
        output_path: Path,
        width: int = 160,
        height: int = 90,
    ) -> Path:
        """Extract a single frame as a JPEG thumbnail."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        (
            ffmpeg
            .input(str(source_path), ss=timestamp_sec)
            .filter("scale", width, height)
            .output(str(output_path), vframes=1)
            .overwrite_output()
            .run(cmd=get_ffmpeg_path(), quiet=True)
        )
        return output_path
