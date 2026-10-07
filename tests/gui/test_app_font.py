"""`gui.fonts.app_font` — 앱 글꼴에서 파생하는 글꼴 헬퍼."""

from __future__ import annotations

import pytest
from PyQt6.QtGui import QFont, QFontInfo
from PyQt6.QtWidgets import QApplication


@pytest.fixture
def fonts(qapp_instance):
    import gui.fonts as fonts_mod

    return fonts_mod


class _Boom:
    @staticmethod
    def font(*_a, **_k):
        raise RuntimeError("no app font")

    @staticmethod
    def instance():
        raise RuntimeError("no app")


class TestAppFont:
    def test_family_and_size_follow_app_font(self, fonts):
        f = fonts.app_font(8)
        assert f.family() == QApplication.font().family()
        assert f.pointSize() == 8

    def test_weight_is_applied(self, fonts):
        f = fonts.app_font(9, QFont.Weight.Bold)
        assert f.weight() == QFont.Weight.Bold
        assert f.pointSize() == 9

    def test_not_cached_follows_app_font_change(self, fonts, qapp_instance):
        original = QFont(QApplication.font())
        try:
            QApplication.setFont(QFont("Arial", 9))
            expected = QApplication.font().family()
            assert fonts.app_font(8).family() == expected
            QApplication.setFont(QFont("Courier New", 9))
            expected2 = QApplication.font().family()
            assert fonts.app_font(8).family() == expected2
        finally:
            QApplication.setFont(original)

    def test_failure_falls_back_without_raising(self, fonts, monkeypatch):
        monkeypatch.setattr("gui.fonts.QApplication", _Boom)
        f = fonts.app_font(8)
        assert isinstance(f, QFont)
        assert f.pointSize() == 8

    @pytest.mark.parametrize("size", [0, -1])
    def test_boundary_sizes_do_not_raise(self, fonts, size):
        f = fonts.app_font(size)
        assert isinstance(f, QFont)
        assert QFontInfo(f).pointSize() > 0

    def test_not_ms_sans_serif(self, fonts):
        # Windows에서만 의미 있다 — 다른 OS에서는 공허하게 통과해도 무방하다.
        assert QFontInfo(fonts.app_font(8)).family() != "MS Sans Serif"
