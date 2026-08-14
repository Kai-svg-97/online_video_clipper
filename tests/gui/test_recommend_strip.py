"""추천 영상 스트립 — 접기/펼치기, 카드 드래그 MIME, 트리 URL 드롭 대상 판정.

드래그는 실제 드롭 경로(카테고리 트리의 URL 드롭)에 의존하므로, 카드가 만드는
MIME이 '브라우저에서 URL을 끌어온 것과 같은 형태'인지와, 트리가 어떤 노드를
URL 드롭 대상으로 인정하는지를 함께 고정한다. 한쪽만 맞으면 드롭이 조용히
무시돼 기능 전체가 죽는다.
"""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from PyQt6.QtCore import QMimeData, QUrl

from application.library.dtos import FeedVideoDTO
from gui.panels.feed_panel import RecommendStrip, _FeedCard
from gui.panels.library_panel import (
    _ITEM_TYPE_ROLE,
    _ITYPE_CATEGORY,
    _NO_URL_TARGET,
    _PlaylistTree,
    _mime_may_contain_url,
    _url_from_mime,
)


def _dto(vid: str = "abc12345678", title: str = "추천 영상") -> FeedVideoDTO:
    return FeedVideoDTO(
        url=f"https://www.youtube.com/watch?v={vid}",
        title=title,
        channel_name="채널",
        channel_id="UC0",
        thumbnail_url="",          # 네트워크 로더가 뜨지 않게 빈 값
        thumbnail_path="",
        published_at="",
        view_count=None,
        duration_sec=125,
        in_library=False,
        yt_video_id=vid,
    )


class TestStripToggle:
    def test_header_stays_visible_when_collapsed(self, qapp_instance):
        strip = RecommendStrip()
        strip.set_items([_dto()])

        strip.set_expanded(False)
        assert strip.is_expanded is False
        assert strip._bar.isVisibleTo(strip)      # 접어도 헤더(=split bar)는 남는다
        assert not strip._scroll.isVisibleTo(strip)

        strip.set_expanded(True)
        assert strip._scroll.isVisibleTo(strip)

    def test_toggle_emits_expanded_changed(self, qapp_instance):
        strip = RecommendStrip()
        seen: list[bool] = []
        strip.expanded_changed.connect(seen.append)

        strip.toggle()
        strip.toggle()

        assert seen == [False, True]

    def test_set_expanded_can_stay_silent(self, qapp_instance):
        """복원 시에는 시그널을 내지 않는다 — 설정 저장·재조회가 유발되면 안 된다."""
        strip = RecommendStrip()
        seen: list[bool] = []
        strip.expanded_changed.connect(seen.append)

        strip.set_expanded(False, notify=False)

        assert seen == []
        assert strip.is_expanded is False

    def test_set_items_replaces_previous_cards(self, qapp_instance):
        strip = RecommendStrip()
        strip.set_items([_dto("v1"), _dto("v2")])
        assert strip.count() == 2

        strip.set_items([_dto("v3")])
        assert strip.count() == 1

    def test_loading_state_disables_refresh(self, qapp_instance):
        strip = RecommendStrip()
        strip.set_loading(True)
        assert not strip._refresh_btn.isEnabled()
        strip.set_loading(False)
        assert strip._refresh_btn.isEnabled()


class TestCardDragMime:
    def test_card_mime_matches_browser_url_drag(self, qapp_instance):
        """카드가 만드는 MIME은 브라우저 URL 드래그와 같은 형태여야 한다."""
        dto = _dto()
        mime = QMimeData()
        mime.setUrls([QUrl(dto.url)])
        mime.setText(dto.url)

        assert _mime_may_contain_url(mime)
        assert _url_from_mime(mime) == dto.url

    def test_drag_suppresses_click(self, qapp_instance):
        """드래그로 끝난 조작은 상세 진입 클릭으로 처리되지 않아야 한다."""
        card = _FeedCard(_dto(), draggable=True)
        clicked: list = []
        card.video_clicked.connect(clicked.append)
        card._start_url_drag = MagicMock()   # 실제 드래그 루프 진입 방지

        # 드래그가 시작된 상태를 재현하고 버튼을 놓는다.
        card._dragged = True
        card.mouseReleaseEvent(_left_release())
        assert clicked == []

        # 드래그가 없었으면 평소처럼 클릭으로 처리된다.
        card.mouseReleaseEvent(_left_release())
        assert len(clicked) == 1

    def test_non_draggable_card_never_starts_drag(self, qapp_instance):
        card = _FeedCard(_dto(), draggable=False)
        card._start_url_drag = MagicMock()
        card._press_pos = _origin()

        card.mouseMoveEvent(_left_move(500, 500))

        card._start_url_drag.assert_not_called()

    def test_dragging_far_enough_starts_url_drag(self, qapp_instance):
        card = _FeedCard(_dto(), draggable=True)
        card._start_url_drag = MagicMock()
        card._press_pos = _origin()

        card.mouseMoveEvent(_left_move(500, 500))

        card._start_url_drag.assert_called_once()

    def test_small_movement_does_not_start_drag(self, qapp_instance):
        card = _FeedCard(_dto(), draggable=True)
        card._start_url_drag = MagicMock()
        card._press_pos = _origin()

        card.mouseMoveEvent(_left_move(1, 1))

        card._start_url_drag.assert_not_called()

    def test_custom_thumb_size_is_applied(self, qapp_instance):
        card = _FeedCard(_dto(), thumb_size=(192, 108))
        assert (card._TW, card._TH) == (192, 108)
        # 기본 카드 크기는 클래스 기본값(320×180)을 유지한다.
        assert (_FeedCard._TW, _FeedCard._TH) == (320, 180)


class TestTreeUrlDropTarget:
    def test_category_node_accepts_url(self, qapp_instance):
        tree = _PlaylistTree(section="local")
        cid = uuid4()
        item = tree._make_category("Music", cid)

        assert tree._url_drop_target(item) == cid

    def test_local_root_maps_to_no_category(self, qapp_instance):
        tree = _PlaylistTree(section="local")
        root = tree._make_root("로컬", "local")

        # None은 '미분류로 등록'이라는 유효한 대상이다 — 거부(sentinel)와 구분된다.
        assert tree._url_drop_target(root) is None

    def test_empty_area_is_rejected(self, qapp_instance):
        tree = _PlaylistTree(section="local")
        assert tree._url_drop_target(None) is _NO_URL_TARGET

    def test_youtube_root_is_rejected(self, qapp_instance):
        tree = _PlaylistTree(section="youtube")
        yt_root = tree._make_root("YouTube", "youtube")
        assert tree._url_drop_target(yt_root) is _NO_URL_TARGET

    def test_non_category_node_is_rejected(self, qapp_instance):
        tree = _PlaylistTree(section="local")
        item = tree._make_category("Music", uuid4())
        item.setData(0, _ITEM_TYPE_ROLE, "channel")   # 카테고리가 아닌 노드로 위장
        assert tree._url_drop_target(item) is _NO_URL_TARGET

    def test_url_dropped_signal_carries_category(self, qapp_instance):
        """드롭 결과가 (url, cat_id)로 전달돼 그 카테고리에 등록된다."""
        tree = _PlaylistTree(section="local")
        cid = uuid4()
        item = tree._make_category("Music", cid)
        assert item.data(0, _ITEM_TYPE_ROLE) == _ITYPE_CATEGORY

        got: list[tuple] = []
        tree.url_dropped.connect(lambda url, cat: got.append((url, cat)))
        tree.url_dropped.emit("https://youtu.be/x", cid)

        assert got == [("https://youtu.be/x", cid)]


class TestFullDropPath:
    """실제 드래그 이벤트로 트리 드롭 경로를 통과시킨다.

    카드의 MIME 형태와 트리의 대상 판정이 각각 맞아도, 그 사이 이벤트 핸들러가
    어긋나면(dragEnter에서 상태를 세팅하지 않는 등) 드롭이 조용히 무시된다.
    """

    def _tree_with_category(self, qtbot):
        tree = _PlaylistTree(section="local")
        qtbot.addWidget(tree)
        cid = uuid4()
        item = tree._make_category("Music", cid)
        tree.addTopLevelItem(item)
        tree.resize(320, 240)
        tree.show()
        qtbot.waitExposed(tree)
        return tree, item, cid

    def _url_mime(self, url: str) -> QMimeData:
        mime = QMimeData()
        mime.setUrls([QUrl(url)])
        mime.setText(url)
        return mime

    def test_drop_on_category_emits_url_and_category(self, qtbot):
        from PyQt6.QtCore import QPointF, Qt
        from PyQt6.QtGui import QDragEnterEvent, QDropEvent

        tree, item, cid = self._tree_with_category(qtbot)
        mime = self._url_mime("https://www.youtube.com/watch?v=recdrop123")
        got: list[tuple] = []
        tree.url_dropped.connect(lambda url, cat: got.append((url, cat)))

        pos = tree.visualItemRect(item).center()
        tree.dragEnterEvent(QDragEnterEvent(
            pos, Qt.DropAction.CopyAction, mime,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        ))
        assert tree._ext_url_drag is True   # dragEnter가 URL 드래그를 인식했다

        tree.dropEvent(QDropEvent(
            QPointF(pos), Qt.DropAction.CopyAction, mime,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        ))

        assert got == [("https://www.youtube.com/watch?v=recdrop123", cid)]

    def test_drop_without_url_is_ignored(self, qtbot):
        from PyQt6.QtCore import QPointF, Qt
        from PyQt6.QtGui import QDropEvent

        tree, item, _cid = self._tree_with_category(qtbot)
        got: list[tuple] = []
        tree.url_dropped.connect(lambda url, cat: got.append((url, cat)))

        tree._ext_url_drag = True   # URL 드래그로 진입했지만 실제 내용이 없는 경우
        pos = tree.visualItemRect(item).center()
        # QDropEvent는 QMimeData를 소유하지 않는다 — 인라인으로 넘기면 임시 객체가
        # 즉시 파괴돼 핸들러가 dangling 포인터를 읽고 프로세스가 죽는다.
        empty = QMimeData()
        tree.dropEvent(QDropEvent(
            QPointF(pos), Qt.DropAction.CopyAction, empty,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
        ))

        assert got == []


# ── 이벤트 헬퍼 ──────────────────────────────────────────────────────────────

def _origin():
    from PyQt6.QtCore import QPoint
    return QPoint(0, 0)


def _left_release():
    from PyQt6.QtCore import QPoint, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    return QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(QPoint(5, 5)),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )


def _left_move(x: int, y: int):
    from PyQt6.QtCore import QPoint, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    return QMouseEvent(
        QMouseEvent.Type.MouseMove,
        QPointF(QPoint(x, y)),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
