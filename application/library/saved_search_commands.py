"""저장된 검색 유스케이스.

화면(뷰모델)이 리포지토리를 직접 잡으면 레이어가 뒤집힌다(`gui → application →
domain`). 하는 일이 얇더라도 이 층을 거친다 — 이름 중복 처리·빈 조건 거부 같은
**정책**이 화면이 아니라 여기 있어야, 나중에 다른 진입점(단축키·명령 팔레트)이
생겨도 같은 규칙을 탄다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from domain.library.repositories import ISavedSearchRepository
from domain.library.saved_search import SavedSearch, unique_name

logger = logging.getLogger(__name__)


@dataclass
class SaveSearchCommand:
    """지금 조건에 이름을 붙여 저장한다.

    필드는 화면의 필터 막대와 1:1이고, **날짜·길이는 프리셋 키**다(값이 아니다).
    """

    name: str
    text: str = ""
    date_key: str = "all"
    duration_key: str = "all"
    download_key: str = "all"
    watched_key: str = "all"
    channel_name: str = ""
    favorite_only: bool = False


class ListSavedSearchesHandler:
    def __init__(self, repo: ISavedSearchRepository) -> None:
        self._repo = repo

    def handle(self) -> list[SavedSearch]:
        """목록(읽지 못하면 빈 목록) — 저장된 검색 때문에 화면이 죽으면 안 된다."""
        try:
            return self._repo.list_all()
        except Exception:
            logger.exception("저장된 검색 목록 조회 실패")
            return []


class SaveSearchHandler:
    def __init__(self, repo: ISavedSearchRepository) -> None:
        self._repo = repo

    def handle(self, cmd: SaveSearchCommand) -> SavedSearch | None:
        """저장하고 저장된 것을 돌려준다. 조건이 없으면 None.

        **이름이 겹쳐도 거절하지 않는다** — 번호를 붙인다. 저장은 곁가지 행동이라,
        거기서 막아 세우면 하려던 일(영상 찾기)의 흐름이 끊긴다.
        """
        try:
            existing = [s.name for s in self._repo.list_all()]
        except Exception:
            logger.exception("저장된 검색 목록 조회 실패 — 이름 중복 판정 생략")
            existing = []

        search = SavedSearch(
            name=unique_name(cmd.name, existing),
            text=cmd.text,
            date_key=cmd.date_key,
            duration_key=cmd.duration_key,
            download_key=cmd.download_key,
            watched_key=cmd.watched_key,
            channel_name=cmd.channel_name,
            favorite_only=cmd.favorite_only,
        )
        if search.is_empty:
            logger.info("조건이 없는 검색은 저장하지 않는다: %s", search.name)
            return None
        try:
            self._repo.save(search)
        except Exception:
            logger.exception("저장된 검색 저장 실패: %s", search.name)
            return None
        return search


class DeleteSavedSearchHandler:
    def __init__(self, repo: ISavedSearchRepository) -> None:
        self._repo = repo

    def handle(self, search_id: UUID) -> None:
        try:
            self._repo.delete(search_id)
        except Exception:
            logger.exception("저장된 검색 삭제 실패: %s", search_id)


class RenameSavedSearchHandler:
    def __init__(self, repo: ISavedSearchRepository) -> None:
        self._repo = repo

    def handle(self, search_id: UUID, name: str) -> None:
        try:
            self._repo.rename(search_id, name)
        except Exception:
            logger.exception("저장된 검색 이름 변경 실패: %s", search_id)
