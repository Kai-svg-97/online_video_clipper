"""`ISubtitleRepository`의 SQLite 구현.

검색은 LIKE 부분 일치다 — 이유는 `db/schema.sql`의 자막 색인 주석 참조(앱의 다른
검색과 규칙을 맞춘다). 저장은 영상·언어 단위 통째 교체라 트랜잭션 하나로 끝난다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from domain.library.subtitle_repository import (
    ISubtitleRepository,
    SubtitleIndexInfo,
    SubtitleLine,
)

logger = logging.getLogger(__name__)


def _like_pattern(text: str) -> str:
    """LIKE 와일드카드를 이스케이프한 부분 일치 패턴.

    `sqlite_video_repository`의 같은 이름 함수와 규칙이 같아야 한다 — 어긋나면
    "제목은 찾는데 자막은 못 찾는" 검색이 된다.
    """
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class SqliteSubtitleRepository(ISubtitleRepository):
    def __init__(self, db) -> None:
        self._db = db

    def replace_lines(
        self, video_id: UUID, lang: str, label: str, lines: list[SubtitleLine]
    ) -> None:
        vid = str(video_id)
        with self._db.connection() as conn:
            conn.execute(
                "DELETE FROM subtitle_lines WHERE video_id=? AND lang=?", (vid, lang)
            )
            conn.execute(
                "DELETE FROM subtitle_index WHERE video_id=? AND lang=?", (vid, lang)
            )
            if not lines:
                return
            conn.executemany(
                "INSERT INTO subtitle_lines (video_id, lang, start_ms, end_ms, text)"
                " VALUES (?, ?, ?, ?, ?)",
                [(vid, lang, ln.start_ms, ln.end_ms, ln.text) for ln in lines],
            )
            conn.execute(
                "INSERT INTO subtitle_index (video_id, lang, label, line_count, indexed_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (vid, lang, label, len(lines), datetime.now(timezone.utc).isoformat()),
            )
        logger.info("자막 색인 저장: video=%s lang=%s lines=%d", vid, lang, len(lines))

    def list_lines(self, video_id: UUID, lang: str | None = None) -> list[SubtitleLine]:
        vid = str(video_id)
        with self._db.connection() as conn:
            if lang is None:
                # 언어를 고르지 않으면 색인된 첫 언어를 쓴다 — 화면이 "무엇을 보여줄지"
                # 매번 되묻지 않게 하기 위한 기본값이다.
                row = conn.execute(
                    "SELECT lang FROM subtitle_index WHERE video_id=? ORDER BY lang LIMIT 1",
                    (vid,),
                ).fetchone()
                if row is None:
                    return []
                lang = row["lang"]
            rows = conn.execute(
                "SELECT start_ms, end_ms, text FROM subtitle_lines"
                " WHERE video_id=? AND lang=? ORDER BY start_ms",
                (vid, lang),
            ).fetchall()
        return [SubtitleLine(r["start_ms"], r["end_ms"], r["text"]) for r in rows]

    def list_indexes(self, video_id: UUID) -> list[SubtitleIndexInfo]:
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT lang, label, line_count, indexed_at FROM subtitle_index"
                " WHERE video_id=? ORDER BY lang",
                (str(video_id),),
            ).fetchall()
        return [
            SubtitleIndexInfo(
                lang=r["lang"],
                label=r["label"],
                line_count=r["line_count"],
                indexed_at=datetime.fromisoformat(r["indexed_at"]),
            )
            for r in rows
        ]

    def search_lines(
        self, video_id: UUID, text: str, limit: int = 200
    ) -> list[SubtitleLine]:
        if not text:
            return []
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT start_ms, end_ms, text FROM subtitle_lines"
                " WHERE video_id=? AND text LIKE ? ESCAPE '\\'"
                " ORDER BY start_ms LIMIT ?",
                (str(video_id), _like_pattern(text), limit),
            ).fetchall()
        return [SubtitleLine(r["start_ms"], r["end_ms"], r["text"]) for r in rows]

    def indexed_video_ids(self) -> set[UUID]:
        with self._db.connection() as conn:
            rows = conn.execute("SELECT DISTINCT video_id FROM subtitle_index").fetchall()
        return {UUID(r["video_id"]) for r in rows}

    def delete(self, video_id: UUID) -> None:
        vid = str(video_id)
        with self._db.connection() as conn:
            conn.execute("DELETE FROM subtitle_lines WHERE video_id=?", (vid,))
            conn.execute("DELETE FROM subtitle_index WHERE video_id=?", (vid,))
