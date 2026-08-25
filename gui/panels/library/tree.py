"""좌측 내비게이션 트리 — 로컬(카테고리·재생목록) + YouTube(구독) 두 섹션.

이 모듈은 위젯 **조립**만 담당한다: 시그널 정의, `__init__`, 행 그리기
(`drawBranches`), 노드 탐색·선택이다. 부피가 큰 동작은 `tree_mixins/` 패키지가
나눠 갖는다 — 스피너·로드/아이템 팩토리·드래그앤드롭·컨텍스트 메뉴.
런타임 클래스는 하나(mixin 합성)라 상태 공유 방식은 분할 전과 같다.

행 그리기는 `delegates._TreeRowDelegate`가, 셰브론·들여쓰기 선은 `drawBranches`가
그린다(아이템 영역에 그리면 펼침 클릭이 죽는다).
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import (
    QRect,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QFont, QPen,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from gui.themes.manager import ThemeManager
from gui.view_models.feed_vm import CHANNELS_ROOT_KEY, FEED_ALL_KEY

from gui.panels.library.constants import _CAT_ID_ROLE, _CHANNEL_URL_ROLE, _FOLDER_ID_ROLE, _ITEM_TYPE_ROLE, _ITYPE_CATEGORY, _ITYPE_CHANNEL, _ITYPE_FEED_ALL, _ITYPE_FOLDER, _ITYPE_PLAYLIST, _ITYPE_ROOT, _PLAYLIST_ID_ROLE, _SECTION_ROLE
from gui.panels.library.delegates import _TreeRowDelegate
from gui.panels.library.formatting import _t, tag_color
from gui.panels.library.tree_mixins import (
    _TreeContextMenuMixin,
    _TreeDragDropMixin,
    _TreeItemsMixin,
    _TreeSpinnerMixin,
)

logger = logging.getLogger(__name__)


class _PlaylistTree(
    _TreeSpinnerMixin,
    _TreeItemsMixin,
    _TreeDragDropMixin,
    _TreeContextMenuMixin,
    QTreeWidget,
):
    """재생목록 트리 위젯 — 로컬·YouTube 그룹 + 카테고리 + 폴더 + DnD."""

    playlist_selected             = pyqtSignal(object)         # UUID | None
    folder_selected               = pyqtSignal(object)         # folder UUID
    unfiled_selected              = pyqtSignal(object)         # source str ("local"|"youtube") — 미분류 디렉토리
    category_selected             = pyqtSignal(object)         # category UUID
    channel_selected              = pyqtSignal(str)            # 구독 채널 URL
    feed_all_selected             = pyqtSignal()               # 전체 구독 피드
    channels_root_selected        = pyqtSignal()               # "구독 채널" 노드 — 채널 목록 그리드
    sync_subs_req                 = pyqtSignal()               # "구독 채널" 노드 — YouTube 구독 재동기화
    playlist_delete_req           = pyqtSignal(object)         # playlist UUID
    playlist_rename_req           = pyqtSignal(object)         # playlist UUID
    playlist_move_req             = pyqtSignal(object, object) # (playlist_id, folder_id|None)
    folder_create_req             = pyqtSignal(str)            # source ("local"|"youtube")
    folder_rename_req             = pyqtSignal(object, str)    # (folder_id, old_name)
    folder_delete_req             = pyqtSignal(object)         # folder UUID
    copy_yt_to_local_req          = pyqtSignal(object)         # yt_playlist_id str
    sync_yt_req                   = pyqtSignal(object)         # yt_playlist_id str
    push_to_yt_req                = pyqtSignal(object, bool)   # (playlist_id, move: bool)
    import_yt_req                 = pyqtSignal()               # "↓ YouTube" button
    video_move_to_playlist_req    = pyqtSignal(object, object, object)  # (video_id_str, src_pl_id_str, tgt_pl_id UUID)
    add_category_req              = pyqtSignal(object)         # parent_id (UUID | None)
    rename_category_req           = pyqtSignal(object)         # category UUID
    delete_category_req           = pyqtSignal(object)         # category UUID
    category_reparented           = pyqtSignal(object, object) # (cat_id, new_parent_id | None)
    yt_playlist_to_category_req   = pyqtSignal(str, object)    # (yt_playlist_id, cat_id UUID)
    favorite_toggle_req           = pyqtSignal(str, str, str)  # (type, id, name)
    video_assign_category_req     = pyqtSignal(object, object) # (video_id UUID, cat_id UUID | None)
    local_playlist_to_category_req = pyqtSignal(object, object) # (playlist_id UUID, parent_cat_id UUID | None)
    url_dropped                   = pyqtSignal(str, object)    # (url, cat_id UUID | None)

    def __init__(self, section: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._section = section   # "local" | "youtube" | None (둘 다)
        self._favs: set[tuple[str, str]] = set()   # {("category"|"playlist", id_str)}
        self._ext_url_drag: bool = False   # 외부 URL 드래그 진행 중 여부
        self.setHeaderHidden(True)
        self.setIndentation(20)
        self.setItemDelegate(_TreeRowDelegate(self))
        self.setMouseTracking(True)      # 호버 배경용 State_MouseOver 활성화
        self.setUniformRowHeights(True)
        # DragDrop: 내부 재생목록 폴더 이동 + 외부 영상 드롭 모두 지원
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setAcceptDrops(True)
        # 트리는 접힌 상태로 로드되므로(collapseAll), 하위 카테고리에 브라우저 URL을
        # 끌어다 놓으려면 드래그 중에 부모가 펼쳐져야 한다. Qt 기본값은 -1(비활성).
        self.setAutoExpandDelay(600)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.currentItemChanged.connect(self._on_selection_changed)
        self.itemExpanded.connect(self._on_item_expanded)
        self.itemCollapsed.connect(self._on_item_collapsed)
        # 로딩 스피너 (다중 스피너 — key별 독립 관리)
        self._spinner_items: dict[str, QTreeWidgetItem] = {}   # key → item
        self._spinner_frame_idx: dict[str, int] = {}           # key → frame index
        self._spinner_frames = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧")
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(120)
        self._spinner_timer.timeout.connect(self._tick_spinner)

    def drawBranches(self, painter, rect, index) -> None:  # noqa: N802
        """셰브론과 들여쓰기 가이드를 branch 영역에 직접 그린다.

        델리게이트(아이템 영역)에 그리면 클릭이 확장/축소로 처리되지 않는다 —
        QTreeView는 branch 영역의 클릭만 확장 히트로 본다. 여기서 그리면
        네이티브 히트테스트가 그대로 유지된다.
        """
        tokens = ThemeManager.instance().current()
        painter.save()

        indent = self.indentation()
        depth = 0
        walk = index.parent()
        while walk.isValid():
            depth += 1
            walk = walk.parent()

        # 깊이별 세로 가이드선 — 화살표에 의존하지 않고 계층을 읽히게 한다
        painter.setPen(QPen(QColor(tokens.border_muted), 1))
        for level in range(depth):
            gx = rect.left() + indent * level + indent // 2
            painter.drawLine(gx, rect.top(), gx, rect.bottom())

        # 셰브론 — 자식이 있는 항목만
        item = self.itemFromIndex(index)
        if item is not None and item.childCount() > 0:
            cx = rect.left() + indent * depth + indent // 2
            painter.setPen(QColor(tokens.text_muted))
            painter.setFont(QFont("", 7))
            painter.drawText(
                QRect(cx - 6, rect.top(), 14, rect.height()),
                Qt.AlignmentFlag.AlignCenter,
                "▾" if item.isExpanded() else "▸",
            )

        painter.restore()

    def find_item_by_type(self, itype: str) -> "QTreeWidgetItem | None":
        """트리에서 _ITEM_TYPE_ROLE이 itype인 첫 번째 아이템을 반환한다."""
        it = QTreeWidgetItemIterator(self)
        while it.value():
            item = it.value()
            if item.data(0, _ITEM_TYPE_ROLE) == itype:
                return item
            it += 1
        return None

    def find_item_by_channel_url(self, url: str) -> "QTreeWidgetItem | None":
        """트리에서 _CHANNEL_URL_ROLE이 url인 아이템을 반환한다."""
        it = QTreeWidgetItemIterator(self)
        while it.value():
            item = it.value()
            if item.data(0, _CHANNEL_URL_ROLE) == url:
                return item
            it += 1
        return None

    def find_item_by_cat_id(self, cat_id) -> "QTreeWidgetItem | None":
        """트리에서 _CAT_ID_ROLE이 cat_id인 카테고리 아이템을 반환한다."""
        it = QTreeWidgetItemIterator(self)
        while it.value():
            item = it.value()
            if (
                item.data(0, _ITEM_TYPE_ROLE) == _ITYPE_CATEGORY
                and str(item.data(0, _CAT_ID_ROLE)) == str(cat_id)
            ):
                return item
            it += 1
        return None

    def find_item_by_playlist_id(self, pl_id) -> "QTreeWidgetItem | None":
        """트리에서 _PLAYLIST_ID_ROLE이 pl_id인 재생목록 아이템을 반환한다."""
        it = QTreeWidgetItemIterator(self)
        while it.value():
            item = it.value()
            if (
                item.data(0, _ITEM_TYPE_ROLE) == _ITYPE_PLAYLIST
                and str(item.data(0, _PLAYLIST_ID_ROLE)) == str(pl_id)
            ):
                return item
            it += 1
        return None

    # ── 선택 이벤트 ────────────────────────────────────────────────────────────

    def _on_selection_changed(self, current, _prev) -> None:
        if current is None:
            self.playlist_selected.emit(None)
            return
        itype = current.data(0, _ITEM_TYPE_ROLE)
        if itype == _ITYPE_PLAYLIST:
            self.playlist_selected.emit(current.data(0, _PLAYLIST_ID_ROLE))
        elif itype == _ITYPE_CHANNEL:
            self.channel_selected.emit(current.data(0, _CHANNEL_URL_ROLE) or "")
        elif itype == _ITYPE_FEED_ALL:
            self.feed_all_selected.emit()
        elif itype == _ITYPE_CATEGORY:
            self.category_selected.emit(current.data(0, _CAT_ID_ROLE))
        elif itype == _ITYPE_FOLDER:
            fid = current.data(0, _FOLDER_ID_ROLE)
            if fid:
                self.folder_selected.emit(fid)
            else:
                # 미분류 디렉토리 — 해당 섹션의 미분류 재생목록을 표시
                self.unfiled_selected.emit(current.data(0, _SECTION_ROLE))
        elif itype == _ITYPE_ROOT:
            if current.data(0, _SECTION_ROLE) == "local":
                self.category_selected.emit(None)  # 전체 영상
            elif current.data(0, _SECTION_ROLE) == "youtube":
                self.channels_root_selected.emit()  # 구독 채널 목록 그리드

    def _find_item(self, predicate):
        """술어를 만족하는 첫 노드를 깊이우선으로 찾는다 (없으면 None)."""
        def rec(item: QTreeWidgetItem):
            if predicate(item):
                return item
            for i in range(item.childCount()):
                found = rec(item.child(i))
                if found is not None:
                    return found
            return None
        for i in range(self.topLevelItemCount()):
            found = rec(self.topLevelItem(i))
            if found is not None:
                return found
        return None

    def select_for_snapshot(self, snap: dict) -> bool:
        """스냅샷(kind+id)에 해당하는 노드를 시그널 차단 상태로 선택. 찾으면 True."""
        kind = snap.get("kind", "category")

        def pred(item: QTreeWidgetItem) -> bool:
            it = item.data(0, _ITEM_TYPE_ROLE)
            if kind == "playlist":
                return it == _ITYPE_PLAYLIST and item.data(0, _PLAYLIST_ID_ROLE) == snap.get("playlist_id")
            if kind == "channel":
                return it == _ITYPE_CHANNEL and (item.data(0, _CHANNEL_URL_ROLE) or "") == (snap.get("channel_url") or "")
            if kind == "feed_all":
                return it == _ITYPE_FEED_ALL
            if kind == "channels_root":
                return it == _ITYPE_ROOT and item.data(0, _SECTION_ROLE) == "youtube"
            if kind == "folder":
                fid = snap.get("folder_id")
                if fid is None:   # 미분류
                    return it == _ITYPE_FOLDER and not item.data(0, _FOLDER_ID_ROLE)
                return it == _ITYPE_FOLDER and item.data(0, _FOLDER_ID_ROLE) == fid
            # category
            cat_id = snap.get("cat_id")
            if cat_id is None:
                return it == _ITYPE_ROOT and item.data(0, _SECTION_ROLE) == "local"
            return it == _ITYPE_CATEGORY and item.data(0, _CAT_ID_ROLE) == cat_id

        target = self._find_item(pred)
        if target is None:
            return False
        self.blockSignals(True)
        try:
            parent = target.parent()
            while parent is not None:
                parent.setExpanded(True)
                parent = parent.parent()
            self.setCurrentItem(target)
        finally:
            self.blockSignals(False)
        # setCurrentItem도 스크롤은 하지만 EnsureVisible이라 노드를 뷰포트 *경계까지만*
        # 밀어 넣어 아래쪽 끝에 걸치게 둔다(실측: 340px 뷰포트에서 중심보다 145px 아래).
        # 즐겨찾기 바에서 눌렀을 때 트리의 어디로 갔는지 한눈에 보여야 하므로 가운데 놓는다.
        self.scrollToItem(target, QAbstractItemView.ScrollHint.PositionAtCenter)
        return True

    def _restore_selection(self, pl_id) -> None:
        def _find(item: QTreeWidgetItem) -> bool:
            if item.data(0, _PLAYLIST_ID_ROLE) == pl_id:
                self.setCurrentItem(item)
                return True
            for i in range(item.childCount()):
                if _find(item.child(i)):
                    return True
            return False
        for i in range(self.topLevelItemCount()):
            if _find(self.topLevelItem(i)):
                break

    def _restore_category_selection(self, cat_id) -> None:
        def _find(item: QTreeWidgetItem) -> QTreeWidgetItem | None:
            if item.data(0, _CAT_ID_ROLE) == cat_id:
                return item
            for i in range(item.childCount()):
                found = _find(item.child(i))
                if found is not None:
                    return found
            return None
        target = None
        for i in range(self.topLevelItemCount()):
            target = _find(self.topLevelItem(i))
            if target is not None:
                break
        if target is None:
            return
        # 선택 카테고리와 새로 추가된 하위 카테고리가 보이도록 자신·조상을 펼친다.
        target.setExpanded(True)
        parent = target.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        self.setCurrentItem(target)

    # ── 아이템 확장/축소 화살표 갱신 ────────────────────────────────────────────

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        if item.data(0, _ITEM_TYPE_ROLE) == _ITYPE_CATEGORY:
            text = item.text(0)
            if text.startswith("▸ "):
                item.setText(0, "▾ " + text[2:])

    def _on_item_collapsed(self, item: QTreeWidgetItem) -> None:
        if item.data(0, _ITEM_TYPE_ROLE) == _ITYPE_CATEGORY:
            text = item.text(0)
            if text.startswith("▾ "):
                item.setText(0, "▸ " + text[2:])


class _BreadcrumbBar(QWidget):
    """경로 탐색 바 — 즐겨찾기 바 위. 각 세그먼트는 클릭 가능하고 선택된 태그를 우측에 ✕ 칩으로 표시."""

    segment_clicked = pyqtSignal(object)  # category_id UUID | None
    tag_removed     = pyqtSignal(object)  # tag UUID

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(26)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(8, 0, 8, 0)
        self._row.setSpacing(0)
        self.hide()

    def update_path(
        self,
        segments: list,    # list[tuple[str, click_val]] — click_val=None → 비클릭(마지막)
        tag_pairs: list,   # list[tuple[UUID, str]]
    ) -> None:
        while self._row.count():
            item = self._row.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not segments:
            self.hide()
            return

        tok = _t()
        n = len(segments)
        for i, (name, click_val) in enumerate(segments):
            is_last = (i == n - 1)
            is_clickable = not is_last and click_val is not None
            btn = QPushButton(name)
            btn.setFlat(True)
            if is_last:
                btn.setStyleSheet(
                    f"color:{tok.text_primary};font-size:9pt;font-weight:600;"
                    "background:transparent;border:none;padding:0 3px;"
                )
                btn.setCursor(Qt.CursorShape.ArrowCursor)
            elif is_clickable:
                btn.setStyleSheet(
                    f"color:{tok.accent};font-size:9pt;"
                    "background:transparent;border:none;padding:0 3px;"
                    "text-decoration:underline;"
                )
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                _cv = click_val
                btn.clicked.connect(lambda _, cv=_cv: self.segment_clicked.emit(cv))
            else:
                btn.setStyleSheet(
                    f"color:{tok.text_secondary};font-size:9pt;"
                    "background:transparent;border:none;padding:0 3px;"
                )
                btn.setCursor(Qt.CursorShape.ArrowCursor)
            self._row.addWidget(btn)

            if not is_last:
                sep = QLabel(" › ")
                sep.setStyleSheet(f"color:{tok.text_muted};font-size:9pt;")
                self._row.addWidget(sep)

        if tag_pairs:
            div = QLabel("  :  ")
            div.setStyleSheet(f"color:{tok.text_muted};font-size:9pt;")
            self._row.addWidget(div)
            for tag_id, tname in tag_pairs:
                color = tag_color(tname)
                chip = QPushButton(f"#{tname}  ✕")
                chip.setFlat(True)
                chip.setStyleSheet(
                    f"color:#ffffff;font-size:8pt;"
                    f"background:{color};border-radius:4px;padding:2px 8px;"
                    "border:none;"
                )
                chip.setCursor(Qt.CursorShape.PointingHandCursor)
                chip.setToolTip(f"#{tname} 태그 필터 제거")
                _tid = tag_id
                chip.clicked.connect(lambda _, tid=_tid: self.tag_removed.emit(tid))
                self._row.addWidget(chip)

        self._row.addStretch()
        self.show()


class _PlaylistPanel(QWidget):
    """통합 사이드바 패널 — 로컬 트리 + YouTube 트리 분리."""

    playlist_selected             = pyqtSignal(object)         # UUID | None
    folder_selected               = pyqtSignal(object)         # folder UUID
    unfiled_selected              = pyqtSignal(object)         # source str — 미분류 디렉토리
    category_selected             = pyqtSignal(object)         # category UUID
    channel_selected              = pyqtSignal(str)            # 구독 채널 URL
    feed_all_selected             = pyqtSignal()               # 전체 구독 피드
    channels_root_selected        = pyqtSignal()               # "구독 채널" 노드 — 채널 목록 그리드
    sync_subs_req                 = pyqtSignal()               # "구독 채널" 노드 — YouTube 구독 재동기화
    delete_playlist_req           = pyqtSignal(object)         # playlist UUID
    rename_playlist_req           = pyqtSignal(object)         # playlist UUID
    playlist_move_req             = pyqtSignal(object, object) # (playlist_id, folder_id|None)
    import_yt_req                 = pyqtSignal()
    sync_all_yt_req               = pyqtSignal()               # 전체 YouTube 재생목록 동기화
    folder_create_req             = pyqtSignal(str)            # source
    folder_rename_req             = pyqtSignal(object, str)    # (folder_id, old_name)
    folder_delete_req             = pyqtSignal(object)         # folder UUID
    copy_yt_to_local_req          = pyqtSignal(object)         # yt_playlist_id str
    sync_yt_req                   = pyqtSignal(object)         # yt_playlist_id str
    push_to_yt_req                = pyqtSignal(object, bool)   # (playlist_id, move: bool)
    video_move_to_playlist_req    = pyqtSignal(object, object, object)  # (vid_str, src_pl_str, tgt_pl_id)
    video_reordered               = pyqtSignal(object, list)   # (playlist_id, list[UUID])
    add_category_req              = pyqtSignal(object)         # parent_id (UUID | None)
    rename_category_req           = pyqtSignal(object)         # category UUID
    delete_category_req           = pyqtSignal(object)         # category UUID
    category_reparented           = pyqtSignal(object, object) # (cat_id, new_parent_id | None)
    yt_playlist_to_category_req   = pyqtSignal(str, object)    # (yt_playlist_id, cat_id UUID)
    favorite_toggle_req           = pyqtSignal(str, str, str)  # (type, id, name)
    video_assign_category_req      = pyqtSignal(object, object) # (video_id UUID, cat_id UUID | None)
    local_playlist_to_category_req = pyqtSignal(object, object) # (playlist_id UUID, parent_cat_id UUID | None)
    url_dropped                    = pyqtSignal(str, object)   # (url, cat_id UUID | None)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ── 로컬 섹션(상단 고정) + 접을 수 있는 YouTube 섹션 ──
        # (이전에는 수직 QSplitter로 묶었으나, YouTube 섹션을 기본 접힘으로 두고
        #  삼각형 토글 바로 펼치도록 스플리터를 제거했다.)

        # 로컬 섹션
        local_container = QWidget()
        local_layout = QVBoxLayout(local_container)
        local_layout.setContentsMargins(0, 0, 0, 0)
        local_layout.setSpacing(2)
        local_hdr_row = QHBoxLayout()
        local_hdr_row.setContentsMargins(0, 0, 0, 0)
        self._local_hdr = QPushButton("📁  로컬")
        self._local_hdr.setObjectName("playlist_section_header_local")
        self._local_hdr.setFlat(True)
        self._local_hdr.setCheckable(True)   # QSS :checked 로 활성 표시
        self._local_hdr.setCursor(Qt.CursorShape.PointingHandCursor)
        self._local_hdr.setToolTip("클릭: 카테고리 전체 영상 표시")
        self._local_hdr.clicked.connect(self._on_local_root_clicked)
        local_hdr_row.addWidget(self._local_hdr, stretch=1)
        local_cat_btn = QToolButton()
        local_cat_btn.setText("🏷+")
        local_cat_btn.setToolTip("새 카테고리 만들기")
        local_cat_btn.setFixedHeight(18)
        local_cat_btn.clicked.connect(lambda: self.add_category_req.emit(None))
        local_hdr_row.addWidget(local_cat_btn)
        local_layout.addLayout(local_hdr_row)
        self._local_tree = _PlaylistTree(section="local")
        local_layout.addWidget(self._local_tree, stretch=1)
        layout.addWidget(local_container, stretch=3)

        # ── YouTube 섹션 토글 바 (기존 스플리터 핸들을 대체) ──
        # 삼각형 아이콘 + 빨간 "YouTube" 헤더 + 동기화/폴더 버튼을 한 줄에 둔다.
        # 바 아래(구독 트리)는 기본적으로 접혀(숨겨져) 있고, 삼각형으로 펼친다.
        self._yt_bar = QWidget()
        self._yt_bar.setObjectName("yt_toggle_bar")
        yt_bar_row = QHBoxLayout(self._yt_bar)
        yt_bar_row.setContentsMargins(2, 2, 2, 2)
        yt_bar_row.setSpacing(4)
        self._yt_toggle_btn = QToolButton()
        self._yt_toggle_btn.setObjectName("yt_toggle_arrow")
        self._yt_toggle_btn.setText("▸")   # 접힘 상태 표시(펼치면 ▾)
        self._yt_toggle_btn.setToolTip("YouTube 구독 섹션 펼치기/접기")
        self._yt_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._yt_toggle_btn.setAutoRaise(True)
        self._yt_toggle_btn.setFixedWidth(18)
        self._yt_toggle_btn.clicked.connect(self._toggle_yt_section)
        yt_bar_row.addWidget(self._yt_toggle_btn)
        # YouTube 헤더 — 클릭 시 재생목록 가져오기 다이얼로그 열기
        self._yt_title_btn = QPushButton("YouTube")
        self._yt_title_btn.setObjectName("playlist_section_header_yt_btn")
        self._yt_title_btn.setFlat(True)
        self._yt_title_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._yt_title_btn.setToolTip("클릭 — YouTube 재생목록 가져오기")
        self._yt_title_btn.clicked.connect(self.import_yt_req)
        yt_bar_row.addWidget(self._yt_title_btn, stretch=1)
        # 동기화 버튼 (순환 화살표 ⟳)
        yt_sync_btn = QToolButton()
        yt_sync_btn.setText("⟳")
        yt_sync_btn.setToolTip("YouTube 재생목록 전체 동기화")
        yt_sync_btn.setFixedHeight(18)
        yt_sync_btn.clicked.connect(self.sync_all_yt_req)
        yt_bar_row.addWidget(yt_sync_btn)
        yt_folder_btn = QToolButton()
        yt_folder_btn.setText("📂+")
        yt_folder_btn.setToolTip("새 YouTube 폴더 만들기")
        yt_folder_btn.setFixedHeight(18)
        yt_folder_btn.clicked.connect(lambda: self.folder_create_req.emit("youtube"))
        yt_bar_row.addWidget(yt_folder_btn)
        layout.addWidget(self._yt_bar)

        # YouTube 트리 (바 아래) — 기본 접힘(숨김)
        self._yt_tree = _PlaylistTree(section="youtube")
        self._yt_tree.setVisible(False)
        layout.addWidget(self._yt_tree, stretch=2)

        self._connect_tree(self._local_tree)
        self._connect_tree(self._yt_tree)

    # ── "로컬" 루트 활성 상태 ────────────────────────────────────────────────
    def is_local_root_active(self) -> bool:
        return self._local_hdr.isChecked()

    def set_local_root_active(self, active: bool) -> None:
        """"로컬" 헤더의 활성 표시를 켜고 끈다(QSS :checked 규칙이 걸린다)."""
        if self._local_hdr.isChecked() != active:
            self._local_hdr.setChecked(active)

    def _clear_tree_selection(self) -> None:
        """두 트리의 선택을 해제한다.

        blockSignals로 감싸 currentItemChanged가 선택 핸들러를 재실행하지 않게 한다
        (select_snapshot이 쓰는 것과 같은 패턴).
        """
        for tr in self.trees:
            tr.blockSignals(True)
            tr.clearSelection()
            tr.setCurrentItem(None)
            tr.blockSignals(False)

    def _on_local_root_clicked(self) -> None:
        """"로컬" 헤더 클릭 — 트리 선택을 지우고 헤더를 활성으로 표시한다."""
        self._clear_tree_selection()
        self.set_local_root_active(True)
        self.category_selected.emit(None)

    def _on_tree_current_changed(self, current, _prev) -> None:
        """트리에서 노드를 선택하면 "로컬" 루트 활성 표시를 해제한다."""
        if current is not None:
            self.set_local_root_active(False)

    def _connect_tree(self, tree: _PlaylistTree) -> None:
        tree.currentItemChanged.connect(self._on_tree_current_changed)
        tree.playlist_selected.connect(self.playlist_selected)
        tree.folder_selected.connect(self.folder_selected)
        tree.unfiled_selected.connect(self.unfiled_selected)
        tree.category_selected.connect(self.category_selected)
        tree.channel_selected.connect(self.channel_selected)
        tree.feed_all_selected.connect(self.feed_all_selected)
        tree.channels_root_selected.connect(self.channels_root_selected)
        tree.sync_subs_req.connect(self.sync_subs_req)
        tree.playlist_delete_req.connect(self.delete_playlist_req)
        tree.playlist_rename_req.connect(self.rename_playlist_req)
        tree.playlist_move_req.connect(self.playlist_move_req)
        tree.folder_create_req.connect(self.folder_create_req)
        tree.folder_rename_req.connect(self.folder_rename_req)
        tree.folder_delete_req.connect(self.folder_delete_req)
        tree.copy_yt_to_local_req.connect(self.copy_yt_to_local_req)
        tree.sync_yt_req.connect(self.sync_yt_req)
        tree.import_yt_req.connect(self.import_yt_req)
        tree.push_to_yt_req.connect(self.push_to_yt_req)
        tree.video_move_to_playlist_req.connect(self.video_move_to_playlist_req)
        tree.add_category_req.connect(self.add_category_req)
        tree.rename_category_req.connect(self.rename_category_req)
        tree.delete_category_req.connect(self.delete_category_req)
        tree.category_reparented.connect(self.category_reparented)
        tree.yt_playlist_to_category_req.connect(self.yt_playlist_to_category_req)
        tree.favorite_toggle_req.connect(self.favorite_toggle_req)
        tree.video_assign_category_req.connect(self.video_assign_category_req)
        tree.local_playlist_to_category_req.connect(self.local_playlist_to_category_req)
        tree.url_dropped.connect(self.url_dropped)

    def _toggle_yt_section(self) -> None:
        """YouTube 구독 트리를 펼치거나 접는다(삼각형 아이콘 상태도 갱신)."""
        show = not self._yt_tree.isVisible()
        self._yt_tree.setVisible(show)
        self._yt_toggle_btn.setText("▾" if show else "▸")

    @property
    def trees(self) -> list:
        return [self._local_tree, self._yt_tree]

    def refresh(self, playlists, folders=None, categories=None, subscriptions=None) -> None:
        self._local_tree.load(playlists, folders or [], categories or [])
        self._yt_tree.load(playlists, folders or [], subscriptions=subscriptions or [])

    def select_playlist(self, playlist_id) -> None:
        """두 트리에서 해당 재생목록 항목을 선택한다."""
        self._local_tree._restore_selection(playlist_id)
        self._yt_tree._restore_selection(playlist_id)

    def set_yt_node_loading(self, key: str, item: "QTreeWidgetItem | None", loading: bool) -> None:
        """지정 키 노드에 로딩 스피너를 표시/해제한다."""
        self._yt_tree.set_node_loading(key, item, loading)

    def find_yt_item_by_key(self, key: str) -> "QTreeWidgetItem | None":
        """key(채널 URL·FEED_ALL_KEY·CHANNELS_ROOT_KEY)에 해당하는 YouTube 트리 아이템을 반환한다."""
        if key == FEED_ALL_KEY:
            return self._yt_tree.find_item_by_type(_ITYPE_FEED_ALL)
        if key == CHANNELS_ROOT_KEY:
            return self._yt_tree.find_item_by_type(_ITYPE_ROOT)
        return self._yt_tree.find_item_by_channel_url(key)

    def set_local_node_loading(self, key: str, item: "QTreeWidgetItem | None", loading: bool) -> None:
        """로컬 트리의 지정 키 노드에 로딩 스피너를 표시/해제한다."""
        self._local_tree.set_node_loading(key, item, loading)

    def find_local_item_by_key(self, key: str) -> "QTreeWidgetItem | None":
        """노드 키("cat:{uuid}" | "pl:{uuid}" | "local_root")에 해당하는 로컬 트리 아이템을 반환한다."""
        if key == "local_root":
            it = QTreeWidgetItemIterator(self._local_tree)
            while it.value():
                item = it.value()
                if (
                    item.data(0, _ITEM_TYPE_ROLE) == _ITYPE_ROOT
                    and item.data(0, _SECTION_ROLE) == "local"
                ):
                    return item
                it += 1
            return None
        if key.startswith("cat:"):
            return self._local_tree.find_item_by_cat_id(key[4:])
        if key.startswith("pl:"):
            return self._local_tree.find_item_by_playlist_id(key[3:])
        return None

    def select_snapshot(self, snap: dict) -> None:
        """뒤로/앞으로 복원 시 스냅샷에 해당하는 트리 노드를 강조한다.

        시그널을 차단해 선택 변경이 핸들러를 재실행하지 않도록 한다(이중 실행 방지).
        일치 노드를 찾은 트리만 선택하고 나머지 트리는 선택 해제한다.
        """
        matched = None
        for tr in self.trees:
            if matched is None and tr.select_for_snapshot(snap):
                matched = tr
        for tr in self.trees:
            if tr is not matched:
                tr.blockSignals(True)
                tr.clearSelection()
                tr.blockSignals(False)
        # 어떤 트리 노드와도 일치하지 않으면 "로컬" 루트 화면이다.
        self.set_local_root_active(matched is None)
