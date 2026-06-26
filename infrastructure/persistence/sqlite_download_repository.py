from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

from domain.download.entities import DownloadJob, JobStatus
from domain.download.repositories import IDownloadRepository
from domain.download.value_objects import DownloadSettings, MediaFormat, Quality
from infrastructure.persistence.database import Database


class SqliteDownloadRepository(IDownloadRepository):
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, job: DownloadJob) -> None:
        s = job.settings
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO download_history
                    (id, url, title, quality, format, subtitle_langs,
                     include_thumbnail, include_metadata,
                     status, file_path, error_msg, retry_count,
                     created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    file_path=excluded.file_path,
                    error_msg=excluded.error_msg,
                    retry_count=excluded.retry_count,
                    updated_at=excluded.updated_at
                """,
                (
                    str(job.id), job.url, job.title,
                    s.quality.value, s.format.value,
                    json.dumps(list(s.subtitle_langs)),
                    int(s.include_thumbnail), int(s.include_metadata),
                    job.status.value, job.file_path, job.error_msg,
                    job.retry_count,
                    job.created_at.isoformat(), job.updated_at.isoformat(),
                ),
            )

    def get_by_id(self, job_id: UUID) -> DownloadJob | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM download_history WHERE id=?", (str(job_id),)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_job(row)

    def get_history(self, limit: int = 50, offset: int = 0) -> list[DownloadJob]:
        jobs: list[DownloadJob] = []
        with self._db.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM download_history ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
            for row in cursor:
                jobs.append(self._row_to_job(row))
        return jobs

    def count_history(self) -> int:
        with self._db.connection() as conn:
            row = conn.execute("SELECT COUNT(*) FROM download_history").fetchone()
            return row[0] if row else 0

    def delete(self, job_id: UUID) -> None:
        with self._db.connection() as conn:
            conn.execute("DELETE FROM download_history WHERE id=?", (str(job_id),))

    def find_completed_by_url(self, url: str) -> list[DownloadJob]:
        jobs: list[DownloadJob] = []
        with self._db.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM download_history WHERE url=? AND status='completed' ORDER BY created_at DESC",
                (url,),
            )
            for row in cursor:
                jobs.append(self._row_to_job(row))
        return jobs

    def find_failed_by_url(self, url: str) -> list[DownloadJob]:
        jobs: list[DownloadJob] = []
        with self._db.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM download_history WHERE url=? AND status='failed'"
                " ORDER BY created_at DESC",
                (url,),
            )
            for row in cursor:
                jobs.append(self._row_to_job(row))
        return jobs

    def delete_completed_duplicates(
        self, url: str, quality: str, fmt: str, keep_job_id: UUID
    ) -> None:
        """Delete older completed records with the same url+quality+format and their files."""
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, file_path FROM download_history
                WHERE url=? AND quality=? AND format=? AND status='completed' AND id!=?
                """,
                (url, quality, fmt, str(keep_job_id)),
            ).fetchall()
            for row in rows:
                fp = row["file_path"]
                if fp:
                    try:
                        Path(fp).unlink(missing_ok=True)
                    except OSError:
                        pass
                conn.execute("DELETE FROM download_history WHERE id=?", (row["id"],))

    @staticmethod
    def _row_to_job(row) -> DownloadJob:
        settings = DownloadSettings(
            quality=Quality(row["quality"]),
            fmt=MediaFormat(row["format"]),
            subtitle_langs=tuple(json.loads(row["subtitle_langs"] or "[]")),
            include_thumbnail=bool(row["include_thumbnail"]),
            include_metadata=bool(row["include_metadata"]),
        )
        return DownloadJob(
            id=UUID(row["id"]),
            url=row["url"],
            title=row["title"],
            settings=settings,
            status=JobStatus(row["status"]),
            progress=__import__(
                "domain.download.value_objects", fromlist=["DownloadProgress"]
            ).DownloadProgress(),
            file_path=row["file_path"] or "",
            error_msg=row["error_msg"] or "",
            retry_count=row["retry_count"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
