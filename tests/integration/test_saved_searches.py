"""저장된 검색 보관 — 진짜 SQLite 로.

여기서 지키는 것은 "넣으면 나온다"가 아니라 **깨져도 살아남는가**다. 저장된 검색은
사용자가 DB를 손볼 수도, 앱 버전을 오르내리며 필드가 바뀔 수도 있는 값인데, 그때
한 줄 때문에 목록 전체가 안 뜨면 기능이 통째로 죽는다.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from domain.library.saved_search import MAX_SAVED, SavedSearch
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_saved_search_repository import (
    SqliteSavedSearchRepository,
)


@pytest.fixture
def repo(tmp_path):
    db = Database(path=tmp_path / "saved.db")
    db.initialize()
    return SqliteSavedSearchRepository(db)


def _make(name="내 검색", **kw) -> SavedSearch:
    return SavedSearch(name=name, **kw)


class TestRoundTrip:
    def test_넣은_조건이_그대로_나온다(self, repo):
        repo.save(_make(text="클로드", date_key="7d", duration_key="long",
                        download_key="yes", watched_key="no",
                        channel_name="침착맨", favorite_only=True))

        got = repo.list_all()[0]

        assert got.text == "클로드"
        assert got.date_key == "7d"
        assert got.duration_key == "long"
        assert got.download_key == "yes"
        assert got.watched_key == "no"
        assert got.channel_name == "침착맨"
        assert got.favorite_only is True

    def test_날짜를_값이_아니라_키로_담는다(self, repo):
        """값으로 굳히면 '최근 1주'가 저장한 그 주로 얼어붙는다."""
        repo.save(_make(date_key="7d"))

        with repo._db.connection() as conn:
            raw = conn.execute("SELECT query_json FROM saved_searches").fetchone()[0]

        assert '"7d"' in raw
        assert "2026-" not in raw          # 풀린 날짜가 들어가 있으면 안 된다

    def test_저장한_순서를_지킨다(self, repo):
        for name in ("가", "나", "다"):
            repo.save(_make(name=name, text=name))

        assert [s.name for s in repo.list_all()] == ["가", "나", "다"]

    def test_이름의_앞뒤_공백을_턴다(self, repo):
        repo.save(_make(name="  긴  이름  "))
        assert repo.list_all()[0].name == "긴 이름"

    def test_이름이_비면_기본값을_준다(self, repo):
        """빈 이름이면 목록에서 고를 수 없다."""
        repo.save(_make(name="   "))
        assert repo.list_all()[0].name


class TestUpdate:
    def test_같은_id로_덮어쓴다(self, repo):
        s = _make(text="처음")
        repo.save(s)
        repo.save(SavedSearch(id=s.id, name=s.name, text="바뀜"))

        rows = repo.list_all()
        assert len(rows) == 1
        assert rows[0].text == "바뀜"

    def test_이름만_바꾼다(self, repo):
        s = _make(text="조건 유지")
        repo.save(s)

        repo.rename(s.id, "새 이름")

        got = repo.list_all()[0]
        assert got.name == "새 이름"
        assert got.text == "조건 유지"

    def test_빈_이름으로는_바꾸지_않는다(self, repo):
        s = _make(name="원래")
        repo.save(s)

        repo.rename(s.id, "   ")

        assert repo.list_all()[0].name == "원래"

    def test_지우면_사라진다(self, repo):
        s = _make()
        repo.save(s)
        repo.delete(s.id)
        assert repo.list_all() == []

    def test_없는_것을_지워도_조용하다(self, repo):
        repo.delete(uuid4())


class TestLimit:
    def test_상한을_넘기면_오래된_것을_밀어낸다(self, repo):
        """저장을 거절하면 사용자는 뭘 지워야 할지 모른 채 막힌다."""
        for i in range(MAX_SAVED + 5):
            repo.save(_make(name=f"검색 {i:03d}", text=f"q{i}"))

        rows = repo.list_all()
        assert len(rows) == MAX_SAVED
        assert rows[-1].name == f"검색 {MAX_SAVED + 4:03d}"      # 최신은 남는다
        assert "검색 000" not in {r.name for r in rows}          # 가장 오래된 건 빠진다


class TestCorruptRows:
    def _insert_raw(self, repo, query_json: str, name: str = "깨진 것"):
        with repo._db.connection() as conn:
            conn.execute(
                "INSERT INTO saved_searches (id, name, query_json, sort_order, created_at) "
                "VALUES (?, ?, ?, 0, '2026-01-01')",
                (str(uuid4()), name, query_json),
            )
            conn.commit()

    def test_JSON이_깨져도_목록이_뜬다(self, repo):
        self._insert_raw(repo, "{이건 JSON이 아니다")
        repo.save(_make(name="멀쩡한 것"))

        names = {s.name for s in repo.list_all()}

        assert "멀쩡한 것" in names
        assert "깨진 것" in names          # 조건만 기본값으로 떨어질 뿐 사라지지 않는다

    def test_모르는_키는_버린다(self, repo):
        """앱 버전을 오르내리면 필드가 늘거나 준다."""
        self._insert_raw(repo, '{"text": "살아남음", "없는필드": 1}')

        got = repo.list_all()[0]

        assert got.text == "살아남음"

    def test_빠진_키는_기본값으로_채운다(self, repo):
        self._insert_raw(repo, '{"text": "일부만"}')

        got = repo.list_all()[0]

        assert got.date_key == "all"
        assert got.favorite_only is False

    def test_id가_깨진_행은_건너뛴다(self, repo):
        with repo._db.connection() as conn:
            conn.execute(
                "INSERT INTO saved_searches (id, name, query_json, sort_order, created_at) "
                "VALUES ('uuid가-아님', '나쁜 행', '{}', 0, '2026-01-01')"
            )
            conn.commit()
        repo.save(_make(name="멀쩡한 것"))

        assert [s.name for s in repo.list_all()] == ["멀쩡한 것"]
