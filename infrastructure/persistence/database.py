from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from config.settings import DATABASE_PATH
from utils.resources import get_resource_path


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
