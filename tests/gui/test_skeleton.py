"""공유 스켈레톤 프리미티브(`gui/widgets/skeleton.py`) 검증.

목록·앨범 등 실제 화면 스켈레톤(Step 3~5)이 이 프리미티브에 얹히기 전에, 애니메이션
시작/중단·테마 톤 파생·칸 배치 규칙을 이 파일에서 먼저 고정한다.
"""
from __future__ import annotations

from gui.themes.tokens import PRESETS
from gui.widgets.skeleton import (
    SHIMMER_CYCLE_MS,
    ShimmerEffect,
    SkeletonRow,
    _skeleton_tones,
)


def test_애니메이션_주기는_300ms다() -> None:
    assert SHIMMER_CYCLE_MS == 300


def test_반짝임_색이_바탕보다_밝거나_같다() -> None:
    """전 테마 프리셋에서 하드코딩 없이 톤이 파생되는지 함께 확인한다."""
    for tokens in PRESETS.values():
        base, highlight = _skeleton_tones(tokens)
        base_sum = base.red() + base.green() + base.blue()
        highlight_sum = highlight.red() + highlight.green() + highlight.blue()
        assert highlight_sum >= base_sum


def test_밝은_테마와_어두운_테마의_바탕톤이_서로_다르다() -> None:
    base_dark, _ = _skeleton_tones(PRESETS["slate"])
    base_light, _ = _skeleton_tones(PRESETS["mist"])
    assert base_dark.name() != base_light.name()


class TestShimmerEffect:
    def test_초기상태는_애니메이션이_꺼져있다(self, qtbot) -> None:
        w = ShimmerEffect()
        qtbot.addWidget(w)
        assert not w.is_loading
        assert not w._timer.isActive()

    def test_로딩을_켜면_타이머가_돈다(self, qtbot) -> None:
        w = ShimmerEffect()
        qtbot.addWidget(w)
        w.show()
        w.set_loading(True)
        assert w.is_loading
        assert w._timer.isActive()

    def test_로딩을_끄면_타이머가_멈춘다(self, qtbot) -> None:
        w = ShimmerEffect()
        qtbot.addWidget(w)
        w.show()
        w.set_loading(True)
        w.set_loading(False)
        assert not w.is_loading
        assert not w._timer.isActive()

    def test_숨겨지면_로딩중이어도_타이머가_멈춘다(self, qtbot) -> None:
        w = ShimmerEffect()
        qtbot.addWidget(w)
        w.show()
        w.set_loading(True)
        w.hide()
        assert not w._timer.isActive()

    def test_다시_보이면_로딩중이던_타이머가_재개된다(self, qtbot) -> None:
        w = ShimmerEffect()
        qtbot.addWidget(w)
        w.show()
        w.set_loading(True)
        w.hide()
        w.show()
        assert w._timer.isActive()

    def test_같은_값으로_다시_불러도_상태가_바뀌지_않는다(self, qtbot) -> None:
        w = ShimmerEffect()
        qtbot.addWidget(w)
        w.show()
        w.set_loading(False)
        assert not w._timer.isActive()

    def test_그려도_예외없이_동작한다(self, qtbot) -> None:
        w = ShimmerEffect()
        qtbot.addWidget(w)
        w.resize(120, 20)
        w.show()
        w.set_loading(True)
        pixmap = w.grab()
        assert not pixmap.isNull()


class TestSkeletonRow:
    def test_높이가_지정한_값으로_고정된다(self, qtbot) -> None:
        row = SkeletonRow(cell_count=3, height=24)
        qtbot.addWidget(row)
        assert row.height() == 24

    def test_기본_칸_비율은_균등분할이다(self, qtbot) -> None:
        row = SkeletonRow(cell_count=2, height=16)
        qtbot.addWidget(row)
        row.resize(100, 16)
        rects = row._cell_rects()
        assert len(rects) == 2
        assert abs(rects[0].width() - rects[1].width()) < 0.01

    def test_비율을_다르게_주면_폭이_비율대로_나뉜다(self, qtbot) -> None:
        row = SkeletonRow(cell_count=2, height=16, cell_ratios=[3, 1])
        qtbot.addWidget(row)
        row.resize(100, 16)
        rects = row._cell_rects()
        assert rects[0].width() > rects[1].width()
        ratio = rects[0].width() / rects[1].width()
        assert 2.5 < ratio < 3.5

    def test_set_loading은_행_전체에_적용된다(self, qtbot) -> None:
        row = SkeletonRow(cell_count=3, height=16)
        qtbot.addWidget(row)
        row.show()
        row.set_loading(True)
        assert row.is_loading
        assert row._timer.isActive()
        row.set_loading(False)
        assert not row.is_loading
        assert not row._timer.isActive()

    def test_숨겨지면_타이머가_멈추고_다시_보이면_재개된다(self, qtbot) -> None:
        row = SkeletonRow(cell_count=2, height=16)
        qtbot.addWidget(row)
        row.show()
        row.set_loading(True)
        row.hide()
        assert not row._timer.isActive()
        row.show()
        assert row._timer.isActive()

    def test_그려도_예외없이_동작한다(self, qtbot) -> None:
        row = SkeletonRow(cell_count=3, height=16, cell_ratios=[2, 1, 1])
        qtbot.addWidget(row)
        row.resize(200, 16)
        row.show()
        row.set_loading(True)
        pixmap = row.grab()
        assert not pixmap.isNull()
