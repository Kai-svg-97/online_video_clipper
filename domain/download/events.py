from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class DownloadStarted:
    job_id: UUID
    url: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class DownloadProgressUpdated:
    job_id: UUID
    percent: float
    speed_bps: float
    eta_sec: int
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class DownloadCompleted:
    job_id: UUID
    url: str
    file_path: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class DownloadFailed:
    job_id: UUID
    url: str
    error: str
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class DownloadCancelled:
    job_id: UUID
    occurred_at: datetime = field(default_factory=_now)
