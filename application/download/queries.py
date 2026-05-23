from __future__ import annotations

from dataclasses import dataclass

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


class GetDownloadQueueHandler:
    def __init__(self, queue: DownloadQueueAggregate) -> None:
        self._queue = queue

    def handle(self, query: GetDownloadQueueQuery) -> list[DownloadJob]:
        return self._queue.all_jobs()


class GetDownloadHistoryHandler:
    def __init__(self, repo: IDownloadRepository) -> None:
        self._repo = repo

    def handle(self, query: GetDownloadHistoryQuery) -> list[DownloadJob]:
        return self._repo.get_history(query.limit, query.offset)
