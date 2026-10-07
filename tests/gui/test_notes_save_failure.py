"""메모 저장 실패를 사용자에게 알린다 (성능 배치 4, B4-a).

예전에는 `save_notes` 가 실패하면(DB 잠금 등) 로그만 남겨, 사용자는 메모가 저장됐다고
믿은 채 내용을 잃었다. 메인 세션 결정: 해당 뷰모델의 기존 `error_occurred` 신호로 알린다.
"""
from __future__ import annotations

import logging
import sqlite3
from uuid import uuid4

import pytest


@pytest.fixture
def received(library_vm):
    got: list[str] = []
    library_vm.error_occurred.connect(got.append)
    return got


def test_저장이_실패하면_error_occurred가_정확히_한_번_나간다(library_vm, received):
    library_vm._update_video.handle.side_effect = sqlite3.OperationalError(
        "database is locked"
    )

    library_vm.save_notes(uuid4(), "내 메모")

    assert len(received) == 1
    assert received[0].strip() != ""


def test_실패는_로그에도_남는다(library_vm, received, caplog):
    library_vm._update_video.handle.side_effect = sqlite3.OperationalError(
        "database is locked"
    )

    with caplog.at_level(logging.ERROR):
        library_vm.save_notes(uuid4(), "내 메모")

    assert any(r.exc_info for r in caplog.records), "logger.exception 기록이 없다"


def test_저장이_성공하면_알리지_않는다(library_vm, received):
    library_vm.save_notes(uuid4(), "내 메모")

    library_vm._update_video.handle.assert_called_once()
    assert received == []
