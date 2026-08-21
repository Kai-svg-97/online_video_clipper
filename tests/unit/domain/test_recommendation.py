"""추천 검색어 파생 규칙(순수 도메인 로직)을 고정한다.

이 규칙이 흔들리면 추천 품질이 조용히 나빠지는데(검색어가 노이즈로 채워지거나
목록을 대표하지 못함) 화면만 봐서는 원인을 알 수 없다. 규칙을 테스트로 못박는다.
"""
from __future__ import annotations

from domain.library.recommendation import derive_seed_queries


class TestSeedQueries:
    def test_empty_input_returns_no_queries(self):
        assert derive_seed_queries([]) == []
        assert derive_seed_queries([], channels=[], tags=[]) == []

    def test_shared_title_keyword_becomes_first_query(self):
        queries = derive_seed_queries(
            [
                "[MV] 아이유 - 밤편지 (Official Video)",
                "아이유 좋은날",
                "아이유 - Blueming",
            ]
        )
        # 세 제목 모두에 있는 '아이유'가 대표 키워드다.
        assert queries[0] == "아이유"

    def test_bracketed_and_stopword_noise_is_dropped(self):
        queries = derive_seed_queries(
            ["[MV] 쏘스뮤직 (Official Video) 4K", "쏘스뮤직 Official Audio 1080p"]
        )
        assert queries[0] == "쏘스뮤직"

    def test_order_is_keywords_then_tag_then_channel(self):
        queries = derive_seed_queries(
            titles=["파이썬 강의 1", "파이썬 강의 2"],
            channels=["코딩채널", "코딩채널", "다른채널"],
            tags=["개발", "개발", "취미"],
        )
        assert queries == ["파이썬 강의", "개발", "코딩채널"]

    def test_max_queries_is_respected(self):
        queries = derive_seed_queries(
            titles=["파이썬 강의 1", "파이썬 강의 2"],
            channels=["코딩채널"],
            tags=["개발"],
            max_queries=2,
        )
        assert len(queries) == 2

    def test_duplicate_queries_are_removed_case_insensitively(self):
        # 태그와 채널명이 같으면 같은 검색을 두 번 돌리지 않는다.
        queries = derive_seed_queries(
            titles=["Rust 튜토리얼", "Rust 튜토리얼 심화"],
            channels=["RustLang"],
            tags=["rustlang"],
        )
        assert len(queries) == len(set(q.lower() for q in queries))

    def test_falls_back_to_single_occurrence_keywords(self):
        # 제목이 하나뿐이면 df>=2 토큰이 없다 — 그래도 검색어를 만들어야 한다.
        queries = derive_seed_queries(["초격차 패키지 데이터분석"])
        assert queries and queries[0]

    def test_channel_only_input_still_yields_query(self):
        assert derive_seed_queries([], channels=["침착맨"]) == ["침착맨"]

    def test_result_is_deterministic(self):
        titles = ["A 리뷰 후기", "B 리뷰 후기", "C 리뷰"]
        first = derive_seed_queries(titles)
        assert all(derive_seed_queries(titles) == first for _ in range(5))


class TestSearchText:
    """검색창에 낱말이 있으면 짐작을 그만두고 그 낱말만 쓴다."""

    def test_search_text_replaces_derived_queries(self):
        queries = derive_seed_queries(
            titles=["아이유 밤편지", "아이유 좋은날"],
            channels=["1theK"],
            tags=["발라드"],
            search_text="뉴진스",
        )
        assert queries == ["뉴진스"]

    def test_search_text_works_without_any_seed(self):
        # 검색 결과가 0건이라 목록이 비어도 검색어는 유효하다.
        assert derive_seed_queries([], search_text="파이썬 강의") == ["파이썬 강의"]

    def test_search_text_is_trimmed(self):
        assert derive_seed_queries([], search_text="  뉴진스  ") == ["뉴진스"]

    def test_blank_search_text_falls_back_to_seeds(self):
        # 공백만 입력한 상태는 '검색 안 함'과 같다.
        assert derive_seed_queries([], channels=["침착맨"], search_text="   ") == ["침착맨"]

    def test_search_text_ignores_max_queries_beyond_one(self):
        queries = derive_seed_queries(
            titles=["아이유 밤편지", "아이유 좋은날"], search_text="뉴진스", max_queries=3
        )
        assert queries == ["뉴진스"]
