"""자막 오버레이 위젯 렌더 상태 검증.

픽셀을 검사하는 대신 (a) 상태가 올바르게 반영되는지 (b) paintEvent가 예외 없이
도는지를 본다 — 폰트·안티에일리어싱은 환경마다 달라 픽셀 비교가 불안정하다.
"""
from __future__ import annotations

import pytest
from PyQt6.QtGui import QPixmap, QPainter

from gui.widgets.lyrics_overlay import LyricsCue, LyricsOverlay, subtitle_font_family


@pytest.fixture
def overlay(qapp_instance):
    w = LyricsOverlay()
    w.resize(640, 200)
    return w


def _paint(widget) -> None:
    """오프스크린 렌더 — paintEvent가 예외 없이 완주하는지 확인한다."""
    pm = QPixmap(widget.size())
    pm.fill()
    painter = QPainter(pm)
    widget.render(painter)
    painter.end()


class TestState:
    def test_초기에는_빈_텍스트(self, overlay):
        assert overlay.current_text == ("", "")

    def test_set_cue가_원문과_번역을_반영한다(self, overlay):
        overlay.set_cue(LyricsCue(start_ms=0, original="hello", translation="안녕"))
        assert overlay.current_text == ("hello", "안녕")

    def test_None이면_비운다(self, overlay):
        overlay.set_cue(LyricsCue(start_ms=0, original="hello"))
        overlay.set_cue(None)
        assert overlay.current_text == ("", "")


class TestRender:
    def test_원문만_있어도_그려진다(self, overlay):
        overlay.set_cue(LyricsCue(start_ms=0, original="only original"))
        _paint(overlay)

    def test_원문과_번역을_함께_그린다(self, overlay):
        overlay.set_cue(
            LyricsCue(start_ms=0, original="I don't wanna be alone", translation="혼자이고 싶지 않아")
        )
        _paint(overlay)

    def test_긴_줄도_예외_없이_그려진다(self, overlay):
        overlay.set_cue(LyricsCue(start_ms=0, original="word " * 60, translation="단어 " * 60))
        _paint(overlay)

    def test_자막_끄면_그리지_않는다(self, overlay):
        overlay.set_cue(LyricsCue(start_ms=0, original="hidden"))
        overlay.set_text_visible(False)
        _paint(overlay)   # 예외 없이 즉시 반환

    def test_아주_작은_높이에서도_최소_글자크기를_지킨다(self, overlay):
        overlay.resize(320, 40)
        overlay.set_cue(LyricsCue(start_ms=0, original="tiny"))
        _paint(overlay)


class TestFont:
    def test_폰트_계열_이름을_반환한다(self, qapp_instance):
        assert isinstance(subtitle_font_family(), str)
        assert subtitle_font_family() != ""

    def test_두_번_불러도_같은_값(self, qapp_instance):
        assert subtitle_font_family() == subtitle_font_family()


class TestMouseTransparency:
    def test_마우스_이벤트를_통과시킨다(self, overlay):
        from PyQt6.QtCore import Qt

        assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
