"""전사 모델 카탈로그와 결과 변환 규칙.

두 가지가 중요하다. **고를 때 필요한 정보가 있는가**(크기·걸리는 시간 — 없으면
사용자가 "가장 좋은 것"을 골랐다가 몇 시간을 기다린다), 그리고 **결과에 쓰레기가
섞이지 않는가**(음성 인식은 무음에서 빈 조각을 내놓는다).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from domain.library.transcribe import (
    DEFAULT_MODEL_KEY,
    MODELS,
    MODELS_BY_KEY,
    find_model,
    resolve_model,
    segments_to_cues,
)


class TestCatalog:
    def test_키가_겹치지_않는다(self):
        keys = [m.key for m in MODELS]
        assert len(keys) == len(set(keys))

    def test_기본값이_목록에_있다(self):
        assert DEFAULT_MODEL_KEY in MODELS_BY_KEY

    def test_모든_모델에_크기와_설명이_있다(self):
        """무엇을 고르는지 모르면 고를 수 없다."""
        for model in MODELS:
            assert model.disk_mb > 0, model.key
            assert model.name and model.note, model.key

    def test_클수록_느리다(self):
        """크기와 속도가 역전되면 사용자가 잘못된 판단을 한다."""
        by_size = sorted(MODELS, key=lambda m: m.disk_mb)
        ratios = [m.realtime_ratio for m in by_size]
        assert ratios == sorted(ratios)

    def test_저사양_PC를_고려해_큰_모델은_넣지_않았다(self):
        """medium 이상은 4GB RAM 목표 사양에서 사실상 못 쓴다."""
        assert all(m.disk_mb <= 600 for m in MODELS)


class TestResolve:
    def test_키로_찾는다(self):
        assert find_model("base").key == "base"

    def test_모르는_키는_None(self):
        assert find_model("없는모델") is None

    def test_설정값이_이상해도_기본값으로_되돌린다(self):
        """설정 파일이 손으로 고쳐져도 기능이 죽으면 안 된다."""
        assert resolve_model("없는모델").key == DEFAULT_MODEL_KEY

    def test_빈_값도_기본값이다(self):
        assert resolve_model("").key == DEFAULT_MODEL_KEY


class TestEstimate:
    def test_짧으면_1분_미만으로_알린다(self):
        assert find_model("tiny").estimate_text(60) == "1분 미만"

    def test_분_단위로_알린다(self):
        # base: 0.12 → 30분 영상이면 약 3.6분
        assert find_model("base").estimate_text(30 * 60).startswith("약 3분")

    def test_한_시간을_넘으면_시간으로_알린다(self):
        text = find_model("small").estimate_text(10 * 3600)   # 0.35 → 3.5시간
        assert "시간" in text

    def test_길이를_모르면_0으로_본다(self):
        assert find_model("base").estimate_sec(0) == 0.0


class TestSegmentsToCues:
    def _seg(self, start, end, text):
        return SimpleNamespace(start=start, end=end, text=text)

    def test_초를_밀리초로_바꾼다(self):
        cues = segments_to_cues([self._seg(1.5, 3.25, "안녕하세요")])
        assert cues == [(1500, 3250, "안녕하세요")]

    def test_앞뒤_공백을_턴다(self):
        """Whisper 는 세그먼트 앞에 공백을 붙여 내놓는다."""
        assert segments_to_cues([self._seg(0, 1, "  말  ")])[0][2] == "말"

    def test_빈_텍스트는_버린다(self):
        """무음 구간에서 나오는 빈 조각이 색인에 섞이면 검색 결과에 빈 줄이 뜬다."""
        assert segments_to_cues([self._seg(0, 1, "   ")]) == []

    def test_길이가_0이거나_거꾸로면_버린다(self):
        assert segments_to_cues([self._seg(5, 5, "말")]) == []
        assert segments_to_cues([self._seg(5, 3, "말")]) == []

    def test_음수_시작은_0으로_본다(self):
        assert segments_to_cues([self._seg(-1, 2, "말")])[0][0] == 0

    def test_빈_입력도_받는다(self):
        assert segments_to_cues([]) == []
        assert segments_to_cues(None) == []

    def test_순서를_지킨다(self):
        cues = segments_to_cues([self._seg(0, 1, "첫"), self._seg(1, 2, "둘")])
        assert [c[2] for c in cues] == ["첫", "둘"]


class TestPrefix:
    def test_전사_자막은_YouTube_자막과_다른_언어키를_쓴다(self):
        """겹치면 다시 받은 YouTube 자막이 전사 결과를 통째로 덮어쓴다."""
        from application.library.subtitle_commands import TranscribeVideoHandler

        assert TranscribeVideoHandler.LANG_PREFIX
        assert not TranscribeVideoHandler.LANG_PREFIX.startswith(("ko", "en"))


@pytest.mark.parametrize("key", [m.key for m in MODELS])
def test_모든_모델이_resolve된다(key):
    assert resolve_model(key).key == key
