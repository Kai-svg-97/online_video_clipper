from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from domain.song.aggregates import SongInfoAggregate
from domain.song.entities import LyricsSource, SongInfo
from domain.song.repositories import ISongRepository
from domain.song.value_objects import LyricsLine, SongSourceRef
from infrastructure.persistence.database import Database

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lyrics_to_json(lines: list[LyricsLine]) -> str:
    return json.dumps(
        [{"o": ln.original, "t": ln.translation} for ln in lines],
        ensure_ascii=False,
    )


def _lyrics_from_json(raw: str | None) -> list[LyricsLine]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        logger.debug("가사 JSON 파싱 실패 — 빈 목록 사용")
        return []
    out: list[LyricsLine] = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict):
            out.append(LyricsLine(original=item.get("o", ""), translation=item.get("t", "")))
    return out


def _row_to_aggregate(row) -> SongInfoAggregate:
    source = None
    if row["source_name"]:
        source = SongSourceRef(name=row["source_name"], url=row["source_url"] or "")
    try:
        manual = frozenset(json.loads(row["manual_fields"] or "[]"))
    except (ValueError, TypeError):
        manual = frozenset()
    info = SongInfo(
        video_id=UUID(row["video_id"]),
        is_song=bool(row["is_song"]),
        artist=row["artist"] or "",
        album=row["album"] or "",
        song_title=row["song_title"] or "",
        release_year=row["release_year"] or "",
        lyrics_lines=_lyrics_from_json(row["lyrics_json"]),
        lyrics_language=row["lyrics_language"] or "",
        source=source,
        manual_fields=manual,
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
    return SongInfoAggregate(info)


class SqliteSongRepository(ISongRepository):
    def __init__(self, db: Database) -> None:
        self._db = db

    # ── SongInfo ──────────────────────────────────────────────────
    def get(self, video_id: UUID) -> SongInfoAggregate | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM song_info WHERE video_id=?", (str(video_id),)
            ).fetchone()
        return _row_to_aggregate(row) if row else None

    def save(self, aggregate: SongInfoAggregate) -> None:
        info = aggregate.info
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO song_info
                    (video_id, is_song, artist, album, song_title, release_year,
                     lyrics_json, lyrics_language, source_name, source_url,
                     manual_fields, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(video_id) DO UPDATE SET
                    is_song=excluded.is_song,
                    artist=excluded.artist,
                    album=excluded.album,
                    song_title=excluded.song_title,
                    release_year=excluded.release_year,
                    lyrics_json=excluded.lyrics_json,
                    lyrics_language=excluded.lyrics_language,
                    source_name=excluded.source_name,
                    source_url=excluded.source_url,
                    manual_fields=excluded.manual_fields,
                    updated_at=excluded.updated_at
                """,
                (
                    str(info.video_id),
                    int(info.is_song),
                    info.artist,
                    info.album,
                    info.song_title,
                    info.release_year,
                    _lyrics_to_json(info.lyrics_lines),
                    info.lyrics_language,
                    info.source.name if info.source else "",
                    info.source.url if info.source else "",
                    json.dumps(sorted(info.manual_fields)),
                    _now_iso(),
                ),
            )

    def delete(self, video_id: UUID) -> None:
        with self._db.connection() as conn:
            conn.execute("DELETE FROM song_info WHERE video_id=?", (str(video_id),))

    # ── 가사 출처 레지스트리 ────────────────────────────────────────
    def list_lyrics_sources(self) -> list[LyricsSource]:
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM lyrics_sources ORDER BY priority, name"
            ).fetchall()
        return [
            LyricsSource(
                id=UUID(r["id"]),
                name=r["name"],
                provider_key=r["provider_key"],
                base_url=r["base_url"] or "",
                enabled=bool(r["enabled"]),
                priority=r["priority"],
            )
            for r in rows
        ]

    def save_lyrics_source(self, source: LyricsSource) -> None:
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO lyrics_sources
                    (id, name, provider_key, base_url, enabled, priority)
                VALUES (?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    provider_key=excluded.provider_key,
                    base_url=excluded.base_url,
                    enabled=excluded.enabled,
                    priority=excluded.priority
                """,
                (
                    str(source.id),
                    source.name,
                    source.provider_key,
                    source.base_url,
                    int(source.enabled),
                    source.priority,
                ),
            )

    def delete_lyrics_source(self, source_id: UUID) -> None:
        with self._db.connection() as conn:
            conn.execute("DELETE FROM lyrics_sources WHERE id=?", (str(source_id),))

    def set_lyrics_sources_order(self, ordered_ids: list[UUID]) -> None:
        with self._db.connection() as conn:
            for pos, sid in enumerate(ordered_ids):
                conn.execute(
                    "UPDATE lyrics_sources SET priority=? WHERE id=?",
                    ((pos + 1) * 10, str(sid)),
                )
