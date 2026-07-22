from __future__ import annotations

from datetime import datetime
from uuid import UUID

from config.settings import resolve_media_path, to_portable_path
from domain.clip.aggregates import ClipAggregate
from domain.clip.entities import Clip
from domain.clip.repositories import IClipRepository
from domain.clip.value_objects import TimeRange
from infrastructure.persistence.database import Database


class SqliteClipRepository(IClipRepository):
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, aggregate: ClipAggregate) -> None:
        c = aggregate.clip
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO clips
                    (id, source_video_id, title, file_path, thumbnail_path,
                     start_sec, end_sec, created_at)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    file_path=excluded.file_path,
                    thumbnail_path=excluded.thumbnail_path
                """,
                (
                    str(c.id), str(c.source_video_id), c.title,
                    to_portable_path(c.file_path), to_portable_path(c.thumbnail_path),
                    c.time_range.start_sec, c.time_range.end_sec,
                    c.created_at.isoformat(),
                ),
            )

    def get_by_id(self, clip_id: UUID) -> ClipAggregate | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM clips WHERE id=?", (str(clip_id),)
            ).fetchone()
        if row is None:
            return None
        return ClipAggregate(self._row_to_clip(row))

    def list_by_video(self, source_video_id: UUID) -> list[ClipAggregate]:
        results: list[ClipAggregate] = []
        with self._db.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM clips WHERE source_video_id=? ORDER BY start_sec",
                (str(source_video_id),),
            )
            for row in cursor:
                results.append(ClipAggregate(self._row_to_clip(row)))
        return results

    def delete(self, clip_id: UUID) -> None:
        with self._db.connection() as conn:
            conn.execute("DELETE FROM clips WHERE id=?", (str(clip_id),))

    @staticmethod
    def _row_to_clip(row) -> Clip:
        return Clip(
            id=UUID(row["id"]),
            source_video_id=UUID(row["source_video_id"]),
            title=row["title"],
            file_path=resolve_media_path(row["file_path"] or ""),
            thumbnail_path=resolve_media_path(row["thumbnail_path"] or ""),
            time_range=TimeRange(row["start_sec"], row["end_sec"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )
