"""변환 프리셋 정의와 scale 필터.

프리셋을 코드에 고정하는 이유는, 코덱을 직접 고르는 화면은 거의 쓰이지 않고 잘못
고르면 결과가 재생되지 않기 때문이다. 그래서 **모든 영상 프리셋이 H.264+AAC+mp4**
라는 계약을 테스트로 못 박는다 — 이 조합만 폰·TV·차량에서 사실상 항상 열린다.
"""

from __future__ import annotations

import pytest

from domain.clip.presets import (
    AUDIO_EXTS,
    PRESETS,
    ConvertPreset,
    find_preset,
    scale_filter,
)


class TestCatalog:
    def test_키가_겹치지_않는다(self):
        keys = [p.key for p in PRESETS]
        assert len(keys) == len(set(keys))

    def test_영상_프리셋은_전부_H264_AAC_mp4다(self):
        for preset in PRESETS:
            if preset.is_audio_only:
                continue
            assert preset.video_codec == "libx264", preset.key
            assert preset.audio_codec == "aac", preset.key
            assert preset.ext == "mp4", preset.key

    def test_음원_프리셋은_아는_확장자만_쓴다(self):
        for preset in PRESETS:
            if preset.is_audio_only:
                assert preset.ext in AUDIO_EXTS, preset.key

    def test_모든_프리셋에_설명이_있다(self):
        """무엇을 고르는지 모르면 고를 수 없다."""
        assert all(p.name and p.description for p in PRESETS)

    def test_키로_찾는다(self):
        assert find_preset("mp3").ext == "mp3"

    def test_모르는_키는_None(self):
        assert find_preset("없는키") is None


class TestOutputName:
    def test_프리셋_이름이_파일명에_들어간다(self):
        """원본을 덮어쓰지 않기 위해 — 변환은 되돌릴 수 없다."""
        preset = find_preset("mp4-720p")
        assert preset.output_name("영상") == "영상 [mp4-720p].mp4"

    def test_음원_프리셋은_확장자가_바뀐다(self):
        assert find_preset("mp3").output_name("노래").endswith(".mp3")


class TestScaleFilter:
    def test_높이_제한이_없으면_필터도_없다(self):
        assert scale_filter(ConvertPreset("x", "x", "x", "mp4", "libx264")) is None

    def test_음원은_필터가_없다(self):
        assert scale_filter(find_preset("mp3")) is None

    @pytest.mark.parametrize("key,height", [("mp4-1080p", 1080), ("mp4-720p", 720)])
    def test_지정한_높이로_줄인다(self, key, height):
        assert f"min({height},ih)" in scale_filter(find_preset(key))

    def test_작은_영상을_늘리지_않는다(self):
        """min(제한, 입력높이) — 늘리면 화질은 그대로인데 파일만 커진다."""
        assert "min(" in scale_filter(find_preset("mp4-480p"))

    def test_너비는_짝수로_맞춘다(self):
        """H.264는 홀수 크기를 인코딩하지 못해 -1로 두면 세로 영상에서 실패한다."""
        assert scale_filter(find_preset("mp4-720p")).startswith("scale=-2:")
