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
    def find_failed_by_url(self, url: str) -> list[DownloadJob]: ...

    @abstractmethod
    def delete_completed_duplicates(
        self, url: str, quality: str, fmt: str, keep_job_id: "UUID"
    ) -> None:
        """Delete older completed records with the same url+quality+format and their files."""

    def find_completed_formats_by_urls(self, urls: list[str]) -> dict[str, set[str]]:
        """URL별 완료된 다운로드 포맷(소문자) 집합을 한 번에 조회한다.

        목록 화면의 영상/음원 배지처럼 수십 건을 동시에 판정할 때 URL 단건 조회를
        반복하면 N+1이 되어 메인 스레드가 멈춘다. 구현체는 단일 쿼리로 최적화하고,
        여기서는 안전한 기본 동작(단건 조회 반복)만 제공한다.
        """
        result: dict[str, set[str]] = {}
        for url in dict.fromkeys(urls):
            fmts = {
                (job.settings.format.value or "").lower()
                for job in self.find_completed_by_url(url)
            }
            if fmts:
                result[url] = fmts
        return result
