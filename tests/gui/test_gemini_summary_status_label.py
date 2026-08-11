"""요약 추출 실패 시 상태 라벨이 실패 사유별로 다른 안내를 보여주는지 검증.

과거에는 실패 사유(SUMMARY_REASON_*)와 무관하게 항상 "설정에서 브라우저/프로필을
선택하거나 쿠키 파일을 등록하세요"라는 문구를 보여줬다. "no_button"(YouTube가 이
영상에 요약 기능을 제공하지 않음)처럼 사용자가 손쓸 수 없는 사유에도 매번 설정을
만지라고 안내해 불필요한 시행착오를 유발했다.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4


def _widget(qapp_instance):
    from gui.panels.video_detail_panel import VideoDetailWidget

    widget = VideoDetailWidget()
    return widget


class TestGeminiFailureStatusLabel:
    def test_no_button_사유는_쿠키_설정_안내를_보여주지_않는다(self, qapp_instance):
        widget = _widget(qapp_instance)
        video_id = uuid4()
        widget._detail = SimpleNamespace(id=video_id)

        widget._on_gemini_done(video_id, "", "no_button")

        text = widget._summary_status_lbl.text()
        assert "브라우저/프로필" not in text
        assert "쿠키 파일" not in text
        widget.deleteLater()

    def test_not_signed_in_사유는_로그인_문제임을_알린다(self, qapp_instance):
        widget = _widget(qapp_instance)
        video_id = uuid4()
        widget._detail = SimpleNamespace(id=video_id)

        widget._on_gemini_done(video_id, "", "not_signed_in")

        text = widget._summary_status_lbl.text()
        assert "로그인" in text
        widget.deleteLater()

    def test_error_사유는_재시도_안내를_보여준다(self, qapp_instance):
        widget = _widget(qapp_instance)
        video_id = uuid4()
        widget._detail = SimpleNamespace(id=video_id)

        widget._on_gemini_done(video_id, "", "error")

        text = widget._summary_status_lbl.text()
        assert text  # 비어있지 않음
        assert "브라우저/프로필" not in text
        widget.deleteLater()

    def test_성공하면_상태_라벨이_비워진다(self, qapp_instance):
        widget = _widget(qapp_instance)
        video_id = uuid4()
        widget._detail = SimpleNamespace(id=video_id)

        widget._on_gemini_done(video_id, "실제 요약 본문", "")

        assert widget._summary_status_lbl.text() == ""
        widget.deleteLater()
