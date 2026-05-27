from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from domain.download.entities import DownloadJob


class IDownloadRepository(ABC):
    @abstractmethod
    def save(self, job: DownloadJob) -> None: ...

    @abstractmethod
    def get_by_id(self, job_id: UUID) -> DownloadJob | None: ...

    @abstractmethod
    def get_history(self, limit: int = 50, offset: int = 0) -> list[DownloadJob]: ...

    @abstractmethod
    def count_history(self) -> int: ...

    @abstractmethod
    def delete(self, job_id: UUID) -> None: ...

    @abstractmethod
    def find_completed_by_url(self, url: str) -> list[DownloadJob]: ...

    @abstractmethod
    def delete_completed_duplicates(
        self, url: str, quality: str, fmt: str, keep_job_id: "UUID"
    ) -> None:
        """Delete older completed records with the same url+quality+format and their files."""
