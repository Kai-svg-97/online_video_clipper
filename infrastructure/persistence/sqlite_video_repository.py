from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from functools import lru_cache
from uuid import UUID

from domain.library.aggregates import VideoAggregate
from domain.library.entities import Category, Tag, Video
from domain.library.repositories import (
    MATCH_FIELD_KEYS,
    MUSIC_ROOT_CATEGORY_NAMES,
    IVideoRepository,
    SearchQuery,
)
from domain.library.value_objects import ChannelInfo, Duration, VideoUrl, normalize_video_url
from infrastructure.persistence.database import Database

logger = logging.getLogger(__name__)


# LIKE 패턴에서 특수 취급되는 문자 — ESCAPE 절과 함께 이스케이프한다.
_LIKE_ESCAPE = "\\"


def _like_pattern(text: str) -> str:
    """부분 일치용 LIKE 패턴을 만든다.

    %·_ 는 LIKE 와일드카드이고 백슬래시는 우리가 지정한 ESCAPE 문자이므로 모두
    이스케이프해야 사용자가 입력한 문자 그대로 찾는다.
    """
    escaped = (
        text.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", _LIKE_ESCAPE + "%")
        .replace("_", _LIKE_ESCAPE + "_")
    )
    return f"%{escaped}%"


def _lyrics_prefilter_safe(text: str) -> bool:
    """가사 원문(lyrics_json)에 LIKE 프리필터를 걸어도 누락이 없는 검색어인지 판정.

    가사는 `[{"o":원문,"t":번역}]` JSON 으로 저장되며 ensure_ascii=False 라 값이
    그대로 들어 있다. 따라서 값에 검색어가 있으면 원문 JSON 에도 반드시 있다 —
    단 아래 경우는 예외라 프리필터를 포기하고 전체 스캔으로 돌아간다.

    - `"`·`\\`·제어문자: JSON 직렬화가 이스케이프해 원문과 글자가 달라진다.
      (줄 사이는 개행으로 이어 붙이므로 개행이 없는 검색어는 한 줄 안에서만 매칭된다.)
    - 대소문자가 있는 비ASCII 문자: SQLite LIKE 는 ASCII 만 대소문자를 무시한다.
    """
    for ch in text:
        if ch in '"\\' or ord(ch) < 0x20:
            return False
        if not ch.isascii() and ch.lower() != ch.upper():
            return False
    return True


@lru_cache(maxsize=256)
def _lyrics_text(lyrics_json: str) -> str:
    """lyrics_json 에서 원문·번역 텍스트만 뽑아 이어붙인다.

    JSON 문자열에 LIKE 를 직접 쓰면 검색어 'o'·'t' 가 키 이름에 걸려 모든 노래를
    오탐한다. 그래서 파싱해 값만 비교한다.

    같은 가사를 검색어마다 다시 파싱하지 않도록 결과를 캐시한다(입력 문자열이
    곧 키라 가사가 바뀌면 자연히 다른 항목이 된다).
    """
    try:
        lines = json.loads(lyrics_json or "[]")
    except (ValueError, TypeError):
        logger.warning("가사 JSON 파싱 실패 — 가사 검색에서 제외한다")
        return ""
    parts: list[str] = []
    for ln in lines:
        if isinstance(ln, dict):
            parts.append(str(ln.get("o", "")))
            parts.append(str(ln.get("t", "")))
    return "\n".join(parts)


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
        gemini_summary=row["gemini_summary"] if "gemini_summary" in row.keys() else "",
        thumbnail_path=row["thumbnail_path"] or "",
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        # 이어보기 — 구버전 DB(마이그레이션 전)에도 뜨도록 키 존재를 확인한다.
        last_position_ms=(
            row["last_position_ms"] if "last_position_ms" in row.keys() else 0
        ) or 0,
        last_played_at=(
            datetime.fromisoformat(row["last_played_at"])
            if "last_played_at" in row.keys() and row["last_played_at"]
            else None
        ),
    )


class SqliteVideoRepository(IVideoRepository):
    def __init__(self, db: Database) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Video CRUD
    # ------------------------------------------------------------------

    def save_playback_position(
        self, video_id: UUID, position_ms: int, played_at: datetime | None = None
    ) -> None:
        """재생 위치만 갱신한다 — 재생 중 몇 초마다 불리므로 가볍게 쓴다.

        아그리게이트 전체를 저장하면 태그 재작성까지 따라와 낭비다. **동기화 캡처
        대상도 아니다**(기기마다 보던 지점이 다르다) — 그래서 `save`를 타지 않는
        전용 경로를 둔다.
        """
        with self._db.connection() as conn:
            conn.execute(
                "UPDATE videos SET last_position_ms=?, last_played_at=? WHERE id=?",
                (
                    max(0, int(position_ms)),
                    _fmt_dt(played_at or datetime.now(timezone.utc)),
                    str(video_id),
                ),
            )

    def save(self, aggregate: VideoAggregate) -> None:
        v = aggregate.video
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO videos
                    (id, url, title, channel_name, channel_url, channel_id,
                     duration_sec, published_at, view_count, favorite, watched,
                     notes, gemini_summary, thumbnail_path, category_id, created_at, updated_at,
                     last_position_ms, last_played_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                    gemini_summary=excluded.gemini_summary,
                    thumbnail_path=excluded.thumbnail_path,
                    category_id=excluded.category_id,
                    updated_at=excluded.updated_at,
                    last_position_ms=excluded.last_position_ms,
                    last_played_at=excluded.last_played_at
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
                    v.notes, v.gemini_summary, v.thumbnail_path,
                    str(aggregate.category_id) if aggregate.category_id else None,
                    _fmt_dt(v.created_at), _fmt_dt(v.updated_at),
                    int(v.last_position_ms or 0),
                    _fmt_dt(v.last_played_at) if v.last_played_at else None,
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

    def list_tags_with_counts(
        self,
        *,
        category_ids: list[UUID] | None = None,
        video_ids: list[UUID] | None = None,
    ) -> list[tuple[Tag, int]]:
        """태그별 사용 횟수를 집계한다.

        스코프 미지정(둘 다 None/빈 리스트) 시 라이브러리 전체를 LEFT JOIN으로
        집계(0회 태그 포함). category_ids/video_ids 지정 시 해당 영상들에 실제로
        달린 태그만 INNER JOIN으로 집계한다(GROUP BY — 전체를 메모리에 올리지 않음).
        """
        if category_ids:
            ph = ",".join("?" * len(category_ids))
            sql = f"""
                SELECT t.id, t.name, COUNT(vt.video_id) AS cnt
                FROM tags t
                JOIN video_tags vt ON vt.tag_id = t.id
                JOIN videos v ON v.id = vt.video_id
                WHERE v.category_id IN ({ph})
                GROUP BY t.id
                ORDER BY t.name
            """
            params: list = [str(c) for c in category_ids]
        elif video_ids:
            ph = ",".join("?" * len(video_ids))
            sql = f"""
                SELECT t.id, t.name, COUNT(vt.video_id) AS cnt
                FROM tags t
                JOIN video_tags vt ON vt.tag_id = t.id
                WHERE vt.video_id IN ({ph})
                GROUP BY t.id
                ORDER BY t.name
            """
            params = [str(v) for v in video_ids]
        else:
            sql = """
                SELECT t.id, t.name, COUNT(vt.video_id) AS cnt
                FROM tags t
                LEFT JOIN video_tags vt ON vt.tag_id = t.id
                GROUP BY t.id
                ORDER BY t.name
            """
            params = []
        with self._db.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
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

    def get_channel_category_stats(self) -> list[tuple[str, str, str, str, int]]:
        """채널별·카테고리별 영상 수 집계.

        (channel_name, channel_url, channel_id, category_id, count) 튜플 목록을 반환한다.
        카테고리가 지정된 영상만 대상으로 하며(경로 표시를 위해),
        category_id는 저장된 UUID 문자열 그대로 넘긴다(상위에서 변환).
        channel_url/channel_id는 같은 채널 그룹에서 비지 않은 값 하나(MAX)를 대표로 쓴다."""
        with self._db.connection() as conn:
            rows = conn.execute(
                """SELECT COALESCE(NULLIF(channel_name, ''), '(채널 없음)') AS channel,
                          COALESCE(MAX(channel_url), '') AS ch_url,
                          COALESCE(MAX(channel_id), '')  AS ch_id,
                          category_id, COUNT(*) AS cnt
                   FROM videos
                   WHERE category_id IS NOT NULL
                   GROUP BY channel, category_id"""
            ).fetchall()
        return [
            (r["channel"], r["ch_url"] or "", r["ch_id"] or "", r["category_id"], r["cnt"])
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Gemini 요약 실패 사유 (상세 화면 안내 문구용)
    # ------------------------------------------------------------------

    def get_summary_status(self, video_id: UUID) -> str:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT status FROM video_summary_status WHERE video_id=?",
                (str(video_id),),
            ).fetchone()
        return row["status"] if row else ""

    def set_summary_status(self, video_id: UUID, status: str) -> None:
        with self._db.connection() as conn:
            conn.execute(
                "INSERT INTO video_summary_status (video_id, status, updated_at) "
                "VALUES (?, ?, ?) ON CONFLICT(video_id) DO UPDATE SET "
                "status=excluded.status, updated_at=excluded.updated_at",
                (str(video_id), status, _fmt_dt(datetime.now())),
            )

    def clear_summary_status(self, video_id: UUID) -> None:
        with self._db.connection() as conn:
            conn.execute(
                "DELETE FROM video_summary_status WHERE video_id=?", (str(video_id),)
            )

    # ------------------------------------------------------------------
    # 검색 일치 속성
    # ------------------------------------------------------------------

    def _music_category_ids(self, conn) -> list[str]:
        """최상위 조상 카테고리 이름이 음악인 카테고리 id 전체(중첩 포함).

        depth 가드는 선택이 아니라 필수다 — categories 에 순환을 막는 제약이
        UNIQUE(name, parent_id) 뿐이라, 데이터가 순환하면 재귀 CTE 가 끝나지 않고
        앱이 멈춘다. 32단계면 실제 카테고리 깊이를 한참 넘는다.
        """
        names = sorted(MUSIC_ROOT_CATEGORY_NAMES)
        ph = ",".join("?" * len(names))
        sql = f"""
            WITH RECURSIVE tree(id, root_name, depth) AS (
                SELECT id, name, 0 FROM categories WHERE parent_id IS NULL
                UNION ALL
                SELECT c.id, t.root_name, t.depth + 1
                  FROM categories c JOIN tree t ON c.parent_id = t.id
                 WHERE t.depth < 32
            )
            SELECT id FROM tree WHERE lower(trim(root_name)) IN ({ph})
        """
        return [r[0] for r in conn.execute(sql, names).fetchall()]

    def _lyrics_match_ids(self, text: str) -> list[str]:
        """가사(원문·번역)에 검색어가 든 video_id 목록을 반환한다.

        최상위 카테고리가 음악인 영상만 대상으로 한다. lyrics_json 에 SQL LIKE 를
        쓰면 검색어 'o'·'t' 가 JSON 키에 걸려 모든 노래를 오탐하므로 파싱해서
        값만 비교한다.
        """
        needle = text.lower()
        with self._db.connection() as conn:
            music_ids = self._music_category_ids(conn)
            if not music_ids:
                return []
            cat_ph = ",".join("?" * len(music_ids))
            sql = (
                "SELECT s.video_id, s.lyrics_json FROM song_info s "
                "JOIN videos v ON v.id = s.video_id "
                f"WHERE s.lyrics_json <> '[]' AND v.category_id IN ({cat_ph})"
            )
            params: list = list(music_ids)
            if _lyrics_prefilter_safe(text):
                # 후보를 SQL 로 먼저 좁힌다 — 전체 가사를 매 검색마다 JSON 파싱하면
                # 검색어를 한 글자 칠 때마다 라이브러리 전체를 파싱하게 된다.
                sql += " AND s.lyrics_json LIKE ? ESCAPE '\\'"
                params.append(_like_pattern(text))
            rows = conn.execute(sql, params).fetchall()
        return [
            r["video_id"]
            for r in rows
            if needle in _lyrics_text(r["lyrics_json"]).lower()
        ]

    def match_fields_for(
        self, video_ids: list[UUID], text: str
    ) -> dict[UUID, tuple[str, ...]]:
        """각 영상이 검색어와 어느 속성에서 일치했는지 판정한다.

        현재 페이지(기본 50건)에만 실행하므로 영상당 몇 번의 조회로 끝난다.
        """
        if not text or not video_ids:
            return {}

        ids = [str(v) for v in video_ids]
        ph = ",".join("?" * len(ids))
        like = _like_pattern(text)
        found: dict[str, set[str]] = {i: set() for i in ids}

        probes = [
            ("title", f"SELECT id FROM videos WHERE id IN ({ph}) AND title LIKE ? ESCAPE '\\'", 1),
            ("notes", f"SELECT id FROM videos WHERE id IN ({ph}) AND notes LIKE ? ESCAPE '\\'", 1),
            (
                "summary",
                f"SELECT id FROM videos WHERE id IN ({ph}) "
                "AND gemini_summary LIKE ? ESCAPE '\\'",
                1,
            ),
            (
                "description",
                f"SELECT video_id FROM video_descriptions WHERE video_id IN ({ph}) "
                "AND description LIKE ? ESCAPE '\\'",
                1,
            ),
            (
                "tags",
                "SELECT vt.video_id FROM video_tags vt JOIN tags t ON t.id = vt.tag_id "
                f"WHERE vt.video_id IN ({ph}) AND t.name LIKE ? ESCAPE '\\'",
                1,
            ),
            (
                "song",
                f"SELECT video_id FROM song_info WHERE video_id IN ({ph}) AND ("
                "artist LIKE ? ESCAPE '\\' OR album LIKE ? ESCAPE '\\' "
                "OR song_title LIKE ? ESCAPE '\\' OR release_year LIKE ? ESCAPE '\\')",
                4,
            ),
        ]

        with self._db.connection() as conn:
            for key, sql, n_like in probes:
                for row in conn.execute(sql, [*ids, *([like] * n_like)]).fetchall():
                    found[row[0]].add(key)

            # 가사는 파싱해서 비교한다(JSON 키 오탐 방지). 음악 카테고리만 대상.
            needle = text.lower()
            music_ids = self._music_category_ids(conn)
            if music_ids:
                cat_ph = ",".join("?" * len(music_ids))
                lyric_rows = conn.execute(
                    "SELECT s.video_id, s.lyrics_json FROM song_info s "
                    "JOIN videos v ON v.id = s.video_id "
                    f"WHERE s.video_id IN ({ph}) AND v.category_id IN ({cat_ph})",
                    [*ids, *music_ids],
                ).fetchall()
            else:
                lyric_rows = []

        for row in lyric_rows:
            if needle in _lyrics_text(row["lyrics_json"]).lower():
                found[row["video_id"]].add("lyrics")

        return {
            UUID(vid): tuple(k for k in MATCH_FIELD_KEYS if k in keys)
            for vid, keys in found.items()
            if keys
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

        if query.in_progress_only:
            # 이어보기 — 보던 지점이 남아 있는 영상만.
            where.append("videos.last_position_ms > 0")

        if query.text:
            # 부분 일치 — 제목·메모·요약·설명·태그·노래 정보를 UNION 으로 덮는다.
            # 가사는 lyrics_json 을 파싱해 별도로 구한다(JSON 키 오탐 방지).
            like = _like_pattern(query.text)
            clauses = [
                "SELECT id FROM videos WHERE title LIKE ? ESCAPE '\\'",
                "SELECT id FROM videos WHERE notes LIKE ? ESCAPE '\\'",
                "SELECT id FROM videos WHERE gemini_summary LIKE ? ESCAPE '\\'",
                "SELECT video_id FROM video_descriptions WHERE description LIKE ? ESCAPE '\\'",
                "SELECT vt.video_id FROM video_tags vt JOIN tags t ON t.id = vt.tag_id "
                "WHERE t.name LIKE ? ESCAPE '\\'",
                "SELECT video_id FROM song_info WHERE artist LIKE ? ESCAPE '\\' "
                "OR album LIKE ? ESCAPE '\\' OR song_title LIKE ? ESCAPE '\\' "
                "OR release_year LIKE ? ESCAPE '\\'",
            ]
            union = " UNION ".join(clauses)
            # ? 개수를 세어 바인딩한다 — 절을 추가·삭제해도 어긋나지 않는다.
            text_params = [like] * union.count("?")

            lyric_ids = self._lyrics_match_ids(query.text)
            if lyric_ids:
                ph = ",".join("?" * len(lyric_ids))
                where.append(f"(videos.id IN ({union}) OR videos.id IN ({ph}))")
                params.extend(text_params)
                params.extend(lyric_ids)
            else:
                where.append(f"videos.id IN ({union})")
                params.extend(text_params)

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
