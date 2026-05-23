from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from domain.download.value_objects import DownloadProgress, DownloadSettings, Quality, MediaFormat


def _now() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    CANCELLED = "cancelled"


@dataclass
class DownloadJob:
    id: UUID
    url: str
    title: str
    settings: DownloadSettings
    status: JobStatus
    progress: DownloadProgress
    file_path: str            # populated when completed
    error_msg: str            # populated when failed
    retry_count: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def create(
        cls,
        url: str,
        title: str,
        settings: DownloadSettings | None = None,
    ) -> DownloadJob:
        now = _now()
        return cls(
            id=uuid4(),
            url=url,
            title=title,
            settings=settings or DownloadSettings(),
            status=JobStatus.PENDING,
            progress=DownloadProgress(),
            file_path="",
            error_msg="",
            retry_count=0,
            created_at=now,
            updated_at=now,
        )
