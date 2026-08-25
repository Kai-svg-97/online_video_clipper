"""트리 우클릭 컨텍스트 메뉴 — 노드 종류에 따라 항목을 구성한다.

메뉴는 동작을 직접 하지 않고 `_PlaylistTree`의 시그널만 방출한다(실제 처리는
`LibraryPanel` 쪽 믹스인이 맡는다).
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu

from gui.panels.library.constants import (
    _CAT_ID_ROLE,
    _FOLDER_ID_ROLE,
    _ITEM_TYPE_ROLE,
    _ITYPE_CATEGORY,
    _ITYPE_FOLDER,
    _ITYPE_PLAYLIST,
    _ITYPE_ROOT,
    _PLAYLIST_ID_ROLE,
    _SECTION_ROLE,
)


class _TreeContextMenuMixin:
    """노드 우클릭 메뉴 구성."""

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
