from __future__ import annotations

from datetime import datetime
from uuid import UUID

from domain.library.aggregates import VideoAggregate
from domain.library.entities import Category, Tag, Video
from domain.library.repositories import IVideoRepository, SearchQuery
from domain.library.value_objects import ChannelInfo, Duration, VideoUrl, normalize_video_url
from infrastructure.persistence.database import Database


def _sanitize_fts_query(text: str) -> str:
    """사용자 검색어를 FTS5 안전 형태로 변환.

    각 공백 토큰을 큰따옴표로 감싼 구문(phrase)으로 만들어 결합한다. 이렇게 하면
    ``-``·``(``·``*`` 등 FTS5 연산자 문자가 리터럴로 처리돼 ``fts5: syntax error``가
    발생하지 않는다. 토큰 내부의 ``"``는 ``""``로 이스케이프한다. 결과가 비면
    빈 문자열을 반환하며, 호출부는 이 경우 MATCH 절을 생략해 전체 목록을 반환한다.
    """
    tokens = text.split()
    quoted = [f'"{t.replace(chr(34), chr(34) * 2)}"' for t in tokens if t]
    return " ".join(quoted)


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
            rows = conn.execute(sql, params).fetchall()  # page size = 50, acceptable
            if not rows:
                return results
            video_ids = [row["id"] for row in rows]
            # Bulk-load tags for all result videos in a single query
            placeholders = ",".join("?" * len(video_ids))
            tag_rows = conn.execute(
                f"SELECT video_id, tag_id FROM video_tags WHERE video_id IN ({placeholders})",
                video_ids,
            ).fetchall()
            tag_map: dict[str, list[UUID]] = {}
            for tr in tag_rows:
                tag_map.setdefault(tr["video_id"], []).append(UUID(tr["tag_id"]))
            for row in rows:
                video = _row_to_video(row)
                cat_id = UUID(row["category_id"]) if row["category_id"] else None
                results.append(VideoAggregate(video, category_id=cat_id, tag_ids=tag_map.get(row["id"], [])))
        return results

    def count(self, query: SearchQuery) -> int:
        sql, params = self._build_search_sql(query, count_only=True)
        with self._db.connection() as conn:
            row = conn.execute(sql, params).fetchone()
            return row[0] if row else 0

    def delete(self, video_id: UUID) -> None:
        vid = str(video_id)
        with self._db.connection() as conn:
            # CASCADE 삭제 전에 이 영상이 속한 재생목록의 item_count를 먼저 감소
            conn.execute(
                """UPDATE playlists
                   SET item_count = MAX(0, item_count - 1)
                   WHERE id IN (
                       SELECT playlist_id FROM playlist_items WHERE video_id = ?
                   )""",
                (vid,),
            )
            conn.execute("DELETE FROM videos WHERE id=?", (vid,))

    def exists_by_url(self, url: str) -> bool:
        url = normalize_video_url(url)
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM videos WHERE url=?", (url,)
            ).fetchone()
            return row is not None

    def get_by_url(self, url: str) -> VideoAggregate | None:
        url = normalize_video_url(url)
        with self._db.connection() as conn:
            row = conn.execute("SELECT * FROM videos WHERE url=?", (url,)).fetchone()
            if row is None:
                return None
            video = _row_to_video(row)
            desc_row = conn.execute(
                "SELECT description FROM video_descriptions WHERE video_id=?",
                (row["id"],),
            ).fetchone()
            if desc_row:
                video.description = desc_row["description"]
            tag_rows = conn.execute(
                "SELECT tag_id FROM video_tags WHERE video_id=?", (row["id"],)
            ).fetchall()
            tag_ids = [UUID(r["tag_id"]) for r in tag_rows]
            cat_id = UUID(row["category_id"]) if row["category_id"] else None
            return VideoAggregate(video, category_id=cat_id, tag_ids=tag_ids)

    # ------------------------------------------------------------------
    # Categories
    # ------------------------------------------------------------------

    def list_categories(self) -> list[Category]:
        with self._db.connection() as conn:
            rows = conn.execute("SELECT id, name, parent_id FROM categories ORDER BY name").fetchall()
        return [
            Category(
                id=UUID(r["id"]),
                name=r["name"],
                parent_id=UUID(r["parent_id"]) if r["parent_id"] else None,
            )
            for r in rows
        ]

    def list_category_video_counts(self) -> dict[UUID, int]:
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT category_id, COUNT(*) AS cnt FROM videos WHERE category_id IS NOT NULL GROUP BY category_id"
            ).fetchall()
        return {UUID(r["category_id"]): r["cnt"] for r in rows}

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

    def list_tags_with_counts(self) -> list[tuple[Tag, int]]:
        with self._db.connection() as conn:
            rows = conn.execute(
                """
                SELECT t.id, t.name, COUNT(vt.video_id) AS cnt
                FROM tags t
                LEFT JOIN video_tags vt ON vt.tag_id = t.id
                GROUP BY t.id
                ORDER BY t.name
                """
            ).fetchall()
        return [(Tag(id=UUID(r["id"]), name=r["name"]), r["cnt"]) for r in rows]

    def save_tag(self, tag: Tag) -> None:
        with self._db.connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO tags(id, name) VALUES (?,?)",
                (str(tag.id), tag.name),
            )

    def delete_tag(self, tag_id: UUID) -> None:
        with self._db.connection() as conn:
            # video_tags rows cascade automatically (ON DELETE CASCADE)
            conn.execute("DELETE FROM tags WHERE id=?", (str(tag_id),))

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

    def delete_zero_count_tags(self) -> int:
        with self._db.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM video_tags)"
            )
            return cursor.rowcount

    # ------------------------------------------------------------------
    # Category video order
    # ------------------------------------------------------------------

    def get_category_video_order(self, category_id: UUID) -> list[UUID]:
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT video_id FROM category_video_order "
                "WHERE category_id=? ORDER BY position",
                (str(category_id),),
            ).fetchall()
        return [UUID(r["video_id"]) for r in rows]

    def set_category_video_order(self, category_id: UUID, video_ids: list[UUID]) -> None:
        cid = str(category_id)
        with self._db.connection() as conn:
            conn.execute("DELETE FROM category_video_order WHERE category_id=?", (cid,))
            conn.executemany(
                "INSERT INTO category_video_order (category_id, video_id, position) VALUES (?,?,?)",
                [(cid, str(vid), pos) for pos, vid in enumerate(video_ids)],
            )

    def get_library_stats(self) -> dict:
        """통계 집계: total, watched, favorite, duration, category counts."""
        with self._db.connection() as conn:
            row = conn.execute(
                """SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN watched=1 THEN 1 ELSE 0 END) as watched,
                    SUM(CASE WHEN favorite=1 THEN 1 ELSE 0 END) as favorite,
                    COALESCE(SUM(duration_sec), 0) as total_dur
                FROM videos"""
            ).fetchone()
            cat_rows = conn.execute(
                """SELECT COALESCE(c.name, '미분류') as name, COUNT(v.id) as cnt
                FROM categories c
                LEFT JOIN videos v ON v.category_id = c.id
                GROUP BY c.id
                ORDER BY cnt DESC LIMIT 15"""
            ).fetchall()
        return {
            "total_videos": row["total"] or 0,
            "watched_count": row["watched"] or 0,
            "favorite_count": row["favorite"] or 0,
            "total_duration_sec": row["total_dur"] or 0,
            "category_stats": [(r["name"], r["cnt"]) for r in cat_rows],
        }

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
            fts_expr = _sanitize_fts_query(query.text)
            if fts_expr:
                joins.append(
                    "JOIN videos_fts ON videos_fts.rowid = videos.rowid"
                )
                where.append("videos_fts MATCH ?")
                params.append(fts_expr)

        if query.category_ids:
            placeholders = ",".join("?" * len(query.category_ids))
            where.append(f"videos.category_id IN ({placeholders})")
            params.extend(str(cid) for cid in query.category_ids)
        elif query.category_id:
            where.append("videos.category_id = ?")
            params.append(str(query.category_id))
        elif query.categorized_only:
            # "로컬" 루트 — 카테고리에 속한 영상 전체(미분류·재생목록 전용 제외)
            where.append("videos.category_id IS NOT NULL")

        if query.tag_ids:
            placeholders = ",".join("?" * len(query.tag_ids))
            joins.append(
                "JOIN video_tags ON video_tags.video_id = videos.id"
            )
            where.append(f"video_tags.tag_id IN ({placeholders})")
            params.extend(str(t) for t in query.tag_ids)

        if query.video_ids:
            placeholders = ",".join("?" * len(query.video_ids))
            where.append(f"videos.id IN ({placeholders})")
            params.extend(str(vid) for vid in query.video_ids)

        if query.favorite_only:
            where.append("videos.favorite = 1")

        if query.watched is not None:
            where.append("videos.watched = ?")
            params.append(int(query.watched))

        if query.min_duration_sec is not None:
            where.append("videos.duration_sec >= ?")
            params.append(query.min_duration_sec)

        if query.max_duration_sec is not None:
            where.append("videos.duration_sec <= ?")
            params.append(query.max_duration_sec)

        where_clause = ("WHERE " + " AND ".join(where)) if where else ""
        join_clause = " ".join(joins)

        # SQL 인젝션 방지: 허용된 컬럼명만 사용
        from domain.library.repositories import _ALLOWED_SORT_COLUMNS  # noqa: PLC0415
        sort_col = query.sort_by if query.sort_by in _ALLOWED_SORT_COLUMNS else "created_at"
        sort_dir = "ASC" if query.sort_asc else "DESC"

        if count_only:
            sql = f"SELECT COUNT(DISTINCT videos.id) FROM videos {join_clause} {where_clause}"
        else:
            sql = (
                f"SELECT DISTINCT videos.* FROM videos {join_clause} {where_clause} "
                f"ORDER BY videos.{sort_col} {sort_dir} "
                f"LIMIT ? OFFSET ?"
            )
            params.extend([query.limit, query.offset])

        return sql, params
