"""일치 속성 키가 한글 라벨로 온전히 매핑되는지 검증한다.

키(영어)는 도메인/애플리케이션이 다루고 표시 문자열은 GUI만 갖는다.
키를 추가하고 라벨을 빼먹으면 배지에 영어가 노출되므로 테스트로 막는다.
"""
from __future__ import annotations

from domain.library.repositories import MATCH_FIELD_KEYS


class TestMatchFieldLabels:
    def test_every_key_has_korean_label(self):
        from gui.panels.library_panel import match_field_labels

        for key in MATCH_FIELD_KEYS:
            assert key in match_field_labels(), f"라벨 누락: {key}"
            assert match_field_labels()[key], f"라벨이 비었다: {key}"

    def test_no_extra_labels(self):
        from gui.panels.library_panel import match_field_labels

        assert set(match_field_labels()) == set(MATCH_FIELD_KEYS)

    def test_expected_labels(self):
        from gui.panels.library_panel import match_field_labels

        assert match_field_labels()["title"] == "제목"
        assert match_field_labels()["lyrics"] == "가사"
        assert match_field_labels()["summary"] == "요약"
