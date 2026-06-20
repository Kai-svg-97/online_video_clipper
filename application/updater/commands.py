"""업데이트 커맨드 핸들러."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from domain.shared.ports import IUpdateChecker, UpdateInfo

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DownloadUpdateCommand:
    info: UpdateInfo   # domain VO — SHA256 검증에 필요
    dest_dir: Path


class DownloadUpdateHandler:
    def __init__(self, checker: IUpdateChecker) -> None:
        self._checker = checker

    def handle(
        self,
        cmd: DownloadUpdateCommand,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> Path:
        return self._checker.download_asset(cmd.info, cmd.dest_dir, on_progress)
