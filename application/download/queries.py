from __future__ import annotations

from dataclasses import dataclass

from application.download.dtos import DownloadJobDTO, DownloadProgressDTO
from domain.download.aggregates import DownloadQueueAggregate
from domain.download.entities import DownloadJob
from domain.download.repositories import IDownloadRepository


@dataclass
class GetDownloadQueueQuery:
    pass


@dataclass
class GetDownloadHistoryQuery:
    limit: int = 50
    offset: int = 0


def _to_dto(job: DownloadJob) -> DownloadJobDTO:
    return DownloadJobDTO(
        id=job.id,
        url=job.url,
        title=job.title,
        status=job.status.value,
        progress=DownloadProgressDTO(
            percent=job.progress.percent,
            speed_bps=job.progress.speed_bps,
            eta_sec=job.progress.eta_sec,
            # 라이브 녹화는 퍼센트가 성립하지 않아 화면이 이 셋으로 대신 알린다.
            # 빠뜨리면 카드를 그리는 순간 앱이 죽는다(dtos.py 주석 참고).
            downloaded_bytes=job.progress.downloaded_bytes,
            total_bytes=job.progress.total_bytes,
            elapsed_sec=job.progress.elapsed_sec,
        ),
        file_path=job.file_path,
        error_msg=job.error_msg,
    )


class GetDownloadQueueHandler:
    def __init__(self, queue: DownloadQueueAggregate) -> None:
        self._queue = queue

    def handle(self, query: GetDownloadQueueQuery) -> list[DownloadJobDTO]:
        return [_to_dto(job) for job in self._queue.all_jobs()]


class GetDownloadHistoryHandler:
    def __init__(self, repo: IDownloadRepository) -> None:
        self._repo = repo

    def handle(self, query: GetDownloadHistoryQuery) -> list[DownloadJobDTO]:
        return [_to_dto(job) for job in self._repo.get_history(query.limit, query.offset)]
