from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from domain.song.aggregates import SongInfoAggregate
from domain.song.entities import LyricsSource, SongInfo
from domain.song.repositories import ISongRepository, SongFields
from domain.song.value_objects import LyricsLine, SongSourceRef
from infrastructure.persistence.database import Database

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lyrics_to_json(lines: list[LyricsLine]) -> str:
    """가사를 JSON으로 직렬화한다.

    ``"s"``(시작ms)는 값이 있을 때만 넣는다 — 타이밍 없는 가사에 null을 잔뜩 남기지
    않고, 검색 프리필터(lyrics_json LIKE)의 오탐 여지도 줄인다.
    """
    out = []
    for ln in lines:
        item = {"o": ln.original, "t": ln.translation}
        if ln.start_ms is not None:
            item["s"] = int(ln.start_ms)
        out.append(item)
    return json.dumps(out, ensure_ascii=False)


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
        if not isinstance(item, dict):
            continue
        raw_start = item.get("s")
        # "s"가 없거나(구 데이터) 정수가 아니면 시간 정보 없음으로 취급한다.
        start_ms = int(raw_start) if isinstance(raw_start, (int, float)) else None
        out.append(
            LyricsLine(
                original=item.get("o", ""),
                translation=item.get("t", ""),
                start_ms=start_ms,
            )
        )
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
        lyrics_offset_ms=int(row["lyrics_offset_ms"] or 0),
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
                     lyrics_json, lyrics_language, lyrics_offset_ms, source_name, source_url,
                     manual_fields, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(video_id) DO UPDATE SET
                    is_song=excluded.is_song,
                    artist=excluded.artist,
                    album=excluded.album,
                    song_title=excluded.song_title,
                    release_year=excluded.release_year,
                    lyrics_json=excluded.lyrics_json,
                    lyrics_language=excluded.lyrics_language,
                    lyrics_offset_ms=excluded.lyrics_offset_ms,
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
                    info.lyrics_offset_ms,
                    info.source.name if info.source else "",
                    info.source.url if info.source else "",
                    json.dumps(sorted(info.manual_fields)),
                    _now_iso(),
                ),
            )

    def delete(self, video_id: UUID) -> None:
        with self._db.connection() as conn:
            conn.execute("DELETE FROM song_info WHERE video_id=?", (str(video_id),))

    def find_video_ids_by(
        self, *, artist: str | None = None, album: str | None = None
    ) -> list[UUID]:
        conds = ["is_song=1"]
        params: list = []
        if artist:
            conds.append("artist=?")
            params.append(artist)
        if album:
            conds.append("album=?")
            params.append(album)
        if len(conds) == 1:   # artist·album 모두 미지정 — 매칭 없음
            return []
        sql = f"SELECT video_id FROM song_info WHERE {' AND '.join(conds)}"
        with self._db.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [UUID(r["video_id"]) for r in rows]

    def list_song_fields(self, video_ids: list[UUID]) -> dict[UUID, SongFields]:
        """앨범 그루핑용 노래 정보 일괄 조회 — 가사(JSON)는 읽지 않는다."""
        if not video_ids:
            return {}
        ids = [str(v) for v in video_ids]
        out: dict[UUID, SongFields] = {}
        with self._db.connection() as conn:
            # SQLite 변수 상한(기본 999)을 넘지 않게 나눠 조회한다.
            for i in range(0, len(ids), 400):
                chunk = ids[i:i + 400]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    "SELECT video_id, is_song, artist, album, song_title FROM song_info"
                    f" WHERE video_id IN ({placeholders})",  # noqa: S608
                    chunk,
                ).fetchall()
                for r in rows:
                    out[UUID(r["video_id"])] = SongFields(
                        is_song=bool(r["is_song"]),
                        artist=r["artist"] or "",
                        album=r["album"] or "",
                        song_title=r["song_title"] or "",
                    )
        return out

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
