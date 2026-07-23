"""MergeApplier — 병합된 op를 라이브 DB에 반영한다.

OpLogMerger(순수)로 승자를 계산한 뒤, 자연키→로컬 UUID를 해석하고 FK를 재작성해
엔티티 타입 위상 순서로 라이브 테이블에 직접 적용한다. 적용은 **plain 리포지토리/직접
SQL**로 하므로 RecordingRepository가 개입하지 않는다 → 원격 op를 다시 op로 기록하는
루프가 생기지 않는다. FTS 트리거는 테이블에 걸려 있어 직접 write에도 정상 발화하고,
rowid는 로컬에서 재할당된다(이식성 문제 없음).

Phase 3에서는 video upsert/delete + category 참조 해석을 구현한다. 다른 엔티티 핸들러는
후속 Phase에서 registry에 추가한다.
"""

from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from uuid import uuid4

from domain.sync.services import (
    OpLogMerger,
    split_link_key,
    topo_order,
)
from domain.sync.value_objects import (
    ClockEntry,
    EntityKey,
    Op,
)
from domain.sync.services import FieldEntry, MergeResult, MergeState, PresenceEntry

logger = logging.getLogger(__name__)

_REF = "__ref__"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _register_identity(conn, entity: str, nkey: str, local_uuid: str) -> None:
    """origin-identity 엔티티를 배치 내 즉시 참조 가능하도록 sync_identity에 등록.

    _persist_state는 모든 핸들러 이후라, 같은 배치의 자식이 부모를 resolve_*로 찾으려면
    핸들러 적용 시점에 미리 등록돼 있어야 한다(present/clock은 이후 _persist_state가 확정)."""
    conn.execute(
        "INSERT OR IGNORE INTO sync_identity"
        "(entity, nkey, local_uuid, present, pres_lamport, pres_install) "
        "VALUES (?,?,?,1,0,'')",
        (entity, nkey, local_uuid),
    )


class MergeApplier:
    def __init__(self, db, clock, handlers: dict | None = None) -> None:
        self._db = db
        self._clock = clock
        self._handlers = handlers or {
            "category": CategoryApplyHandler(),
            "playlist_folder": PlaylistFolderApplyHandler(),
            "video": VideoApplyHandler(),
            "song_info": SongApplyHandler(),
            "playlist": PlaylistApplyHandler(),
            "video_tag": VideoTagApplyHandler(),
            "playlist_item": PlaylistItemApplyHandler(),
            "category_video_order": CategoryVideoOrderApplyHandler(),
            "clip": ClipApplyHandler(),
            "download_history": DownloadApplyHandler(),
        }
        self._merger = OpLogMerger()

    def apply(self, ops: list[Op]) -> MergeResult:
        ops = list(ops)
        keys = {op.entity_key for op in ops}
        op_ids = {op.op_id for op in ops}

        with self._db.connection() as conn:
            state = self._load_state(conn, keys, op_ids)

        result = self._merger.merge(ops, state)
        if not result.newly_applied:
            return result

        with self._db.connection() as conn:
            uuid_map = self._resolve_uuids(conn, result.changed)
            self._apply_changes(conn, result, uuid_map)
            self._persist_state(conn, result, uuid_map)

        max_lam = max((op.lamport for op in ops), default=0)
        self._clock.observe(max_lam)
        return result

    # -- 상태 로드 --------------------------------------------------------
    def _load_state(self, conn, keys, op_ids) -> MergeState:
        presence: dict = {}
        fields: dict = {}
        refs: dict = {}
        for ek in keys:
            row = conn.execute(
                "SELECT present, pres_lamport, pres_install FROM sync_identity "
                "WHERE entity=? AND nkey=?",
                (ek.entity, ek.nkey),
            ).fetchone()
            if row is not None:
                presence[ek] = PresenceEntry(
                    ClockEntry(row["pres_lamport"], row["pres_install"]),
                    bool(row["present"]),
                )
            for fc in conn.execute(
                "SELECT field, lamport, install FROM sync_field_clock "
                "WHERE entity=? AND nkey=?",
                (ek.entity, ek.nkey),
            ).fetchall():
                ce = ClockEntry(fc["lamport"], fc["install"])
                name = fc["field"]
                # 값은 clock 테이블에 없음(None) — LWW 판정엔 clock만 필요.
                if name.startswith(_REF):
                    refs.setdefault(ek, {})[name[len(_REF):]] = FieldEntry(ce, None)
                else:
                    fields.setdefault(ek, {})[name] = FieldEntry(ce, None)

        applied = set()
        for oid in op_ids:
            if conn.execute(
                "SELECT 1 FROM sync_applied_ops WHERE op_id=?", (oid,)
            ).fetchone():
                applied.add(oid)
        return MergeState(presence=presence, fields=fields, refs=refs, applied_op_ids=applied)

    def _resolve_uuids(self, conn, changed) -> dict[EntityKey, str]:
        out: dict[EntityKey, str] = {}
        for ek in changed:
            row = conn.execute(
                "SELECT local_uuid FROM sync_identity WHERE entity=? AND nkey=?",
                (ek.entity, ek.nkey),
            ).fetchone()
            out[ek] = row["local_uuid"] if row else str(uuid4())
        return out

    # -- 적용 -------------------------------------------------------------
    def _apply_changes(self, conn, result: MergeResult, uuid_map) -> None:
        upserts = result.upserts()
        deletions = result.deletions()
        by_entity: dict[str, list[EntityKey]] = defaultdict(list)
        for ek in result.changed:
            by_entity[ek.entity].append(ek)

        for entity in topo_order(by_entity.keys()):
            handler = self._handlers.get(entity)
            if handler is None:
                logger.warning("적용 핸들러 없는 엔티티 건너뜀: %s", entity)
                continue
            for ek in by_entity[entity]:
                luuid = uuid_map[ek]
                if ek in deletions:
                    handler.delete(conn, luuid, ek.nkey)
                elif ek in upserts:
                    w = upserts[ek]
                    field_vals = {k: v for k, v in w.items() if not k.startswith(_REF)}
                    ref_vals = {
                        k[len(_REF):]: v for k, v in w.items() if k.startswith(_REF)
                    }
                    handler.upsert(conn, luuid, ek.nkey, field_vals, ref_vals, self)

    def _persist_state(self, conn, result: MergeResult, uuid_map) -> None:
        for ek in result.changed:
            pe = result.state.presence.get(ek)
            if pe is not None:
                conn.execute(
                    """
                    INSERT INTO sync_identity(entity, nkey, local_uuid, present, pres_lamport, pres_install)
                    VALUES (?,?,?,?,?,?)
                    ON CONFLICT(entity, nkey) DO UPDATE SET
                        present=excluded.present,
                        pres_lamport=excluded.pres_lamport,
                        pres_install=excluded.pres_install
                    """,
                    (
                        ek.entity, ek.nkey, uuid_map[ek],
                        1 if pe.present else 0, pe.clock.lamport, pe.clock.install_id,
                    ),
                )
            for name, fe in result.state.fields.get(ek, {}).items():
                self._upsert_clock(conn, ek, name, fe.clock)
            for name, fe in result.state.refs.get(ek, {}).items():
                self._upsert_clock(conn, ek, _REF + name, fe.clock)

        now = _now_iso()
        for op_id in result.newly_applied:
            conn.execute(
                "INSERT OR IGNORE INTO sync_applied_ops(op_id, applied_at) VALUES (?, ?)",
                (op_id, now),
            )

    @staticmethod
    def _upsert_clock(conn, ek: EntityKey, field_name: str, clk: ClockEntry) -> None:
        conn.execute(
            """
            INSERT INTO sync_field_clock(entity, nkey, field, lamport, install)
            VALUES (?,?,?,?,?)
            ON CONFLICT(entity, nkey, field) DO UPDATE SET
                lamport=excluded.lamport, install=excluded.install
            """,
            (ek.entity, ek.nkey, field_name, clk.lamport, clk.install_id),
        )

    # -- 참조 해석 (핸들러가 호출) ---------------------------------------
    @staticmethod
    def resolve_video(conn, video_nkey: str | None) -> str | None:
        """영상 자연키(URL) → 로컬 UUID. sync_identity 우선, 없으면 videos.url."""
        if not video_nkey:
            return None
        row = conn.execute(
            "SELECT local_uuid FROM sync_identity WHERE entity='video' AND nkey=?",
            (video_nkey,),
        ).fetchone()
        if row:
            return row["local_uuid"]
        row = conn.execute("SELECT id FROM videos WHERE url=?", (video_nkey,)).fetchone()
        return row["id"] if row else None

    @staticmethod
    def resolve_playlist(conn, nkey: str | None) -> str | None:
        if not nkey:
            return None
        row = conn.execute(
            "SELECT local_uuid FROM sync_identity WHERE entity='playlist' AND nkey=?",
            (nkey,),
        ).fetchone()
        return row["local_uuid"] if row else None

    @staticmethod
    def resolve_folder(conn, nkey: str | None) -> str | None:
        if not nkey:
            return None
        row = conn.execute(
            "SELECT local_uuid FROM sync_identity WHERE entity='playlist_folder' AND nkey=?",
            (nkey,),
        ).fetchone()
        return row["local_uuid"] if row else None

    @staticmethod
    def resolve_tag(conn, tag_nkey: str) -> str:
        """태그 자연키(이름) → 로컬 UUID. 없으면 태그 행을 생성하고 sync_identity에 등록."""
        row = conn.execute(
            "SELECT local_uuid FROM sync_identity WHERE entity='tag' AND nkey=?",
            (tag_nkey,),
        ).fetchone()
        if row:
            return row["local_uuid"]
        row = conn.execute("SELECT id FROM tags WHERE name=?", (tag_nkey,)).fetchone()
        if row:
            tid = row["id"]
        else:
            tid = str(uuid4())
            conn.execute("INSERT INTO tags(id, name) VALUES (?,?)", (tid, tag_nkey))
        conn.execute(
            "INSERT OR IGNORE INTO sync_identity"
            "(entity, nkey, local_uuid, present, pres_lamport, pres_install) "
            "VALUES ('tag', ?, ?, 1, 0, '')",
            (tag_nkey, tid),
        )
        return tid

    @staticmethod
    def resolve_category(conn, cat_nkey: str | None) -> str | None:
        """카테고리 origin 자연키 → 로컬 UUID.

        origin-identity라 nkey는 (생성기기, uuid) 조합이다. 아직 없으면 **스텁 행**을 만든다
        (이름 placeholder=nkey — 실제 category op이 적용될 때 UPDATE로 채워짐). 스텁은
        자식이 부모보다 먼저 적용되거나(배치 내 순서 무관), video가 category op보다 먼저
        참조될 때 FK 대상을 보장한다. placeholder 이름은 nkey라 서로 충돌하지 않는다.
        """
        if not cat_nkey:
            return None
        row = conn.execute(
            "SELECT local_uuid FROM sync_identity WHERE entity='category' AND nkey=?",
            (cat_nkey,),
        ).fetchone()
        if row:
            return row["local_uuid"]
        cid = str(uuid4())
        conn.execute(
            "INSERT INTO categories(id, name, parent_id) VALUES (?,?,NULL)", (cid, cat_nkey)
        )
        conn.execute(
            "INSERT OR IGNORE INTO sync_identity"
            "(entity, nkey, local_uuid, present, pres_lamport, pres_install) "
            "VALUES ('category', ?, ?, 1, 0, '')",
            (cat_nkey, cid),
        )
        return cid


class VideoApplyHandler:
    """video 엔티티의 라이브 테이블 반영(직접 SQL, 부분 컬럼 갱신)."""

    _COLS = (
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

    def upsert(self, conn, local_uuid, nkey, fields, refs, applier) -> None:
        exists = conn.execute(
            "SELECT 1 FROM videos WHERE id=?", (local_uuid,)
        ).fetchone()
        cat_id = None
        if "category" in refs:
            cat_id = applier.resolve_category(conn, refs["category"])

        if exists:
            sets, vals = [], []
            for col in self._COLS:
                if col in fields:
                    sets.append(f"{col}=?")
                    vals.append(fields[col])
            if "category" in refs:
                sets.append("category_id=?")
                vals.append(cat_id)
            if sets:
                sets.append("updated_at=?")
                vals.append(_now_iso())
                conn.execute(
                    f"UPDATE videos SET {', '.join(sets)} WHERE id=?", (*vals, local_uuid)
                )
        else:
            now = _now_iso()
            conn.execute(
                """
                INSERT INTO videos
                    (id, url, title, channel_name, channel_url, channel_id,
                     duration_sec, published_at, view_count, favorite, watched,
                     notes, gemini_summary, thumbnail_path, category_id, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    local_uuid, nkey, fields.get("title", ""),
                    fields.get("channel_name"), fields.get("channel_url"),
                    fields.get("channel_id"), fields.get("duration_sec"),
                    fields.get("published_at"), None,
                    int(fields.get("favorite", 0)), int(fields.get("watched", 0)),
                    fields.get("notes", ""), fields.get("gemini_summary", ""),
                    fields.get("thumbnail_path", ""), cat_id, now, now,
                ),
            )

    def delete(self, conn, local_uuid, nkey) -> None:
        conn.execute("DELETE FROM videos WHERE id=?", (local_uuid,))


class CategoryApplyHandler:
    """category(origin-identity) 반영. nkey=origin_key(생성기기,uuid), name은 필드,
    parent는 부모 카테고리 origin nkey ref. rename은 필드 변경으로 자연히 반영된다."""

    def upsert(self, conn, local_uuid, nkey, fields, refs, applier) -> None:
        cid = applier.resolve_category(conn, nkey)  # 이 카테고리의 로컬 id(스텁/기존)
        parent_id = None
        if "parent" in refs:
            parent_id = applier.resolve_category(conn, refs["parent"]) if refs["parent"] else None
            if parent_id == cid:  # 자기참조 방지(비정상 데이터)
                parent_id = None
        sets, vals = [], []
        if "name" in fields:
            sets.append("name=?")
            vals.append(fields["name"])
        if "parent" in refs:
            sets.append("parent_id=?")
            vals.append(parent_id)
        if not sets:
            return
        try:
            conn.execute(
                f"UPDATE categories SET {', '.join(sets)} WHERE id=?", (*vals, cid)
            )
        except sqlite3.IntegrityError:
            # UNIQUE(name,parent_id) 충돌 — 두 기기가 같은 이름을 독립 생성(드문 경우).
            # 기존 동명 카테고리로 병합: 이 nkey를 그 id로 재지정하고 스텁 제거.
            name = fields.get("name")
            existing = conn.execute(
                "SELECT id FROM categories WHERE name=? AND parent_id IS ? AND id<>?",
                (name, parent_id, cid),
            ).fetchone()
            if existing:
                conn.execute("DELETE FROM categories WHERE id=?", (cid,))
                conn.execute(
                    "UPDATE sync_identity SET local_uuid=? "
                    "WHERE entity='category' AND nkey=?",
                    (existing["id"], nkey),
                )
                logger.info("동명 카테고리 병합: nkey=%s → %s", nkey, existing["id"])
            else:
                logger.exception("카테고리 UPDATE 실패(원인 미상): %s", nkey)

    def delete(self, conn, local_uuid, nkey) -> None:
        conn.execute("DELETE FROM categories WHERE id=?", (local_uuid,))


class SongApplyHandler:
    """song_info 반영. nkey=영상 URL 키라 그 영상의 로컬 UUID로 video_id를 해석한다."""

    _COLS = (
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

    def upsert(self, conn, local_uuid, nkey, fields, refs, applier) -> None:
        vid = applier.resolve_video(conn, nkey)
        if vid is None:
            logger.warning("song_info 적용 skip — 영상 미해결: %s", nkey)
            return
        exists = conn.execute(
            "SELECT 1 FROM song_info WHERE video_id=?", (vid,)
        ).fetchone()
        if exists:
            sets, vals = [], []
            for col in self._COLS:
                if col in fields:
                    sets.append(f"{col}=?")
                    vals.append(fields[col])
            if sets:
                sets.append("updated_at=?")
                vals.append(_now_iso())
                conn.execute(
                    f"UPDATE song_info SET {', '.join(sets)} WHERE video_id=?",
                    (*vals, vid),
                )
        else:
            conn.execute(
                """
                INSERT INTO song_info
                    (video_id, is_song, artist, album, song_title, release_year,
                     lyrics_json, lyrics_language, source_name, source_url,
                     manual_fields, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    vid,
                    int(fields.get("is_song", 0)),
                    fields.get("artist", ""),
                    fields.get("album", ""),
                    fields.get("song_title", ""),
                    fields.get("release_year", ""),
                    fields.get("lyrics_json", "[]"),
                    fields.get("lyrics_language", ""),
                    fields.get("source_name", ""),
                    fields.get("source_url", ""),
                    fields.get("manual_fields", "[]"),
                    _now_iso(),
                ),
            )

    def delete(self, conn, local_uuid, nkey) -> None:
        vid = MergeApplier.resolve_video(conn, nkey)
        if vid is not None:
            conn.execute("DELETE FROM song_info WHERE video_id=?", (vid,))


class VideoTagApplyHandler:
    """video_tag 링크(조인 행) 반영. nkey=link_key(video_nkey, tag_nkey)."""

    def upsert(self, conn, local_uuid, nkey, fields, refs, applier) -> None:
        vnk = refs.get("video")
        tnk = refs.get("tag")
        if not vnk or not tnk:  # 방어 — 정상 LINK op엔 refs가 있음
            vnk, tnk = split_link_key(nkey)
        vid = applier.resolve_video(conn, vnk)
        if vid is None:
            logger.warning("video_tag 적용 skip — 영상 미해결: %s", vnk)
            return
        tid = applier.resolve_tag(conn, tnk)
        conn.execute(
            "INSERT OR IGNORE INTO video_tags(video_id, tag_id) VALUES (?,?)", (vid, tid)
        )

    def delete(self, conn, local_uuid, nkey) -> None:
        vnk, tnk = split_link_key(nkey)
        vid = MergeApplier.resolve_video(conn, vnk)
        trow = conn.execute("SELECT id FROM tags WHERE name=?", (tnk,)).fetchone()
        if vid is not None and trow is not None:
            conn.execute(
                "DELETE FROM video_tags WHERE video_id=? AND tag_id=?",
                (vid, trow["id"]),
            )


class ClipApplyHandler:
    """clip 반영. nkey=origin-identity, source_video는 ref(영상 URL 키). 파일 경로는 상대경로."""

    _COLS = ("title", "file_path", "thumbnail_path", "start_sec", "end_sec")

    def upsert(self, conn, local_uuid, nkey, fields, refs, applier) -> None:
        vid = applier.resolve_video(conn, refs.get("video"))
        exists = conn.execute("SELECT 1 FROM clips WHERE id=?", (local_uuid,)).fetchone()
        if exists:
            sets, vals = [], []
            for col in self._COLS:
                if col in fields:
                    sets.append(f"{col}=?")
                    vals.append(fields[col])
            if refs.get("video") and vid is not None:
                sets.append("source_video_id=?")
                vals.append(vid)
            if sets:
                conn.execute(
                    f"UPDATE clips SET {', '.join(sets)} WHERE id=?", (*vals, local_uuid)
                )
        else:
            if vid is None:
                logger.warning("clip 적용 skip — 소스 영상 미해결: %s", nkey)
                return
            conn.execute(
                """
                INSERT INTO clips
                    (id, source_video_id, title, file_path, thumbnail_path,
                     start_sec, end_sec, created_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    local_uuid, vid, fields.get("title", ""),
                    fields.get("file_path", ""), fields.get("thumbnail_path", ""),
                    fields.get("start_sec", 0.0), fields.get("end_sec", 0.0),
                    _now_iso(),
                ),
            )

    def delete(self, conn, local_uuid, nkey) -> None:
        conn.execute("DELETE FROM clips WHERE id=?", (local_uuid,))


class DownloadApplyHandler:
    """download_history 반영. nkey=origin-identity(video FK 없음). 파일 경로는 상대경로."""

    _COLS = (
        "url", "title", "quality", "format", "subtitle_langs",
        "include_thumbnail", "include_metadata", "status", "file_path",
        "error_msg", "retry_count",
    )

    def upsert(self, conn, local_uuid, nkey, fields, refs, applier) -> None:
        exists = conn.execute(
            "SELECT 1 FROM download_history WHERE id=?", (local_uuid,)
        ).fetchone()
        if exists:
            sets, vals = [], []
            for col in self._COLS:
                if col in fields:
                    sets.append(f"{col}=?")
                    vals.append(fields[col])
            if sets:
                sets.append("updated_at=?")
                vals.append(_now_iso())
                conn.execute(
                    f"UPDATE download_history SET {', '.join(sets)} WHERE id=?",
                    (*vals, local_uuid),
                )
        else:
            now = _now_iso()
            conn.execute(
                """
                INSERT INTO download_history
                    (id, url, title, quality, format, subtitle_langs,
                     include_thumbnail, include_metadata, status, file_path,
                     error_msg, retry_count, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    local_uuid,
                    fields.get("url", ""), fields.get("title", ""),
                    fields.get("quality", ""), fields.get("format", ""),
                    fields.get("subtitle_langs", "[]"),
                    int(fields.get("include_thumbnail", 1)),
                    int(fields.get("include_metadata", 1)),
                    fields.get("status", ""), fields.get("file_path", ""),
                    fields.get("error_msg", ""), int(fields.get("retry_count", 0)),
                    now, now,
                ),
            )

    def delete(self, conn, local_uuid, nkey) -> None:
        conn.execute("DELETE FROM download_history WHERE id=?", (local_uuid,))


class PlaylistFolderApplyHandler:
    """playlist_folders 반영(origin-identity). 필드=name·source."""

    _COLS = ("name", "source")

    def upsert(self, conn, local_uuid, nkey, fields, refs, applier) -> None:
        exists = conn.execute(
            "SELECT 1 FROM playlist_folders WHERE id=?", (local_uuid,)
        ).fetchone()
        if exists:
            sets, vals = [], []
            for col in self._COLS:
                if col in fields:
                    sets.append(f"{col}=?")
                    vals.append(fields[col])
            if sets:
                sets.append("updated_at=?")
                vals.append(_now_iso())
                conn.execute(
                    f"UPDATE playlist_folders SET {', '.join(sets)} WHERE id=?",
                    (*vals, local_uuid),
                )
        else:
            now = _now_iso()
            conn.execute(
                "INSERT INTO playlist_folders(id, name, source, created_at, updated_at) "
                "VALUES (?,?,?,?,?)",
                (local_uuid, fields.get("name", ""), fields.get("source", "local"), now, now),
            )
        # 같은 배치의 playlist가 resolve_folder로 참조하려면 지금 등록돼 있어야 한다
        # (_persist_state는 모든 핸들러 이후라 배치 내 참조엔 늦다).
        _register_identity(conn, "playlist_folder", nkey, local_uuid)

    def delete(self, conn, local_uuid, nkey) -> None:
        conn.execute(
            "UPDATE playlists SET folder_id=NULL WHERE folder_id=?", (local_uuid,)
        )
        conn.execute("DELETE FROM playlist_folders WHERE id=?", (local_uuid,))


class PlaylistApplyHandler:
    """playlists 반영(origin-identity, folder ref). item_count는 playlist_item 적용 시 재계산."""

    _COLS = ("title", "yt_playlist_id", "source")

    def upsert(self, conn, local_uuid, nkey, fields, refs, applier) -> None:
        folder_id = applier.resolve_folder(conn, refs["folder"]) if refs.get("folder") else None
        exists = conn.execute(
            "SELECT 1 FROM playlists WHERE id=?", (local_uuid,)
        ).fetchone()
        if exists:
            sets, vals = [], []
            for col in self._COLS:
                if col in fields:
                    sets.append(f"{col}=?")
                    vals.append(fields[col])
            if "folder" in refs:
                sets.append("folder_id=?")
                vals.append(folder_id)
            if sets:
                sets.append("updated_at=?")
                vals.append(_now_iso())
                conn.execute(
                    f"UPDATE playlists SET {', '.join(sets)} WHERE id=?", (*vals, local_uuid)
                )
        else:
            now = _now_iso()
            conn.execute(
                """
                INSERT INTO playlists
                    (id, title, yt_playlist_id, source, item_count, folder_id, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    local_uuid, fields.get("title", ""), fields.get("yt_playlist_id"),
                    fields.get("source", "local"), 0, folder_id, now, now,
                ),
            )
        # 같은 배치의 playlist_item이 resolve_playlist로 참조할 수 있도록 즉시 등록.
        _register_identity(conn, "playlist", nkey, local_uuid)

    def delete(self, conn, local_uuid, nkey) -> None:
        conn.execute("DELETE FROM playlists WHERE id=?", (local_uuid,))


def _recount_playlist(conn, playlist_id) -> None:
    conn.execute(
        "UPDATE playlists SET item_count="
        "(SELECT COUNT(*) FROM playlist_items WHERE playlist_id=?) WHERE id=?",
        (playlist_id, playlist_id),
    )


class PlaylistItemApplyHandler:
    """playlist_item 링크. 멤버십만 동기화 — position은 append(순서는 기기 로컬)."""

    def upsert(self, conn, local_uuid, nkey, fields, refs, applier) -> None:
        pnk, vnk = refs.get("playlist"), refs.get("video")
        if not pnk or not vnk:
            pnk, vnk = split_link_key(nkey)
        pid = applier.resolve_playlist(conn, pnk)
        vid = applier.resolve_video(conn, vnk)
        if pid is None or vid is None:
            logger.warning("playlist_item 적용 skip — 미해결(p=%s v=%s)", pnk, vnk)
            return
        pos = conn.execute(
            "SELECT COALESCE(MAX(position)+1, 0) AS p FROM playlist_items WHERE playlist_id=?",
            (pid,),
        ).fetchone()["p"]
        conn.execute(
            "INSERT OR IGNORE INTO playlist_items(playlist_id, video_id, position, added_at) "
            "VALUES (?,?,?,?)",
            (pid, vid, pos, _now_iso()),
        )
        _recount_playlist(conn, pid)

    def delete(self, conn, local_uuid, nkey) -> None:
        pnk, vnk = split_link_key(nkey)
        pid = MergeApplier.resolve_playlist(conn, pnk)
        vid = MergeApplier.resolve_video(conn, vnk)
        if pid is not None and vid is not None:
            conn.execute(
                "DELETE FROM playlist_items WHERE playlist_id=? AND video_id=?", (pid, vid)
            )
            _recount_playlist(conn, pid)


class CategoryVideoOrderApplyHandler:
    """category_video_order 링크(카테고리 내 수동 정렬 멤버십). position은 append."""

    def upsert(self, conn, local_uuid, nkey, fields, refs, applier) -> None:
        cnk, vnk = refs.get("category"), refs.get("video")
        if not cnk or not vnk:
            cnk, vnk = split_link_key(nkey)
        cid = applier.resolve_category(conn, cnk)
        vid = applier.resolve_video(conn, vnk)
        if cid is None or vid is None:
            logger.warning("category_video_order 적용 skip — 미해결(c=%s v=%s)", cnk, vnk)
            return
        pos = conn.execute(
            "SELECT COALESCE(MAX(position)+1, 0) AS p FROM category_video_order WHERE category_id=?",
            (cid,),
        ).fetchone()["p"]
        conn.execute(
            "INSERT OR IGNORE INTO category_video_order(category_id, video_id, position) "
            "VALUES (?,?,?)",
            (cid, vid, pos),
        )

    def delete(self, conn, local_uuid, nkey) -> None:
        cnk, vnk = split_link_key(nkey)
        crow = conn.execute(
            "SELECT local_uuid FROM sync_identity WHERE entity='category' AND nkey=?", (cnk,)
        ).fetchone()
        vid = MergeApplier.resolve_video(conn, vnk)
        if crow is not None and vid is not None:
            conn.execute(
                "DELETE FROM category_video_order WHERE category_id=? AND video_id=?",
                (crow["local_uuid"], vid),
            )
