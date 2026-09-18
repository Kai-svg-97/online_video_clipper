"""DB 백업 실행 — 진짜 SQLite 파일로.

**라이브 DB 파일을 그냥 복사하면 안 된다.** WAL 모드라 `-wal` 사이드카에 아직 본체로
넘어가지 않은 내용이 남아 있고, 그 상태의 `.db` 하나만 떼면 어제까지의 DB가 된다.
그래서 여기서는 "파일이 생겼나"가 아니라 **방금 쓴 내용이 사본에 들어 있나**를 본다 —
그게 이 기능의 전부다.
"""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from domain.library.backup import backup_name
from infrastructure.persistence.database import Database
from infrastructure.persistence.db_backup import DbBackup


@pytest.fixture
def live_db(tmp_path):
    """WAL 모드로 열린 실제 DB — 사이드카에 내용이 남은 상태를 만든다."""
    db = Database(path=tmp_path / "library.db")
    db.initialize()
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO categories (id, name, parent_id) VALUES (?, ?, NULL)",
            ("cat-1", "백업 확인용"),
        )
        conn.commit()
    return db


@pytest.fixture
def backup(live_db, tmp_path):
    return DbBackup(live_db.path, tmp_path / "backups")


def _names_in(backup: DbBackup) -> set[str]:
    return set(backup.existing())


class TestConsistency:
    def test_방금_쓴_내용이_사본에_들어_있다(self, backup):
        """WAL 사이드카를 반영하지 않으면 여기서 0건이 된다."""
        made = backup.run_daily(date(2026, 9, 18))

        assert made is not None
        conn = sqlite3.connect(made)
        try:
            rows = conn.execute("SELECT name FROM categories").fetchall()
        finally:
            conn.close()
        assert [r[0] for r in rows] == ["백업 확인용"]

    def test_사본은_따로_논다(self, backup, live_db):
        """백업한 뒤 원본을 고쳐도 사본은 그대로여야 복구에 쓸모가 있다."""
        backup.run_daily(date(2026, 9, 18))
        with live_db.connection() as conn:
            conn.execute("DELETE FROM categories")
            conn.commit()

        made = backup.latest()
        conn = sqlite3.connect(made)
        try:
            count = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
        finally:
            conn.close()
        assert count == 1


class TestDailyGate:
    def test_같은_날_다시_불러도_한_번만_만든다(self, backup):
        backup.run_daily(date(2026, 9, 18))
        again = backup.run_daily(date(2026, 9, 18))

        assert again is None
        assert _names_in(backup) == {backup_name(date(2026, 9, 18))}

    def test_날이_바뀌면_새로_만든다(self, backup):
        backup.run_daily(date(2026, 9, 18))
        backup.run_daily(date(2026, 9, 19))

        assert len(_names_in(backup)) == 2


class TestRetention:
    def test_여드레째에_가장_오래된_것이_빠진다(self, backup):
        for day in range(10, 18):            # 8일치
            backup.run_daily(date(2026, 9, day))

        names = _names_in(backup)
        assert len(names) == 7
        assert backup_name(date(2026, 9, 10)) not in names
        assert backup_name(date(2026, 9, 17)) in names

    def test_남의_파일은_건드리지_않는다(self, backup, tmp_path):
        """백업 폴더는 클라우드 동기화의 충돌 백업도 쓰는 곳이다."""
        (tmp_path / "backups").mkdir(parents=True, exist_ok=True)
        stranger = tmp_path / "backups" / "conflict-20260101.db"
        stranger.write_text("남의 것", encoding="utf-8")

        for day in range(10, 20):
            backup.run_daily(date(2026, 9, day))

        assert stranger.exists()


class TestFailureIsolation:
    def test_DB가_없으면_조용히_넘어간다(self, tmp_path):
        b = DbBackup(tmp_path / "없는.db", tmp_path / "backups")
        assert b.run_daily(date(2026, 9, 18)) is None

    def test_백업_폴더를_못_만들어도_앱을_멈추지_않는다(self, live_db, tmp_path):
        """시작 경로에서 부르므로 여기서 터지면 앱이 못 뜬다."""
        blocker = tmp_path / "blocked"
        blocker.write_text("폴더가 아니라 파일", encoding="utf-8")

        b = DbBackup(live_db.path, blocker)

        assert b.run_daily(date(2026, 9, 18)) is None

    def test_만들다_만_파일을_오늘치로_치지_않는다(self, backup, tmp_path):
        """반쪽짜리가 '오늘치'로 남으면 내일까지 다시 시도하지 않는다."""
        (tmp_path / "backups").mkdir(parents=True, exist_ok=True)
        half = tmp_path / "backups" / (backup_name(date(2026, 9, 18)) + ".part")
        half.write_bytes(b"\x00" * 16)

        made = backup.run_daily(date(2026, 9, 18))

        assert made is not None and made.exists()


class TestLatest:
    def test_백업이_없으면_None(self, backup):
        assert backup.latest() is None

    def test_가장_최근_것을_돌려준다(self, backup):
        backup.run_daily(date(2026, 9, 17))
        backup.run_daily(date(2026, 9, 18))

        assert backup.latest().name == backup_name(date(2026, 9, 18))
