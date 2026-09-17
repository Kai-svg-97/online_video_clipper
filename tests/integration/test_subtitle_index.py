"""자막 색인 저장소 + 라이브러리 검색 통합.

가장 중요한 계약은 **검색 규칙이 다른 속성과 같아야 한다**는 것이다. 제목은 부분
일치로 찾는데 자막만 단어 단위로 찾으면, 사용자에게는 "검색이 가끔 안 된다"로 보인다.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from domain.library.aggregates import VideoAggregate
from domain.library.repositories import SearchQuery
from domain.library.subtitle_repository import SubtitleLine
from domain.library.value_objects import VideoUrl
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_subtitle_repository import SqliteSubtitleRepository
from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository


@pytest.fixture
def db():
    path = Path(tempfile.mkdtemp()) / "t.db"
    database = Database(path)
    database.initialize()
    return database


@pytest.fixture
def repo(db):
    return SqliteSubtitleRepository(db)


@pytest.fixture
def videos(db):
    return SqliteVideoRepository(db)


def _add_video(videos, title="영상", url=None) -> VideoAggregate:
    agg = VideoAggregate.create(
        url=VideoUrl(url or f"https://youtu.be/{uuid4().hex[:11]}"), title=title
    )
    videos.save(agg)
    return agg


def _lines(*texts) -> list[SubtitleLine]:
    return [
        SubtitleLine(start_ms=i * 1000, end_ms=(i + 1) * 1000, text=t)
        for i, t in enumerate(texts)
    ]


class TestStore:
    def test_저장하고_읽는다(self, repo, videos):
        agg = _add_video(videos)
        repo.replace_lines(agg.id, "ko", "한국어", _lines("첫 줄", "둘째 줄"))
        got = repo.list_lines(agg.id)
        assert [ln.text for ln in got] == ["첫 줄", "둘째 줄"]

    def test_시작_시각_순으로_돌려준다(self, repo, videos):
        agg = _add_video(videos)
        repo.replace_lines(agg.id, "ko", "", [
            SubtitleLine(5000, 6000, "나중"),
            SubtitleLine(1000, 2000, "먼저"),
        ])
        assert [ln.text for ln in repo.list_lines(agg.id)] == ["먼저", "나중"]

    def test_다시_저장하면_통째로_바뀐다(self, repo, videos):
        """자동 자막이 사람 자막으로 바뀌는 일이 흔하다 — 줄 단위 병합은 중복만 만든다."""
        agg = _add_video(videos)
        repo.replace_lines(agg.id, "ko", "", _lines("옛날"))
        repo.replace_lines(agg.id, "ko", "", _lines("새것", "하나 더"))
        assert [ln.text for ln in repo.list_lines(agg.id)] == ["새것", "하나 더"]

    def test_빈_목록을_주면_그_언어_색인을_지운다(self, repo, videos):
        agg = _add_video(videos)
        repo.replace_lines(agg.id, "ko", "", _lines("있다"))
        repo.replace_lines(agg.id, "ko", "", [])
        assert repo.list_indexes(agg.id) == []

    def test_언어가_여럿이면_따로_보관한다(self, repo, videos):
        agg = _add_video(videos)
        repo.replace_lines(agg.id, "ko", "한국어", _lines("안녕"))
        repo.replace_lines(agg.id, "en", "English", _lines("hello"))
        assert [i.lang for i in repo.list_indexes(agg.id)] == ["en", "ko"]
        assert [ln.text for ln in repo.list_lines(agg.id, "en")] == ["hello"]

    def test_언어를_고르지_않으면_첫_언어를_쓴다(self, repo, videos):
        agg = _add_video(videos)
        repo.replace_lines(agg.id, "ko", "", _lines("안녕"))
        repo.replace_lines(agg.id, "en", "", _lines("hello"))
        assert [ln.text for ln in repo.list_lines(agg.id)] == ["hello"]  # 'en' < 'ko'

    def test_색인_정보에_줄_수가_담긴다(self, repo, videos):
        agg = _add_video(videos)
        repo.replace_lines(agg.id, "ko", "한국어", _lines("a", "b", "c"))
        info = repo.list_indexes(agg.id)[0]
        assert (info.lang, info.label, info.line_count) == ("ko", "한국어", 3)

    def test_지우면_줄과_색인이_함께_사라진다(self, repo, videos):
        agg = _add_video(videos)
        repo.replace_lines(agg.id, "ko", "", _lines("있다"))
        repo.delete(agg.id)
        assert repo.list_lines(agg.id) == []
        assert repo.list_indexes(agg.id) == []

    def test_색인된_영상_id_목록(self, repo, videos):
        a, b = _add_video(videos), _add_video(videos)
        repo.replace_lines(a.id, "ko", "", _lines("있다"))
        assert repo.indexed_video_ids() == {a.id}
        assert b.id not in repo.indexed_video_ids()


class TestSearchWithinVideo:
    def test_부분_일치로_찾는다(self, repo, videos):
        """'가정부'로 '가정부라고'를 찾아야 한다 — 앱의 다른 검색과 같은 규칙."""
        agg = _add_video(videos)
        repo.replace_lines(agg.id, "ko", "", _lines("그게 가정부라고 하더군요", "다른 줄"))
        got = repo.search_lines(agg.id, "가정부")
        assert [ln.text for ln in got] == ["그게 가정부라고 하더군요"]

    def test_결과에_시작_시각이_담긴다(self, repo, videos):
        agg = _add_video(videos)
        repo.replace_lines(agg.id, "ko", "", [SubtitleLine(90_000, 92_000, "찾는 말")])
        assert repo.search_lines(agg.id, "찾는")[0].start_ms == 90_000

    def test_다른_영상의_자막은_섞이지_않는다(self, repo, videos):
        a, b = _add_video(videos), _add_video(videos)
        repo.replace_lines(a.id, "ko", "", _lines("사과"))
        repo.replace_lines(b.id, "ko", "", _lines("사과"))
        assert len(repo.search_lines(a.id, "사과")) == 1

    def test_LIKE_특수문자가_와일드카드로_동작하지_않는다(self, repo, videos):
        agg = _add_video(videos)
        repo.replace_lines(agg.id, "ko", "", _lines("100% 확실", "아무 말"))
        assert [ln.text for ln in repo.search_lines(agg.id, "100%")] == ["100% 확실"]
        # '%'를 와일드카드로 흘려보내면 모든 줄이 걸린다 — 리터럴로 취급돼야 한다.
        assert [ln.text for ln in repo.search_lines(agg.id, "%")] == ["100% 확실"]

    def test_빈_검색어는_빈_목록(self, repo, videos):
        agg = _add_video(videos)
        repo.replace_lines(agg.id, "ko", "", _lines("아무 말"))
        assert repo.search_lines(agg.id, "") == []


class TestLibrarySearchIntegration:
    def test_자막에만_있는_말로도_영상을_찾는다(self, repo, videos):
        agg = _add_video(videos, title="제목에는 없음")
        repo.replace_lines(agg.id, "ko", "", _lines("여기 코끼리가 나온다"))
        found = videos.search(SearchQuery(text="코끼리"))
        assert [a.id for a in found] == [agg.id]

    def test_자막_일치는_subtitle_배지로_표시된다(self, repo, videos):
        agg = _add_video(videos, title="제목에는 없음")
        repo.replace_lines(agg.id, "ko", "", _lines("여기 코끼리가 나온다"))
        fields = videos.match_fields_for([agg.id], "코끼리")
        assert fields[agg.id] == ("subtitle",)

    def test_색인이_없으면_자막으로는_찾히지_않는다(self, videos):
        _add_video(videos, title="제목에는 없음")
        assert videos.search(SearchQuery(text="코끼리")) == []

    def test_제목과_자막에_모두_있으면_배지가_둘_다_뜬다(self, repo, videos):
        agg = _add_video(videos, title="코끼리 다큐")
        repo.replace_lines(agg.id, "ko", "", _lines("코끼리가 나온다"))
        assert videos.match_fields_for([agg.id], "코끼리")[agg.id] == ("title", "subtitle")
