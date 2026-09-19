"""저장된 검색 값 객체 — 직렬화와 이름 규칙.

## 왜 날짜를 값이 아니라 프리셋 키로 담나

"최근 1주"를 `published_from="2026-09-12"`로 굳혀 저장하면, 다음 달에 그 검색을 열었을
때 **그 주의 영상만** 나온다. 사용자가 기대한 것은 "지금으로부터 최근 1주"다. 이 규칙이
깨지면 예외도 오류도 없이 **조용히 엉뚱한 결과**가 나오므로 여기서 고정한다.
"""

from __future__ import annotations

import json
from uuid import uuid4

from domain.library.saved_search import (
    MAX_NAME_LEN,
    SavedSearch,
    normalize_name,
    unique_name,
)


class TestSerialization:
    def test_조건만_담고_이름과_id는_빼둔다(self):
        """그 둘은 DB 열이다 — JSON에 또 담으면 두 곳이 어긋난다."""
        payload = json.loads(SavedSearch(name="내 검색", text="클로드").to_json())

        assert "name" not in payload
        assert "id" not in payload
        assert payload["text"] == "클로드"

    def test_날짜를_키로_담는다(self):
        payload = json.loads(SavedSearch(date_key="7d").to_json())
        assert payload["date_key"] == "7d"

    def test_왕복해도_같다(self):
        sid = uuid4()
        original = SavedSearch(
            id=sid, name="이름", text="말", date_key="30d", duration_key="short",
            download_key="no", watched_key="yes", channel_name="채널",
            favorite_only=True,
        )

        restored = SavedSearch.from_json(sid, "이름", original.to_json())

        assert restored == original

    def test_한글이_깨지지_않는다(self):
        raw = SavedSearch(text="침착맨").to_json()
        assert "침착맨" in raw


class TestFromJsonSurvivesGarbage:
    """앱 버전을 오르내리며 필드가 바뀌고, 사용자가 DB를 손볼 수도 있다.

    그때 저장된 검색 하나 때문에 목록 전체가 안 뜨면 기능이 통째로 죽는다.
    """

    def test_JSON이_아니어도_산다(self):
        got = SavedSearch.from_json(uuid4(), "이름", "{깨진 것")
        assert got.name == "이름"
        assert got.text == ""

    def test_빈_문자열도_산다(self):
        assert SavedSearch.from_json(uuid4(), "이름", "").date_key == "all"

    def test_JSON이지만_객체가_아니면_무시한다(self):
        assert SavedSearch.from_json(uuid4(), "이름", "[1, 2, 3]").text == ""

    def test_모르는_키는_버린다(self):
        raw = '{"text": "살아남음", "옛날필드": 1, "또다른것": null}'
        assert SavedSearch.from_json(uuid4(), "이름", raw).text == "살아남음"

    def test_빠진_키는_기본값으로_채운다(self):
        got = SavedSearch.from_json(uuid4(), "이름", '{"text": "일부만"}')
        assert got.duration_key == "all"
        assert got.favorite_only is False


class TestIsEmpty:
    def test_아무_조건도_없으면_빈_것이다(self):
        """되불러도 아무 일이 없는 것을 저장하게 두면 목록만 지저분해진다."""
        assert SavedSearch(name="이름만").is_empty is True

    def test_공백뿐인_검색어는_조건이_아니다(self):
        assert SavedSearch(text="   ").is_empty is True

    def test_하나라도_있으면_빈_것이_아니다(self):
        assert SavedSearch(text="말").is_empty is False
        assert SavedSearch(date_key="7d").is_empty is False
        assert SavedSearch(favorite_only=True).is_empty is False
        assert SavedSearch(channel_name="채널").is_empty is False

    def test_전체를_고른_것은_조건이_아니다(self):
        assert SavedSearch(date_key="all", duration_key="all").is_empty is True


class TestNames:
    def test_앞뒤_공백과_중복_공백을_턴다(self):
        assert normalize_name("  긴   이름  ") == "긴 이름"

    def test_너무_길면_자른다(self):
        assert len(normalize_name("가" * 100)) == MAX_NAME_LEN

    def test_빈_이름은_빈_문자열(self):
        assert normalize_name("   ") == ""
        assert normalize_name(None) == ""

    def test_겹치지_않으면_그대로(self):
        assert unique_name("내 검색", ["다른 것"]) == "내 검색"

    def test_겹치면_번호를_붙인다(self):
        """거절하고 다시 묻는 대신 붙여 준다 — 저장은 곁가지 행동이다."""
        assert unique_name("내 검색", ["내 검색"]) == "내 검색 2"

    def test_번호도_겹치면_계속_올린다(self):
        existing = ["내 검색", "내 검색 2", "내 검색 3"]
        assert unique_name("내 검색", existing) == "내 검색 4"

    def test_이름이_비면_기본값을_준다(self):
        assert unique_name("   ", []) == "저장된 검색"
