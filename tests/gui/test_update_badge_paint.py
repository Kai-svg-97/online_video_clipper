"""업데이트 배지를 **실제로 그려 본다**.

`paintEvent` 안에서 난 파이썬 예외는 PyQt가 프로세스 종료로 처리한다(Windows에서
0xC0000409) — 예외 메시지도 로그도 없이 앱이 그냥 사라진다. v1.27.0에서 다운로드
카드가 이 경로로 앱을 죽인 적이 있다(DTO에 속성 하나가 빠져 있었다).

그래서 여기서는 '값을 잘 계산했나'(그건 `tests/unit/domain/test_update_badge_state.py`가
본다)가 아니라 **그리다가 죽지 않는가**를 본다. 특히 배지는 상태가 7가지이고 진행률에
따라 그리는 경로가 갈리므로, 그 갈림을 전부 밟아 본다.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QPainter, QPixmap

from domain.updater.badge_state import BadgeState, ClickAction
from gui.themes.manager import ThemeManager
from gui.themes.tokens import PRESETS
from gui.widgets.update_badge import UpdateBadge


@pytest.fixture
def badge(qtbot, qapp_instance):
    b = UpdateBadge("1.29.0")
    qtbot.addWidget(b)
    return b


def _paint(widget) -> None:
    """실제로 그린다 — 그리다 죽으면 테스트가 아니라 프로세스가 끝난다."""
    pm = QPixmap(QSize(max(widget.width(), 1), max(widget.height(), 1)))
    pm.fill()
    painter = QPainter(pm)
    try:
        widget.render(painter)
    finally:
        painter.end()


class TestPaintsInEveryState:
    def test_발견(self, badge):
        badge.show_found("1.30.0", 179 * 1024 * 1024)
        _paint(badge)

    def test_다운로드_시작_직후(self, badge):
        """0%에서 채움 경로를 건너뛰는 분기를 밟는다."""
        badge.show_found("1.30.0")
        badge.show_progress(0, 100)
        _paint(badge)

    @pytest.mark.parametrize("pct", [1, 49, 50, 51, 99, 100])
    def test_진행률_전_구간(self, badge, pct):
        """50%에서 글자색이 갈린다 — 그 경계를 양쪽 다 밟는다."""
        badge.show_found("1.30.0")
        badge.show_progress(pct, 100)
        _paint(badge)

    def test_총량을_모를_때(self, badge):
        """Content-Length 없는 응답 — 0으로 나누는 경로가 없어야 한다."""
        badge.show_found("1.30.0")
        badge.show_progress(5 * 1024 * 1024, 0)
        _paint(badge)

    def test_받은_양이_전체를_넘을_때(self, badge):
        badge.show_found("1.30.0")
        badge.show_progress(150, 100)
        _paint(badge)

    def test_준비됨(self, badge):
        badge.show_ready("1.30.0")
        _paint(badge)

    def test_설치_중(self, badge):
        badge.show_ready("1.30.0")
        badge.show_installing()
        _paint(badge)

    def test_실패(self, badge):
        badge.show_found("1.30.0")
        badge.show_failed("Read timed out.")
        _paint(badge)

    def test_실패_사유가_비어도(self, badge):
        badge.show_found("1.30.0")
        badge.show_failed("")
        _paint(badge)

    def test_아주_긴_버전_문자열(self, badge):
        """폭 상한을 넘겨 글자가 잘리는 경로."""
        badge.show_found("1.30.0-rc1.build.20260919.longer")
        _paint(badge)

    def test_호버_상태(self, badge):
        badge.show_found("1.30.0")
        badge._hover = True
        _paint(badge)


class TestPaintsInEveryTheme:
    @pytest.mark.parametrize("preset", sorted(PRESETS))
    def test_모든_테마에서_그려진다(self, badge, preset):
        ThemeManager.instance().apply(preset)
        badge.show_found("1.30.0")
        _paint(badge)
        badge.show_progress(70, 100)
        _paint(badge)


class TestVisibility:
    def test_처음에는_숨어_있다(self, badge):
        """업데이트가 없을 때 빈 배지가 자리를 차지하면 안 된다."""
        assert badge.state is BadgeState.HIDDEN
        assert badge.isHidden()

    def test_발견하면_보인다(self, badge, qtbot):
        badge.show_found("1.30.0")
        assert not badge.isHidden()

    def test_숨기면_사라진다(self, badge):
        badge.show_found("1.30.0")
        badge.hide_badge()
        assert badge.isHidden()


class TestClick:
    def test_발견_상태에서_누르면_신호가_나간다(self, badge, qtbot):
        badge.show_found("1.30.0")
        with qtbot.waitSignal(badge.clicked, timeout=500):
            badge.mouseReleaseEvent(_left_click(badge))

    def test_받는_중에는_눌러도_조용하다(self, badge):
        """두 번 누르면 워커가 둘이 된다."""
        badge.show_found("1.30.0")
        badge.show_progress(50, 100)
        seen: list = []
        badge.clicked.connect(lambda: seen.append(True))
        badge.mouseReleaseEvent(_left_click(badge))
        assert not seen

    def test_준비되면_설치_동작을_알린다(self, badge):
        badge.show_ready("1.30.0")
        assert badge.action is ClickAction.INSTALL

    def test_실패하면_다시_받기_동작(self, badge):
        badge.show_found("1.30.0")
        badge.show_failed("boom")
        assert badge.action is ClickAction.DOWNLOAD

    def test_버전을_모른_채_실패하면_숨는다(self, badge):
        """발견 없이 실패가 오는 경로는 없지만, 와도 빈 배지를 띄우진 않는다."""
        badge.show_failed("boom")
        assert badge.isHidden()


class TestProgressMonotonic:
    def test_진행률은_되돌아가지_않는다(self, badge):
        """이어받기 재시도로 0이 오면 배지가 깜빡인다 — 최대값만 반영한다."""
        badge.show_found("1.30.0")
        badge.show_progress(80, 100)
        badge.show_progress(10, 100)
        assert badge._view.fill == pytest.approx(0.8)

    def test_새로_발견하면_진행률이_초기화된다(self, badge):
        badge.show_found("1.30.0")
        badge.show_progress(80, 100)
        badge.show_found("1.31.0")
        assert badge._view.fill == 0.0


def _left_click(widget):
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtCore import Qt as _Qt

    center = QPointF(widget.rect().center())
    return QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        center,
        center,
        _Qt.MouseButton.LeftButton,
        _Qt.MouseButton.LeftButton,
        _Qt.KeyboardModifier.NoModifier,
    )
