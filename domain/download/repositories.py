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
