"""번역 경로 — 없는 번역은 **원문으로 남는다**.

이 성질이 단계적 번역을 안전하게 만든다. 카탈로그를 조금만 채워도 나머지는 한국어로
보일 뿐 화면이 비지 않는다.

실측으로 확인한 Qt 계약과 같은 판단이다: 번역이 없을 때 빈 문자열을 돌려주면 라벨이
**사라진다**. 그래서 이 구현은 어떤 경우에도 빈 문자열을 내지 않는다.
"""

from __future__ import annotations

import json

import pytest

from gui import text as text_mod
from gui.text import active_language, set_language, tr
from gui.text.catalog import (
    AVAILABLE_LANGUAGES,
    SOURCE_LANGUAGE,
    is_supported,
    language_name,
    load_catalog,
)


@pytest.fixture(autouse=True)
def _restore_language():
    """시험이 서로의 언어 설정을 건드리지 않게 한다."""
    before = active_language()
    yield
    set_language(before)


class TestFallback:
    def test_번역이_있으면_번역문(self):
        set_language("en")
        assert tr("설정") == "Settings"

    def test_번역이_없으면_원문(self):
        set_language("en")
        assert tr("여기에 없는 문구입니다") == "여기에 없는 문구입니다"

    def test_원문_언어에서는_그대로(self):
        set_language("ko")
        assert tr("설정") == "설정"

    def test_빈_번역은_원문으로_친다(self, monkeypatch):
        """카탈로그에 빈 값이 들어가면 라벨이 사라진다 — 미번역으로 취급한다."""
        monkeypatch.setattr(text_mod, "_CATALOG", {"설정": "   "})
        assert tr("설정") == "설정"

    def test_어떤_경우에도_빈_문자열을_내지_않는다(self, monkeypatch):
        monkeypatch.setattr(text_mod, "_CATALOG", {"설정": ""})
        assert tr("설정") == "설정"


class TestCatalogLoading:
    def test_원문_언어는_카탈로그가_필요_없다(self):
        assert load_catalog(SOURCE_LANGUAGE) == {}

    def test_빈_코드도_안전하다(self):
        assert load_catalog("") == {}

    def test_없는_언어는_빈_표(self):
        """번역을 못 읽었다고 앱이 뜨지 않으면 안 된다 — 최악이 한국어 화면이다."""
        assert load_catalog("zz") == {}

    def test_깨진_파일도_앱을_막지_않는다(self, tmp_path, monkeypatch):
        bad = tmp_path / "xx.json"
        bad.write_text("{ 깨진 json", encoding="utf-8")
        monkeypatch.setattr("gui.text.catalog.locale_path", lambda code: bad)
        assert load_catalog("xx") == {}

    def test_빈_번역은_걸러서_싣는다(self, tmp_path, monkeypatch):
        cat = tmp_path / "xx.json"
        cat.write_text(
            json.dumps({"가": "A", "나": "", "다": "   "}, ensure_ascii=False),
            encoding="utf-8",
        )
        monkeypatch.setattr("gui.text.catalog.locale_path", lambda code: cat)
        assert load_catalog("xx") == {"가": "A"}

    def test_사전이_아니면_빈_표(self, tmp_path, monkeypatch):
        bad = tmp_path / "xx.json"
        bad.write_text('["가", "나"]', encoding="utf-8")
        monkeypatch.setattr("gui.text.catalog.locale_path", lambda code: bad)
        assert load_catalog("xx") == {}


class TestAvailableLanguages:
    def test_한국어가_들어_있다(self):
        assert SOURCE_LANGUAGE in dict(AVAILABLE_LANGUAGES)

    def test_이름은_자국어로_쓴다(self):
        """지금 화면이 어떤 언어든 자기 언어는 알아볼 수 있어야 고를 수 있다."""
        names = dict(AVAILABLE_LANGUAGES)
        assert names["ko"] == "한국어"
        assert names["en"] == "English"

    def test_지원_여부를_묻는다(self):
        assert is_supported("en") and not is_supported("zz")

    def test_모르는_코드는_코드를_그대로(self):
        assert language_name("zz") == "zz"

    def test_카탈로그_파일이_실제로_있다(self):
        """빌드가 번들할 파일이다 — 없으면 영어를 골라도 한국어가 나온다."""
        for code, _name in AVAILABLE_LANGUAGES:
            if code == SOURCE_LANGUAGE:
                continue
            assert load_catalog(code), f"{code} 카탈로그가 비어 있다"


class TestSettingKey:
    def test_설정에_앱_언어_키가_있다(self):
        import config.settings as cfg

        assert hasattr(cfg, "UI_LANGUAGE")
        assert hasattr(cfg, "save_ui_language")

    def test_저장하면_런타임_값도_따라온다(self, monkeypatch, tmp_path):
        """`save_setting` 의 mapping 에 등록을 빠뜨리면 yaml 에만 쓰이고 모듈
        변수는 그대로다 — 다시 시작하기 전까지 반영되지 않는 가장 쉬운 함정이다."""
        import config.settings as cfg

        monkeypatch.setattr(cfg, "_CONFIG_FILE", tmp_path / "config.yaml")
        cfg._load_config.cache_clear()
        try:
            cfg.save_ui_language("en")
            assert cfg.UI_LANGUAGE == "en"
        finally:
            cfg.save_ui_language("ko")
            cfg._load_config.cache_clear()
