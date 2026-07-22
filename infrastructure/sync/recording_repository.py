"""변경 캡처 리포지토리 데코레이터.

기존 Sqlite*Repository를 상속해 mutating 메서드(save/delete 등)만 오버라이드하고,
super()로 라이브 DB에 정상 반영한 뒤 OplogRecorder로 op를 기록한다. 나머지 메서드는
상속으로 그대로 위임된다. application/gui 레이어엔 투명하다.

Phase 2에서는 핵심 경로인 Video의 save/delete를 캡처한다. tag/카테고리순서 등 링크
엔티티와 다른 리포지토리(download/clip/playlist/song) 캡처는 Phase 2b에서 추가한다.
"""

from __future__ import annotations

from uuid import UUID

from domain.library.aggregates import VideoAggregate
from domain.sync.services import category_key, video_key
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository
from infrastructure.sync.recorder import OplogRecorder

_REF = "__ref__"

# 캡처할 video 컬럼(로그 대상). view_count는 churn이라 제외(스냅샷이 담당),
# description은 지연 로드라 Phase 2b로 미룸, created_at/updated_at은 메타라 제외.
_VIDEO_COLS = (
    "title",
    "notes",
    "favorite",
    "watched",
    "thumbnail_path",
    "gemini_summary",
    "channel_name",
    "channel_url",
    "channel_id",
    "duration_sec",
    "published_at",
)


class RecordingVideoRepository(SqliteVideoRepository):
    """SqliteVideoRepository + video save/delete op 캡처."""

    def __init__(self, db: Database, recorder: OplogRecorder) -> None:
        super().__init__(db)
        self._recorder = recorder

    def save(self, aggregate: VideoAggregate) -> None:
        old = self._read_old(aggregate.id)
        super().save(aggregate)
        new = self._extract(aggregate)
        self._recorder.record_change(
            "video", video_key(str(aggregate.video.url)), str(aggregate.id), old or {}, new
        )

    def delete(self, video_id: UUID) -> None:
        nkey = self._read_url_key(video_id)
        super().delete(video_id)
        if nkey is not None:
            self._recorder.record_delete("video", nkey)

    # -- 값 추출 ---------------------------------------------------------
    def _read_old(self, video_id: UUID) -> dict | None:
        with self._db.connection() as conn:
            cols = ", ".join(_VIDEO_COLS)
            row = conn.execute(
                f"SELECT {cols}, category_id FROM videos WHERE id=?", (str(video_id),)
            ).fetchone()
            if row is None:
                return None
            d = {c: row[c] for c in _VIDEO_COLS}
            d[_REF + "category"] = self._category_path(conn, row["category_id"])
            return d

    def _extract(self, agg: VideoAggregate) -> dict:
        v = agg.video
        ch = v.channel
        d = {
            "title": v.title,
            "notes": v.notes,
            "favorite": int(v.favorite),
            "watched": int(v.watched),
            "thumbnail_path": v.thumbnail_path,
            "gemini_summary": v.gemini_summary,
            "channel_name": ch.name if ch else None,
            "channel_url": ch.url if ch else None,
            "channel_id": ch.channel_id if ch else None,
            "duration_sec": v.duration.seconds if v.duration else None,
            "published_at": v.published_at.isoformat() if v.published_at else None,
        }
        with self._db.connection() as conn:
            cat = str(agg.category_id) if agg.category_id else None
            d[_REF + "category"] = self._category_path(conn, cat)
        return d

    def _read_url_key(self, video_id: UUID) -> str | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT url FROM videos WHERE id=?", (str(video_id),)
            ).fetchone()
        return video_key(row["url"]) if row else None

    @staticmethod
    def _category_path(conn, category_id) -> str:
        """category_id → 루트→리프 이름 경로 자연키. 없으면 빈 문자열."""
        if not category_id:
            return ""
        names: list[str] = []
        cur = category_id
        seen: set[str] = set()
        while cur and cur not in seen:
            seen.add(cur)
            row = conn.execute(
                "SELECT name, parent_id FROM categories WHERE id=?", (cur,)
            ).fetchone()
            if row is None:
                break
            names.append(row["name"])
            cur = row["parent_id"]
        names.reverse()
        return category_key(names)
