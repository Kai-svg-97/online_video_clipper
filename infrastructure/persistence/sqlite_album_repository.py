"""앨범 캐시/자동 매핑 SQLite 저장소 (IAlbumRepository 구현).

전부 파생 캐시라 동기화 캡처 대상이 아니다(Recording* 데코레이터로 감싸지 않는다).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import UUID

from domain.song.album_repository import (
    TRACK_LINK_REJECTED,
    AlbumCacheRecord,
    AlbumTrackLink,
    IAlbumRepository,
)
from domain.song.ports import AlbumTrackInfo
from infrastructure.persistence.database import Database

logger = logging.getLogger(__name__)

# IN (?) 바인딩 상한을 넘지 않도록 나눠 조회한다(SQLite 기본 변수 상한 999).
_CHUNK = 400


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tracks_to_json(tracks: list[AlbumTrackInfo]) -> str:
    return json.dumps(
        [
            {"n": t.track_no, "t": t.title, "a": t.artist, "d": t.duration_sec,
             "c": t.disc_no}
            for t in tracks
        ],
        ensure_ascii=False,
    )


def _tracks_from_json(raw: str | None) -> list[AlbumTrackInfo]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        logger.debug("앨범 수록곡 JSON 파싱 실패 — 빈 목록 사용")
        return []
    out: list[AlbumTrackInfo] = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        out.append(
            AlbumTrackInfo(
                track_no=int(item.get("n") or 0),
                title=item.get("t", ""),
                artist=item.get("a", ""),
                duration_sec=item.get("d"),
                disc_no=int(item.get("c") or 1),
            )
        )
    return out


def _row_to_record(row) -> AlbumCacheRecord:
    return AlbumCacheRecord(
        album_key=row["album_key"],
        album_title=row["album_title"],
        artist=row["artist"],
        artwork_url=row["artwork_url"],
        artwork_path=row["artwork_path"],
        description=row["description"],
        release_date=row["release_date"],
        genre=row["genre"],
        copyright=row["copyright"],
        track_count=row["track_count"],
        tracks=_tracks_from_json(row["tracks_json"]),
        source_name=row["source_name"],
        source_url=row["source_url"],
        fetched_at=row["fetched_at"],
    )


class SqliteAlbumRepository(IAlbumRepository):
    def __init__(self, db: Database) -> None:
        self._db = db

    # ── 앨범 캐시 ──────────────────────────────────────────────────
    def get_album(self, album_key: str) -> AlbumCacheRecord | None:
        if not album_key:
            return None
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM album_cache WHERE album_key=?", (album_key,)
            ).fetchone()
        return _row_to_record(row) if row else None

    def save_album(self, record: AlbumCacheRecord) -> None:
        if not record.album_key:
            return
        with self._db.connection() as conn:
            conn.execute(
                "INSERT INTO album_cache(album_key, album_title, artist, artwork_url,"
                " artwork_path, description, release_date, genre, copyright, track_count,"
                " tracks_json, source_name, source_url, fetched_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(album_key) DO UPDATE SET"
                "  album_title=excluded.album_title, artist=excluded.artist,"
                "  artwork_url=excluded.artwork_url, artwork_path=excluded.artwork_path,"
                "  description=excluded.description, release_date=excluded.release_date,"
                "  genre=excluded.genre, copyright=excluded.copyright,"
                "  track_count=excluded.track_count, tracks_json=excluded.tracks_json,"
                "  source_name=excluded.source_name, source_url=excluded.source_url,"
                "  fetched_at=excluded.fetched_at",
                (
                    record.album_key, record.album_title, record.artist,
                    record.artwork_url, record.artwork_path, record.description,
                    record.release_date, record.genre, record.copyright,
                    int(record.track_count), _tracks_to_json(record.tracks),
                    record.source_name, record.source_url, record.fetched_at or _now_iso(),
                ),
            )

    def list_albums(self, album_keys: list[str]) -> dict[str, AlbumCacheRecord]:
        keys = [k for k in album_keys if k]
        if not keys:
            return {}
        out: dict[str, AlbumCacheRecord] = {}
        with self._db.connection() as conn:
            for i in range(0, len(keys), _CHUNK):
                chunk = keys[i:i + _CHUNK]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"SELECT * FROM album_cache WHERE album_key IN ({placeholders})",  # noqa: S608
                    chunk,
                ).fetchall()
                for row in rows:
                    out[row["album_key"]] = _row_to_record(row)
        return out

    # ── 자동 매핑(스트리밍 영상) ────────────────────────────────────
    def get_track_links(self, album_key: str) -> dict[tuple[int, int], AlbumTrackLink]:
        if not album_key:
            return {}
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM album_track_links WHERE album_key=?"
                " ORDER BY disc_no, track_no",
                (album_key,),
            ).fetchall()
        return {
            (int(r["disc_no"]), int(r["track_no"])): AlbumTrackLink(
                album_key=r["album_key"],
                track_no=int(r["track_no"]),
                disc_no=int(r["disc_no"]),
                track_title=r["track_title"],
                stream_url=r["stream_url"],
                stream_title=r["stream_title"],
                stream_channel=r["stream_channel"],
                stream_yt_id=r["stream_yt_id"],
                duration_sec=r["duration_sec"],
                origin=r["origin"],
            )
            for r in rows
        }

    def save_track_link(self, link: AlbumTrackLink) -> None:
        if not link.album_key:
            return
        with self._db.connection() as conn:
            conn.execute(
                "INSERT INTO album_track_links(album_key, disc_no, track_no, track_title,"
                " stream_url, stream_title, stream_channel, stream_yt_id, duration_sec,"
                " origin, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(album_key, disc_no, track_no) DO UPDATE SET"
                "  track_title=excluded.track_title, stream_url=excluded.stream_url,"
                "  stream_title=excluded.stream_title, stream_channel=excluded.stream_channel,"
                "  stream_yt_id=excluded.stream_yt_id, duration_sec=excluded.duration_sec,"
                "  origin=excluded.origin",
                (
                    link.album_key, int(link.disc_no), int(link.track_no), link.track_title,
                    link.stream_url, link.stream_title, link.stream_channel,
                    link.stream_yt_id, link.duration_sec, link.origin, _now_iso(),
                ),
            )

    def clear_track_links(self, album_key: str) -> None:
        with self._db.connection() as conn:
            conn.execute("DELETE FROM album_track_links WHERE album_key=?", (album_key,))

    def reject_track_link(self, album_key: str, disc_no: int, track_no: int) -> None:
        # 행을 지우지 않고 스트림 정보만 비운 채 origin을 rejected로 남긴다 —
        # 지우면 다음 자동 채우기가 같은 영상을 도로 붙인다(album_repository 설명 참고).
        with self._db.connection() as conn:
            conn.execute(
                "INSERT INTO album_track_links(album_key, disc_no, track_no, track_title,"
                " stream_url, stream_title, stream_channel, stream_yt_id, duration_sec,"
                " origin, created_at)"
                " VALUES (?,?,?,'','','','','',NULL,?,?)"
                " ON CONFLICT(album_key, disc_no, track_no) DO UPDATE SET"
                "  stream_url='', stream_title='', stream_channel='', stream_yt_id='',"
                "  duration_sec=NULL, origin=excluded.origin",
                (album_key, int(disc_no), int(track_no), TRACK_LINK_REJECTED, _now_iso()),
            )

    # ── 앨범 추정 조회 기록 ─────────────────────────────────────────
    def mark_album_lookup(self, video_id: UUID, found: bool) -> None:
        with self._db.connection() as conn:
            conn.execute(
                "INSERT INTO album_lookup_state(video_id, found, tried_at) VALUES (?,?,?)"
                " ON CONFLICT(video_id) DO UPDATE SET found=excluded.found,"
                " tried_at=excluded.tried_at",
                (str(video_id), 1 if found else 0, _now_iso()),
            )

    def filter_unlooked(self, video_ids: list[UUID]) -> list[UUID]:
        if not video_ids:
            return []
        tried: set[str] = set()
        ids = [str(v) for v in video_ids]
        with self._db.connection() as conn:
            for i in range(0, len(ids), _CHUNK):
                chunk = ids[i:i + _CHUNK]
                placeholders = ",".join("?" for _ in chunk)
                rows = conn.execute(
                    f"SELECT video_id FROM album_lookup_state WHERE video_id IN ({placeholders})",  # noqa: S608
                    chunk,
                ).fetchall()
                tried.update(r["video_id"] for r in rows)
        return [v for v in video_ids if str(v) not in tried]
