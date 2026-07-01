from __future__ import annotations

from enum import Enum


class Quality(str, Enum):
    BEST    = "best"
    P2160   = "2160p"
    P1080   = "1080p"
    P720    = "720p"
    P480    = "480p"
    P360    = "360p"
    WORST   = "worst"
    AUDIO   = "audio"


class MediaFormat(str, Enum):
    MP4  = "mp4"
    MKV  = "mkv"
    WEBM = "webm"
    MP3  = "mp3"
    M4A  = "m4a"


class DownloadSettings:
    __slots__ = (
        "quality",
        "format",
        "subtitle_langs",
        "include_thumbnail",
        "include_metadata",
        "capture_gemini",
    )

    def __init__(
        self,
        quality: Quality = Quality.P1080,
        fmt: MediaFormat = MediaFormat.MP4,
        subtitle_langs: tuple[str, ...] = (),
        include_thumbnail: bool = True,
        include_metadata: bool = True,
        capture_gemini: bool = False,
    ) -> None:
        self.quality = quality
        self.format = fmt
        self.subtitle_langs = subtitle_langs
        self.include_thumbnail = include_thumbnail
        self.include_metadata = include_metadata
        self.capture_gemini = capture_gemini

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DownloadSettings):
            return NotImplemented
        return (
            self.quality == other.quality
            and self.format == other.format
            and self.subtitle_langs == other.subtitle_langs
            and self.include_thumbnail == other.include_thumbnail
            and self.include_metadata == other.include_metadata
            and self.capture_gemini == other.capture_gemini
        )

    def __hash__(self) -> int:
        return hash((self.quality, self.format, self.subtitle_langs, self.capture_gemini))


class DownloadProgress:
    __slots__ = ("percent", "speed_bps", "eta_sec", "downloaded_bytes")

    def __init__(
        self,
        percent: float = 0.0,
        speed_bps: float = 0.0,
        eta_sec: int = 0,
        downloaded_bytes: int = 0,
    ) -> None:
        self.percent = percent
        self.speed_bps = speed_bps
        self.eta_sec = eta_sec
        self.downloaded_bytes = downloaded_bytes

    def speed_formatted(self) -> str:
        if self.speed_bps < 1024:
            return f"{self.speed_bps:.0f} B/s"
        if self.speed_bps < 1024 ** 2:
            return f"{self.speed_bps / 1024:.1f} KB/s"
        return f"{self.speed_bps / 1024 ** 2:.1f} MB/s"
