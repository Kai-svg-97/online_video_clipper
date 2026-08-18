"""좌측 내비게이션 트리 — 로컬(카테고리·재생목록) + YouTube(구독) 두 섹션.

드래그앤드롭(영상·재생목록·브라우저 URL), 컨텍스트 메뉴, 로딩 스피너, 즐겨찾기까지
이 트리가 담당한다. 행 그리기는 `delegates._TreeRowDelegate`가, 셰브론·들여쓰기 선은
`_PlaylistTree.drawBranches`가 그린다(아이템 영역에 그리면 펼침 클릭이 죽는다).
"""

from __future__ import annotations

import logging
from uuid import UUID

from PyQt6.QtCore import (
    QByteArray,
    QMimeData,
    QPoint,
    QRect,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction, QColor, QDrag, QFont, QPainter, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QMenu,
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

from gui.panels.library.constants import _CAT_ID_ROLE, _CHANNEL_URL_ROLE, _COLOR_ROLE, _COUNT_ROLE, _FOLDER_ID_ROLE, _GLYPH_ROLE, _ITEM_TYPE_ROLE, _ITYPE_CATEGORY, _ITYPE_CHANNEL, _ITYPE_FEED_ALL, _ITYPE_FOLDER, _ITYPE_PLAYLIST, _ITYPE_ROOT, _MIME_PLAYLIST_ID, _MIME_PLAYLIST_SECTION, _MIME_VIDEO_ID, _MIME_YT_PLAYLIST_ID, _NAME_ROLE, _NO_URL_TARGET, _ORIG_TEXT_ROLE, _PLAYLIST_ID_ROLE, _SECTION_ROLE, _STAR_ROLE
from gui.panels.library.delegates import _TreeRowDelegate
from gui.panels.library.formatting import _mime_may_contain_url, _t, _url_from_mime, tag_color

logger = logging.getLogger(__name__)


class _PlaylistTree(QTreeWidget):
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

    # ── 스피너 ───────────────────────────────────────────────────────────────

    def set_node_loading(self, key: str, item: "QTreeWidgetItem | None", loading: bool) -> None:
        """지정 키 노드의 로딩 스피너를 시작/종료한다."""
        if key in self._spinner_items:
            old_item = self._spinner_items.pop(key)
            self._spinner_frame_idx.pop(key, None)
            orig = old_item.data(0, _ORIG_TEXT_ROLE)
            if orig is not None:
                old_item.setText(0, orig)
                old_item.setData(0, _ORIG_TEXT_ROLE, None)
        if loading and item is not None:
            self._spinner_items[key] = item
            self._spinner_frame_idx[key] = 0
            item.setData(0, _ORIG_TEXT_ROLE, item.text(0))
            self._update_spinner_text(key)
            if not self._spinner_timer.isActive():
                self._spinner_timer.start()
        if not self._spinner_items:
            self._spinner_timer.stop()

    def _clear_all_spinners(self) -> None:
        """load() 전 모든 스피너를 안전하게 정리한다 (clear() 후 해제된 Qt 객체 참조 방지)."""
        for item in self._spinner_items.values():
            orig = item.data(0, _ORIG_TEXT_ROLE)
            if orig is not None:
                item.setText(0, orig)
                item.setData(0, _ORIG_TEXT_ROLE, None)
        self._spinner_items.clear()
        self._spinner_frame_idx.clear()
        self._spinner_timer.stop()

    def _tick_spinner(self) -> None:
        if not self._spinner_items:
            self._spinner_timer.stop()
            return
        for key in list(self._spinner_items):
            self._spinner_frame_idx[key] = (self._spinner_frame_idx.get(key, 0) + 1) % len(self._spinner_frames)
            self._update_spinner_text(key)

    def _update_spinner_text(self, key: str) -> None:
        item = self._spinner_items.get(key)
        if item is None:
            return
        orig = item.data(0, _ORIG_TEXT_ROLE)
        if orig is None:
            return
        frame = self._spinner_frames[self._spinner_frame_idx.get(key, 0)]
        item.setText(0, f"{orig}  {frame}")

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

    # ── 로드 ─────────────────────────────────────────────────────────────────

    def load(self, playlists, folders, categories=None, subscriptions=None) -> None:
        """playlists: list[PlaylistDTO], folders: list[PlaylistFolderDTO], categories: list[CategoryDTO],
        subscriptions: list[SubscriptionDTO] (YouTube 섹션에서만 사용)"""
        self._clear_all_spinners()   # clear() 전 스피너 정리 — 해제된 Qt 객체 참조 방지
        from application.library.favorites import load_favorites  # noqa: PLC0415
        self._favs = {(f.type, f.id) for f in load_favorites()}
        self.blockSignals(True)
        prev_pl = None
        prev_cat = None
        cur = self.currentItem()
        if cur:
            prev_pl = cur.data(0, _PLAYLIST_ID_ROLE)
            prev_cat = cur.data(0, _CAT_ID_ROLE)

        self.clear()
        self._sub_group_item = None

        if self._section == "local":
            self._load_local_section(playlists, folders, categories)
        elif self._section == "youtube":
            self._load_youtube_section(playlists, folders, subscriptions or [])
        else:
            self._load_both_sections(playlists, folders, categories)

        # 모든 트리는 기본적으로 최상위(1레벨) 항목만 보이도록 하위를 접는다.
        # 하위는 사용자가 펼침 화살표를 눌러야 나타난다.
        self.collapseAll()
        self.blockSignals(False)

        if prev_pl:
            self._restore_selection(prev_pl)
        elif prev_cat:
            # 카테고리 선택 유지 — 하위 카테고리 추가 등으로 트리가 재구성돼도
            # 작업 대상 카테고리가 선택된 채 보이도록 복원한다.
            self._restore_category_selection(prev_cat)

    def _load_local_section(self, playlists, folders, categories) -> None:
        if categories:
            child_parent_ids = {c.parent_id for c in categories if c.parent_id is not None}
            cat_by_id: dict = {}
            roots = [c for c in categories if c.parent_id is None]
            for c in roots:
                ci = self._make_category(c.name, c.id, getattr(c, "video_count", 0), has_children=c.id in child_parent_ids)
                self.addTopLevelItem(ci)
                cat_by_id[c.id] = ci
            queue = list(roots)
            while queue:
                parent_cat = queue.pop(0)
                for c in categories:
                    if c.parent_id == parent_cat.id:
                        ci = self._make_category(c.name, c.id, getattr(c, "video_count", 0), has_children=c.id in child_parent_ids)
                        cat_by_id[parent_cat.id].addChild(ci)
                        cat_by_id[c.id] = ci
                        queue.append(c)

        local_folders_by_id: dict = {}
        for f in folders:
            if f.source != "local":
                continue
            fi = self._make_folder(f.name, f.id, "local")
            self.addTopLevelItem(fi)
            local_folders_by_id[f.id] = fi

        local_unfiled = self._make_unfiled("local")
        self.addTopLevelItem(local_unfiled)

        for pl in playlists:
            if pl.source != "local":
                continue
            pi = self._make_playlist(pl.title, pl.item_count, pl.id, pl.yt_playlist_id)
            if pl.folder_id and pl.folder_id in local_folders_by_id:
                local_folders_by_id[pl.folder_id].addChild(pi)
            else:
                local_unfiled.addChild(pi)

    def _load_youtube_section(self, playlists, folders, subscriptions=None) -> None:
        # ── 구독 섹션 (피드 통합) ──
        # "전체 구독 피드" + 구독 채널 폴더 트리. 채널 클릭 시 해당 채널 영상을
        # 메인 영역에 카드로 표시한다.
        feed_all = QTreeWidgetItem(["📡  전체 구독 피드"])
        feed_all.setData(0, _ITEM_TYPE_ROLE, _ITYPE_FEED_ALL)
        feed_all.setData(0, _SECTION_ROLE, "youtube")
        feed_all.setData(0, _NAME_ROLE, "전체 구독 피드")
        feed_all.setData(0, _GLYPH_ROLE, "feed")
        feed_all.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self.addTopLevelItem(feed_all)

        sub_group = QTreeWidgetItem(["📡  구독 채널"])
        sub_group.setData(0, _ITEM_TYPE_ROLE, _ITYPE_ROOT)
        sub_group.setData(0, _SECTION_ROLE, "youtube")
        sub_group.setData(0, _NAME_ROLE, "구독 채널")
        sub_group.setData(0, _GLYPH_ROLE, "group")
        sub_group.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        gf = sub_group.font(0)
        gf.setWeight(QFont.Weight.Bold)
        sub_group.setFont(0, gf)
        self.addTopLevelItem(sub_group)
        self._sub_group_item = sub_group
        # 채널 목록은 이름 오름차순(대소문자 무시)으로 표시한다.
        for sub in sorted(subscriptions or [], key=lambda s: (s.channel_name or "").lower()):
            sub_group.addChild(self._make_channel(sub.channel_name, sub.channel_url))

        yt_folders_by_id: dict = {}
        for f in folders:
            if f.source != "youtube":
                continue
            fi = self._make_folder(f.name, f.id, "youtube")
            self.addTopLevelItem(fi)
            yt_folders_by_id[f.id] = fi

        yt_unfiled = self._make_unfiled("youtube")
        self.addTopLevelItem(yt_unfiled)

        for pl in playlists:
            if pl.source != "youtube":
                continue
            pi = self._make_playlist(pl.title, pl.item_count, pl.id, pl.yt_playlist_id)
            if pl.folder_id and pl.folder_id in yt_folders_by_id:
                yt_folders_by_id[pl.folder_id].addChild(pi)
            else:
                yt_unfiled.addChild(pi)

    def _load_both_sections(self, playlists, folders, categories) -> None:
        # ── 로컬 섹션 ──
        local_root = self._make_root("로컬", "local")
        self.addTopLevelItem(local_root)

        if categories:
            child_parent_ids = {c.parent_id for c in categories if c.parent_id is not None}
            cat_by_id: dict = {}
            roots = [c for c in categories if c.parent_id is None]
            for c in roots:
                ci = self._make_category(c.name, c.id, getattr(c, "video_count", 0), has_children=c.id in child_parent_ids)
                local_root.addChild(ci)
                cat_by_id[c.id] = ci
            queue = list(roots)
            while queue:
                parent_cat = queue.pop(0)
                for c in categories:
                    if c.parent_id == parent_cat.id:
                        ci = self._make_category(c.name, c.id, getattr(c, "video_count", 0), has_children=c.id in child_parent_ids)
                        cat_by_id[parent_cat.id].addChild(ci)
                        cat_by_id[c.id] = ci
                        queue.append(c)

        local_folders_by_id: dict = {}
        for f in folders:
            if f.source != "local":
                continue
            fi = self._make_folder(f.name, f.id, "local")
            local_root.addChild(fi)
            local_folders_by_id[f.id] = fi

        local_unfiled = self._make_unfiled("local")
        local_root.addChild(local_unfiled)

        for pl in playlists:
            if pl.source != "local":
                continue
            pi = self._make_playlist(pl.title, pl.item_count, pl.id, pl.yt_playlist_id)
            if pl.folder_id and pl.folder_id in local_folders_by_id:
                local_folders_by_id[pl.folder_id].addChild(pi)
            else:
                local_unfiled.addChild(pi)

        # ── YouTube 섹션 ──
        yt_root = self._make_root("YouTube", "youtube")
        self.addTopLevelItem(yt_root)

        yt_folders_by_id: dict = {}
        for f in folders:
            if f.source != "youtube":
                continue
            fi = self._make_folder(f.name, f.id, "youtube")
            yt_root.addChild(fi)
            yt_folders_by_id[f.id] = fi

        yt_unfiled = self._make_unfiled("youtube")
        yt_root.addChild(yt_unfiled)

        for pl in playlists:
            if pl.source != "youtube":
                continue
            pi = self._make_playlist(pl.title, pl.item_count, pl.id, pl.yt_playlist_id)
            if pl.folder_id and pl.folder_id in yt_folders_by_id:
                yt_folders_by_id[pl.folder_id].addChild(pi)
            else:
                yt_unfiled.addChild(pi)

    # ── 아이템 팩토리 ──────────────────────────────────────────────────────────

    @staticmethod
    def _no_drop_flags() -> Qt.ItemFlag:
        return (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
        )

    def _make_root(self, label: str, source: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([label])
        item.setData(0, _ITEM_TYPE_ROLE, _ITYPE_ROOT)
        item.setData(0, _SECTION_ROLE, source)
        item.setData(0, _NAME_ROLE, label)
        item.setData(0, _GLYPH_ROLE, "group")
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsDropEnabled)
        f = item.font(0)
        f.setWeight(QFont.Weight.Bold)
        f.setPointSize(9)
        item.setFont(0, f)
        return item

    def _make_folder(self, name: str, folder_id, source: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([f"📂  {name}"])
        item.setData(0, _ITEM_TYPE_ROLE, _ITYPE_FOLDER)
        item.setData(0, _FOLDER_ID_ROLE, folder_id)
        item.setData(0, _SECTION_ROLE, source)
        item.setData(0, _NAME_ROLE, name)
        item.setData(0, _GLYPH_ROLE, "folder")
        item.setToolTip(0, name)
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDropEnabled
        )
        return item

    def _make_unfiled(self, source: str) -> QTreeWidgetItem:
        # 미분류도 디렉토리로 기능하므로 폴더 아이콘을 앞에 표시한다.
        item = QTreeWidgetItem(["📂  미분류"])
        item.setData(0, _ITEM_TYPE_ROLE, _ITYPE_FOLDER)
        item.setData(0, _FOLDER_ID_ROLE, None)   # None = 미분류
        item.setData(0, _SECTION_ROLE, source)
        item.setData(0, _NAME_ROLE, "미분류")
        item.setData(0, _GLYPH_ROLE, "folder")
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsDropEnabled
        )
        f = item.font(0)
        f.setItalic(True)
        item.setFont(0, f)
        return item

    def _make_category(self, name: str, cat_id, video_count: int = 0, has_children: bool = False) -> QTreeWidgetItem:
        # 펼침/접힘 세모는 트리 branch 컬럼(들여쓰기 영역)에 네이티브 인디케이터로 표시한다.
        # 라벨에는 더 이상 세모(▸)를 넣지 않는다. (has_children 인자는 호환을 위해 유지)
        starred = ("category", str(cat_id)) in self._favs
        label = f"🏷  {name}  ({video_count})" if video_count > 0 else f"🏷  {name}"
        item = QTreeWidgetItem([label])
        item.setData(0, _ITEM_TYPE_ROLE, _ITYPE_CATEGORY)
        item.setData(0, _CAT_ID_ROLE, cat_id)
        item.setData(0, _SECTION_ROLE, "local")
        item.setData(0, _NAME_ROLE, name)
        item.setData(0, _COUNT_ROLE, video_count if video_count > 0 else None)
        item.setData(0, _GLYPH_ROLE, "category")
        item.setData(0, _COLOR_ROLE, tag_color(name))
        # 즐겨찾기는 배경 틴트가 아니라 _TreeRowDelegate가 그리는 ★로 표시한다
        # (델리게이트가 배경을 직접 그리므로 setBackground 틴트는 가려진다).
        item.setData(0, _STAR_ROLE, starred)
        item.setToolTip(0, name)
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsDropEnabled
        )
        return item

    def _make_playlist(self, title: str, count: int, pl_id, yt_id) -> QTreeWidgetItem:
        starred = ("playlist", str(pl_id)) in self._favs
        item = QTreeWidgetItem([f"{title}  ({count})"])
        item.setData(0, _ITEM_TYPE_ROLE, _ITYPE_PLAYLIST)
        item.setData(0, _PLAYLIST_ID_ROLE, pl_id)
        item.setData(0, _NAME_ROLE, title)
        item.setData(0, _COUNT_ROLE, count if count > 0 else None)
        item.setData(0, _GLYPH_ROLE, "playlist")
        # 즐겨찾기는 배경 틴트가 아니라 델리게이트가 그리는 ★로 표시한다.
        item.setData(0, _STAR_ROLE, starred)
        if yt_id:
            item.setToolTip(0, f"{title}\nYouTube: {yt_id}")
        else:
            item.setToolTip(0, title)
        item.setFlags(
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsDragEnabled
            | Qt.ItemFlag.ItemIsDropEnabled   # 영상 드롭 수신용
        )
        return item

    def _make_channel(self, name: str, channel_url: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([f"📺  {name}"])
        item.setData(0, _ITEM_TYPE_ROLE, _ITYPE_CHANNEL)
        item.setData(0, _CHANNEL_URL_ROLE, channel_url)
        item.setData(0, _SECTION_ROLE, "youtube")
        item.setData(0, _NAME_ROLE, name)
        item.setData(0, _GLYPH_ROLE, "channel")
        item.setToolTip(0, f"{name}\n{channel_url}")
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        return item

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

    # ── 드래그 앤 드롭 ────────────────────────────────────────────────────────

    # ── 드롭 대상 오버레이 (QSS를 우회하는 QFrame 기반 hover 강조) ─────────────

    def _ensure_drop_indicator(self):
        if not hasattr(self, "_drop_ind"):
            from PyQt6.QtWidgets import QFrame
            ind = QFrame(self.viewport())
            ind.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            ind.setStyleSheet(
                "QFrame { border: 2px solid rgba(100,160,255,220);"
                " border-radius: 3px; background: rgba(100,160,255,45); }"
            )
            ind.hide()
            self._drop_ind = ind
        return self._drop_ind

    def _show_drop_on(self, item) -> None:
        ind = self._ensure_drop_indicator()
        if item is not None:
            r = self.visualItemRect(item)
            ind.setGeometry(r)
            ind.show()
            ind.raise_()
        else:
            ind.hide()

    def _hide_drop_ind(self) -> None:
        if hasattr(self, "_drop_ind"):
            self._drop_ind.hide()

    def startDrag(self, supported_actions) -> None:
        item = self.currentItem()
        if item is None:
            return
        itype = item.data(0, _ITEM_TYPE_ROLE)
        if itype == _ITYPE_CATEGORY:
            # 카테고리는 기존 Qt DnD로 처리 (_MIME_CAT_ID는 _CategoryTree에서 사용)
            super().startDrag(supported_actions)
            return
        if itype != _ITYPE_PLAYLIST:
            return
        pl_id = item.data(0, _PLAYLIST_ID_ROLE)
        section = self._section_of(item)
        mime = QMimeData()
        mime.setData(_MIME_PLAYLIST_ID, QByteArray(str(pl_id).encode()))
        mime.setData(_MIME_PLAYLIST_SECTION, QByteArray(section.encode()))
        tip = item.toolTip(0) or ""
        if tip.startswith("YouTube: "):
            yt_id = tip[len("YouTube: "):]
            mime.setData(_MIME_YT_PLAYLIST_ID, QByteArray(yt_id.encode()))
        drag = QDrag(self)
        drag.setMimeData(mime)

        # 반투명 드래그 픽스맵
        item_rect = self.visualItemRect(item)
        if not item_rect.isEmpty():
            raw = self.viewport().grab(item_rect)
            transp = QPixmap(raw.size())
            transp.fill(Qt.GlobalColor.transparent)
            _p = QPainter(transp)
            _p.setOpacity(0.55)
            _p.drawPixmap(0, 0, raw)
            _p.end()
            drag.setPixmap(transp)
            drag.setHotSpot(item_rect.center() - item_rect.topLeft())

        drag.exec(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction)

    def _is_url_drag(self, mime) -> bool:
        """이 드래그를 URL 드롭으로 다뤄야 하는지 — MIME만 보고 매번 다시 판단한다.

        ``_ext_url_drag`` 플래그 하나에만 의존하면, dragEnter를 놓치거나 중간에
        dragLeave가 끼어 플래그가 꺼진 경우(창 경계·스크롤·오버레이) 드롭이 **조용히**
        무시된다. 내부 드래그(영상·재생목록)와는 MIME으로 확실히 구분되므로
        매 이벤트에서 다시 계산해도 안전하다.
        """
        if mime.hasFormat(_MIME_VIDEO_ID) or mime.hasFormat(_MIME_PLAYLIST_ID):
            return False
        return _mime_may_contain_url(mime)

    def dragEnterEvent(self, event) -> None:
        mime = event.mimeData()
        self._ext_url_drag = False
        if mime.hasFormat(_MIME_VIDEO_ID):
            event.acceptProposedAction()
        elif mime.hasFormat(_MIME_PLAYLIST_ID):
            event.acceptProposedAction()
        elif event.source() is self:
            event.acceptProposedAction()
        elif self._is_url_drag(mime):
            # 외부 URL 드래그(브라우저 주소·추천 스트립 카드) — 내용 검증은 dropEvent에서.
            self._ext_url_drag = True
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        target = self.itemAt(event.position().toPoint())
        mime = event.mimeData()

        # 드롭 대상 hover 강조 (QFrame 오버레이)
        self._show_drop_on(target)

        if self._is_url_drag(mime):
            self._ext_url_drag = True
            if self._url_drop_target(target) is not _NO_URL_TARGET:
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
            else:
                event.ignore()
            return

        if mime.hasFormat(_MIME_VIDEO_ID):
            # 영상 드롭: 재생목록 또는 카테고리 항목 위에서 허용
            if target and target.data(0, _ITEM_TYPE_ROLE) in (_ITYPE_PLAYLIST, _ITYPE_CATEGORY):
                event.acceptProposedAction()
            else:
                event.ignore()

        elif mime.hasFormat(_MIME_PLAYLIST_ID):
            # 재생목록 드래그 (내부 또는 크로스-트리)
            drag_section_bytes = mime.data(_MIME_PLAYLIST_SECTION)
            drag_section = drag_section_bytes.data().decode() if drag_section_bytes else ""
            if target is None:
                event.ignore()
                return
            target_type = target.data(0, _ITEM_TYPE_ROLE)
            target_section = target.data(0, _SECTION_ROLE) or self._section_of(target)

            if drag_section == "youtube" and target_type == _ITYPE_CATEGORY:
                # YouTube 재생목록 → 로컬 카테고리 (영상 임포트)
                event.acceptProposedAction()
            elif drag_section == "youtube" and target_type in (_ITYPE_FOLDER, _ITYPE_ROOT) and target_section == "local":
                # YouTube 재생목록 → 로컬 폴더/루트 (재생목록 복사)
                event.acceptProposedAction()
            elif drag_section == "local" and target_type in (_ITYPE_CATEGORY, _ITYPE_ROOT):
                # 로컬 재생목록 → 카테고리/루트 (영상 복사 + 새 카테고리 생성)
                event.acceptProposedAction()
            elif drag_section == target_section and target_type in (_ITYPE_FOLDER, _ITYPE_ROOT):
                # 같은 섹션 내 폴더 이동
                event.acceptProposedAction()
            else:
                event.ignore()

        elif event.source() is self:
            # 카테고리 reparent (내부 드래그)
            dragged = self.currentItem()
            if dragged is None or target is None:
                event.ignore()
                return
            drag_type = dragged.data(0, _ITEM_TYPE_ROLE)
            target_type = target.data(0, _ITEM_TYPE_ROLE)
            if drag_type == _ITYPE_CATEGORY and target_type in (_ITYPE_CATEGORY, _ITYPE_ROOT):
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._hide_drop_ind()
        self._ext_url_drag = False
        super().dragLeaveEvent(event)

    def _url_drop_target(self, item) -> object:
        """URL 드롭 가능한 대상이면 대상 카테고리 id(루트는 None)를 돌려준다.

        불가한 대상이면 ``_NO_URL_TARGET``을 반환한다 — ``None``은 '미분류로 등록'
        이라는 유효한 값이라 실패와 구분해야 한다.
        """
        if item is None:
            return _NO_URL_TARGET
        item_type = item.data(0, _ITEM_TYPE_ROLE)
        if item_type == _ITYPE_CATEGORY:
            return item.data(0, _CAT_ID_ROLE)
        if item_type == _ITYPE_ROOT:
            section = item.data(0, _SECTION_ROLE) or self._section_of(item)
            if section == "local":
                return None   # 로컬 루트 = 카테고리 없이 등록
        return _NO_URL_TARGET

    def dropEvent(self, event) -> None:
        self._hide_drop_ind()
        mime   = event.mimeData()
        target = self.itemAt(event.position().toPoint())

        # ── 외부 URL 드롭 (브라우저 주소 · 추천 스트립 카드) ───────────────
        if self._is_url_drag(mime):
            self._ext_url_drag = False
            cat_id = self._url_drop_target(target)
            url = _url_from_mime(mime)
            if url and cat_id is not _NO_URL_TARGET:
                self.url_dropped.emit(url, cat_id)
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
            else:
                # 무엇 때문에 무시됐는지 남긴다 — 화면에는 아무 일도 일어나지 않아
                # 사용자가 "드래그가 안 된다"고만 알 수 있다.
                logger.debug(
                    "URL 드롭 무시 — url=%r, target=%s, formats=%s",
                    url, "거부" if cat_id is _NO_URL_TARGET else cat_id,
                    mime.formats(),
                )
                event.ignore()
            return

        # ── 영상 → 재생목록 / 카테고리 드롭 ────────────────────────────────
        if mime.hasFormat(_MIME_VIDEO_ID):
            if target is None:
                event.ignore()
                return
            target_type = target.data(0, _ITEM_TYPE_ROLE)
            raw_vids = mime.data(_MIME_VIDEO_ID).data()

            if target_type == _ITYPE_PLAYLIST:
                tgt_pl_id = target.data(0, _PLAYLIST_ID_ROLE)
                raw_src   = mime.data("application/x-source-playlist-id").data()
                src_pl_str = raw_src.decode() if raw_src else ""
                for vid_str in raw_vids.decode().split(","):
                    if vid_str:
                        self.video_move_to_playlist_req.emit(vid_str, src_pl_str, tgt_pl_id)
                event.accept()
                return

            if target_type == _ITYPE_CATEGORY:
                cat_id = target.data(0, _CAT_ID_ROLE)
                for vid_str in raw_vids.decode().split(","):
                    vid_str = vid_str.strip()
                    if vid_str:
                        try:
                            self.video_assign_category_req.emit(UUID(vid_str), cat_id)
                        except (ValueError, AttributeError):
                            pass
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
                return

            event.ignore()
            return

        # ── 재생목록 드래그 (커스텀 MIME) ─────────────────────────────────
        if mime.hasFormat(_MIME_PLAYLIST_ID):
            if target is None:
                event.ignore()
                return

            drag_section_bytes = mime.data(_MIME_PLAYLIST_SECTION)
            drag_section = drag_section_bytes.data().decode() if drag_section_bytes else ""
            yt_id_bytes = mime.data(_MIME_YT_PLAYLIST_ID)
            yt_playlist_id = yt_id_bytes.data().decode() if yt_id_bytes else ""
            pl_id_bytes = mime.data(_MIME_PLAYLIST_ID)
            pl_id_str = pl_id_bytes.data().decode() if pl_id_bytes else ""

            target_type = target.data(0, _ITEM_TYPE_ROLE)
            target_section = target.data(0, _SECTION_ROLE) or self._section_of(target)

            if drag_section == "youtube" and target_type == _ITYPE_CATEGORY:
                # YouTube 재생목록 → 로컬 카테고리 (영상 임포트)
                cat_id = target.data(0, _CAT_ID_ROLE)
                if yt_playlist_id:
                    self.yt_playlist_to_category_req.emit(yt_playlist_id, cat_id)
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
                return

            if drag_section == "youtube" and target_type in (_ITYPE_FOLDER, _ITYPE_ROOT) and target_section == "local":
                # YouTube 재생목록 → 로컬 폴더/루트 (재생목록 복사)
                if yt_playlist_id:
                    self.copy_yt_to_local_req.emit(yt_playlist_id)
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
                return

            if drag_section == "local" and target_type in (_ITYPE_CATEGORY, _ITYPE_ROOT):
                # 로컬 재생목록 → 카테고리/루트 (새 카테고리 생성 + 영상 복사)
                try:
                    pl_id = UUID(pl_id_str)
                except (ValueError, AttributeError):
                    event.ignore()
                    return
                parent_cat_id = target.data(0, _CAT_ID_ROLE) if target_type == _ITYPE_CATEGORY else None
                self.local_playlist_to_category_req.emit(pl_id, parent_cat_id)
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
                return

            if drag_section == target_section and target_type in (_ITYPE_FOLDER, _ITYPE_ROOT):
                # 같은 섹션 내 폴더/미분류로 이동
                try:
                    pl_id = UUID(pl_id_str)
                except (ValueError, AttributeError):
                    event.ignore()
                    return
                folder_id = target.data(0, _FOLDER_ID_ROLE)
                self.playlist_move_req.emit(pl_id, folder_id)
                event.setDropAction(Qt.DropAction.CopyAction)
                event.accept()
                return

            event.ignore()
            return

        # ── 내부 드래그: 카테고리 reparent ────────────────────────────────
        dragged = self.currentItem()
        if dragged is None or target is None:
            event.ignore()
            return

        drag_type    = dragged.data(0, _ITEM_TYPE_ROLE)
        target_type  = target.data(0, _ITEM_TYPE_ROLE)

        if drag_type == _ITYPE_CATEGORY and target_type in (_ITYPE_CATEGORY, _ITYPE_ROOT):
            cat_id = dragged.data(0, _CAT_ID_ROLE)
            if target_type == _ITYPE_ROOT:
                new_parent_id = None
            else:
                new_parent_id = target.data(0, _CAT_ID_ROLE)
                if new_parent_id == cat_id:
                    event.ignore()
                    return
            self.category_reparented.emit(cat_id, new_parent_id)
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            return

        event.ignore()

    def _section_of(self, item: QTreeWidgetItem) -> str:
        """item 조상에서 섹션(source)을 찾는다. 없으면 트리의 section으로 폴백."""
        s = item.data(0, _SECTION_ROLE)
        if s:
            return s
        p = item.parent()
        while p is not None:
            s = p.data(0, _SECTION_ROLE)
            if s:
                return s
            p = p.parent()
        return self._section or ""

    # ── 컨텍스트 메뉴 ─────────────────────────────────────────────────────────

    def _show_context_menu(self, pos: QPoint) -> None:
        item = self.itemAt(pos)
        menu = QMenu(self)

        if item is None:
            # 빈 공간 우클릭 — 섹션 루트 메뉴 (section-specific 트리 전용)
            sec = self._section
            if sec:
                if sec == "local":
                    act_cat = QAction("새 카테고리 추가", self)
                    act_cat.triggered.connect(lambda: self.add_category_req.emit(None))
                    menu.addAction(act_cat)
                else:
                    act_folder = QAction("새 폴더 추가", self)
                    act_folder.triggered.connect(lambda: self.folder_create_req.emit(sec))
                    menu.addAction(act_folder)
                if sec == "youtube":
                    act_yt = QAction("↓ YouTube 재생목록 가져오기", self)
                    act_yt.triggered.connect(self.import_yt_req)
                    menu.addAction(act_yt)
            if menu.actions():
                menu.exec(self.viewport().mapToGlobal(pos))
            return

        itype   = item.data(0, _ITEM_TYPE_ROLE)
        section = item.data(0, _SECTION_ROLE) or self._section_of(item)

        if itype == _ITYPE_ROOT:
            if section == "youtube":
                # "구독 채널" 노드 — YouTube 구독 목록을 다시 가져와 재동기화
                act_sync = QAction("⟳ 새로고침 (YouTube 구독 재동기화)", self)
                act_sync.triggered.connect(self.sync_subs_req)
                menu.addAction(act_sync)
                menu.addSeparator()
            if section == "local":
                act_cat = QAction("새 카테고리 추가", self)
                act_cat.triggered.connect(lambda: self.add_category_req.emit(None))
                menu.addAction(act_cat)
            else:
                act = QAction("새 폴더 추가", self)
                act.triggered.connect(lambda: self.folder_create_req.emit(section))
                menu.addAction(act)
            if section == "youtube":
                act_yt = QAction("↓ YouTube 재생목록 가져오기", self)
                act_yt.triggered.connect(self.import_yt_req)
                menu.addAction(act_yt)

        elif itype == _ITYPE_CATEGORY:
            cat_id = item.data(0, _CAT_ID_ROLE)
            cat_name = item.text(0).replace("🏷  ", "").split("  (")[0]
            from application.library.favorites import is_favorite  # noqa: PLC0415
            fav_label = "★ 즐겨찾기 제거" if is_favorite(str(cat_id), "category") else "☆ 즐겨찾기 추가"
            fav_act = QAction(fav_label, self)
            fav_act.triggered.connect(lambda: self.favorite_toggle_req.emit("category", str(cat_id), cat_name))
            menu.addAction(fav_act)
            menu.addSeparator()
            add_child_act = QAction("하위 카테고리 추가", self)
            add_child_act.triggered.connect(lambda: self.add_category_req.emit(cat_id))
            menu.addAction(add_child_act)
            rename_act = QAction("이름 변경", self)
            rename_act.triggered.connect(lambda: self.rename_category_req.emit(cat_id))
            menu.addAction(rename_act)
            menu.addSeparator()
            del_act = QAction("삭제", self)
            del_act.triggered.connect(lambda: self.delete_category_req.emit(cat_id))
            menu.addAction(del_act)

        elif itype == _ITYPE_FOLDER:
            folder_id = item.data(0, _FOLDER_ID_ROLE)
            if folder_id is not None:  # 미분류는 이름변경/삭제 불가
                rename_act = QAction("이름 변경", self)
                rename_act.triggered.connect(
                    lambda: self.folder_rename_req.emit(folder_id, item.text(0).replace("📂  ", ""))
                )
                menu.addAction(rename_act)
                del_act = QAction("폴더 삭제 (재생목록은 미분류로 이동)", self)
                del_act.triggered.connect(lambda: self.folder_delete_req.emit(folder_id))
                menu.addAction(del_act)

        elif itype == _ITYPE_PLAYLIST:
            pl_id = item.data(0, _PLAYLIST_ID_ROLE)
            pl_name = item.text(0).strip().rsplit("  (", 1)[0]
            from application.library.favorites import is_favorite  # noqa: PLC0415
            fav_label = "★ 즐겨찾기 제거" if is_favorite(str(pl_id), "playlist") else "☆ 즐겨찾기 추가"
            fav_act = QAction(fav_label, self)
            fav_act.triggered.connect(lambda: self.favorite_toggle_req.emit("playlist", str(pl_id), pl_name))
            menu.addAction(fav_act)
            menu.addSeparator()
            rename_act = QAction("이름 변경", self)
            rename_act.triggered.connect(lambda: self.playlist_rename_req.emit(pl_id))
            menu.addAction(rename_act)

            if section == "local":
                menu.addSeparator()
                copy_to_yt_act = QAction("YouTube로 복사 (YouTube에 새 재생목록 생성)", self)
                copy_to_yt_act.triggered.connect(
                    lambda: self.push_to_yt_req.emit(pl_id, False)
                )
                menu.addAction(copy_to_yt_act)
                move_to_yt_act = QAction("YouTube로 이동 (로컬 항목을 YouTube로 전환)", self)
                move_to_yt_act.triggered.connect(
                    lambda: self.push_to_yt_req.emit(pl_id, True)
                )
                menu.addAction(move_to_yt_act)

            if section == "youtube":
                yt_id = item.toolTip(0).replace("YouTube: ", "") if item.toolTip(0) else ""
                menu.addSeparator()
                copy_act = QAction("로컬로 복사", self)
                copy_act.triggered.connect(lambda: self.copy_yt_to_local_req.emit(yt_id))
                menu.addAction(copy_act)
                sync_act = QAction("YouTube에서 동기화", self)
                sync_act.triggered.connect(lambda: self.sync_yt_req.emit(yt_id))
                menu.addAction(sync_act)

            menu.addSeparator()
            del_act = QAction("삭제", self)
            del_act.triggered.connect(lambda: self.playlist_delete_req.emit(pl_id))
            menu.addAction(del_act)

        if menu.actions():
            menu.exec(self.viewport().mapToGlobal(pos))


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
