"""휠 스크롤 부드러움 — 픽셀 단위 이동과 수정키 통과 규칙을 고정한다.

여기서 지키는 계약:
* 아이템 뷰는 **픽셀 단위**로 구른다(기본값은 항목 단위라 카드 한 장씩 점프한다).
* **수정키가 눌린 휠은 가로채지 않는다** — Ctrl+휠(목록 뷰 전환)·Ctrl+Shift+휠(자막
  크기·위치)이 이미 그 입력을 쓴다. 가로채면 그 기능들이 조용히 죽는다.
* 세로로 스크롤할 게 없고 가로만 있는 띠(추천 스트립)에서는 휠이 가로로 흐른다.
* 영상 표시면(QGraphicsView)에는 걸지 않는다 — 그 위 휠은 자막 조절용이다.
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QGraphicsView,
    QLabel,
    QListWidget,
    QScrollArea,
)

from gui.smooth_scroll import apply_smooth_scroll, apply_smooth_scroll_tree


def _wheel(delta: int = -120, modifiers=Qt.KeyboardModifier.NoModifier) -> QWheelEvent:
    return QWheelEvent(
        QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, delta),
        Qt.MouseButton.NoButton, modifiers, Qt.ScrollPhase.NoScrollPhase, False,
    )


def _list_with_items(qtbot, count: int = 200) -> QListWidget:
    view = QListWidget()
    qtbot.addWidget(view)
    for i in range(count):
        view.addItem(f"항목 {i}")
    view.resize(200, 150)
    view.show()
    qtbot.waitExposed(view)
    return view


class TestScrollMode:
    def test_아이템_뷰는_픽셀_단위로_구른다(self, qtbot):
        view = _list_with_items(qtbot)

        assert apply_smooth_scroll(view) is True

        assert view.verticalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerPixel
        assert view.horizontalScrollMode() == QAbstractItemView.ScrollMode.ScrollPerPixel

    def test_두_번_적용해도_한_번만_설치된다(self, qtbot):
        view = _list_with_items(qtbot)
        assert apply_smooth_scroll(view) is True
        assert apply_smooth_scroll(view) is False

    def test_영상_표시면에는_걸지_않는다(self, qtbot):
        view = QGraphicsView()
        qtbot.addWidget(view)

        assert apply_smooth_scroll(view) is False

    def test_스크롤_영역이_아닌_위젯은_건너뛴다(self, qtbot):
        label = QLabel("x")
        qtbot.addWidget(label)

        assert apply_smooth_scroll(label) is False


class TestWheelHandling:
    def test_수정키_휠은_가로채지_않는다(self, qtbot):
        """Ctrl+휠은 뷰 전환·자막 조절이 쓴다 — 여기서 삼키면 그 기능이 죽는다."""
        view = _list_with_items(qtbot)
        apply_smooth_scroll(view)
        scroller = view._smooth_scroller

        for mod in (Qt.KeyboardModifier.ControlModifier,
                    Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            assert scroller.eventFilter(view.viewport(), _wheel(modifiers=mod)) is False

    def test_보통_휠은_받아서_애니메이션으로_옮긴다(self, qtbot):
        view = _list_with_items(qtbot)
        apply_smooth_scroll(view)
        scroller = view._smooth_scroller
        bar = view.verticalScrollBar()
        start = bar.value()

        assert scroller.eventFilter(view.viewport(), _wheel(-120)) is True

        qtbot.waitUntil(lambda: bar.value() > start, timeout=2000)

    def test_연속으로_굴리면_더_멀리_간다(self, qtbot):
        view = _list_with_items(qtbot)
        apply_smooth_scroll(view)
        scroller = view._smooth_scroller

        scroller.eventFilter(view.viewport(), _wheel(-120))
        one_step_target = scroller._target
        scroller.eventFilter(view.viewport(), _wheel(-120))

        assert scroller._target > one_step_target   # 목표가 누적된다

    def test_끝에_닿으면_부모에게_넘긴다(self, qtbot):
        view = _list_with_items(qtbot)
        apply_smooth_scroll(view)
        scroller = view._smooth_scroller
        bar = view.verticalScrollBar()
        bar.setValue(bar.minimum())

        # 이미 맨 위인데 위로 굴림 → 소비하지 않아야 바깥 스크롤이 이어진다
        assert scroller.eventFilter(view.viewport(), _wheel(+120)) is False

    def test_세로가_없으면_가로로_흐른다(self, qtbot):
        """추천 스트립처럼 가로로만 긴 띠 — 휠이 아무 일도 안 하면 안 된다."""
        area = QScrollArea()
        qtbot.addWidget(area)
        inner = QLabel("가로로 아주 긴 내용")
        inner.setFixedSize(3000, 80)
        area.setWidget(inner)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.resize(300, 100)
        area.show()
        qtbot.waitExposed(area)
        apply_smooth_scroll(area)
        scroller = area._smooth_scroller
        hbar = area.horizontalScrollBar()
        start = hbar.value()

        assert scroller.eventFilter(area.viewport(), _wheel(-120)) is True

        qtbot.waitUntil(lambda: hbar.value() > start, timeout=2000)

    def test_내용이_뷰포트보다_살짝_커도_가로로_흐른다(self, qtbot):
        """추천 스트립 실제 신고 — 카드 높이가 뷰포트보다 몇 px만 더 커도 세로
        스크롤바(숨겨져 있어도)가 근소한 범위를 가져, 예전엔 휠마다 그 숨은 막대가
        움직이며 화면이 위아래로 덜거덕거렸다. ``ScrollBarAlwaysOff``는 설계상
        가로 전용이라는 뜻이므로, 근소한 범위가 있어도 가로로 고정해야 한다.
        """
        area = QScrollArea()
        qtbot.addWidget(area)
        inner = QLabel("가로로 아주 긴 내용")
        # 뷰포트보다 세로로 살짝 더 크게 — 실제 신고의 "카드가 몇 px 더 크다" 상황 재현.
        inner.setFixedSize(3000, 130)
        area.setWidget(inner)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.resize(300, 120)
        area.show()
        qtbot.waitExposed(area)
        vbar = area.verticalScrollBar()
        assert vbar.maximum() > vbar.minimum(), "재현 전제 — 세로 범위가 실제로 생겨야 한다"
        apply_smooth_scroll(area)
        scroller = area._smooth_scroller
        hbar = area.horizontalScrollBar()
        v_before = vbar.value()
        h_start = hbar.value()

        assert scroller.eventFilter(area.viewport(), _wheel(-120)) is True

        qtbot.waitUntil(lambda: hbar.value() > h_start, timeout=2000)
        assert vbar.value() == v_before   # 숨은 세로 막대는 전혀 움직이지 않는다


class TestApplyToTree:
    def test_하위_스크롤_영역에_한_번에_적용된다(self, qtbot):
        from PyQt6.QtWidgets import QVBoxLayout, QWidget

        root = QWidget()
        qtbot.addWidget(root)
        layout = QVBoxLayout(root)
        first, second = QListWidget(), QScrollArea()
        layout.addWidget(first)
        layout.addWidget(second)

        count = apply_smooth_scroll_tree(root)

        assert count == 2
        assert first._smooth_scroller is not None
        assert second._smooth_scroller is not None
        QApplication.processEvents()
