from __future__ import annotations

from domain.library.repositories import IVideoRepository


class DuplicateVideoError(Exception):
    pass


class DuplicateDetectionService:
    """Checks whether a URL already exists in the library."""

    def __init__(self, repo: IVideoRepository) -> None:
        self._repo = repo

    def assert_unique(self, url: str) -> None:
        if self._repo.exists_by_url(url):
            raise DuplicateVideoError(f"Video already in library: {url}")
