from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from config.settings import DATABASE_PATH
from utils.resources import get_resource_path

logger = logging.getLogger(__name__)


# 이 코드가 아는 마이그레이션 id 집합(적용 순서). 각 id에 대응하는 메서드는 "_" + id 이다.
# sync 스키마 게이트가 이 집합을 "로컬이 지원하는 스키마 능력"으로 사용한다 —
# 원격 op의 schema_ids가 이 집합에 없는 항목을 포함하면 원격이 더 최신이므로 차단한다.
MIGRATION_IDS: tuple[str, ...] = (
    "migrate_normalize_urls",
    "migrate_playlist_schema",
    "migrate_channel_ids",
    "migrate_sort_indexes",
    "migrate_gemini_summary",
    "migrate_videos_gemini_summary",
    "migrate_song_tables",
    "migrate_song_sources_reorder",
    "migrate_media_paths_relative",
    "migrate_video_summary_status",
    "migrate_lyrics_offset",
    "migrate_album_tables",
    "migrate_album_disc_no",
    "migrate_playback_position",
    "migrate_album_links_reverify",
)


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
        for migration_id in MIGRATION_IDS:
            self._run_once(migration_id, getattr(self, "_" + migration_id))

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

    def _migrate_video_summary_status(self) -> None:
        """video_summary_status 테이블을 만든다 (idempotent).

        Gemini 요약 실패 사유를 담아 상세 화면이 정확한 안내 문구를 띄우게 한다.
        진단 정보이므로 동기화 대상이 아니며, videos 행을 늘리지 않도록 분리했다.
        """
        with self.connection() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS video_summary_status ("
                " video_id   TEXT PRIMARY KEY REFERENCES videos(id) ON DELETE CASCADE,"
                " status     TEXT NOT NULL,"
                " updated_at TEXT NOT NULL)"
            )

    def _migrate_lyrics_offset(self) -> None:
        """song_info에 lyrics_offset_ms 컬럼을 추가한다 (idempotent).

        기존 설치본은 schema.sql의 CREATE TABLE IF NOT EXISTS로는 컬럼이 늘지 않으므로
        ALTER TABLE로 보강한다.
        """
        with self.connection() as conn:
            try:
                conn.execute(
                    "ALTER TABLE song_info ADD COLUMN lyrics_offset_ms INTEGER NOT NULL DEFAULT 0"
                )
                logger.info("song_info.lyrics_offset_ms 컬럼 추가 완료")
            except Exception:
                logger.debug("song_info.lyrics_offset_ms 컬럼 이미 존재 — 건너뜀")

    def _migrate_album_tables(self) -> None:
        """앨범 캐시/자동 매핑 테이블을 만든다 (idempotent).

        기존 설치본에도 schema.sql의 CREATE TABLE IF NOT EXISTS가 적용되지만, 마이그레이션
        목록에 넣어 "이 코드가 아는 스키마 능력"(MIGRATION_IDS)에 포함시킨다 — 동기화
        스키마 게이트가 이 집합으로 호환성을 판정한다. 두 표 모두 **파생 캐시**라
        동기화 대상이 아니며, 지워도 다시 조회하면 복구된다.
        """
        with self.connection() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS album_cache ("
                " album_key TEXT PRIMARY KEY,"
                " album_title TEXT NOT NULL DEFAULT '',"
                " artist TEXT NOT NULL DEFAULT '',"
                " artwork_url TEXT NOT NULL DEFAULT '',"
                " artwork_path TEXT NOT NULL DEFAULT '',"
                " description TEXT NOT NULL DEFAULT '',"
                " release_date TEXT NOT NULL DEFAULT '',"
                " genre TEXT NOT NULL DEFAULT '',"
                " copyright TEXT NOT NULL DEFAULT '',"
                " track_count INTEGER NOT NULL DEFAULT 0,"
                " tracks_json TEXT NOT NULL DEFAULT '[]',"
                " source_name TEXT NOT NULL DEFAULT '',"
                " source_url TEXT NOT NULL DEFAULT '',"
                " fetched_at TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS album_track_links ("
                " album_key TEXT NOT NULL,"
                " disc_no INTEGER NOT NULL DEFAULT 1,"
                " track_no INTEGER NOT NULL,"
                " track_title TEXT NOT NULL DEFAULT '',"
                " stream_url TEXT NOT NULL DEFAULT '',"
                " stream_title TEXT NOT NULL DEFAULT '',"
                " stream_channel TEXT NOT NULL DEFAULT '',"
                " stream_yt_id TEXT NOT NULL DEFAULT '',"
                " duration_sec INTEGER,"
                " origin TEXT NOT NULL DEFAULT 'auto',"
                " created_at TEXT NOT NULL,"
                " PRIMARY KEY (album_key, disc_no, track_no))"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS album_lookup_state ("
                " video_id TEXT PRIMARY KEY,"
                " found INTEGER NOT NULL DEFAULT 0,"
                " tried_at TEXT NOT NULL)"
            )

    def _migrate_playback_position(self) -> None:
        """videos에 이어보기 컬럼(last_position_ms·last_played_at)을 추가한다 (idempotent).

        기기마다 보던 지점이 다르므로 **동기화 캡처 대상이 아니다**(view_count와 같은 취급).
        """
        with self.connection() as conn:
            for ddl in (
                "ALTER TABLE videos ADD COLUMN last_position_ms INTEGER NOT NULL DEFAULT 0",
                "ALTER TABLE videos ADD COLUMN last_played_at TEXT",
            ):
                try:
                    conn.execute(ddl)
                except Exception:
                    logger.debug("이어보기 컬럼이 이미 존재 — 건너뜀")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_videos_last_played"
                " ON videos(last_played_at DESC)"
            )

    def _migrate_album_disc_no(self) -> None:
        """album_track_links의 키를 (album_key, disc_no, track_no)로 바꾼다.

        트랙 번호는 **디스크 안에서만 유일**해서, 2장짜리 앨범은 disc1·disc2의 같은
        번호가 서로를 덮어썼다 — 서로 다른 곡이 같은 영상을 가리키는 증상이 실제로
        나왔다. 기존 행은 어느 디스크의 것인지 알 수 없으므로(그래서 틀린 매핑이
        섞여 있다) **버리고 다시 만든다** — 자동 매핑은 앨범을 열면 다시 찾는 캐시라
        잃어도 복구된다.
        """
        with self.connection() as conn:
            conn.execute("DROP TABLE IF EXISTS album_track_links")
            conn.execute(
                "CREATE TABLE album_track_links ("
                " album_key TEXT NOT NULL,"
                " disc_no INTEGER NOT NULL DEFAULT 1,"
                " track_no INTEGER NOT NULL,"
                " track_title TEXT NOT NULL DEFAULT '',"
                " stream_url TEXT NOT NULL DEFAULT '',"
                " stream_title TEXT NOT NULL DEFAULT '',"
                " stream_channel TEXT NOT NULL DEFAULT '',"
                " stream_yt_id TEXT NOT NULL DEFAULT '',"
                " duration_sec INTEGER,"
                " origin TEXT NOT NULL DEFAULT 'auto',"
                " created_at TEXT NOT NULL,"
                " PRIMARY KEY (album_key, disc_no, track_no))"
            )
            # 앨범 캐시의 수록곡 JSON에도 디스크 번호가 없으므로 함께 비운다
            # (다음에 앨범을 열 때 외부에서 다시 받아 채운다).
            conn.execute("DELETE FROM album_cache")
        logger.info("앨범 자동 매핑 캐시를 디스크 번호 포함 스키마로 재생성했다")

    def _migrate_album_links_reverify(self) -> None:
        """저장된 자동 매핑을 새 검증 규칙으로 한 번 다시 판정해 틀린 것만 비운다.

        예전 규칙은 가수를 **점수 가산 요소로만** 써서, 제목만 같으면 남의 곡이 그대로
        붙었다(Mr.Children 'HOME'의 "Wake Me Up!"에 Avicii, "Piano Man"에 Billy Joel).
        규칙을 고쳐도 **이미 저장된 잘못된 연결은 그대로 남아** 사용자 눈에는 아무것도
        달라지지 않으므로, 가수가 맞지 않는 자동 매핑만 골라 비운다 — 앨범을 열면 새
        규칙으로 다시 찾고, 이번엔 근거가 없으면 '없음'으로 남는다.

        **전부 비우지는 않는다.** 실측한 라이브러리에서 잘못된 매핑은 45건 중 3건뿐이었고,
        나머지를 함께 버리면 앨범을 열 때마다 곡마다 yt-dlp 검색이 다시 돈다. 저장된
        행에 이미 스트림 제목·채널이 있고 앨범 키의 앞부분이 정규화된 가수명이라,
        **네트워크 없이 그 자리에서 새 규칙으로 다시 판정**할 수 있다.

        **사용자가 지운(rejected) 행은 손대지 않는다.** 그건 캐시가 아니라 '이건 아니다'라는
        사용자의 판단이라, 지우면 그 자리가 자동 채우기 대상으로 되살아난다.
        """
        from domain.song.album import album_key_artist, link_artist_matches  # noqa: PLC0415

        with self.connection() as conn:
            rows = conn.execute(
                "SELECT album_key, disc_no, track_no, stream_title, stream_channel"
                " FROM album_track_links WHERE origin = 'auto'"
            ).fetchall()
            stale = [
                (r[0], r[1], r[2])
                for r in rows
                if not link_artist_matches(
                    album_key_artist(str(r[0])), r[3] or "", r[4] or ""
                )
            ]
            for key in stale:
                conn.execute(
                    "DELETE FROM album_track_links"
                    " WHERE album_key=? AND disc_no=? AND track_no=?",
                    key,
                )
        if stale:
            logger.info(
                "가수가 맞지 않는 앨범 자동 매핑 %d/%d건을 비웠다(새 검증 규칙으로 재조회)",
                len(stale), len(rows),
            )

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

    def _migrate_media_paths_relative(self) -> None:
        """미디어/썸네일 경로를 DATA_DIR 기준 상대경로로 정규화한다 (머신 간 이식성).

        대상: download_history.file_path, clips.file_path, clips.thumbnail_path.
        (videos.thumbnail_path는 이미 THUMBNAIL_DIR 기준 상대경로라 제외.)
        DATA_DIR 밖이거나 빈 값·이미 상대경로면 그대로 둔다 → idempotent.
        """
        from config.settings import to_portable_path  # noqa: PLC0415

        targets = [
            ("download_history", ("file_path",)),
            ("clips", ("file_path", "thumbnail_path")),
        ]
        with self.connection() as conn:
            for table, cols in targets:
                col_list = ", ".join(cols)
                rows = conn.execute(f"SELECT id, {col_list} FROM {table}").fetchall()
                for row in rows:
                    updates = {}
                    for col in cols:
                        old = row[col] or ""
                        new = to_portable_path(old)
                        if new != old:
                            updates[col] = new
                    if updates:
                        set_clause = ", ".join(f"{c}=?" for c in updates)
                        conn.execute(
                            f"UPDATE {table} SET {set_clause} WHERE id=?",
                            (*updates.values(), row["id"]),
                        )
            logger.info("미디어 경로 상대경로화 마이그레이션 완료")

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
