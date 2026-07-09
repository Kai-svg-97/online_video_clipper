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
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(id TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
        self._run_once("migrate_normalize_urls", self._migrate_normalize_urls)
        self._run_once("migrate_playlist_schema", self._migrate_playlist_schema)
        self._run_once("migrate_channel_ids", self._migrate_channel_ids)
        self._run_once("migrate_sort_indexes", self._migrate_sort_indexes)
        self._run_once("migrate_gemini_summary", self._migrate_gemini_summary)
        self._run_once("migrate_videos_gemini_summary", self._migrate_videos_gemini_summary)
        self._run_once("migrate_song_tables", self._migrate_song_tables)
        self._run_once("migrate_song_sources_reorder", self._migrate_song_sources_reorder)

    def _run_once(self, migration_id: str, func) -> None:
        """마이그레이션을 최초 1회만 실행한다 (schema_migrations 테이블로 추적)."""
        with self.connection() as conn:
            if conn.execute(
                "SELECT 1 FROM schema_migrations WHERE id=?", (migration_id,)
            ).fetchone():
                return
        func()
        with self.connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(id, applied_at) VALUES (?, datetime('now'))",
                (migration_id,),
            )

    def _migrate_channel_ids(self) -> None:
        """channel_subscriptions의 URL 형식 channel_id를 UCxxx로 정규화 (idempotent).

        같은 UC ID 레코드가 이미 존재하면 URL 형식 레코드를 삭제해 중복 제거.
        """
        import re  # noqa: PLC0415

        def _norm(raw: str) -> str:
            m = re.search(r"/channel/(UC[A-Za-z0-9_-]+)", raw)
            return m.group(1) if m else raw

        with self.connection() as conn:
            rows = conn.execute(
                "SELECT id, channel_id FROM channel_subscriptions WHERE channel_id LIKE 'https://%'"
            ).fetchall()
            for row in rows:
                uc_id = _norm(row["channel_id"])
                if uc_id == row["channel_id"]:
                    continue
                existing = conn.execute(
                    "SELECT id FROM channel_subscriptions WHERE channel_id=?", (uc_id,)
                ).fetchone()
                if existing:
                    conn.execute("DELETE FROM channel_subscriptions WHERE id=?", (row["id"],))
                    logger.info("중복 채널 구독 레코드 제거: %s (UC 형식 레코드 유지)", row["channel_id"])
                else:
                    conn.execute(
                        "UPDATE channel_subscriptions SET channel_id=? WHERE id=?",
                        (uc_id, row["id"]),
                    )
                    logger.info("채널 구독 ID 정규화: %s → %s", row["channel_id"], uc_id)

    def _migrate_sort_indexes(self) -> None:
        """정렬 가속 인덱스를 추가한다 (idempotent — IF NOT EXISTS로 재실행 안전)."""
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_videos_published_at ON videos(published_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_videos_title        ON videos(title COLLATE NOCASE)",
            "CREATE INDEX IF NOT EXISTS idx_videos_view_count   ON videos(view_count DESC)",
            "CREATE INDEX IF NOT EXISTS idx_videos_duration_sec ON videos(duration_sec)",
        ]
        with self.connection() as conn:
            for sql in indexes:
                try:
                    conn.execute(sql)
                except Exception:
                    logger.debug("정렬 인덱스 생성 건너뜀: %s", sql)

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

    def _migrate_videos_gemini_summary(self) -> None:
        """videos 테이블에 gemini_summary 컬럼을 추가한다 (idempotent)."""
        with self.connection() as conn:
            try:
                conn.execute(
                    "ALTER TABLE videos ADD COLUMN gemini_summary TEXT DEFAULT ''"
                )
                logger.info("videos.gemini_summary 컬럼 추가 완료")
            except Exception:
                logger.debug("videos.gemini_summary 컬럼 이미 존재 — 건너뜀")

    def _migrate_song_tables(self) -> None:
        """노래 정보/가사 출처 테이블 시드 (idempotent).

        테이블 자체는 schema.sql의 CREATE TABLE IF NOT EXISTS로 생성되므로, 여기서는
        가사 출처 레지스트리가 비어 있을 때 기본 출처(LRCLIB→Genius→멜론→벅스→지니)를
        priority 순으로 시드한다. 이미 항목이 있으면 건드리지 않는다.
        """
        from uuid import uuid4  # noqa: PLC0415

        # 한국곡 조회에 유리하도록 지니·벅스를 Genius·멜론보다 앞에 둔다
        # (실측상 지니·벅스가 국내곡 원가사를 안정적으로 반환).
        defaults = [
            ("LRCLIB", "lrclib", "https://lrclib.net", 10),
            ("지니", "genie", "https://www.genie.co.kr", 20),
            ("벅스", "bugs", "https://music.bugs.co.kr", 30),
            ("Genius", "genius", "https://genius.com", 40),
            ("멜론", "melon", "https://www.melon.com", 50),
        ]
        with self.connection() as conn:
            existing = conn.execute("SELECT COUNT(*) FROM lyrics_sources").fetchone()
            if existing and existing[0]:
                return
            for name, key, url, prio in defaults:
                conn.execute(
                    "INSERT INTO lyrics_sources(id, name, provider_key, base_url, enabled, priority) "
                    "VALUES (?,?,?,?,1,?)",
                    (str(uuid4()), name, key, url, prio),
                )
            logger.info("가사 출처 기본값 시드 완료 (%d개)", len(defaults))

    def _migrate_song_sources_reorder(self) -> None:
        """기존 설치본의 기본 가사 출처 우선순위를 한국곡 조회에 유리하게 재정렬한다.

        지니·벅스를 Genius·멜론보다 앞으로 옮긴다(provider_key 기준 1회 갱신). Genius가
        쓰레기 헤더로 '조회 성공' 처리돼 국내 사이트가 시도되지 않던 문제를 완화한다.
        사용자가 추가한 커스텀 출처는 건드리지 않는다.
        """
        new_priority = {"lrclib": 10, "genie": 20, "bugs": 30, "genius": 40, "melon": 50}
        with self.connection() as conn:
            for key, prio in new_priority.items():
                conn.execute(
                    "UPDATE lyrics_sources SET priority=? WHERE provider_key=?",
                    (prio, key),
                )
            logger.info("가사 출처 우선순위 재정렬 완료 (지니·벅스 우선)")

    def _migrate_gemini_summary(self) -> None:
        """download_history 테이블에 gemini_summary 컬럼을 추가한다 (idempotent)."""
        with self.connection() as conn:
            try:
                conn.execute(
                    "ALTER TABLE download_history ADD COLUMN gemini_summary TEXT DEFAULT ''"
                )
                logger.info("download_history.gemini_summary 컬럼 추가 완료")
            except Exception:
                logger.debug("gemini_summary 컬럼 이미 존재 — 건너뜀")

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
