from __future__ import annotations

from pathlib import Path
from typing import Callable

import yt_dlp

from config.settings import DOWNLOAD_DIR, THUMBNAIL_DIR
from domain.download.value_objects import DownloadProgress, DownloadSettings, MediaFormat


class YtDlpAdapter:
    """Thin wrapper around yt-dlp for single-video downloads.

    All network I/O runs in a background QThread — never call from the GUI thread.
    """

    def __init__(
        self,
        on_progress: Callable[[DownloadProgress], None] | None = None,
    ) -> None:
        self._on_progress = on_progress

    def fetch_metadata(self, url: str) -> dict:
        """Return video metadata without downloading."""
        opts = {"quiet": True, "no_warnings": True, "skip_download": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False) or {}

    def download(
        self,
        url: str,
        settings: DownloadSettings,
        output_dir: Path | None = None,
    ) -> Path:
        """Download *url* with *settings*; return the final file path."""
        out_dir = output_dir or DOWNLOAD_DIR
        out_dir.mkdir(parents=True, exist_ok=True)

        format_spec = self._build_format_spec(settings)
        opts: dict = {
            "format": format_spec,
            "outtmpl": str(out_dir / "%(title)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [self._progress_hook],
        }

        if settings.subtitle_langs:
            opts["writesubtitles"] = True
            opts["subtitleslangs"] = list(settings.subtitle_langs)

        if settings.include_thumbnail:
            opts["writethumbnail"] = True

        if settings.include_metadata:
            opts["addmetadata"] = True
            opts["postprocessors"] = [{"key": "FFmpegMetadata"}]

        # Postprocessor: convert to target container format
        if settings.format in (MediaFormat.MP3, MediaFormat.M4A):
            opts.setdefault("postprocessors", []).append(
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": settings.format.value,
                }
            )

        self._last_filepath: str = ""
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info:
                self._last_filepath = ydl.prepare_filename(info)

        return Path(self._last_filepath)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_format_spec(self, settings: DownloadSettings) -> str:
        from domain.download.value_objects import Quality

        if settings.quality == Quality.AUDIO:
            return "bestaudio/best"
        if settings.quality == Quality.BEST:
            return "bestvideo+bestaudio/best"
        if settings.quality == Quality.WORST:
            return "worstvideo+worstaudio/worst"
        h = settings.quality.value.rstrip("p")
        return (
            f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"
        )

    def _progress_hook(self, info: dict) -> None:
        if self._on_progress is None:
            return
        if info.get("status") != "downloading":
            return
        progress = DownloadProgress(
            percent=float(info.get("_percent_str", "0").strip("%") or 0),
            speed_bps=float(info.get("speed") or 0),
            eta_sec=int(info.get("eta") or 0),
            downloaded_bytes=int(info.get("downloaded_bytes") or 0),
        )
        self._on_progress(progress)
