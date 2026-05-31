from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from domain.library.entities import Playlist, PlaylistFolder
from domain.library.repositories import IPlaylistFolderRepository, IPlaylistRepository
from infrastructure.persistence.database import Database


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_playlist(row) -> Playlist:
    folder_id_raw = row["folder_id"] if "folder_id" in row.keys() else None
    return Playlist(
        id=UUID(row["id"]),
        title=row["title"],
        yt_playlist_id=row["yt_playlist_id"],
        source=row["source"],
        item_count=row["item_count"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        folder_id=UUID(folder_id_raw) if folder_id_raw else None,
    )


def _row_to_folder(row) -> PlaylistFolder:
    return PlaylistFolder(
        id=UUID(row["id"]),
        name=row["name"],
        source=row["source"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


class SqlitePlaylistFolderRepository(IPlaylistFolderRepository):
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, folder: PlaylistFolder) -> None:
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO playlist_folders (id, name, source, created_at, updated_at)
                VALUES (?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    source=excluded.source,
                    updated_at=excluded.updated_at
                """,
                (
                    str(folder.id),
                    folder.name,
                    folder.source,
                    folder.created_at.isoformat(),
                    folder.updated_at.isoformat(),
                ),
            )

    def get_by_id(self, folder_id: UUID) -> PlaylistFolder | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM playlist_folders WHERE id=?", (str(folder_id),)
            ).fetchone()
        return _row_to_folder(row) if row else None

    def list_by_source(self, source: str | None = None) -> list[PlaylistFolder]:
        with self._db.connection() as conn:
            if source is None:
                rows = conn.execute(
                    "SELECT * FROM playlist_folders ORDER BY source, name"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM playlist_folders WHERE source=? ORDER BY name",
                    (source,),
                ).fetchall()
        return [_row_to_folder(r) for r in rows]

    def delete(self, folder_id: UUID) -> None:
        now = _now_iso()
        fid = str(folder_id)
        with self._db.connection() as conn:
            # 폴더 삭제 전 소속 재생목록을 미분류로 이동
            conn.execute(
                "UPDATE playlists SET folder_id=NULL, updated_at=? WHERE folder_id=?",
                (now, fid),
            )
            conn.execute("DELETE FROM playlist_folders WHERE id=?", (fid,))


class SqlitePlaylistRepository(IPlaylistRepository):
    def __init__(self, db: Database) -> None:
        self._db = db

    def save(self, playlist: Playlist) -> None:
        with self._db.connection() as conn:
            conn.execute(
                """
                INSERT INTO playlists
                    (id, title, yt_playlist_id, source, item_count, folder_id, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    yt_playlist_id=excluded.yt_playlist_id,
                    source=excluded.source,
                    item_count=excluded.item_count,
                    folder_id=excluded.folder_id,
                    updated_at=excluded.updated_at
                """,
                (
                    str(playlist.id),
                    playlist.title,
                    playlist.yt_playlist_id,
                    playlist.source,
                    playlist.item_count,
                    str(playlist.folder_id) if playlist.folder_id else None,
                    playlist.created_at.isoformat(),
                    playlist.updated_at.isoformat(),
                ),
            )

    def get_by_id(self, playlist_id: UUID) -> Playlist | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM playlists WHERE id=?", (str(playlist_id),)
            ).fetchone()
        return _row_to_playlist(row) if row else None

    def list_all(self) -> list[Playlist]:
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM playlists ORDER BY source DESC, created_at ASC"
            ).fetchall()
        return [_row_to_playlist(r) for r in rows]

    def delete(self, playlist_id: UUID) -> None:
        with self._db.connection() as conn:
            conn.execute("DELETE FROM playlists WHERE id=?", (str(playlist_id),))

    def get_by_yt_id(self, yt_playlist_id: str) -> Playlist | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM playlists WHERE yt_playlist_id=?", (yt_playlist_id,)
            ).fetchone()
        return _row_to_playlist(row) if row else None

    def get_items(self, playlist_id: UUID) -> list[tuple[UUID, int]]:
        with self._db.connection() as conn:
            rows = conn.execute(
                "SELECT video_id, position FROM playlist_items "
                "WHERE playlist_id=? ORDER BY position",
                (str(playlist_id),),
            ).fetchall()
        return [(UUID(r["video_id"]), r["position"]) for r in rows]

    def set_items(self, playlist_id: UUID, video_ids: list[UUID]) -> None:
        now = _now_iso()
        pid = str(playlist_id)
        with self._db.connection() as conn:
            conn.execute("DELETE FROM playlist_items WHERE playlist_id=?", (pid,))
            conn.executemany(
                "INSERT INTO playlist_items (playlist_id, video_id, position, added_at) "
                "VALUES (?,?,?,?)",
                [(pid, str(vid), pos, now) for pos, vid in enumerate(video_ids)],
            )
            conn.execute(
                "UPDATE playlists SET item_count=?, updated_at=? WHERE id=?",
                (len(video_ids), now, pid),
            )

    def add_video(
        self,
        playlist_id: UUID,
        video_id: UUID,
        position: int | None = None,
    ) -> None:
        now = _now_iso()
        pid = str(playlist_id)
        vid = str(video_id)
        with self._db.connection() as conn:
            if position is None:
                row = conn.execute(
                    "SELECT COALESCE(MAX(position)+1, 0) AS pos FROM playlist_items WHERE playlist_id=?",
                    (pid,),
                ).fetchone()
                position = row["pos"]
            conn.execute(
                "INSERT OR IGNORE INTO playlist_items (playlist_id, video_id, position, added_at) "
                "VALUES (?,?,?,?)",
                (pid, vid, position, now),
            )
            conn.execute(
                "UPDATE playlists SET item_count=item_count+1, updated_at=? WHERE id=?",
                (now, pid),
            )

    def remove_video(self, playlist_id: UUID, video_id: UUID) -> None:
        now = _now_iso()
        pid = str(playlist_id)
        with self._db.connection() as conn:
            conn.execute(
                "DELETE FROM playlist_items WHERE playlist_id=? AND video_id=?",
                (pid, str(video_id)),
            )
            conn.execute(
                "UPDATE playlists SET item_count=MAX(0, item_count-1), updated_at=? WHERE id=?",
                (now, pid),
            )

    def update_folder(self, playlist_id: UUID, folder_id: UUID | None) -> None:
        with self._db.connection() as conn:
            conn.execute(
                "UPDATE playlists SET folder_id=?, updated_at=? WHERE id=?",
                (
                    str(folder_id) if folder_id else None,
                    _now_iso(),
                    str(playlist_id),
                ),
            )

    def get_yt_item_id(self, playlist_id: UUID, video_id: UUID) -> str | None:
        with self._db.connection() as conn:
            row = conn.execute(
                "SELECT yt_item_id FROM playlist_items WHERE playlist_id=? AND video_id=?",
                (str(playlist_id), str(video_id)),
            ).fetchone()
        return row["yt_item_id"] if row else None

    def set_yt_item_id(self, playlist_id: UUID, video_id: UUID, yt_item_id: str) -> None:
        with self._db.connection() as conn:
            conn.execute(
                "UPDATE playlist_items SET yt_item_id=? WHERE playlist_id=? AND video_id=?",
                (yt_item_id, str(playlist_id), str(video_id)),
            )
