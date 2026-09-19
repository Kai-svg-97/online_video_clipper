"""`ISavedSearchRepository`의 SQLite 구현.

조건은 JSON 한 덩어리(`query_json`)로 담고, 이름·정렬 순서만 열로 둔다. 조건으로
검색할 일이 없어서 — 저장된 검색은 **목록에서 골라 되부르는 것**이지 조건으로
찾는 것이 아니다. 필드가 늘 때마다 마이그레이션을 하지 않아도 되는 값이 크다.

**깨진 행 하나가 목록 전체를 막지 않는다.** 앱을 오르내리며 필드가 바뀌거나
사용자가 DB를 손볼 수 있는데, 그때 저장된 검색 하나 때문에 기능이 통째로 죽으면
안 된다(`SavedSearch.from_json`이 모르는 키를 버리고 빠진 키를 채운다).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from domain.library.repositories import ISavedSearchRepository
from domain.library.saved_search import MAX_SAVED, SavedSearch, normalize_name

logger = logging.getLogger(__name__)


class SqliteSavedSearchRepository(ISavedSearchRepository):
    def __init__(self, db) -> None:
        self._db = db

    def list_all(self) -> list[SavedSearch]:
        """저장된 순서대로. 읽다 깨진 행은 건너뛴다."""
        out: list[SavedSearch] = []
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT id, name, query_json FROM saved_searches "
                "ORDER BY sort_order, created_at"
            ).fetchall()
        for row in rows:
            try:
                out.append(
                    SavedSearch.from_json(
                        UUID(row["id"]), row["name"] or "", row["query_json"] or "{}"
                    )
                )
            except (ValueError, TypeError):
                logger.exception("저장된 검색을 읽지 못함 (건너뜀): %s", row["id"])
        return out

    def save(self, search: SavedSearch) -> None:
        """새로 넣거나 덮어쓴다.

        **상한을 여기서 지킨다.** 목록이 길어지면 고르는 것이 조건을 다시 거는 것보다
        번거로워진다. 새 항목이 상한을 넘기면 가장 오래된 것을 밀어낸다 —
        저장을 거절하면 사용자는 뭘 지워야 할지 모른 채 막힌다.
        """
        name = normalize_name(search.name) or "저장된 검색"
        now = datetime.now(timezone.utc).isoformat()
        with self._db.connection() as conn:
            conn.execute(
                "INSERT INTO saved_searches (id, name, query_json, sort_order, created_at) "
                "VALUES (?, ?, ?, COALESCE((SELECT MAX(sort_order) + 1 FROM saved_searches), 0), ?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, query_json=excluded.query_json",
                (str(search.id), name, search.to_json(), now),
            )
            conn.execute(
                "DELETE FROM saved_searches WHERE id IN ("
                "  SELECT id FROM saved_searches ORDER BY sort_order DESC, created_at DESC"
                "  LIMIT -1 OFFSET ?"
                ")",
                (MAX_SAVED,),
            )
            conn.commit()

    def delete(self, search_id: UUID) -> None:
        with self._db.connection() as conn:
            conn.execute("DELETE FROM saved_searches WHERE id = ?", (str(search_id),))
            conn.commit()

    def rename(self, search_id: UUID, name: str) -> None:
        clean = normalize_name(name)
        if not clean:
            return      # 빈 이름으로 덮어쓰면 목록에서 고를 수 없게 된다
        with self._db.connection() as conn:
            conn.execute(
                "UPDATE saved_searches SET name = ? WHERE id = ?",
                (clean, str(search_id)),
            )
            conn.commit()
