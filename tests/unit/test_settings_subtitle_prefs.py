"""자막 표시 설정(크기 배율·하단 여백 비율)의 로드·저장 왕복 검증."""
from __future__ import annotations

import importlib


def test_기본값(monkeypatch, tmp_path):
    import config.settings as s
    importlib.reload(s)
    assert s.SUBTITLE_FONT_SCALE == 1.0
    assert s.SUBTITLE_BOTTOM_RATIO == 0.10


def test_저장하면_모듈변수가_즉시_갱신된다(tmp_path, monkeypatch):
    import config.settings as s
    monkeypatch.setattr(s, "DATA_DIR", tmp_path)
    monkeypatch.setattr(s, "_CONFIG_FILE", tmp_path / "config.yaml")
    s._load_config.cache_clear()
    s.save_setting("subtitle_font_scale", 1.6)
    s.save_setting("subtitle_bottom_ratio", 0.24)
    assert s.SUBTITLE_FONT_SCALE == 1.6
    assert s.SUBTITLE_BOTTOM_RATIO == 0.24


def test_잘못된_값은_기본값으로_떨어진다(monkeypatch):
    import config.settings as s
    monkeypatch.setattr(s, "_load_config", lambda: {"subtitle_font_scale": "삼"})
    assert s._load_float("subtitle_font_scale", 1.0) == 1.0
