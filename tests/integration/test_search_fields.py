"""검색이 제목·태그·설명·메모·요약·노래·가사를 모두 덮는지, 일치 필드를 정확히
보고하는지 검증한다.

핵심 회귀: lyrics_json 은 [{"o": 원문, "t": 번역}] 형태의 JSON 문자열이라
SQL LIKE 를 쓰면 검색어 'o'·'t' 가 JSON 키에 걸려 모든 노래를 오탐한다.
"""
from __future__ import annotations

import pytest

from domain.library.aggregates import VideoAggregate
from domain.library.repositories import MATCH_FIELD_KEYS, SearchQuery
from domain.library.value_objects import VideoUrl
from domain.song.aggregates import SongInfoAggregate
from domain.song.value_objects import LyricsLine
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_song_repository import SqliteSongRepository
from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository


@pytest.fixture
def db(tmp_path):
    d = Database(path=tmp_path / "search.db")
    d.initialize()
    return d


@pytest.fixture
def repo(db):
    return SqliteVideoRepository(db)


@pytest.fixture
def songs(db):
    return SqliteSongRepository(db)


def _add(repo, url, title, **meta):
    agg = VideoAggregate.create(VideoUrl(url), title)
    if meta:
        agg.update_metadata(**meta)
    repo.save(agg)
    return agg


def _ids(results):
    return {a.id for a in results}


class TestFieldCoverage:
    def test_title(self, repo):
        a = _add(repo, "https://youtu.be/t1", "파이썬 강의")
        _add(repo, "https://youtu.be/t2", "자바 강의")
        assert _ids(repo.search(SearchQuery(text="파이썬"))) == {a.id}

    def test_notes(self, repo):
        a = _add(repo, "https://youtu.be/n1", "무제", notes="레디스 캐시 정리")
        _add(repo, "https://youtu.be/n2", "무제2")
        assert _ids(repo.search(SearchQuery(text="레디스"))) == {a.id}

    def test_summary(self, repo):
        a = _add(repo, "https://youtu.be/s1", "무제", gemini_summary="옵시디언 활용법 요약")
        _add(repo, "https://youtu.be/s2", "무제2")
        assert _ids(repo.search(SearchQuery(text="옵시디언"))) == {a.id}

    def test_description(self, repo):
        a = _add(repo, "https://youtu.be/d1", "무제", description="이 영상은 도커를 다룬다")
        _add(repo, "https://youtu.be/d2", "무제2")
        assert _ids(repo.search(SearchQuery(text="도커"))) == {a.id}

    def test_tags(self, repo):
        a = _add(repo, "https://youtu.be/g1", "무제")
        tag = repo.get_or_create_tag("바이브코딩")
        a.set_tags([tag.id])
        repo.save(a)
        _add(repo, "https://youtu.be/g2", "무제2")
        assert _ids(repo.search(SearchQuery(text="바이브"))) == {a.id}

    def test_song_fields(self, repo, songs):
        a = _add(repo, "https://youtu.be/m1", "무제")
        s = SongInfoAggregate.create(a.id)
        s.set_song_flag(True)
        s.edit_field("artist", "모리카와 미호")
        songs.save(s)
        _add(repo, "https://youtu.be/m2", "무제2")
        assert _ids(repo.search(SearchQuery(text="모리카와"))) == {a.id}

    def test_lyrics(self, repo, songs):
        a = _add(repo, "https://youtu.be/l1", "무제")
        s = SongInfoAggregate.create(a.id)
        s.apply_fetched(
            lyrics_lines=[LyricsLine("You will be in my heart", "내 마음속에")],
            mark_song=True,
        )
        songs.save(s)
        _add(repo, "https://youtu.be/l2", "무제2")
        assert _ids(repo.search(SearchQuery(text="heart"))) == {a.id}
        assert _ids(repo.search(SearchQuery(text="마음속"))) == {a.id}


class TestLyricsJsonFalsePositive:
    """가사를 SQL LIKE 로 다루면 안 되는 이유를 고정한다."""

    def test_json_key_does_not_match(self, repo, songs):
        a = _add(repo, "https://youtu.be/j1", "무제")
        s = SongInfoAggregate.create(a.id)
        s.apply_fetched(lyrics_lines=[LyricsLine("Sunshine", "햇살")], mark_song=True)
        songs.save(s)

        # 'o'·'t' 는 lyrics_json 의 키 이름이다. 원문/번역에 없으므로 매칭되면 안 된다.
        assert _ids(repo.search(SearchQuery(text="o"))) == set()
        assert _ids(repo.search(SearchQuery(text="t"))) == set()

    def test_real_lyrics_word_still_matches(self, repo, songs):
        a = _add(repo, "https://youtu.be/j2", "무제")
        s = SongInfoAggregate.create(a.id)
        s.apply_fetched(lyrics_lines=[LyricsLine("Sunshine", "햇살")], mark_song=True)
        songs.save(s)
        assert _ids(repo.search(SearchQuery(text="Sunshine"))) == {a.id}


class TestSubstringAndEscaping:
    def test_partial_match_inside_word(self, repo):
        """한글 어미가 붙어도 찾아야 한다."""
        a = _add(repo, "https://youtu.be/p1", "가정부라고 개무시 받던")
        assert _ids(repo.search(SearchQuery(text="가정부"))) == {a.id}

    def test_case_insensitive_ascii(self, repo):
        a = _add(repo, "https://youtu.be/c1", "Obsidian 정리")
        assert _ids(repo.search(SearchQuery(text="obsidian"))) == {a.id}

    def test_percent_is_literal(self, repo):
        a = _add(repo, "https://youtu.be/e1", "할인 50% 행사")
        _add(repo, "https://youtu.be/e2", "관계없는 제목")
        assert _ids(repo.search(SearchQuery(text="50%"))) == {a.id}

    def test_underscore_is_literal(self, repo):
        a = _add(repo, "https://youtu.be/e3", "snake_case 규칙")
        _add(repo, "https://youtu.be/e4", "snakeXcase 규칙")
        assert _ids(repo.search(SearchQuery(text="snake_case"))) == {a.id}

    def test_empty_text_returns_all(self, repo):
        _add(repo, "https://youtu.be/a1", "하나")
        _add(repo, "https://youtu.be/a2", "둘")
        assert len(repo.search(SearchQuery(text=""))) == 2


class TestMatchFieldsFor:
    def test_reports_matching_field(self, repo):
        a = _add(repo, "https://youtu.be/f1", "파이썬 강의")
        result = repo.match_fields_for([a.id], "파이썬")
        assert result[a.id] == ("title",)

    def test_reports_multiple_fields(self, repo):
        a = _add(repo, "https://youtu.be/f2", "레디스 입문", notes="레디스 메모")
        result = repo.match_fields_for([a.id], "레디스")
        assert set(result[a.id]) == {"title", "notes"}

    def test_reports_lyrics_field(self, repo, songs):
        a = _add(repo, "https://youtu.be/f3", "무제")
        s = SongInfoAggregate.create(a.id)
        s.apply_fetched(lyrics_lines=[LyricsLine("Moonlight", "달빛")], mark_song=True)
        songs.save(s)
        result = repo.match_fields_for([a.id], "달빛")
        assert result[a.id] == ("lyrics",)

    def test_reports_song_field(self, repo, songs):
        a = _add(repo, "https://youtu.be/f4", "무제")
        s = SongInfoAggregate.create(a.id)
        s.set_song_flag(True)
        s.edit_field("album", "Blue Water")
        songs.save(s)
        result = repo.match_fields_for([a.id], "Blue")
        assert result[a.id] == ("song",)

    def test_empty_text_returns_empty(self, repo):
        a = _add(repo, "https://youtu.be/f5", "무제")
        assert repo.match_fields_for([a.id], "") == {}

    def test_empty_ids_returns_empty(self, repo):
        assert repo.match_fields_for([], "무엇") == {}

    def test_no_match_omits_video(self, repo):
        a = _add(repo, "https://youtu.be/f6", "무제")
        assert repo.match_fields_for([a.id], "없는키워드").get(a.id, ()) == ()

    def test_field_order_follows_match_field_keys(self, repo):
        """표시 순서가 MATCH_FIELD_KEYS 를 따라 실행마다 흔들리지 않아야 한다."""
        a = _add(repo, "https://youtu.be/f7", "키워드", notes="키워드", gemini_summary="키워드")
        got = repo.match_fields_for([a.id], "키워드")[a.id]

        assert set(got) == {"title", "notes", "summary"}
        assert list(got) == [k for k in MATCH_FIELD_KEYS if k in set(got)]
