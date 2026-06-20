"""업데이트 쿼리 핸들러."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from application.updater.dtos import UpdateDTO
from domain.shared.ports import IUpdateChecker

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CheckForUpdateQuery:
    pass


class CheckForUpdateHandler:
    def __init__(self, checker: IUpdateChecker) -> None:
        self._checker = checker

    def handle(self, query: CheckForUpdateQuery) -> UpdateDTO | None:  # noqa: ARG002
        info = self._checker.check_latest()
        if info is None:
            return None
        return UpdateDTO(
            version=info.version,
            asset_name=info.asset_name,
            download_url=info.download_url,
            size_bytes=info.size_bytes,
            sha256=info.sha256,
            release_notes=info.release_notes,
        )
