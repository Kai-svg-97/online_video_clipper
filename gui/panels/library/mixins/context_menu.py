"""VideoContextMenuMixin — LibraryPanel의 context_menu 영역.

    LibraryPanel에 섞여 들어가는 mixin이라 `self._vm`·`self._view_stack` 같은
    패널 상태를 그대로 쓴다(런타임 클래스는 여전히 하나다). 파일을 나눈 목적은
    "이 동작이 어디 있나"를 파일 이름으로 찾게 하는 것이다.
"""

from __future__ import annotations

import logging
from uuid import UUID

from PyQt6.QtCore import (
    QModelIndex,
    QPoint,
)
from PyQt6.QtGui import (
    QAction,
)
from PyQt6.QtWidgets import (
    QListView,
    QMenu,
    QMessageBox,
)

from application.library.dtos import CategoryDTO, VideoDTO
from gui.dialogs.batch_download_dialog import BatchDownloadDialog


# ── 분할된 부품 (gui/panels/library/*) ──────────────────────────────
# 화면 조립과 흐름 제어만 이 파일에 남기고, 위젯·모델·상수는 패키지로 옮겼다.
from gui.panels.library.constants import (  # noqa: F401
    MATCH_FIELD_LABELS,
    _BADGE_EMPTY_BG,
    _CAT_ID_ROLE,
    _CAT_PARENT_ROLE,
    _CHANNEL_URL_ROLE,
    _COLOR_ROLE,
    _COUNT_ROLE,
    _DETAIL_RECOMMEND_COUNT,
    _FAV_BADGE_W,
    _FOLDER_ID_ROLE,
    _GLYPH_ROLE,
    _ICON_PAD,
    _ICON_TEXT_H,
    _ITEM_TYPE_ROLE,
    _ITYPE_CATEGORY,
    _ITYPE_CHANNEL,
    _ITYPE_FEED_ALL,
    _ITYPE_FOLDER,
    _ITYPE_PLAYLIST,
    _ITYPE_ROOT,
    _MATCH_ROW_H,
    _MIME_CAT_ID,
    _MIME_PLAYLIST_ID,
    _MIME_PLAYLIST_SECTION,
    _MIME_VIDEO_ID,
    _MIME_YT_PLAYLIST_ID,
    _NAME_ROLE,
    _NAV_ALBUM_DETAIL,
    _NO_URL_TARGET,
    _ORIG_TEXT_ROLE,
    _PLAYLIST_ID_ROLE,
    _QWIDGET_MAX_H,
    _RECOMMEND_COUNT,
    _RECOMMEND_DEBOUNCE_MS,
    _RECOMMEND_REVEAL_MS,
    _RECOMMEND_SEED_LIMIT,
    _SEARCH_DEBOUNCE_MS,
    _SECTION_ROLE,
    _STAR_ROLE,
    _TAG_COUNT_W,
    _TAG_PALETTE,
    _THUMB_RENDER_SIZE_KINDS,
    _TH_ICON,
    _TH_LIST,
    _TH_PREV,
    _TW_ICON,
    _TW_LIST,
    _TW_PREV,
    _VIEW_ALBUMS,
    _VIEW_CHANNELS,
    _VIEW_DETAIL,
    _VIEW_FEED,
    _VIEW_FOLDER,
    _VIEW_ICON,
    _VIEW_LIST,
    _YT_BRAND_RED,
    _YT_BRAND_RED_HOVER,
)
from gui.panels.library.formatting import (  # noqa: F401
    _fmt_elapsed,
    _fmt_views,
    _mime_may_contain_url,
    _pub_sort_key,
    _relative_time,
    _t,
    _url_from_mime,
    chip_colors,
    tag_color,
)
from gui.panels.library.thumbnails import (  # noqa: F401
    _ThumbBgLoader,
    _ThumbnailCache,
    _load_thumb,
    _load_thumb_async,
    _thumb_cache,
)
from gui.panels.library.models import (  # noqa: F401
    VideoListModel,
    _VideoListView,
)
from gui.panels.library.delegates import (  # noqa: F401
    _FavChipDelegate,
    _IconDelegate,
    _ListDelegate,
    _TagChipDelegate,
    _TreeRowDelegate,
    _paint_duration_badge,
    _paint_match_badges,
)
from gui.panels.library.tag_widgets import (  # noqa: F401
    _ActiveTagsBar,
    _FavListWidget,
    _FavoritesBar,
    _PopularTagButton,
    _TagListWidget,
)
from gui.panels.library.cards import (  # noqa: F401
    _BaseCard,
    _FolderCard,
    _FolderContentsView,
    _PlaylistCard,
    _PlaylistThumbLabel,
    _UnfiledCard,
)
from gui.panels.library.splitter import (  # noqa: F401
    _CollapseHandle,
    _PreviewSplitter,
)
from gui.panels.library.tree import (  # noqa: F401
    _BreadcrumbBar,
    _PlaylistPanel,
    _PlaylistTree,
)

logger = logging.getLogger(__name__)


class VideoContextMenuMixin:
    """영상 우클릭 메뉴(단일·다중 선택)와 삭제 확인."""

    def _show_video_menu(self, pos: QPoint, view: QListView) -> None:
        indexes = view.selectedIndexes()
        if not indexes:
            return
        global_pos = view.viewport().mapToGlobal(pos)
        if len(indexes) > 1:
            self._build_bulk_menu(indexes, global_pos)
        else:
            dto: VideoDTO = self._model.data(indexes[0], VideoListModel.DtoRole)
            if dto:
                self._build_video_menu(dto, global_pos)

    def _build_bulk_menu(self, indexes: list[QModelIndex], global_pos: QPoint) -> None:
        dtos = [
            self._model.data(idx, VideoListModel.DtoRole)
            for idx in indexes
            if self._model.data(idx, VideoListModel.DtoRole) is not None
        ]
        video_ids = [d.id for d in dtos]
        menu = QMenu(self)
        menu.addSection(f"{len(video_ids)}개 영상 선택됨")

        active_pl_id = self._vm.active_playlist_id
        in_playlist  = active_pl_id is not None and self._playlist_vm is not None

        dl_act = QAction("일괄 다운로드", self)
        dl_act.triggered.connect(lambda: self._on_batch_download(dtos))
        menu.addAction(dl_act)

        tag_act = QAction("태그 추가", self)
        tag_act.triggered.connect(lambda: self._on_bulk_add_tags(video_ids))
        menu.addAction(tag_act)

        menu.addSeparator()

        # 재생목록 모드: "이 재생목록에서 일괄 제거"
        if in_playlist:
            rm_pl_act = QAction(f"이 재생목록에서 제거 ({len(video_ids)}개)", self)
            rm_pl_act.triggered.connect(
                lambda: self._confirm_bulk_remove_from_playlist(video_ids, active_pl_id)
            )
            menu.addAction(rm_pl_act)
            menu.addSeparator()

        # 재생목록으로 복사 (모든 모드에서 사용 가능)
        if self._playlist_vm is not None:
            pl_copy_menu = menu.addMenu("재생목록으로 복사")
            for pl in self._playlist_vm.playlists:
                if in_playlist and pl.id == active_pl_id:
                    continue
                act = QAction(
                    f"{'[YT] ' if pl.source == 'youtube' else ''}{pl.title}  ({pl.item_count})",
                    self,
                )
                pid = pl.id
                act.triggered.connect(lambda _, p=pid: self._on_bulk_copy_to_playlist(video_ids, p))
                pl_copy_menu.addAction(act)
            if not pl_copy_menu.actions():
                pl_copy_menu.setEnabled(False)
            menu.addSeparator()

        cat_menu_label = "카테고리 일괄 복사" if in_playlist else "카테고리 일괄 변경"
        cat_menu = menu.addMenu(cat_menu_label)
        uncat_act = QAction("미분류", self)
        uncat_act.triggered.connect(lambda: self._vm.assign_category_bulk(video_ids, None))
        cat_menu.addAction(uncat_act)
        cat_menu.addSeparator()
        self._add_bulk_cat_actions(cat_menu, self._vm.categories, None, video_ids)

        menu.exec(global_pos)

    def _on_batch_download(self, dtos: list[VideoDTO]) -> None:
        dlg = BatchDownloadDialog(len(dtos), self)
        if dlg.exec() != BatchDownloadDialog.DialogCode.Accepted:
            return
        settings = dlg.build_settings()
        skip = dlg.skip_existing
        skipped_urls: set[str] = set()
        if skip:
            try:
                history = getattr(self, "_download_vm", None)
                if history is not None and hasattr(history, "load_history"):
                    skipped_urls = {j.url for j in history.load_history(200) if j.status == "COMPLETED"}
            except Exception:
                logger.exception("기존 다운로드 이력 조회 실패 (중복 건너뛰기)")
        for dto in dtos:
            if skip and dto.url in skipped_urls:
                continue
            self.download_requested.emit(dto.url, dto.title, settings)

    def _add_bulk_cat_actions(
        self, menu: QMenu, cats: list[CategoryDTO], parent_id, video_ids: list[UUID]
    ) -> None:
        for cat in cats:
            if cat.parent_id != parent_id:
                continue
            children = [c for c in cats if c.parent_id == cat.id]
            if children:
                sub = menu.addMenu(cat.name)
                mv = QAction(f"→ {cat.name}", self)
                cid = cat.id
                mv.triggered.connect(lambda _, c=cid: self._vm.assign_category_bulk(video_ids, c))
                sub.addAction(mv)
                sub.addSeparator()
                self._add_bulk_cat_actions(sub, cats, cat.id, video_ids)
            else:
                act = QAction(cat.name, self)
                cid = cat.id
                act.triggered.connect(lambda _, c=cid: self._vm.assign_category_bulk(video_ids, c))
                menu.addAction(act)

    def _build_video_menu(self, dto: VideoDTO, global_pos: QPoint) -> None:
        menu = QMenu(self)

        detail_act = QAction("상세 정보", self)
        detail_act.triggered.connect(lambda: self._open_detail(dto.id))
        menu.addAction(detail_act)

        menu.addSeparator()

        active_pl_id = self._vm.active_playlist_id
        cat_menu_label = "카테고리로 복사" if active_pl_id is not None else "카테고리 이동"
        cat_menu = menu.addMenu(cat_menu_label)
        uncat_act = QAction("미분류", self)
        uncat_act.triggered.connect(lambda: self._on_video_moved(dto.id, None))
        cat_menu.addAction(uncat_act)
        cat_menu.addSeparator()
        self._add_cat_actions(cat_menu, self._vm.categories, None, dto.id)

        # 재생목록이 활성화되어 있을 때만 재생목록 이전 메뉴 표시
        if active_pl_id is not None and self._playlist_vm is not None:
            menu.addSeparator()

            remove_act = QAction("이 재생목록에서 제거", self)
            remove_act.triggered.connect(
                lambda: self._on_remove_video_from_playlist(dto.id, active_pl_id)
            )
            menu.addAction(remove_act)

            pl_move_menu = menu.addMenu("다른 재생목록으로 이전…")
            for pl in self._playlist_vm.playlists:
                if pl.id == active_pl_id:
                    continue
                act = QAction(
                    f"{'[YT] ' if pl.source == 'youtube' else ''}{pl.title}  ({pl.item_count})",
                    self,
                )
                target_id = pl.id
                act.triggered.connect(
                    lambda _, tid=target_id: self._on_move_video_to_playlist(dto.id, active_pl_id, tid)
                )
                pl_move_menu.addAction(act)
            if not pl_move_menu.actions():
                pl_move_menu.setEnabled(False)

        menu.addSeparator()

        fav_act = QAction("즐겨찾기 해제" if dto.favorite else "즐겨찾기 추가", self)
        fav_act.triggered.connect(lambda: self._toggle_video_favorite(dto))
        menu.addAction(fav_act)

        watch_act = QAction("시청 완료 표시", self)
        watch_act.setEnabled(not dto.watched)
        watch_act.triggered.connect(lambda: self._vm.mark_watched(dto.id))
        menu.addAction(watch_act)

        menu.addSeparator()

        del_act = QAction("삭제", self)
        del_act.triggered.connect(lambda: self._confirm_delete(dto))
        menu.addAction(del_act)

        menu.exec(global_pos)

    def _add_cat_actions(
        self, menu: QMenu, cats: list[CategoryDTO], parent_id, video_id: UUID
    ) -> None:
        for cat in cats:
            if cat.parent_id != parent_id:
                continue
            children = [c for c in cats if c.parent_id == cat.id]
            if children:
                sub = menu.addMenu(cat.name)
                mv = QAction(f"→ {cat.name}", self)
                cid = cat.id
                mv.triggered.connect(lambda _, c=cid: self._on_video_moved(video_id, c))
                sub.addAction(mv)
                sub.addSeparator()
                self._add_cat_actions(sub, cats, cat.id, video_id)
            else:
                act = QAction(cat.name, self)
                cid = cat.id
                act.triggered.connect(lambda _, c=cid: self._on_video_moved(video_id, c))
                menu.addAction(act)

    def _confirm_delete(self, dto: VideoDTO) -> None:
        active_pl_id = self._vm.active_playlist_id
        in_playlist  = active_pl_id is not None and self._playlist_vm is not None

        msg = (
            f"'{dto.title}'\n이 영상을 라이브러리에서 완전히 삭제하시겠습니까?\n"
            + ("(재생목록에서도 제거되며, YouTube 재생목록에도 반영됩니다)" if in_playlist
               else "(라이브러리에서 완전히 삭제됩니다)")
        )
        reply = QMessageBox.question(
            self, "영상 삭제",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # 재생목록 뷰 상태일 때: YouTube API 포함 재생목록 제거 먼저 처리
        if in_playlist:
            self._playlist_vm.remove_video_from_playlist(active_pl_id, dto.id)

        self._vm.delete_video(dto.id)
