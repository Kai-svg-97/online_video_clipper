from __future__ import annotations

from pathlib import Path
from typing import Callable
from uuid import UUID

import requests
import yt_dlp

from config.settings import DOWNLOAD_DIR, THUMBNAIL_DIR
from domain.download.value_objects import DownloadProgress, DownloadSettings, MediaFormat, Quality
from utils.resources import get_ffmpeg_path


def _height_to_quality_label(height: int | None) -> str:
    """픽셀 높이를 사람이 읽기 쉬운 품질 레이블로 변환한다.

    예: 1080 → "FHD", 2160 → "UHD (4K)", None → ""
    """
    if height is None:
        return ""
    if height >= 2160:
        return "UHD (4K)"
    if height >= 1440:
        return "QHD (2K)"
    if height >= 1080:
        return "FHD"
    if height >= 720:
        return "HD"
    if height >= 480:
        return "SD"
    return f"{height}p"


def _find_ffmpeg() -> str | None:
    """Return path to ffmpeg executable, or None if not found."""
    try:
        return get_ffmpeg_path()
    except FileNotFoundError:
        return None


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
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "socket_timeout": 30,
            "retries": 0,
            "extractor_retries": 0,
            "noplaylist": True,   # treat list= params as single video, not playlist
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False) or {}

    def download_thumbnail(self, video_id: UUID, thumbnail_url: str, force: bool = False) -> str | None:
        """Download thumbnail image; return relative filename or None on failure.

        Args:
            video_id: UUID of the video, used as the filename stem.
            thumbnail_url: Remote URL of the thumbnail image.
            force: When True, delete any existing cached file before downloading.
        """
        if not thumbnail_url:
            return None
        raw_ext = thumbnail_url.split("?")[0].rsplit(".", 1)
        ext = raw_ext[-1].lower() if len(raw_ext) > 1 and raw_ext[-1].lower() in ("jpg", "jpeg", "png", "webp") else "jpg"
        filename = f"{video_id}.{ext}"
        dest = THUMBNAIL_DIR / filename
        if force:
            dest.unlink(missing_ok=True)
        if dest.exists():
            return filename
        try:
            THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)
            resp = requests.get(thumbnail_url, timeout=15)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            return filename
        except Exception:
            return None

    def download(
        self,
        url: str,
        settings: DownloadSettings,
        output_dir: Path | None = None,
    ) -> Path:
        """Download *url* with *settings*; return the final file path.

        If ffmpeg is not available, falls back to a single-stream format that
        requires no post-processing merging.
        """
        out_dir = output_dir or DOWNLOAD_DIR
        out_dir.mkdir(parents=True, exist_ok=True)

        ffmpeg = _find_ffmpeg()
        has_ffmpeg = ffmpeg is not None

        format_spec = (
            self._build_format_spec(settings)
            if has_ffmpeg
            else self._build_format_spec_no_ffmpeg(settings)
        )

        opts: dict = {
            "format": format_spec,
            "outtmpl": str(out_dir / "%(title)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [self._progress_hook],
            "noplaylist": True,
        }

        if has_ffmpeg:
            opts["ffmpeg_location"] = ffmpeg

            if settings.subtitle_langs:
                opts["writesubtitles"] = True
                opts["subtitleslangs"] = list(settings.subtitle_langs)

            if settings.include_metadata:
                opts.setdefault("postprocessors", [])
                opts["postprocessors"].append({"key": "FFmpegMetadata"})

            if settings.format in (MediaFormat.MP3, MediaFormat.M4A):
                opts.setdefault("postprocessors", [])
                opts["postprocessors"].append(
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": settings.format.value,
                    }
                )

        self._last_filepath: str = ""
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info:
                # requested_downloads contains the actual post-processed filepath
                rd = (info.get("requested_downloads") or [{}])[0]
                self._last_filepath = (
                    rd.get("filepath")
                    or info.get("filepath")
                    or ydl.prepare_filename(info)
                )
                # 오디오 포맷이 아닐 때만 실제 다운로드 품질 레이블을 파일명에 삽입
                if settings.format not in (MediaFormat.MP3, MediaFormat.M4A):
                    actual_height = rd.get("height") or info.get("height")
                    label = _height_to_quality_label(actual_height)
                    if label:
                        p = Path(self._last_filepath)
                        new_path = p.with_name(f"{p.stem} [{label}]{p.suffix}")
                        try:
                            if p.exists() and not new_path.exists():
                                p.rename(new_path)
                                self._last_filepath = str(new_path)
                        except OSError:
                            pass  # 이름 변경 실패 시 원본 경로 유지

        return Path(self._last_filepath)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_format_spec(self, settings: DownloadSettings) -> str:
        """Format spec when ffmpeg IS available (allows merging video+audio)."""
        if settings.quality == Quality.AUDIO:
            return "bestaudio/best"
        if settings.quality == Quality.BEST:
            return "bestvideo+bestaudio/best"
        if settings.quality == Quality.WORST:
            return "worstvideo+worstaudio/worst"
        h = settings.quality.value.rstrip("p")
        return f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"

    def _build_format_spec_no_ffmpeg(self, settings: DownloadSettings) -> str:
        """Format spec when ffmpeg is NOT available (single-stream, no merging)."""
        if settings.quality == Quality.AUDIO:
            return "bestaudio[ext=m4a]/bestaudio[ext=mp4]/bestaudio"
        if settings.quality == Quality.BEST:
            return "best[ext=mp4]/best"
        if settings.quality == Quality.WORST:
            return "worst[ext=mp4]/worst"
        h = settings.quality.value.rstrip("p")
        return f"best[height<={h}][ext=mp4]/best[height<={h}]/best"

    def _progress_hook(self, info: dict) -> None:
        if self._on_progress is None:
            return
        if info.get("status") != "downloading":
            return
        try:
            pct_str = str(info.get("_percent_str") or "0").strip().rstrip("%")
            percent = float(pct_str or 0)
        except (ValueError, TypeError):
            percent = 0.0
        progress = DownloadProgress(
            percent=percent,
            speed_bps=float(info.get("speed") or 0),
            eta_sec=int(info.get("eta") or 0),
            downloaded_bytes=int(info.get("downloaded_bytes") or 0),
        )
        self._on_progress(progress)
