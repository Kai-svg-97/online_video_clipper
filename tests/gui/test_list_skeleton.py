"""`ListSkeleton`(목록 로딩 스켈레톤 오버레이) 단위 검증.

카드/행 하나당 `SkeletonRow` 몇 개로 구성한 자리표시자를 뷰포트에 맞춰 만들고,
로딩이 끝나면 전부 치운다(숨은 채 타이머가 도는 위젯이 없어야 한다).
"""
from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from gui.panels.library.constants import _VIEW_DETAIL, _VIEW_ICON, _VIEW_LIST
from gui.panels.library.skeleton_list import ListSkeleton


def _host(qtbot, w=800, h=600) -> QWidget:
    host = QWidget()
    host.resize(w, h)
    qtbot.addWidget(host)
    host.show()
    return host


class TestVisibility:
    def test_초기상태는_숨어있다(self, qtbot) -> None:
        host = _host(qtbot)
        skeleton = ListSkeleton(host)
        qtbot.addWidget(skeleton)

        assert skeleton.isHidden()
        assert not skeleton.is_loading

    def test_로딩을_켜면_보인다(self, qtbot) -> None:
        host = _host(qtbot)
        skeleton = ListSkeleton(host)
        qtbot.addWidget(skeleton)

        skeleton.set_loading(True)

        assert not skeleton.isHidden()
        assert skeleton.is_loading

    def test_로딩을_끄면_숨고_자식이_모두_비워진다(self, qtbot) -> None:
        host = _host(qtbot)
        skeleton = ListSkeleton(host)
        qtbot.addWidget(skeleton)
        skeleton.set_loading(True)
        assert len(skeleton._blocks) > 0

        skeleton.set_loading(False)

        assert skeleton.isHidden()
        assert skeleton._blocks == []

    def test_같은_값으로_다시_불러도_상태가_바뀌지_않는다(self, qtbot) -> None:
        host = _host(qtbot)
        skeleton = ListSkeleton(host)
        qtbot.addWidget(skeleton)

        skeleton.set_loading(False)

        assert skeleton.isHidden()
        assert skeleton._blocks == []


class TestLayoutByView:
    def test_아이콘_뷰는_카드마다_블록_세_개를_만든다(self, qtbot) -> None:
        host = _host(qtbot)
        skeleton = ListSkeleton(host)
        qtbot.addWidget(skeleton)

        skeleton.set_view(_VIEW_ICON)
        skeleton.set_loading(True)

        assert len(skeleton._blocks) % 3 == 0
        assert len(skeleton._blocks) > 0

    def test_리스트_뷰는_행마다_블록_네_개를_만든다(self, qtbot) -> None:
        host = _host(qtbot)
        skeleton = ListSkeleton(host)
        qtbot.addWidget(skeleton)

        skeleton.set_view(_VIEW_LIST)
        skeleton.set_loading(True)

        assert len(skeleton._blocks) % 4 == 0
        assert len(skeleton._blocks) > 0

    def test_표_뷰는_행마다_블록_한_개를_만든다(self, qtbot) -> None:
        host = _host(qtbot)
        skeleton = ListSkeleton(host)
        qtbot.addWidget(skeleton)

        skeleton.set_view(_VIEW_DETAIL)
        skeleton.set_loading(True)

        assert len(skeleton._blocks) > 0

    def test_뷰를_바꾸면_다시_그려진다(self, qtbot) -> None:
        host = _host(qtbot)
        skeleton = ListSkeleton(host)
        qtbot.addWidget(skeleton)
        skeleton.set_view(_VIEW_ICON)
        skeleton.set_loading(True)
        icon_count = len(skeleton._blocks)

        skeleton.set_view(_VIEW_LIST)

        assert len(skeleton._blocks) % 4 == 0
        assert len(skeleton._blocks) != icon_count or icon_count % 4 == 0

    def test_뷰포트를_채울_만큼만_그린다(self, qtbot) -> None:
        """고정 개수가 아니라 창 크기에 맞춰 계산해야 한다 — 작은 창은 적게."""
        small_host = _host(qtbot, w=400, h=300)
        small_skeleton = ListSkeleton(small_host)
        qtbot.addWidget(small_skeleton)
        small_skeleton.set_view(_VIEW_ICON)
        small_skeleton.set_loading(True)

        big_host = _host(qtbot, w=1600, h=1200)
        big_skeleton = ListSkeleton(big_host)
        qtbot.addWidget(big_skeleton)
        big_skeleton.set_view(_VIEW_ICON)
        big_skeleton.set_loading(True)

        assert len(big_skeleton._blocks) > len(small_skeleton._blocks)


class TestGeometry:
    def test_클릭을_통과시킨다(self, qtbot) -> None:
        from PyQt6.QtCore import Qt

        host = _host(qtbot)
        skeleton = ListSkeleton(host)
        qtbot.addWidget(skeleton)

        assert skeleton.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def test_부모_크기를_따라간다(self, qtbot) -> None:
        host = _host(qtbot, w=1000, h=700)
        skeleton = ListSkeleton(host)
        qtbot.addWidget(skeleton)

        host.resize(640, 480)
        qtbot.wait(50)

        assert skeleton.size() == host.size()

    def test_리사이즈되면_로딩_중일_때만_다시_그려진다(self, qtbot) -> None:
        host = _host(qtbot, w=1000, h=700)
        skeleton = ListSkeleton(host)
        qtbot.addWidget(skeleton)
        skeleton.set_loading(True)
        before = len(skeleton._blocks)

        host.resize(2000, 1400)
        qtbot.wait(50)

        assert len(skeleton._blocks) >= before
