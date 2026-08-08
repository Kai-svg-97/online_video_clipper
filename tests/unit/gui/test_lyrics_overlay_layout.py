"""자막 오버레이의 글자 크기·세로 위치 계산 검증(QApplication 필요, 재생 없음)."""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from gui.widgets.lyrics_overlay import LyricsCue, LyricsOverlay


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def overlay(app):
    w = LyricsOverlay()
    w.resize(1600, 900)
    w.set_cue(LyricsCue(start_ms=0, original="hello", translation="안녕", line_index=0))
    yield w
    w.deleteLater()


def test_글자크기가_영역높이의_약_4_5퍼센트(overlay):
    main, _sub = overlay._fonts()
    assert main.pixelSize() == int(900 * 0.045)


def test_최소_크기_하한이_지켜진다(overlay):
    overlay.resize(200, 60)          # 60 * 0.045 = 2.7px
    main, _sub = overlay._fonts()
    assert main.pixelSize() == LyricsOverlay._MIN_FONT_PX


def test_기본_하단여백은_높이의_10퍼센트(overlay):
    assert overlay._bottom_ratio == pytest.approx(0.10)
    assert overlay._bottom_px() == int(900 * 0.10)


class TestAdjust:
    def test_배율이_글자크기에_선형_반영된다(self, overlay):
        overlay.set_font_scale(2.0)
        main, _ = overlay._fonts()
        assert main.pixelSize() == int(900 * 0.045 * 2.0)

    def test_배율_범위가_clamp_된다(self, overlay):
        overlay.set_font_scale(9.9)
        assert overlay.font_scale == LyricsOverlay.FONT_SCALE_MAX
        overlay.set_font_scale(0.01)
        assert overlay.font_scale == LyricsOverlay.FONT_SCALE_MIN

    def test_위치_범위가_clamp_된다(self, overlay):
        overlay.set_bottom_ratio(5.0)
        assert overlay.bottom_ratio == LyricsOverlay.BOTTOM_RATIO_MAX
        overlay.set_bottom_ratio(-1.0)
        assert overlay.bottom_ratio == LyricsOverlay.BOTTOM_RATIO_MIN

    def test_위치값이_커지면_자막이_위로_올라간다(self, overlay):
        overlay.set_bottom_ratio(0.0)
        low = overlay._bottom_px()
        overlay.set_bottom_ratio(0.30)
        assert overlay._bottom_px() > low
