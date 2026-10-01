"""라이브러리 트리의 고정 헤더(sticky scroll).

펼쳐진 폴더의 자식을 스크롤해 내려가는 동안 그 조상 폴더들이 맨 위에 한 줄씩 쌓여
고정된다. 폴더의 마지막 자손 행이 그 고정 줄 아래까지 올라오면 고정 줄이 함께 밀려
올라가며 사라진다(편집기의 sticky scroll과 같은 연출).

행 높이는 30px(`_TreeRowDelegate`), 스크롤은 앱처럼 픽셀 단위로 둔다 — 밀려 올라가는
거리를 픽셀로 검증하려면 항목 단위 스크롤이면 안 된다.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QWheelEvent
from PyQt6.QtWidgets import QAbstractItemView, QApplication

from gui.panels.library.sticky_header import StickyHeader, compute_sticky_rows
from gui.panels.library_panel import _PlaylistTree

ROW = 30


def _category(tree, name, parent=None):
    item = tree._make_category(name, uuid4(), video_count=1)
    if parent is None:
        tree.addTopLevelItem(item)
    else:
        parent.addChild(item)
    return item


@pytest.fixture
def tree(qtbot):
    """행 번호(0부터)가 곧 y/30인 트리.

        0  음악 ▾
        1    J-pop
        2    K-pop
        3    타국 음악 ▾
        4      일본
        5      중국
        6      대만
        7      태국
        8    배경 음악
        9  영화 ▸        (접힘 — 자식 3개)
       10  공부 ▾
       11    수학
      ...
       30    과목 20      (마지막 행)
    """
    t = _PlaylistTree(section="local")
    qtbot.addWidget(t)
    t.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    t.resize(260, 300)          # 10행 높이의 뷰포트

    music = _category(t, "음악")
    _category(t, "J-pop", music)
    _category(t, "K-pop", music)
    abroad = _category(t, "타국 음악", music)
    for name in ("일본", "중국", "대만", "태국"):
        _category(t, name, abroad)
    _category(t, "배경 음악", music)

    movies = _category(t, "영화")
    for name in ("SF", "드라마", "공포"):
        _category(t, name, movies)

    study = _category(t, "공부")
    _category(t, "수학", study)
    for i in range(2, 21):
        _category(t, f"과목 {i}", study)

    music.setExpanded(True)
    abroad.setExpanded(True)
    study.setExpanded(True)
    t.show()
    qtbot.waitExposed(t)
    t.items = {"음악": music, "타국 음악": abroad, "영화": movies, "공부": study}
    return t


def _scroll(tree, px):
    tree.verticalScrollBar().setValue(px)
    QApplication.processEvents()


def _names(tree):
    from gui.panels.library_panel import _NAME_ROLE
    return [r.item.data(0, _NAME_ROLE) for r in compute_sticky_rows(tree)]


def _tops(tree):
    return [r.top for r in compute_sticky_rows(tree)]


class TestWhatSticks:
    def test_맨_위면_아무것도_고정하지_않는다(self, tree):
        _scroll(tree, 0)
        assert compute_sticky_rows(tree) == []

    def test_자식을_지나는_동안_부모가_고정된다(self, tree):
        _scroll(tree, 2 * ROW)          # 맨 위 행 = K-pop(음악의 자식)
        assert _names(tree) == ["음악"]
        assert _tops(tree) == [0]

    def test_중첩되면_조상을_단계별로_쌓는다(self, tree):
        _scroll(tree, 5 * ROW)          # 맨 위 행 = 중국(타국 음악의 자식)
        assert _names(tree) == ["음악", "타국 음악"]
        assert _tops(tree) == [0, ROW]

    def test_접힌_폴더는_고정하지_않는다(self, tree):
        _scroll(tree, 9 * ROW)          # 맨 위 행 = 영화(접힘) — 조상이 없다
        assert compute_sticky_rows(tree) == []

    def test_폴더를_다_지나면_사라진다(self, tree):
        _scroll(tree, 9 * ROW + 5)      # 음악의 마지막 자손(배경 음악)이 이미 위로 지났다
        assert "음악" not in _names(tree)


class TestPushUp:
    def test_마지막_자손이_올라오면_함께_밀려_올라간다(self, tree):
        # 음악의 마지막 자손 = 8행(배경 음악), 아래끝 = 9*30 = 270.
        # 스크롤 260이면 그 행의 아래끝이 뷰포트 y=10 — 고정 줄(높이 30)은 10-30 = -20에 선다.
        _scroll(tree, 260)
        rows = compute_sticky_rows(tree)
        assert [r.item for r in rows][:1] == [tree.items["음악"]]
        assert rows[0].top == -20

    def test_중첩된_줄은_자기_마지막_자손에서_먼저_밀린다(self, tree):
        # 타국 음악의 마지막 자손 = 7행(태국), 아래끝 240. 스크롤 190이면 뷰포트 y=50 —
        # 2번째 줄(원래 30~60)은 50-30 = 20에 선다. 음악 줄은 그대로 0.
        _scroll(tree, 190)
        assert _names(tree) == ["음악", "타국 음악"]
        assert _tops(tree) == [0, 20]


class TestLimits:
    def test_최대_3줄(self, qtbot):
        t = _PlaylistTree(section="local")
        qtbot.addWidget(t)
        t.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        t.resize(260, 300)
        parent = None
        chain = []
        for depth in range(6):
            parent = _category(t, f"단계 {depth}", parent)
            chain.append(parent)
        for i in range(30):
            _category(t, f"잎 {i}", parent)
        for node in chain:
            node.setExpanded(True)
        t.show()
        qtbot.waitExposed(t)
        _scroll(t, 10 * ROW)
        assert len(compute_sticky_rows(t)) == 3

    def test_낮은_트리에서는_줄을_줄여_목록을_가리지_않는다(self, tree):
        tree.resize(260, 4 * ROW)       # 4행 높이 — 고정 줄은 최대 2줄
        QApplication.processEvents()
        _scroll(tree, 5 * ROW)
        assert len(compute_sticky_rows(tree)) <= 2


class TestHeaderWidget:
    def test_트리에_붙어_있다(self, tree):
        assert isinstance(tree._sticky, StickyHeader)
        assert tree._sticky.parent() is tree.viewport()

    def test_스크롤하면_보이고_맨_위로_가면_숨는다(self, tree):
        _scroll(tree, 5 * ROW)
        assert tree._sticky.isVisible()
        assert tree._sticky.height() == 2 * ROW
        _scroll(tree, 0)
        assert not tree._sticky.isVisible()

    def test_펼치고_접으면_다시_계산한다(self, tree):
        _scroll(tree, 5 * ROW)
        assert tree._sticky.isVisible()
        tree.items["음악"].setExpanded(False)
        QApplication.processEvents()
        assert [r.item for r in tree._sticky.rows()] == [
            r.item for r in compute_sticky_rows(tree)
        ]

    def test_그려도_터지지_않는다(self, tree):
        """paint 안의 예외는 로그 없이 앱을 끈다 — 실제로 그려 본다."""
        _scroll(tree, 190)
        pixmap = tree._sticky.grab()
        assert not pixmap.isNull()

    def test_테마가_바뀌면_다시_그린다(self, tree, monkeypatch):
        """신호를 직접 보낸다 — `apply()`는 사용자 설정에 테마를 저장한다."""
        from gui.themes.manager import ThemeManager
        from gui.themes.tokens import PRESETS

        _scroll(tree, 5 * ROW)
        calls = []
        monkeypatch.setattr(tree._sticky, "update", lambda *a: calls.append(a))
        ThemeManager.instance().theme_changed.emit(next(iter(PRESETS.values())))
        assert calls, "테마가 바뀌었는데 다시 그리지 않았다 — 옛 색으로 남는다"


class TestInput:
    def test_고정_줄을_누르면_그_폴더로_간다(self, tree, qtbot):
        _scroll(tree, 5 * ROW)          # 고정: 음악(0), 타국 음악(30)
        qtbot.mouseClick(tree._sticky, Qt.MouseButton.LeftButton, pos=QPoint(40, ROW + 10))
        assert tree.currentItem() is tree.items["타국 음악"]
        # 그 폴더 행이 자기 조상 고정 줄(음악) 바로 아래에 온다 — 가려지지 않는다
        assert tree.visualItemRect(tree.items["타국 음악"]).top() == ROW

    def test_고정_줄_위에서도_휠로_스크롤된다(self, tree):
        _scroll(tree, 5 * ROW)
        before = tree.verticalScrollBar().value()
        pos = QPointF(40, 10)
        ev = QWheelEvent(
            pos, tree._sticky.mapToGlobal(pos), QPoint(0, 0), QPoint(0, -120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        )
        QApplication.sendEvent(tree._sticky, ev)
        QApplication.processEvents()
        assert tree.verticalScrollBar().value() > before, "고정 줄이 휠을 삼켰다"

    def test_드래그하는_동안_숨는다(self, tree):
        """가려진 행으로 떨어져 엉뚱한 폴더에 들어가면 안 된다."""
        _scroll(tree, 5 * ROW)
        assert tree._sticky.isVisible()
        mime = QMimeData()
        mime.setUrls([QUrl("https://www.youtube.com/watch?v=abc")])
        enter = QDragEnterEvent(
            QPoint(40, 10), Qt.DropAction.CopyAction, mime,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(tree.viewport(), enter)
        assert not tree._sticky.isVisible()
        drop = QDropEvent(
            QPointF(40, 10), Qt.DropAction.CopyAction, mime,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        tree._sticky.eventFilter(tree.viewport(), drop)
        QApplication.processEvents()
        assert tree._sticky.isVisible()
