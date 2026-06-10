"""구독 등록 핸들러 통합 테스트 — 멱등성 + 메타데이터 재조회 회피."""
import pytest

from application.monitoring.commands import (
    SubscribeChannelCommand,
    SubscribeChannelHandler,
)
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_channel_repository import SqliteChannelRepository


class _FakeBus:
    def publish_all(self, events) -> None:
        pass


class _RecordingYtDlp:
    """fetch_metadata 호출 여부를 기록하는 가짜 yt-dlp 어댑터."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch_metadata(self, url: str) -> dict:
        self.calls.append(url)
        return {"channel_id": "UC_resolved", "uploader": "조회된채널"}


@pytest.fixture
def repo(tmp_path):
    db = Database(path=tmp_path / "test.db")
    db.initialize()
    return SqliteChannelRepository(db)


def _handler(repo, ytdlp=None):
    return SubscribeChannelHandler(repo, _FakeBus(), ytdlp)


class TestSubscribeChannelHandler:
    def test_duplicate_channel_id_is_idempotent(self, repo):
        """같은 channel_id를 두 번 구독해도 IntegrityError 없이 1개만 남는다."""
        ytdlp = _RecordingYtDlp()
        h = _handler(repo, ytdlp)
        cmd = SubscribeChannelCommand(
            channel_url="https://www.youtube.com/channel/UC_dup",
            channel_id="UC_dup",
            channel_name="중복채널",
        )
        h.handle(cmd)
        h.handle(cmd)  # 재import 시뮬레이션 — 예외가 발생하면 안 된다

        assert len(repo.list_active()) == 1

    def test_provided_metadata_skips_fetch(self, repo):
        """id·name이 주어지면 yt-dlp 메타데이터 조회를 생략한다 (느린 루프 방지)."""
        ytdlp = _RecordingYtDlp()
        h = _handler(repo, ytdlp)
        h.handle(
            SubscribeChannelCommand(
                channel_url="https://www.youtube.com/channel/UC_known",
                channel_id="UC_known",
                channel_name="알려진채널",
            )
        )
        assert ytdlp.calls == []

    def test_missing_metadata_triggers_fetch(self, repo):
        """id가 없으면 (수동 URL 구독) 기존처럼 1회 조회한다."""
        ytdlp = _RecordingYtDlp()
        h = _handler(repo, ytdlp)
        h.handle(
            SubscribeChannelCommand(
                channel_url="https://www.youtube.com/@manual",
            )
        )
        assert ytdlp.calls == ["https://www.youtube.com/@manual"]
