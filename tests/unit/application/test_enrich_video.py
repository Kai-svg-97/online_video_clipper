"""EnrichVideoHandler 단위 테스트 — 등록 시 요약/가사 자동 보강 분기.

핵심 규약:
- is_song=True면 가사만 조회하고 요약 추출기는 건드리지 않는다.
- is_song=False면 요약만 추출한다.
- 가사를 찾지 못하면 **폴백 없이 종료**한다(요약으로 넘어가지 않는다).
- 이미 값이 있으면 건너뛴다(kind="skipped" 또는 ok=True + 안내 detail).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from application.library.commands import (
    EnrichVideoCommand,
    EnrichVideoHandler,
)


class _FakeSummarySource:
    """호출 횟수를 기록하는 가짜 요약 추출기."""

    def __init__(self, summary: str = "요약 본문") -> None:
        self._summary = summary
        self.calls: list[str] = []

    def extract(self, url: str) -> str:
        self.calls.append(url)
        return self._summary


def _video_agg(gemini_summary: str = "", url: str = "https://youtu.be/abc"):
    """VideoAggregate 대역 — 핸들러가 쓰는 속성만 갖춘다."""
    return SimpleNamespace(
        id=uuid4(),
        video=SimpleNamespace(url=url, gemini_summary=gemini_summary),
        update_metadata=MagicMock(),
        pull_events=MagicMock(return_value=[]),
    )


def _song_agg(is_song: bool, lyrics_lines=None):
    return SimpleNamespace(
        info=SimpleNamespace(is_song=is_song, lyrics_lines=list(lyrics_lines or []))
    )


def _make(video_agg, song_agg, song_fetch=None, summary_source=None):
    repo = MagicMock()
    repo.get_by_id.return_value = video_agg
    song_repo = MagicMock()
    song_repo.get.return_value = song_agg
    handler = EnrichVideoHandler(
        repo=repo,
        song_repo=song_repo,
        song_fetch=song_fetch,
        summary_source=summary_source,
        event_bus=MagicMock(),
    )
    return handler, repo, song_repo


class TestSongBranch:
    def test_song_fetches_lyrics_and_never_touches_summary(self):
        """노래 영상은 가사만 조회하고 요약 추출기는 호출되지 않는다."""
        song_fetch = MagicMock()
        song_fetch.handle.return_value = _song_agg(True, ["1행", "2행"])
        summary = _FakeSummarySource()
        handler, _repo, _ = _make(
            _video_agg(), _song_agg(True), song_fetch, summary
        )

        result = handler.handle(EnrichVideoCommand(video_id=uuid4()))

        assert result.kind == "song"
        assert result.ok is True
        assert summary.calls == []          # 요약은 절대 시도하지 않는다
        cmd = song_fetch.handle.call_args.args[0]
        assert cmd.fetch_lyrics is True

    def test_lyrics_not_found_does_not_fall_back_to_summary(self):
        """가사를 못 찾아도 요약으로 폴백하지 않는다(확정된 정책)."""
        song_fetch = MagicMock()
        song_fetch.handle.return_value = _song_agg(True, [])   # 가사 없음
        summary = _FakeSummarySource()
        handler, _repo, _ = _make(
            _video_agg(), _song_agg(True), song_fetch, summary
        )

        result = handler.handle(EnrichVideoCommand(video_id=uuid4()))

        assert result.kind == "song"
        assert result.ok is False
        assert summary.calls == []

    def test_existing_lyrics_skipped(self):
        """가사가 이미 있으면 재조회하지 않는다."""
        song_fetch = MagicMock()
        handler, _repo, _ = _make(
            _video_agg(), _song_agg(True, ["이미 있음"]), song_fetch, _FakeSummarySource()
        )

        result = handler.handle(EnrichVideoCommand(video_id=uuid4()))

        assert result.ok is True
        assert song_fetch.handle.call_count == 0

    def test_song_fetch_exception_isolated(self):
        """가사 조회가 예외를 던져도 ok=False로 변환되고 전파되지 않는다."""
        song_fetch = MagicMock()
        song_fetch.handle.side_effect = RuntimeError("네트워크 실패")
        handler, _repo, _ = _make(_video_agg(), _song_agg(True), song_fetch, None)

        result = handler.handle(EnrichVideoCommand(video_id=uuid4()))

        assert result.kind == "song"
        assert result.ok is False
        assert "네트워크 실패" in result.detail


class TestSummaryBranch:
    def test_non_song_extracts_summary_and_saves(self):
        """비노래 영상은 요약을 추출해 저장한다."""
        summary = _FakeSummarySource("이 영상은 …")
        video = _video_agg(url="https://youtu.be/xyz")
        handler, repo, _ = _make(video, _song_agg(False), MagicMock(), summary)

        result = handler.handle(EnrichVideoCommand(video_id=uuid4()))

        assert result.kind == "summary"
        assert result.ok is True
        assert summary.calls == ["https://youtu.be/xyz"]
        video.update_metadata.assert_called_once_with(gemini_summary="이 영상은 …")
        repo.save.assert_called_once_with(video)

    def test_no_song_row_treated_as_non_song(self):
        """노래 정보 행이 없으면(yt-dlp 조회 실패 등) 비노래로 취급한다."""
        summary = _FakeSummarySource()
        handler, _repo, _ = _make(_video_agg(), None, MagicMock(), summary)

        result = handler.handle(EnrichVideoCommand(video_id=uuid4()))

        assert result.kind == "summary"
        assert len(summary.calls) == 1

    def test_existing_summary_skipped(self):
        """요약이 이미 있으면 추출하지 않는다."""
        summary = _FakeSummarySource()
        handler, repo, _ = _make(
            _video_agg(gemini_summary="기존 요약"), _song_agg(False), MagicMock(), summary
        )

        result = handler.handle(EnrichVideoCommand(video_id=uuid4()))

        assert result.kind == "skipped"
        assert summary.calls == []
        repo.save.assert_not_called()

    def test_empty_summary_reports_cookie_hint(self):
        """빈 문자열 반환(미로그인)은 쿠키 안내 메시지로 보고한다."""
        handler, repo, _ = _make(
            _video_agg(), _song_agg(False), MagicMock(), _FakeSummarySource("")
        )

        result = handler.handle(EnrichVideoCommand(video_id=uuid4()))

        assert result.ok is False
        assert "쿠키" in result.detail
        repo.save.assert_not_called()

    def test_missing_summary_source_skipped(self):
        """요약 추출기가 주입되지 않아도 예외 없이 skipped."""
        handler, _repo, _ = _make(_video_agg(), _song_agg(False), MagicMock(), None)

        result = handler.handle(EnrichVideoCommand(video_id=uuid4()))

        assert result.kind == "skipped"
        assert result.ok is False


class TestGuards:
    def test_missing_video_skipped(self):
        handler, repo, _ = _make(None, None, MagicMock(), _FakeSummarySource())

        result = handler.handle(EnrichVideoCommand(video_id=uuid4()))

        assert result.kind == "skipped"
        assert result.ok is False

    def test_is_song_video_label_helper(self):
        """상태바 라벨용 사전 판정."""
        handler, _repo, _ = _make(_video_agg(), _song_agg(True))
        assert handler.is_song_video(uuid4()) is True

        handler2, _r2, _ = _make(_video_agg(), _song_agg(False))
        assert handler2.is_song_video(uuid4()) is False

    def test_is_song_video_swallows_repo_error(self):
        handler, _repo, song_repo = _make(_video_agg(), _song_agg(True))
        song_repo.get.side_effect = RuntimeError("DB 오류")
        assert handler.is_song_video(uuid4()) is False
