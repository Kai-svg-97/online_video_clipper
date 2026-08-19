"""읽는 영역(요약·가사) 글자 크기 + 재생 컨트롤 아이콘 크기.

요약·가사는 읽으라고 있는 글인데 크기가 코드에 박혀 있었고, 재생 컨트롤 아이콘은
큰 화면에서 알아보기 어려울 만큼 작았다. 둘 다 "보이는 크기"에 대한 계약이라 한
파일에 묶어 고정한다.

특히 중요한 것:
* 배율은 요약·가사 **양쪽에 함께** 걸린다(글자 크기는 화면 설정이지 영역별 취향이 아니다).
* 한계값에서 더 눌러도 저장이 반복되지 않는다.
* 0.1 누적으로 `1.9700000000000002` 같은 값이 저장되지 않는다(자막 배율에서 겪은 문제).
"""
from __future__ import annotations

import pytest

from gui.panels.detail.text_zoom import (
    DEFAULT_SCALE,
    MAX_SCALE,
    MIN_SCALE,
    clamp_scale,
    scale_label,
    scaled_pt,
)
from gui.panels.video_detail_panel import VideoDetailWidget
from gui.widgets.player.controls import _ICON_BOX, _ICON_PX, _ControlBar, _bar_style


@pytest.fixture(autouse=True)
def _no_config_writes(monkeypatch):
    """실사용 config.yaml을 건드리지 않는다(다음 실행의 다른 테스트가 깨진다)."""
    import config.settings as settings
    monkeypatch.setattr(settings, "save_setting", lambda *a, **k: None)
    monkeypatch.setattr(settings, "DETAIL_TEXT_SCALE", DEFAULT_SCALE, raising=False)


@pytest.fixture
def widget(qtbot) -> VideoDetailWidget:
    w = VideoDetailWidget()
    qtbot.addWidget(w)
    return w


class TestScaleRules:
    def test_범위를_벗어나면_자른다(self):
        assert clamp_scale(99) == MAX_SCALE
        assert clamp_scale(0.01) == MIN_SCALE

    def test_소수점이_길게_늘어지지_않는다(self):
        assert clamp_scale(1.0 + 0.1 * 9) == 1.9

    def test_이상한_값은_기본값으로(self):
        assert clamp_scale(None) == DEFAULT_SCALE
        assert clamp_scale("크게") == DEFAULT_SCALE

    def test_최소_6pt는_보장한다(self):
        assert scaled_pt(8, MIN_SCALE) >= 6

    def test_배율_표기(self):
        assert scale_label(1.0) == "100%"
        assert scale_label(1.25) == "125%"


class TestDetailZoom:
    def test_확대하면_요약과_가사가_함께_커진다(self, widget):
        before_summary = widget._summary_edit.font().pointSize()

        widget.zoom_text_in()

        assert widget._summary_edit.font().pointSize() > before_summary
        assert widget._song_tab._font_scale == widget._text_scale

    def test_축소도_같이_적용된다(self, widget):
        widget.zoom_text_in()
        widget.zoom_text_in()
        bigger = widget._summary_edit.font().pointSize()

        widget.zoom_text_out()

        assert widget._summary_edit.font().pointSize() < bigger

    def test_기본값_버튼이_되돌린다(self, widget):
        widget.zoom_text_in()
        widget.zoom_text_in()

        widget._summary_zoom_btn.click()

        assert widget._text_scale == DEFAULT_SCALE

    def test_가사_헤더_버튼도_기본값으로_되돌린다(self, widget):
        """두 영역 어느 쪽에서든 되돌릴 수 있어야 한다."""
        widget.zoom_text_in()

        widget._song_tab._zoom_btn.click()   # 배선은 위젯이 이미 해 두어야 한다

        assert widget._text_scale == DEFAULT_SCALE

    def test_버튼에_현재_배율이_보인다(self, widget):
        widget.zoom_text_in()

        assert widget._summary_zoom_btn.text() == scale_label(widget._text_scale)
        assert widget._song_tab._zoom_btn.text() == scale_label(widget._text_scale)

    def test_한계를_넘겨_눌러도_저장이_반복되지_않는다(self, widget, monkeypatch):
        saves: list = []
        monkeypatch.setattr(
            "gui.panels.video_detail_panel.save_scale", lambda v: saves.append(v)
        )
        for _ in range(40):
            widget.zoom_text_out()
        count_at_limit = len(saves)

        widget.zoom_text_out()

        assert len(saves) == count_at_limit
        assert widget._text_scale == MIN_SCALE

    def test_저장된_배율로_시작한다(self, qtbot, monkeypatch):
        import config.settings as settings
        monkeypatch.setattr(settings, "DETAIL_TEXT_SCALE", 1.4, raising=False)

        w = VideoDetailWidget()
        qtbot.addWidget(w)

        assert w._text_scale == 1.4
        assert w._summary_zoom_btn.text() == "140%"


class TestLyricsScale:
    def test_가사_줄이_배율만큼_커진다(self, widget):
        tab = widget._song_tab
        small = tab._lyric_label("가사", "#fff", 10).styleSheet()

        tab.set_font_scale(2.0)
        big = tab._lyric_label("가사", "#fff", 10).styleSheet()

        assert "font-size:10pt" in small
        assert "font-size:20pt" in big


class TestControlIconSize:
    """13px/24px(원래) → 26px/48px(2배, 너무 컸다는 반대 신고 없음) →
    28px/38px(상자 20% 축소 + 글자 비율을 키워 상자를 꽉 채움)로 조정된 이력.

    상자를 줄이면서 글자 크기를 그대로 두면 작아진 상자 안에 여백만 커 보인다 —
    그래서 상자 대비 글자 비율(fill ratio)이 이전보다 **커야** 한다.
    """

    def test_상자가_이전보다_20퍼센트가량_작다(self):
        assert _ICON_BOX == 38
        prev_box = 48
        assert 0.75 <= _ICON_BOX / prev_box <= 0.85

    def test_글자가_상자를_꽉_채우도록_비율이_커졌다(self):
        """상자만 줄이고 비율을 그대로 두면 '꽉 찬' 느낌이 나지 않는다."""
        prev_ratio = 26 / 48
        new_ratio = _ICON_PX / _ICON_BOX
        assert new_ratio > prev_ratio

    def test_스타일에_실제로_반영된다(self, qtbot):
        css = _bar_style()

        assert f"font-size: {_ICON_PX}px" in css
        assert f"min-width: {_ICON_BOX}px" in css
        assert f"min-height: {_ICON_BOX}px" in css

    def test_안쪽_여백이_최소화됐다(self, qtbot):
        """여백이 크면 글자가 커져도 상자 가장자리까지 닿지 않는다."""
        css = _bar_style()

        assert "padding: 0px 1px" in css

    def test_바_높이가_아이콘을_담을_만큼_크다(self, qtbot):
        """높이를 그대로 두면 진행 슬라이더와 버튼 행이 서로를 밀어낸다."""
        bar = _ControlBar()
        qtbot.addWidget(bar)

        assert bar.height() >= _ICON_BOX + 24

    def test_버튼_크기가_실제로_이전보다_작다(self, qtbot):
        bar = _ControlBar()
        qtbot.addWidget(bar)

        # 이전 세대(26px/48px)의 재생 버튼 실측 크기 — 회귀 시 이 값과 같아진다.
        prev_height = 55
        assert bar._btn_play.sizeHint().height() < prev_height
