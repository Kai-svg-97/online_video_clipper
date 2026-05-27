from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True)
class DownloadProgressDTO:
    percent: float = 0.0
    speed_bps: float = 0.0
    eta_sec: int = 0

    def speed_formatted(self) -> str:
        if self.speed_bps < 1024:
            return f"{self.speed_bps:.0f} B/s"
        if self.speed_bps < 1_048_576:
            return f"{self.speed_bps / 1024:.1f} KB/s"
        return f"{self.speed_bps / 1_048_576:.1f} MB/s"


@dataclass(frozen=True)
class DownloadJobDTO:
    id: UUID
    url: str
    title: str
    status: str
    progress: DownloadProgressDTO = field(default_factory=DownloadProgressDTO)
