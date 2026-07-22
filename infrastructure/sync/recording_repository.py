"""변경 캡처 리포지토리 데코레이터.

기존 Sqlite*Repository를 상속해 mutating 메서드(save/delete 등)만 오버라이드하고,
super()로 라이브 DB에 정상 반영한 뒤 OplogRecorder로 op를 기록한다. 나머지 메서드는
상속으로 그대로 위임된다. application/gui 레이어엔 투명하다.

Phase 2에서는 핵심 경로인 Video의 save/delete를 캡처한다. tag/카테고리순서 등 링크
엔티티와 다른 리포지토리(download/clip/playlist/song) 캡처는 Phase 2b에서 추가한다.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from domain.library.aggregates import VideoAggregate
from domain.library.entities import Category
from domain.sync.services import link_key, video_key
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_song_repository import SqliteSongRepository
from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository
from infrastructure.sync.recorder import OplogRecorder

_REF = "__ref__"

# song_info 캡처 컬럼(updated_at은 메타라 제외 — churn).
_SONG_COLS = (
    "is_song",
    "artist",
    "album",
    "song_title",
    "release_year",
    "lyrics_json",
    "lyrics_language",
    "source_name",
    "source_url",
    "manual_fields",
)

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
        old_tags = self._tag_nkeys_of_video(aggregate.id)  # super().save 전(연관 재작성 전)
        super().save(aggregate)
        new = self._extract(aggregate)
        vnk = video_key(str(aggregate.video.url))
        self._recorder.record_change("video", vnk, str(aggregate.id), old or {}, new)
        # video_tag 링크 diff — 추가/제거된 태그를 link/unlink op로 캡처.
        new_tags = self._tag_nkeys_of_ids(aggregate.tag_ids)
        for tnk in sorted(new_tags - old_tags):
            self._recorder.record_link(
                "video_tag", link_key(vnk, tnk), str(uuid4()), {"video": vnk, "tag": tnk}
            )
        for tnk in sorted(old_tags - new_tags):
            self._recorder.record_unlink("video_tag", link_key(vnk, tnk))

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
            d[_REF + "category"] = self._category_ref(row["category_id"])
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
        d[_REF + "category"] = self._category_ref(
            str(agg.category_id) if agg.category_id else None
        )
        return d

    def _read_url_key(self, video_id: UUID) -> str | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT url FROM videos WHERE id=?", (str(video_id),)
            ).fetchone()
        return video_key(row["url"]) if row else None

    # -- 카테고리(origin-identity) ---------------------------------------
    def save_category(self, category: Category) -> None:
        old = self._read_category(category.id)
        super().save_category(category)
        nkey = self._recorder.origin_nkey("category", str(category.id))
        new = {"name": category.name}
        new[_REF + "parent"] = self._category_ref(
            str(category.parent_id) if category.parent_id else None
        )
        self._recorder.record_change("category", nkey, str(category.id), old or {}, new)

    def delete_category(self, category_id: UUID) -> None:
        nkey = self._category_ref(str(category_id))
        super().delete_category(category_id)
        if nkey:
            self._recorder.record_delete("category", nkey)

    def _read_category(self, category_id: UUID) -> dict | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT name, parent_id FROM categories WHERE id=?", (str(category_id),)
            ).fetchone()
        if row is None:
            return None
        return {
            "name": row["name"],
            _REF + "parent": self._category_ref(row["parent_id"]),
        }

    def _category_ref(self, category_id) -> str:
        """category_id(로컬 UUID) → 카테고리 origin 자연키. 없으면 빈 문자열."""
        if not category_id:
            return ""
        return self._recorder.origin_nkey("category", str(category_id))

    # -- 태그 연관(video_tag) --------------------------------------------
    def _tag_nkeys_of_video(self, video_id: UUID) -> set[str]:
        """이 영상에 현재 연관된 태그 이름 집합(자연키=이름)."""
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT t.name FROM video_tags vt JOIN tags t ON t.id=vt.tag_id "
                "WHERE vt.video_id=?",
                (str(video_id),),
            ).fetchall()
        return {r["name"] for r in rows}

    def _tag_nkeys_of_ids(self, tag_ids) -> set[str]:
        ids = [str(t) for t in tag_ids]
        if not ids:
            return set()
        placeholders = ",".join("?" * len(ids))
        with self._db.connection() as conn:
            rows = conn.execute(
                f"SELECT name FROM tags WHERE id IN ({placeholders})", ids
            ).fetchall()
        return {r["name"] for r in rows}


class RecordingSongRepository(SqliteSongRepository):
    """SqliteSongRepository + song_info save/delete op 캡처.

    song_info는 Video와 1:1이라 자연키 = 영상의 URL 키(video_key). 적용 측은 이 nkey로
    영상 로컬 UUID를 해석해 song_info(video_id=…)에 반영한다.
    """

    def __init__(self, db: Database, recorder: OplogRecorder) -> None:
        super().__init__(db)
        self._recorder = recorder

    def save(self, aggregate) -> None:
        vid = aggregate.info.video_id
        old = self._read_song_cols(vid)
        super().save(aggregate)
        new = self._read_song_cols(vid)
        vnk = self._video_nkey(vid)
        if vnk and new is not None:
            self._recorder.record_change("song_info", vnk, str(vid), old or {}, new)

    def delete(self, video_id: UUID) -> None:
        vnk = self._video_nkey(video_id)
        super().delete(video_id)
        if vnk:
            self._recorder.record_delete("song_info", vnk)

    def _read_song_cols(self, video_id: UUID) -> dict | None:
        with self._db.connection() as conn:
            cols = ", ".join(_SONG_COLS)
            row = conn.execute(
                f"SELECT {cols} FROM song_info WHERE video_id=?", (str(video_id),)
            ).fetchone()
        return {c: row[c] for c in _SONG_COLS} if row else None

    def _video_nkey(self, video_id: UUID) -> str | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT url FROM videos WHERE id=?", (str(video_id),)
            ).fetchone()
        return video_key(row["url"]) if row else None
