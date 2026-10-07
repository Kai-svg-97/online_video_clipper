"""`busy_timeout` 명시 (성능 배치 4, B4-a).

`sqlite3.connect` 의 기본 대기(5초)에만 기대면 값이 코드 어디에도 드러나지 않고, 쓰기
잠금 경합(동기화·워커·메인 스레드) 때 얼마나 멈추는지 알 수 없다. 연결마다
`PRAGMA busy_timeout` 으로 `Database.BUSY_TIMEOUT_MS` 를 건다.
"""
from __future__ import annotations

import sqlite3
import time

import pytest

from infrastructure.persistence.database import Database


@pytest.fixture
def db(tmp_path):
    d = Database(path=tmp_path / "busy.db")
    d.initialize()
    return d


def test_연결은_busy_timeout을_상수로_건다(db):
    assert Database.BUSY_TIMEOUT_MS > 0
    with db.connection() as conn:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == Database.BUSY_TIMEOUT_MS


def test_상수를_바꾸면_다음_연결에_반영된다(db, monkeypatch):
    monkeypatch.setattr(Database, "BUSY_TIMEOUT_MS", 1234)
    with db.connection() as conn:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 1234


def test_쓰기_잠금이_풀리지_않으면_상수만큼만_기다리고_OperationalError를_낸다(db, monkeypatch):
    holder = sqlite3.connect(db.path, check_same_thread=False)
    try:
        holder.execute("BEGIN IMMEDIATE")           # 쓰기 잠금을 쥔다
        monkeypatch.setattr(Database, "BUSY_TIMEOUT_MS", 50)

        started = time.monotonic()
        with pytest.raises(sqlite3.OperationalError):
            with db.connection() as conn:
                conn.execute(
                    "INSERT INTO tags(id, name) VALUES ('busy-1', 'busy')"
                )
        elapsed = time.monotonic() - started

        # 시간은 환경마다 흔들리므로 엄밀히 재지 않는다 — 기본 5초를 쓰고 있지 않다는 정도만.
        assert elapsed < 3.0, f"{elapsed:.1f}초 대기 — BUSY_TIMEOUT_MS 가 적용되지 않았다"
    finally:
        holder.rollback()
        holder.close()
