"""상세 화면 요약 탭 — 언어별 요약 표시·전환·저장.

요약은 언어별로 저장된다(한 영상에 ko·en 공존). 화면 규칙:
- 앱 언어의 요약을 먼저 보여 주고, 없으면 있는 다른 언어를 보여 주며 이유를 말한다.
- 언어 칩은 **다른 언어의 요약이 있을 때만** 보인다.
- ⟳ 로 받은 요약은 받은 언어 칸에 저장되고 그 언어로 넘어간다.
- 편집은 **보고 있는 언어**에 저장한다.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import gui.panels.detail.mixins.summary as summary_mod


def _widget(summaries=None, statuses=None):
    from gui.panels.video_detail_panel import VideoDetailWidget

    widget = VideoDetailWidget()
    video_id = uuid4()
    widget._detail = SimpleNamespace(id=video_id, url="https://youtu.be/x")
    widget._streaming = False
    widget._load_summaries(
        SimpleNamespace(summaries=dict(summaries or {}), summary_statuses=dict(statuses or {}))
    )
    return widget, video_id


def _chip_langs(widget):
    lay = widget._summary_lang_layout
    return [lay.itemAt(i).widget().property("summary_lang") for i in range(lay.count())]


class TestInitialLanguage:
    def test_app_language_summary_shown_first(self, qapp_instance):
        widget, _ = _widget({"ko": "한국어 요약", "en": "English summary"})
        assert widget._summary_lang == "ko"
        assert widget._summary_raw == "한국어 요약"
        widget.deleteLater()

    def test_falls_back_to_other_language_and_says_why(self, qapp_instance):
        widget, _ = _widget({"en": "English summary"})
        assert widget._summary_lang == "en"
        assert widget._summary_raw == "English summary"
        assert "한국어" in widget._summary_status_lbl.text()   # 왜 이 언어인지
        widget.deleteLater()

    def test_follows_app_language(self, qapp_instance, monkeypatch):
        monkeypatch.setattr(summary_mod, "active_language", lambda: "en")
        widget, _ = _widget({"ko": "한국어 요약", "en": "English summary"})
        assert widget._summary_lang == "en"
        widget.deleteLater()


class TestChips:
    def test_hidden_when_only_app_language(self, qapp_instance):
        widget, _ = _widget({"ko": "한국어 요약"})
        assert widget._summary_lang_bar.isHidden()
        widget.deleteLater()

    def test_hidden_when_no_summary(self, qapp_instance):
        widget, _ = _widget({})
        assert widget._summary_lang_bar.isHidden()
        widget.deleteLater()

    def test_shown_with_other_language(self, qapp_instance):
        widget, _ = _widget({"ko": "한국어 요약", "en": "English summary"})
        assert not widget._summary_lang_bar.isHidden()
        assert _chip_langs(widget) == ["ko", "en"]
        widget.deleteLater()

    def test_app_language_chip_offered_even_if_empty(self, qapp_instance):
        """앱 언어 요약이 없어도 그 칩을 둔다 — 눌러서 ⟳ 로 만들 수 있다."""
        widget, _ = _widget({"en": "English summary"})
        assert _chip_langs(widget) == ["ko", "en"]
        widget.deleteLater()

    def test_chip_switches_language(self, qapp_instance):
        widget, _ = _widget({"ko": "한국어 요약", "en": "English summary"})
        lay = widget._summary_lang_layout
        en_btn = next(
            lay.itemAt(i).widget() for i in range(lay.count())
            if lay.itemAt(i).widget().property("summary_lang") == "en"
        )
        en_btn.click()
        assert widget._summary_lang == "en"
        assert widget._summary_raw == "English summary"
        widget.deleteLater()


class TestGenerationResult:
    def test_result_saved_in_its_language_and_shown(self, qapp_instance):
        widget, video_id = _widget({"ko": "한국어 요약"})
        saved = []
        widget.gemini_summary_saved.connect(lambda *a: saved.append(a))

        widget._on_gemini_done(video_id, "en", "English summary", "")

        assert saved == [(video_id, "en", "English summary")]
        assert widget._summary_lang == "en"
        assert widget._summaries == {"ko": "한국어 요약", "en": "English summary"}
        assert not widget._summary_lang_bar.isHidden()
        widget.deleteLater()

    def test_failure_status_saved_per_language(self, qapp_instance):
        widget, video_id = _widget({"ko": "한국어 요약"})
        statuses = []
        widget.summary_status_saved.connect(lambda *a: statuses.append(a))

        widget._on_gemini_done(video_id, "en", "", "no_button")

        assert statuses == [(video_id, "en", "no_button")]
        # 보고 있던 한국어 요약은 그대로다.
        assert widget._summary_lang == "ko"
        assert widget._summary_raw == "한국어 요약"
        widget.deleteLater()


class TestEditInterruptedByResult:
    def test_edit_is_saved_before_result_switches_view(self, qapp_instance):
        """편집 중에 ⟳ 결과가 도착해도 편집한 글이 버려지지 않는다."""
        widget, video_id = _widget({"ko": "한국어 요약"})
        saved = []
        widget.gemini_summary_saved.connect(lambda *a: saved.append(a))
        widget._enter_summary_edit()
        widget._summary_editor.setPlainText("고친 한국어 요약")

        widget._on_gemini_done(video_id, "en", "English summary", "")

        assert (video_id, "ko", "고친 한국어 요약") in saved
        assert widget._summaries["ko"] == "고친 한국어 요약"
        widget.deleteLater()


class TestEditLanguage:
    def test_edit_saves_to_shown_language(self, qapp_instance):
        """영어 요약을 보고 있다면 편집은 영어 칸에 저장된다(앱 언어가 한국어여도)."""
        widget, video_id = _widget({"ko": "한국어 요약", "en": "English summary"})
        widget._show_summary_lang("en")
        saved = []
        widget.gemini_summary_saved.connect(lambda *a: saved.append(a))

        widget._enter_summary_edit()
        widget._summary_editor.setPlainText("Edited English")
        widget._commit_summary_edit()

        assert saved == [(video_id, "en", "Edited English")]
        assert widget._summaries["ko"] == "한국어 요약"
        widget.deleteLater()
