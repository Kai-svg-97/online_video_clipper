"""챕터 조회 + 여러 구간 순차 추출 유스케이스.

핵심 규칙은 두 가지다 — **한 구간이 실패해도 나머지를 계속한다**(20개 중 3번째가
깨졌다고 17개를 버리면 사용자는 어디까지 됐는지 알 수 없다), 그리고 **끝을 모르는
구간은 만들지 않는다**.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from application.clip.commands import ExtractClipsCommand, ExtractClipsHandler
from application.clip.queries import GetChaptersHandler, GetChaptersQuery


class _FakeExtract:
    """`ExtractClipHandler` 대역 — 제목이 'boom'인 구간만 터진다."""

    def __init__(self):
        self.seen: list[tuple[str, float, float]] = []

    def handle(self, cmd):
        self.seen.append((cmd.title, cmd.start_sec, cmd.end_sec))
        if cmd.title == "boom":
            raise RuntimeError("ffmpeg 실패")
        return type("Agg", (), {"id": uuid4(), "clip": None})()


class TestExtractMany:
    def test_모든_구간을_순서대로_추출한다(self):
        fake = _FakeExtract()
        done, failed = ExtractClipsHandler(fake).handle(
            ExtractClipsCommand(uuid4(), "C:/a.mp4", [("A", 0.0, 10.0), ("B", 10.0, 20.0)])
        )
        assert [t for t, _, _ in fake.seen] == ["A", "B"]
        assert len(done) == 2
        assert failed == []

    def test_한_구간이_실패해도_나머지를_계속한다(self):
        fake = _FakeExtract()
        done, failed = ExtractClipsHandler(fake).handle(
            ExtractClipsCommand(
                uuid4(), "C:/a.mp4",
                [("A", 0.0, 1.0), ("boom", 1.0, 2.0), ("C", 2.0, 3.0)],
            )
        )
        assert [t for t, _, _ in fake.seen] == ["A", "boom", "C"]
        assert len(done) == 2
        assert [t for t, _ in failed] == ["boom"]

    def test_진행_콜백은_1부터_전체까지_센다(self):
        seen: list[tuple[int, int, str]] = []
        ExtractClipsHandler(_FakeExtract()).handle(
            ExtractClipsCommand(uuid4(), "C:/a.mp4", [("A", 0.0, 1.0), ("B", 1.0, 2.0)]),
            on_progress=lambda i, total, title: seen.append((i, total, title)),
        )
        assert seen == [(1, 2, "A"), (2, 2, "B")]

    def test_빈_목록이면_아무것도_하지_않는다(self):
        fake = _FakeExtract()
        done, failed = ExtractClipsHandler(fake).handle(
            ExtractClipsCommand(uuid4(), "C:/a.mp4", [])
        )
        assert (fake.seen, done, failed) == ([], [], [])


# ----------------------------------------------------------------------


class _Duration:
    def __init__(self, seconds):
        self.seconds = seconds


class _VideoRepo:
    def __init__(self, description="", duration=None):
        self._agg = type(
            "Agg", (), {"video": type("V", (), {
                "description": description,
                "duration": _Duration(duration) if duration is not None else None,
            })()},
        )()

    def get_by_id(self, video_id):
        return self._agg


class _EmptyRepo:
    def get_by_id(self, video_id):
        return None


class TestGetChapters:
    def test_설명에서_챕터를_뽑는다(self):
        repo = _VideoRepo("0:00 인트로\n1:00 본론", duration=180)
        chapters = GetChaptersHandler(repo).handle(GetChaptersQuery(video_id=uuid4()))
        assert [(c.title, c.start_sec, c.end_sec) for c in chapters] == [
            ("인트로", 0.0, 60.0),
            ("본론", 60.0, 180.0),
        ]

    def test_없는_영상이면_빈_목록(self):
        assert GetChaptersHandler(_EmptyRepo()).handle(GetChaptersQuery(uuid4())) == []

    def test_설명이_없으면_빈_목록(self):
        repo = _VideoRepo("", duration=180)
        assert GetChaptersHandler(repo).handle(GetChaptersQuery(uuid4())) == []

    def test_길이를_모르면_마지막_구간을_만들지_않는다(self):
        repo = _VideoRepo("0:00 A\n1:00 B\n2:00 C", duration=None)
        chapters = GetChaptersHandler(repo).handle(GetChaptersQuery(uuid4()))
        assert [c.title for c in chapters] == ["A", "B"]

    def test_DTO_길이_속성(self):
        repo = _VideoRepo("0:00 A\n0:30 B", duration=100)
        chapters = GetChaptersHandler(repo).handle(GetChaptersQuery(uuid4()))
        assert chapters[0].duration_sec == pytest.approx(30.0)
