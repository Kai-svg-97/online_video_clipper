"""브라우저에서 끌어온 URL을 카테고리 트리 노드에 떨어뜨리는 경로를 검증한다.

실패가 전부 **조용하다**는 게 이 경로의 특징이다 — MIME 종류를 하나라도 놓치거나
드래그 상태 플래그가 중간에 꺼지면 드롭이 아무 반응 없이 무시되고, 사용자는
"드래그가 안 된다"고만 알게 된다. 그래서 브라우저가 실제로 싣는 MIME 조합과
이벤트 순서를 그대로 재현해 고정한다.
"""
from __future__ import annotations

from uuid import uuid4

from PyQt6.QtCore import QByteArray, QMimeData, QPointF, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent

from gui.panels.library_panel import (
    _ITEM_TYPE_ROLE,
    _NO_URL_TARGET,
    _PlaylistTree,
    _mime_may_contain_url,
    _url_from_mime,
)

URL = "https://www.youtube.com/watch?v=dropTest01"


def _tree_with_category(qtbot):
    tree = _PlaylistTree(section="local")
    qtbot.addWidget(tree)
    cid = uuid4()
    item = tree._make_category("Music", cid)
    tree.addTopLevelItem(item)
    tree.resize(320, 240)
    tree.show()
    qtbot.waitExposed(tree)
    return tree, item, cid


def _chrome_link_mime() -> QMimeData:
    """크롬에서 링크를 끌 때의 조합 — uri-list + text + html."""
    mime = QMimeData()
    mime.setUrls([QUrl(URL)])
    mime.setText(URL)
    mime.setHtml(f'<a href="{URL}">영상</a>')
    return mime


def _text_only_mime() -> QMimeData:
    """주소 표시줄 텍스트처럼 text/plain만 실려 오는 경우."""
    mime = QMimeData()
    mime.setText(URL)
    return mime


def _windows_url_mime() -> QMimeData:
    """Windows 네이티브 URL 포맷(UTF-16LE)만 실려 오는 경우."""
    mime = QMimeData()
    mime.setData(
        'application/x-qt-windows-mime;value="UniformResourceLocatorW"',
        QByteArray((URL + "\x00").encode("utf-16-le")),
    )
    return mime


class TestMimeParsing:
    def test_크롬_링크_조합을_읽는다(self):
        assert _url_from_mime(_chrome_link_mime()) == URL

    def test_텍스트만_있어도_읽는다(self):
        assert _url_from_mime(_text_only_mime()) == URL
        assert _mime_may_contain_url(_text_only_mime()) is True

    def test_windows_네이티브_포맷을_읽는다(self):
        # UTF-16LE를 utf-8로 읽으면 "h" 한 글자에서 끊긴다 — 인코딩을 맞춰야 한다.
        assert _url_from_mime(_windows_url_mime()) == URL
        assert _mime_may_contain_url(_windows_url_mime()) is True

    def test_내용이_비어도_포맷만_있으면_드래그를_받아들인다(self):
        # Windows에서는 dragEnter 시점에 내용이 아직 안 채워질 수 있다.
        mime = QMimeData()
        mime.setData("text/uri-list", QByteArray(b""))
        assert _mime_may_contain_url(mime) is True

    def test_URL이_아니면_거부한다(self):
        mime = QMimeData()
        mime.setText("그냥 텍스트")
        assert _url_from_mime(mime) == ""


class TestDropOnCategoryNode:
    def _drop(self, tree, item, mime, with_enter=True):
        pos = tree.visualItemRect(item).center()
        if with_enter:
            tree.dragEnterEvent(QDragEnterEvent(
                pos, Qt.DropAction.CopyAction, mime,
                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
            ))
        tree.dropEvent(QDropEvent(
            QPointF(pos), Qt.DropAction.CopyAction, mime,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        ))

    def test_크롬_링크_드롭이_카테고리로_등록된다(self, qtbot):
        tree, item, cid = _tree_with_category(qtbot)
        got: list[tuple] = []
        tree.url_dropped.connect(lambda url, cat: got.append((url, cat)))

        self._drop(tree, item, _chrome_link_mime())

        assert got == [(URL, cid)]

    def test_텍스트만_있는_드롭도_등록된다(self, qtbot):
        tree, item, cid = _tree_with_category(qtbot)
        got: list[tuple] = []
        tree.url_dropped.connect(lambda url, cat: got.append((url, cat)))

        self._drop(tree, item, _text_only_mime())

        assert got == [(URL, cid)]

    def test_dragEnter를_놓쳐도_드롭이_동작한다(self, qtbot):
        """dragLeave로 상태가 꺼진 뒤 들어온 드롭 — 예전엔 조용히 무시됐다."""
        tree, item, cid = _tree_with_category(qtbot)
        got: list[tuple] = []
        tree.url_dropped.connect(lambda url, cat: got.append((url, cat)))
        tree._ext_url_drag = False

        self._drop(tree, item, _chrome_link_mime(), with_enter=False)

        assert got == [(URL, cid)]

    def test_dragMove가_카테고리_위에서_드롭을_허용한다(self, qtbot):
        tree, item, _cid = _tree_with_category(qtbot)
        mime = _chrome_link_mime()
        pos = tree.visualItemRect(item).center()

        ev = QDragMoveEvent(
            pos, Qt.DropAction.CopyAction, mime,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        )
        tree.dragMoveEvent(ev)

        assert ev.isAccepted()

    def test_대상이_아니면_거부한다(self, qtbot):
        tree, item, _cid = _tree_with_category(qtbot)
        item.setData(0, _ITEM_TYPE_ROLE, "channel")   # 카테고리가 아닌 노드
        got: list[tuple] = []
        tree.url_dropped.connect(lambda url, cat: got.append((url, cat)))

        self._drop(tree, item, _chrome_link_mime())

        assert got == []
        assert tree._url_drop_target(item) is _NO_URL_TARGET


class TestAutoExpandDuringDrag:
    def test_드래그_중_하위_카테고리에_닿을_수_있다(self, qtbot):
        """트리는 접힌 채로 로드된다 — 자동 펼침이 없으면 자식 노드에 못 떨군다."""
        tree = _PlaylistTree(section="local")
        qtbot.addWidget(tree)

        assert tree.autoExpandDelay() > 0
