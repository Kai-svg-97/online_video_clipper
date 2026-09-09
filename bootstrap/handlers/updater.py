"""자동 업데이트 유스케이스 조립.

GUI가 GitHub API를 직접 부르지 않는다 — `IUpdateChecker` 포트를 거친다(다른 기능과
같은 규약).
"""

from __future__ import annotations

from application.updater.commands import DownloadUpdateHandler
from application.updater.queries import CheckForUpdateHandler
from infrastructure.updater.update_checker import GithubUpdateChecker
from version import __version__

from bootstrap.context import UpdaterHandlers


def build() -> UpdaterHandlers:
    checker = GithubUpdateChecker(__version__)
    return UpdaterHandlers(
        check=CheckForUpdateHandler(checker),
        download=DownloadUpdateHandler(checker),
    )
