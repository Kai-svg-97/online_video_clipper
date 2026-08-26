"""트리 드래그앤드롭 — 영상·재생목록·폴더 이동 + 브라우저 URL 드롭.

**드롭 판정은 매 이벤트에서 MIME으로 다시 계산한다**(`_is_url_drag`). 예전엔
`dragEnterEvent`가 세운 플래그에만 의존해, 진입 이벤트를 놓치거나 중간에
`dragLeave`가 끼면 드롭이 아무 반응 없이 무시됐다.
"""
from __future__ import annotations

import logging
from uuid import UUID

from PyQt6.QtCore import QByteArray, QMimeData, Qt
from PyQt6.QtGui import QColor, QDrag, QPainter, QPixmap
from PyQt6.QtWidgets import QTreeWidgetItem

from gui.panels.library.constants import (
    _CAT_ID_ROLE,
    _FOLDER_ID_ROLE,
    _ITEM_TYPE_ROLE,
    _ITYPE_CATEGORY,
    _ITYPE_FOLDER,
    _ITYPE_PLAYLIST,
    _ITYPE_ROOT,
    _MIME_PLAYLIST_ID,
    _MIME_PLAYLIST_SECTION,
    _MIME_VIDEO_ID,
    _MIME_YT_PLAYLIST_ID,
    _NO_URL_TARGET,
    _PLAYLIST_ID_ROLE,
    _SECTION_ROLE,
)
from gui.panels.library.formatting import _mime_may_contain_url, _t, _url_from_mime

logger = logging.getLogger(__name__)


class _TreeDragDropMixin:
    """드래그 시작·드롭 대상 판정·드롭 처리와 드롭 위치 오버레이."""

    # ── 드롭 대상 오버레이 (QSS를 우회하는 QFrame 기반 hover 강조) ─────────────

    def _ensure_drop_indicator(self):
        if not hasattr(self, "_drop_ind"):
            from PyQt6.QtWidgets import QFrame
            ind = QFrame(self.viewport())
            ind.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            # 드롭 대상 강조는 accent에서 파생한다. 예전엔 파란색을 박아 두어
            # accent가 파랑이 아닌 테마(forest 녹·warm 금·rose 적·lavender 자)에서
            # 드래그할 때마다 테마와 무관한 파란 테두리가 떴다.
            c = QColor(_t().accent)
            rgb = f"{c.red()},{c.green()},{c.blue()}"
            ind.setStyleSheet(
                f"QFrame {{ border: 2px solid rgba({rgb},220);"
                f" border-radius: 6px; background: rgba({rgb},45); }}"
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
