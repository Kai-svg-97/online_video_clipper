"""도메인 키마다 표시 이름이 있는가 — 그리고 남는 라벨은 없는가.

도메인이 영어 키를 갖고 표시 문자열은 GUI가 갖는 구조라, **키를 하나 더하고 라벨을
빠뜨리면 화면에 `music_offtopic` 같은 키가 그대로 뜬다.** 오류도 나지 않는다.

반대쪽도 본다 — 도메인에서 사라진 키의 라벨이 남아 있으면 죽은 문구를 번역하게 된다.
"""

from __future__ import annotations

import pytest

from domain.clip.presets import PRESETS
from domain.clip.sponsor import SKIP_CATEGORIES
from domain.library.availability import (
    STATUS_OK,
    STATUS_PRIVATE,
    STATUS_REMOVED,
    STATUS_UNKNOWN,
)
from domain.library.filters import (
    DATE_PRESETS,
    DOWNLOAD_PRESETS,
    DURATION_PRESETS,
    WATCHED_PRESETS,
)
from domain.library.transcribe import MODELS_BY_KEY
from gui.text.labels import (
    AVAILABILITY_LABELS,
    FILTER_PRESET_LABELS,
    CONVERT_PRESET_LABELS,
    SPONSOR_CATEGORY_LABELS,
    TRANSCRIBE_MODEL_LABELS,
    availability_label,
    filter_preset_label,
    sponsor_category_label,
)

_AVAILABILITY_KEYS = {STATUS_OK, STATUS_REMOVED, STATUS_PRIVATE, STATUS_UNKNOWN}
_FILTER_KEYS = (
    {("date", k) for k, *_ in DATE_PRESETS}
    | {("duration", k) for k, *_ in DURATION_PRESETS}
    | {("download", k) for k, *_ in DOWNLOAD_PRESETS}
    | {("watched", k) for k, *_ in WATCHED_PRESETS}
)


@pytest.mark.parametrize("keys, labels, name", [
    (set(SKIP_CATEGORIES), SPONSOR_CATEGORY_LABELS, "SponsorBlock 카테고리"),
    (_AVAILABILITY_KEYS, AVAILABILITY_LABELS, "원본 확인 상태"),
    (_FILTER_KEYS, FILTER_PRESET_LABELS, "복합 필터 프리셋"),
    ({p.key for p in PRESETS}, CONVERT_PRESET_LABELS, "포맷 변환 프리셋"),
    (set(MODELS_BY_KEY), TRANSCRIBE_MODEL_LABELS, "음성 인식 모델"),
])
class TestCoverage:
    def test_키마다_라벨이_있다(self, keys, labels, name):
        missing = keys - set(labels)
        assert not missing, f"{name}: 라벨 없는 키 {sorted(missing)}"

    def test_남는_라벨이_없다(self, keys, labels, name):
        extra = set(labels) - keys
        assert not extra, f"{name}: 도메인에 없는 라벨 {sorted(extra)}"

    def test_빈_라벨이_없다(self, keys, labels, name):
        def _blank(v) -> bool:
            # (이름, 설명) 짝인 표도 있다 — 둘 다 채워져 있어야 한다.
            return not all(part.strip() for part in (v if isinstance(v, tuple) else (v,)))

        blank = [k for k in keys if _blank(labels.get(k, ""))]
        assert not blank, f"{name}: 빈 라벨 {sorted(blank)}"


class TestUnknownKeyFallback:
    """모르는 키에도 화면이 비지 않는다 — 키를 그대로 보여 준다."""

    def test_sponsor(self):
        assert sponsor_category_label("새로운_카테고리") == "새로운_카테고리"

    def test_availability(self):
        assert availability_label("새_상태") == "새_상태"

    def test_filter(self):
        assert filter_preset_label("date", "새_프리셋") == "새_프리셋"


class TestDomainKeysStayAscii:
    """도메인 키에 한글이 들어가면 그 자체가 번역 불가 지점이 된다."""

    def test_sponsor_키(self):
        assert all(k.isascii() for k in SKIP_CATEGORIES)

    def test_availability_키(self):
        assert all(k.isascii() for k in _AVAILABILITY_KEYS)

    def test_filter_키(self):
        assert all(g.isascii() and k.isascii() for g, k in _FILTER_KEYS)


class TestQualityKeys:
    """화질은 **키로 고른다** — 표시 문자열이 곧 식별자이던 것을 끊었다.

    예전에는 `if short == "자동"` 으로 배지를 숨길지 판정했다. 라벨을 번역하면 그
    판정이 조용히 죽고 배지에 "Auto"가 그대로 뜬다.
    """

    def test_모든_키가_ASCII다(self):
        from gui.widgets.player.constants import _QUALITY_OPTIONS

        assert all(key.isascii() for key, *_ in _QUALITY_OPTIONS)

    def test_키마다_메뉴_라벨이_있다(self):
        from gui.text.labels import QUALITY_MENU_LABELS
        from gui.widgets.player.constants import _QUALITY_OPTIONS

        assert {key for key, *_ in _QUALITY_OPTIONS} == set(QUALITY_MENU_LABELS)

    def test_자동은_배지를_비운다(self):
        from gui.text.labels import quality_badge_text
        from gui.widgets.player.constants import QUALITY_AUTO

        assert quality_badge_text(QUALITY_AUTO) == ""

    def test_나머지는_키를_그대로_적는다(self):
        """"1080p" 는 어느 언어에서도 같다 — 번역 대상이 아니다."""
        from gui.text.labels import quality_badge_text

        assert quality_badge_text("1080p") == "1080p"

    def test_해상도_표에_자동이_없다(self):
        """`auto` 는 제한이 없으므로 높이가 없어야 한다(있으면 메뉴에서 걸러진다)."""
        from gui.widgets.player.constants import QUALITY_AUTO, _QUALITY_HEIGHTS

        assert QUALITY_AUTO not in _QUALITY_HEIGHTS



class TestEnglishLabels:
    """영어 화면에서 라벨 함수가 한국어를 돌려주지 않는다.

    표의 값은 한국어 원문이고 접근 함수가 `tr()`을 씌운다 — 한때 씌우지 않아서
    화질 "자동 (최고 화질)"·SponsorBlock 구간 이름이 영어 화면에 한국어로 나왔다.
    """

    @pytest.fixture(autouse=True)
    def _english(self):
        from gui.text import active_language, set_language

        before = active_language()
        set_language("en")
        yield
        set_language(before)

    def _no_hangul(self, text: str) -> None:
        import re

        assert not re.search(r"[가-힣]", text), text

    def test_표로_고르는_라벨(self):
        from gui.text.labels import (
            BUILTIN_PRESET_LABELS,
            QUALITY_MENU_LABELS,
            convert_preset_description,
            convert_preset_name,
            quality_menu_label,
            transcribe_model_name,
            transcribe_model_note,
        )

        for k in SPONSOR_CATEGORY_LABELS:
            self._no_hangul(sponsor_category_label(k))
        for k in AVAILABILITY_LABELS:
            self._no_hangul(availability_label(k))
        for g, k in FILTER_PRESET_LABELS:
            self._no_hangul(filter_preset_label(g, k))
        for k in CONVERT_PRESET_LABELS:
            self._no_hangul(convert_preset_name(k))
            self._no_hangul(convert_preset_description(k))
        for k in TRANSCRIBE_MODEL_LABELS:
            self._no_hangul(transcribe_model_name(k))
            self._no_hangul(transcribe_model_note(k))
        for k in QUALITY_MENU_LABELS:
            self._no_hangul(quality_menu_label(k))
        assert quality_menu_label("auto") == "Auto (best quality)"
        assert BUILTIN_PRESET_LABELS  # 아래 시험이 빈 표를 통과시키지 않게

    def test_조립하는_라벨(self):
        from types import SimpleNamespace

        from gui.text.labels import (
            BUILTIN_PRESET_LABELS,
            chapter_title,
            default_preset_name,
            download_preset_name,
            subtitle_track_label,
        )

        track = SimpleNamespace(name="English", lang="en", auto=True, translate_to="ja")
        assert subtitle_track_label(track) == "English (auto-generated) → 日本語 translation"
        assert chapter_title("", 3) == "Chapter 3"
        for key in BUILTIN_PRESET_LABELS:
            self._no_hangul(download_preset_name(SimpleNamespace(name="", key=key)))
        self._no_hangul(default_preset_name())

    def test_모르는_키는_그대로(self):
        assert sponsor_category_label("new_category") == "new_category"
