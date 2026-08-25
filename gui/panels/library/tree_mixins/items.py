"""트리 로드 + 아이템 팩토리.

팩토리는 `_NAME_ROLE`·`_COUNT_ROLE`·`_GLYPH_ROLE`·`_COLOR_ROLE`·`_STAR_ROLE`을 심고
`delegates._TreeRowDelegate`는 **롤만 읽는다** — 라벨 텍스트에는 스피너가 덧붙거나
카테고리 이름에 괄호가 들어갈 수 있어 텍스트 파싱은 깨진다.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QTreeWidgetItem

from gui.panels.library.constants import (
    _CAT_ID_ROLE,
    _CHANNEL_URL_ROLE,
    _COLOR_ROLE,
    _COUNT_ROLE,
    _FOLDER_ID_ROLE,
    _GLYPH_ROLE,
    _ITEM_TYPE_ROLE,
    _ITYPE_CATEGORY,
    _ITYPE_CHANNEL,
    _ITYPE_FEED_ALL,
    _ITYPE_FOLDER,
    _ITYPE_PLAYLIST,
    _ITYPE_ROOT,
    _NAME_ROLE,
    _PLAYLIST_ID_ROLE,
    _SECTION_ROLE,
    _STAR_ROLE,
)
from gui.panels.library.formatting import tag_color


class _TreeItemsMixin:
    """트리 로드(로컬·YouTube 섹션)와 아이템 생성."""

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
