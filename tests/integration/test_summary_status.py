"""요약 실패 사유 저장·조회를 검증한다.

상세 화면이 "질문하기 버튼이 없어 실패"와 일반 오류를 구분해 안내하려면 사유가
재시작 후에도 남아야 한다. videos 행을 늘리지 않도록 video_descriptions 와 같은
방식으로 별도 테이블에 둔다.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from domain.library.aggregates import VideoAggregate
from domain.library.value_objects import VideoUrl
from infrastructure.browser.gemini_extractor import (
    SUMMARY_REASON_NOT_SIGNED_IN,
    SUMMARY_REASON_NO_BUTTON,
)
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository


@pytest.fixture
def repo(tmp_path):
    db = Database(path=tmp_path / "status.db")
    db.initialize()
    return SqliteVideoRepository(db)


def _add(repo, url="https://youtu.be/s1", title="무제"):
    agg = VideoAggregate.create(VideoUrl(url), title)
    repo.save(agg)
    return agg


class TestSummaryStatus:
    def test_default_is_empty(self, repo):
        agg = _add(repo)
        assert repo.get_summary_status(agg.id) == ""

    def test_set_and_get(self, repo):
        agg = _add(repo)
        repo.set_summary_status(agg.id, SUMMARY_REASON_NO_BUTTON)
        assert repo.get_summary_status(agg.id) == SUMMARY_REASON_NO_BUTTON

    def test_set_overwrites(self, repo):
        agg = _add(repo)
        repo.set_summary_status(agg.id, SUMMARY_REASON_NO_BUTTON)
        repo.set_summary_status(agg.id, SUMMARY_REASON_NOT_SIGNED_IN)
        assert repo.get_summary_status(agg.id) == SUMMARY_REASON_NOT_SIGNED_IN

    def test_clear_removes_status(self, repo):
        """요약을 성공적으로 가져오면 상태를 지워 안내 문구가 사라져야 한다."""
        agg = _add(repo)
        repo.set_summary_status(agg.id, SUMMARY_REASON_NO_BUTTON)
        repo.clear_summary_status(agg.id)
        assert repo.get_summary_status(agg.id) == ""

    def test_clear_is_idempotent(self, repo):
        agg = _add(repo)
        repo.clear_summary_status(agg.id)   # 없는 상태를 지워도 예외 없음
        assert repo.get_summary_status(agg.id) == ""

    def test_unknown_video_returns_empty(self, repo):
        assert repo.get_summary_status(uuid4()) == ""

    def test_survives_new_repository_instance(self, repo, tmp_path):
        """재시작 상황 — 같은 DB를 새 인스턴스로 열어도 남아 있어야 한다."""
        agg = _add(repo)
        repo.set_summary_status(agg.id, SUMMARY_REASON_NO_BUTTON)

        reopened = SqliteVideoRepository(Database(path=tmp_path / "status.db"))
        assert reopened.get_summary_status(agg.id) == SUMMARY_REASON_NO_BUTTON

    def test_deleting_video_removes_status(self, repo):
        """ON DELETE CASCADE — 영상을 지우면 상태도 사라져야 한다."""
        agg = _add(repo)
        repo.set_summary_status(agg.id, SUMMARY_REASON_NO_BUTTON)
        repo.delete(agg.id)
        assert repo.get_summary_status(agg.id) == ""


class TestDetailDtoCarriesStatus:
    def test_detail_exposes_summary_status(self, repo, tmp_path):
        """상세 DTO가 상태를 실어야 GUI가 문구를 바꿀 수 있다."""
        from unittest.mock import MagicMock

        from application.library.queries import GetVideoDetailHandler

        agg = _add(repo)
        repo.set_summary_status(agg.id, SUMMARY_REASON_NO_BUTTON)

        dl_repo = MagicMock()
        dl_repo.get_by_video_id.return_value = []
        dl_repo.get_failed_by_video_id.return_value = []
        handler = GetVideoDetailHandler(repo, dl_repo)

        dto = handler.handle(agg.id)

        assert dto is not None
        assert dto.summary_status == SUMMARY_REASON_NO_BUTTON
