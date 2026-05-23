from __future__ import annotations

from domain.download.value_objects import DownloadSettings


class MonitoringRule:
    __slots__ = (
        "keywords",
        "min_duration_sec",
        "max_duration_sec",
        "auto_download",
        "download_settings",
    )

    def __init__(
        self,
        keywords: tuple[str, ...] = (),
        min_duration_sec: int | None = None,
        max_duration_sec: int | None = None,
        auto_download: bool = False,
        download_settings: DownloadSettings | None = None,
    ) -> None:
        self.keywords = keywords
        self.min_duration_sec = min_duration_sec
        self.max_duration_sec = max_duration_sec
        self.auto_download = auto_download
        self.download_settings = download_settings or DownloadSettings()

    def matches(self, title: str, duration_sec: int | None) -> bool:
        if self.keywords:
            title_lower = title.lower()
            if not any(kw.lower() in title_lower for kw in self.keywords):
                return False
        if self.min_duration_sec is not None and duration_sec is not None:
            if duration_sec < self.min_duration_sec:
                return False
        if self.max_duration_sec is not None and duration_sec is not None:
            if duration_sec > self.max_duration_sec:
                return False
        return True
