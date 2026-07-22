"""DB 스냅샷 export/import + 스키마 게이트 (ISnapshotStore 구현).

export: 라이브 DB를 직접 올리면 WAL 사이드카 때문에 손상되므로 `VACUUM INTO`로
정합 단일 파일 스냅샷을 만든다(미지원 SQLite면 conn.backup 폴백).

import: pull한 스냅샷을 DB로 교체하기 전에 integrity_check + 스키마 게이트를 거치고,
현재 라이브 DB를 conflict 백업으로 보존한다. **반드시 DB를 열기 전에** 호출해야 한다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from domain.sync.services import SyncSchemaError
from domain.sync.value_objects import SnapshotManifest

logger = logging.getLogger(__name__)

__all__ = ["SnapshotStore", "SyncSchemaError"]


class SnapshotStore:
    """ISnapshotStore를 구조적으로 만족."""

    def __init__(self, db_path: Path, migration_ids) -> None:
        self._db_path = Path(db_path)
        self._migration_ids = frozenset(migration_ids)

    def local_migration_ids(self) -> frozenset[str]:
        return self._migration_ids

    # -- export -----------------------------------------------------------
    def export_snapshot(self, dest: Path) -> str:
        """현재 DB의 정합 스냅샷을 dest에 만들고 sha256을 반환한다."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest.unlink()
        src = sqlite3.connect(self._db_path)
        try:
            try:
                src.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                src.execute("VACUUM INTO ?", (str(dest),))
            except sqlite3.OperationalError:
                logger.warning("VACUUM INTO 미지원 — conn.backup 폴백")
                dst = sqlite3.connect(dest)
                try:
                    src.backup(dst)
                finally:
                    dst.close()
        finally:
            src.close()
        return self._sha256(dest)

    # -- import -----------------------------------------------------------
    def import_snapshot(self, src: Path, backup_dir: Path) -> None:
        """검증·백업 후 DB 파일을 교체한다. (DB가 열려 있지 않은 상태에서만 호출)"""
        src = Path(src)
        self._check_integrity(src)
        self._check_schema_gate(src)

        if self._db_path.exists():
            bdir = Path(backup_dir) / "sync-conflict"
            bdir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = bdir / f"library-{ts}.db"
            self.export_snapshot(backup)  # 정합 백업(덮이는 쪽 보존)
            logger.info("동기화 전 로컬 DB 백업: %s", backup)

        for suffix in ("-wal", "-shm"):
            side = Path(str(self._db_path) + suffix)
            if side.exists():
                side.unlink()
        os.replace(src, self._db_path)
        logger.info("DB 스냅샷 교체 완료: %s", self._db_path)

    def read_manifest(self, path: Path) -> SnapshotManifest | None:
        p = Path(path)
        if not p.exists():
            return None
        try:
            return SnapshotManifest.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            logger.exception("manifest 읽기 실패: %s", p)
            return None

    # -- 내부 ------------------------------------------------------------
    @staticmethod
    def _check_integrity(path: Path) -> None:
        conn = sqlite3.connect(path)
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()
        if not row or row[0] != "ok":
            raise SyncSchemaError(f"스냅샷 integrity_check 실패: {row}")

    def _check_schema_gate(self, path: Path) -> None:
        remote_ids = self._read_migration_ids(path)
        unknown = remote_ids - self._migration_ids
        if unknown:
            raise SyncSchemaError(
                f"원격 스냅샷이 더 최신 스키마 — 앱 업데이트 필요: {sorted(unknown)}"
            )

    @staticmethod
    def _read_migration_ids(path: Path) -> frozenset[str]:
        conn = sqlite3.connect(path)
        try:
            try:
                rows = conn.execute("SELECT id FROM schema_migrations").fetchall()
            except sqlite3.OperationalError:
                return frozenset()
            return frozenset(r[0] for r in rows)
        finally:
            conn.close()

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
