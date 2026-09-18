"""자막 색인 → 제안 구간 쿼리(실제 DB).

이 기능은 **자막 위에서만** 성립한다. 색인이 없으면 조용히 빈 목록이어야 하고,
있으면 챕터와 같은 형태(ChapterDTO)로 나와야 한다 — 화면이 기존 챕터 흐름을 그대로
재사용하기 때문이다.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from application.clip.queries import GetHighlightsHandler, GetHighlightsQuery
from domain.library.aggregates import VideoAggregate
from domain.library.subtitle_repository import SubtitleLine
from domain.library.value_objects import Duration, VideoUrl
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_subtitle_repository import SqliteSubtitleRepository
from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository


@pytest.fixture
def repos():
    db = Database(Path(tempfile.mkdtemp()) / "t.db")
    db.initialize()
    return SqliteVideoRepository(db), SqliteSubtitleRepository(db)


def _video(videos, description="", duration=600):
    agg = VideoAggregate.create(
        url=VideoUrl(f"https://youtu.be/{uuid4().hex[:11]}"), title="영상"
    )
    agg.update_metadata(duration=Duration(duration), description=description)
    videos.save(agg)
    return agg


def _index(subs, video_id, spec):
    """`(시작초, 길이초, 글자수)` 목록을 자막으로 넣는다."""
    lines = [
        SubtitleLine(int(s * 1000), int((s + d) * 1000), "말" * c) for s, d, c in spec
    ]
    subs.replace_lines(video_id, "ko", "한국어", lines)


def _handle(repos, agg, limit=5):
    videos, subs = repos
    return GetHighlightsHandler(subs, videos).handle(
        GetHighlightsQuery(video_id=agg.id, limit=limit)
    )


class TestNoSubtitles:
    def test_색인이_없으면_빈_목록(self, repos):
        videos, _ = repos
        assert _handle(repos, _video(videos)) == []

    def test_없는_영상이면_빈_목록(self, repos):
        videos, subs = repos
        handler = GetHighlightsHandler(subs, videos)
        assert handler.handle(GetHighlightsQuery(video_id=uuid4())) == []


class TestSuggestions:
    def test_말이_몰린_구간을_제안한다(self, repos):
        videos, subs = repos
        agg = _video(videos)
        _index(subs, agg.id, [(60, 5, 5)] + [(300 + i * 4, 4, 60) for i in range(12)])

        picks = _handle(repos, agg, limit=1)

        assert picks and 280 <= picks[0].start_sec <= 320

    def test_챕터_형태로_돌려준다(self, repos):
        """화면이 기존 챕터 흐름(체크박스 + 일괄 추출)을 그대로 쓴다."""
        videos, subs = repos
        agg = _video(videos)
        _index(subs, agg.id, [(100 + i * 5, 5, 40) for i in range(10)])

        pick = _handle(repos, agg, limit=1)[0]

        assert pick.title and pick.end_sec > pick.start_sec
        assert pick.duration_sec > 0

    def test_설명의_챕터를_반영한다(self, repos):
        videos, subs = repos
        agg = _video(videos, description="0:00 인트로\n5:00 본론\n8:00 마무리")
        _index(subs, agg.id, [(302 + i * 4, 4, 50) for i in range(10)])

        picks = _handle(repos, agg, limit=1)

        assert picks[0].start_sec == 300.0
        assert picks[0].title == "본론"

    def test_상한을_지킨다(self, repos):
        videos, subs = repos
        agg = _video(videos, duration=1200)
        _index(subs, agg.id, [(i * 20, 15, 50) for i in range(50)])

        assert len(_handle(repos, agg, limit=3)) <= 3

    def test_영상_길이를_넘지_않는다(self, repos):
        videos, subs = repos
        agg = _video(videos, duration=300)
        _index(subs, agg.id, [(270 + i * 3, 3, 50) for i in range(10)])

        assert all(p.end_sec <= 300 for p in _handle(repos, agg))

    def test_음성_인식_자막으로도_동작한다(self, repos):
        """전사 결과는 별도 언어키로 저장되는데, 그것도 읽어야 한다."""
        videos, subs = repos
        agg = _video(videos)
        lines = [
            SubtitleLine(int(s * 1000), int((s + 4) * 1000), "말" * 50)
            for s in range(200, 260, 4)
        ]
        subs.replace_lines(agg.id, "asr-auto", "음성 인식", lines)

        assert _handle(repos, agg, limit=1)
