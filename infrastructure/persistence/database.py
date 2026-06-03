from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from config.settings import DATABASE_PATH
from utils.resources import get_resource_path

logger = logging.getLogger(__name__)


class Database:
    """Manages the SQLite connection lifecycle."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or DATABASE_PATH

    def initialize(self) -> None:
        """Create schema and enable WAL mode. Called once at startup."""
        schema_sql = get_resource_path("db/schema.sql").read_text(encoding="utf-8")
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(schema_sql)
        self._migrate_normalize_urls()
        self._migrate_playlist_schema()

    def _migrate_playlist_schema(self) -> None:
        """플레이리스트 스키마 컬럼 추가 (idempotent ALTER TABLE)."""
        migrations = [
            "ALTER TABLE playlists ADD COLUMN folder_id TEXT REFERENCES playlist_folders(id) ON DELETE SET NULL",
            "ALTER TABLE playlist_items ADD COLUMN yt_item_id TEXT",
        ]
        with self.connection() as conn:
            for sql in migrations:
                try:
                    conn.execute(sql)
                except Exception:
                    logger.debug("플레이리스트 스키마 마이그레이션 건너뜀 (이미 컬럼 존재 가능)")
                    pass  # 이미 컬럼이 존재하면 무시

    def _migrate_normalize_urls(self) -> None:
        """Idempotent: normalize existing YouTube URLs to canonical ?v=ID form.

        When a canonical record already exists for a non-canonical duplicate,
        the duplicate's tags are merged into the canonical record and the
        duplicate is deleted.
        """
        from domain.library.value_objects import normalize_video_url
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT id, url FROM videos WHERE url LIKE '%youtube%' OR url LIKE '%youtu.be%'"
            ).fetchall()
            for row in rows:
                canonical = normalize_video_url(row["url"])
                if canonical == row["url"]:
                    continue  # already canonical, nothing to do
                # Check if canonical version already exists
                existing = conn.execute(
                    "SELECT id FROM videos WHERE url=?", (canonical,)
                ).fetchone()
                if existing:
                    # Merge: transfer tags from duplicate to canonical, then delete duplicate
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO video_tags(video_id, tag_id)
                        SELECT ?, tag_id FROM video_tags WHERE video_id=?
                        """,
                        (existing["id"], row["id"]),
                    )
                    conn.execute("DELETE FROM videos WHERE id=?", (row["id"],))
                else:
                    conn.execute(
                        "UPDATE videos SET url=? WHERE id=?", (canonical, row["id"])
                    )

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
