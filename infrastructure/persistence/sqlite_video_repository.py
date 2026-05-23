from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from domain.library.aggregates import VideoAggregate
from domain.library.entities import Category, Tag, Video
from domain.library.repositories import IVideoRepository, SearchQuery
from domain.library.value_objects import ChannelInfo, Duration, VideoUrl
from infrastructure.persistence.database import Database


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s)


def _fmt_dt(dt: datetime) -> str:
    return dt.isoformat()


def _row_to_video(row) -> Video:
    channel = None
    if row["channel_id"]:
        channel = ChannelInfo(
            name=row["channel_name"] or "",
            url=row["channel_url"] or "",
            channel_id=row["channel_id"],
        )
    duration = Duration(row["duration_sec"]) if row["duration_sec"] is not None else None
    return Video(
        id=UUID(row["id"]),
        url=VideoUrl(row["url"]),
        title=row["title"],
        channel=channel,
        duration=duration,
        published_at=_parse_dt(row["published_at"]),
        view_count=row["view_count"],
        favorite=bool(row["favorite"]),
        watched=bool(row["watched"]),
        notes=row["notes"] or "",
        thumbnail_path=row["thumbnail_path"] or "",
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


class SqliteVideoRepository(IVideoRepository):
    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Video CRUD
    # ------------------------------------------------------------------

    def save(self, aggregate: VideoAggregate) -> None:
        v = aggregate.video
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO videos
                    (id, url, title, channel_name, channel_url, channel_id,
                     duration_sec, published_at, view_count, favorite, watched,
                     notes, thumbnail_path, category_id, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    channel_name=excluded.channel_name,
                    channel_url=excluded.channel_url,
                    channel_id=excluded.channel_id,
                    duration_sec=excluded.duration_sec,
                    published_at=excluded.published_at,
                    view_count=excluded.view_count,
                    favorite=excluded.favorite,
                    watched=excluded.watched,
                    notes=excluded.notes,
                    thumbnail_path=excluded.thumbnail_path,
                    category_id=excluded.category_id,
                    updated_at=excluded.updated_at
                """,
                (
                    str(v.id), str(v.url), v.title,
                    v.channel.name if v.channel else None,
                    v.channel.url if v.channel else None,
                    v.channel.channel_id if v.channel else None,
                    v.duration.seconds if v.duration else None,
                    _fmt_dt(v.published_at) if v.published_at else None,
                    v.view_count,
                    int(v.favorite), int(v.watched),
                    v.notes, v.thumbnail_path,
                    str(aggregate.category_id) if aggregate.category_id else None,
                    _fmt_dt(v.created_at), _fmt_dt(v.updated_at),
                ),
            )
            # description stored separately for lazy loading
            if v.description:
                conn.execute(
                    """
                    INSERT INTO video_descriptions(video_id, description)
                    VALUES (?,?)
                    ON CONFLICT(video_id) DO UPDATE SET description=excluded.description
                    """,
                    (str(v.id), v.description),
                )
            # Tags: replace association
            conn.execute("DELETE FROM video_tags WHERE video_id=?", (str(v.id),))
            for tag_id in aggregate.tag_ids:
                conn.execute(
                    "INSERT OR IGNORE INTO video_tags(video_id, tag_id) VALUES (?,?)",
                    (str(v.id), str(tag_id)),
                )

    def get_by_id(self, video_id: UUID) -> VideoAggregate | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM videos WHERE id=?", (str(video_id),)
            ).fetchone()
            if row is None:
                return None
            video = _row_to_video(row)
            # Load description on demand
            desc_row = conn.execute(
                "SELECT description FROM video_descriptions WHERE video_id=?",
                (str(video_id),),
            ).fetchone()
            if desc_row:
                video.description = desc_row["description"]
            tag_rows = conn.execute(
                "SELECT tag_id FROM video_tags WHERE video_id=?", (str(video_id),)
            ).fetchall()
            tag_ids = [UUID(r["tag_id"]) for r in tag_rows]
            cat_id = UUID(row["category_id"]) if row["category_id"] else None
            return VideoAggregate(video, category_id=cat_id, tag_ids=tag_ids)

    def search(self, query: SearchQuery) -> list[VideoAggregate]:
        sql, params = self._build_search_sql(query, count_only=False)
        results: list[VideoAggregate] = []
        with self._db.connection() as conn:
            # Use cursor to avoid fetchall on large tables
            cursor = conn.execute(sql, params)
            for row in cursor:
                video = _row_to_video(row)
                cat_id = UUID(row["category_id"]) if row["category_id"] else None
                results.append(VideoAggregate(video, category_id=cat_id))
        return results

    def count(self, query: SearchQuery) -> int:
        sql, params = self._build_search_sql(query, count_only=True)
        with self._db.connection() as conn:
            row = conn.execute(sql, params).fetchone()
            return row[0] if row else 0

    def delete(self, video_id: UUID) -> None:
        with self._db.connection() as conn:
            conn.execute("DELETE FROM videos WHERE id=?", (str(video_id),))

    def exists_by_url(self, url: str) -> bool:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM videos WHERE url=?", (url,)
            ).fetchone()
            return row is not None

    # ------------------------------------------------------------------
    # Categories
    # ------------------------------------------------------------------

    def list_categories(self) -> list[Category]:
        with self._db.connection() as conn:
            rows = conn.execute("SELECT id, name, parent_id FROM categories").fetchall()
        return [
            Category(
                id=UUID(r["id"]),
                name=r["name"],
                parent_id=UUID(r["parent_id"]) if r["parent_id"] else None,
            )
            for r in rows
        ]

    def save_category(self, category: Category) -> None:
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO categories(id, name, parent_id) VALUES (?,?,?)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name, parent_id=excluded.parent_id
                """,
                (
                    str(category.id),
                    category.name,
                    str(category.parent_id) if category.parent_id else None,
                ),
            )

    def delete_category(self, category_id: UUID) -> None:
        with self._db.connection() as conn:
            conn.execute("DELETE FROM categories WHERE id=?", (str(category_id),))

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------

    def list_tags(self) -> list[Tag]:
        with self._db.connection() as conn:
            rows = conn.execute("SELECT id, name FROM tags").fetchall()
        return [Tag(id=UUID(r["id"]), name=r["name"]) for r in rows]

    def save_tag(self, tag: Tag) -> None:
        with self._db.connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO tags(id, name) VALUES (?,?)",
                (str(tag.id), tag.name),
            )

    def get_or_create_tag(self, name: str) -> Tag:
        name = name.lower().strip()
        with self._db.connection() as conn:
            row = conn.execute("SELECT id, name FROM tags WHERE name=?", (name,)).fetchone()
            if row:
                return Tag(id=UUID(row["id"]), name=row["name"])
            tag = Tag.create(name)
            conn.execute(
                "INSERT INTO tags(id, name) VALUES (?,?)", (str(tag.id), tag.name)
            )
        return tag

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_search_sql(
        self, query: SearchQuery, count_only: bool
    ) -> tuple[str, list]:
        params: list = []
        joins: list[str] = []
        where: list[str] = []

        if query.text:
            joins.append(
                "JOIN videos_fts ON videos_fts.rowid = videos.rowid"
            )
            where.append("videos_fts MATCH ?")
            params.append(query.text)

        if query.category_id:
            where.append("videos.category_id = ?")
            params.append(str(query.category_id))

        if query.tag_ids:
            placeholders = ",".join("?" * len(query.tag_ids))
            joins.append(
                f"JOIN video_tags ON video_tags.video_id = videos.id"
            )
            where.append(f"video_tags.tag_id IN ({placeholders})")
            params.extend(str(t) for t in query.tag_ids)

        if query.favorite_only:
            where.append("videos.favorite = 1")

        if query.watched is not None:
            where.append("videos.watched = ?")
            params.append(int(query.watched))

        where_clause = ("WHERE " + " AND ".join(where)) if where else ""
        join_clause = " ".join(joins)

        if count_only:
            sql = f"SELECT COUNT(*) FROM videos {join_clause} {where_clause}"
        else:
            sql = (
                f"SELECT videos.* FROM videos {join_clause} {where_clause} "
                f"ORDER BY videos.created_at DESC "
                f"LIMIT ? OFFSET ?"
            )
            params.extend([query.limit, query.offset])

        return sql, params
