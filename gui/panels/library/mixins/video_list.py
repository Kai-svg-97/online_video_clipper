"""VideoListMixin — LibraryPanel의 video_list 영역.

    LibraryPanel에 섞여 들어가는 mixin이라 `self._vm`·`self._view_stack` 같은
    패널 상태를 그대로 쓴다(런타임 클래스는 여전히 하나다). 파일을 나눈 목적은
    "이 동작이 어디 있나"를 파일 이름으로 찾게 하는 것이다.
"""

from __future__ import annotations

import logging
from uuid import UUID

from PyQt6.QtCore import (
    QTimer,
    QEvent,
    QModelIndex,
    QPoint,
    Qt,
)
from PyQt6.QtGui import (
    QAction, QPixmap,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QInputDialog,
    QListView,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QTableWidgetItem,
)

from application.library.dtos import VideoDTO

from gui.workers import track_thread

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
from gui.panels.library.skeleton_list import ListSkeleton  # noqa: F401

# 목록 조회가 이보다 오래 걸릴 때만 스켈레톤을 띄운다(빠른 조회에서 깜빡임 방지).
_LOADING_HINT_DELAY_MS = 250

logger = logging.getLogger(__name__)


class VideoListMixin:
    """영상 목록 자체 — 검색·정렬·뷰 전환·태그 패널·썸네일 프리로드·표 뷰."""

    def _on_search_text_changed(self, text: str) -> None:
        """입력 중에는 타이머만 다시 시작하고, 지우기(빈 문자열)는 즉시 반영한다."""
        if not text.strip():
            self._search_timer.stop()
            self._apply_search_text()
            return
        self._search_timer.start()

    def _apply_search_text(self) -> None:
        """디바운스가 끝났거나 Enter를 눌렀을 때 실제 검색을 수행한다."""
        self._search_timer.stop()
        self._vm.set_search_text(self._search_box.text())

    # ── 목록 상태 안내판(조회 중·결과 없음) ─────────────────────────
    # 지금까지 목록은 아무 말도 하지 않았다 — 조회 중에는 이전 목록이 그대로 있다가
    # 툭 바뀌고, 0건이면 빈 화면이라 '없는 건지 못 불러온 건지' 알 수 없었다.

    def _ensure_overlay(self):
        """목록 위 안내판(결과 없음 등)을 필요할 때 만든다(레이아웃에 자리를 차지하지 않는다)."""
        overlay = getattr(self, "_list_overlay", None)
        if overlay is None:
            from gui.panels.library.overlay import ListOverlay  # noqa: PLC0415

            overlay = ListOverlay(self._view_stack)
            self._list_overlay = overlay
        return overlay

    def _ensure_skeleton(self) -> ListSkeleton:
        """목록 위 로딩 스켈레톤을 필요할 때 만든다."""
        skeleton = getattr(self, "_list_skeleton", None)
        if skeleton is None:
            skeleton = ListSkeleton(self._view_stack)
            self._list_skeleton = skeleton
            # 짧은 조회에서 스켈레톤이 깜빡이지 않도록 지연 후에만 띄운다.
            self._loading_timer = QTimer(self)
            self._loading_timer.setSingleShot(True)
            self._loading_timer.setInterval(_LOADING_HINT_DELAY_MS)
            self._loading_timer.timeout.connect(self._show_skeleton_now)
        return skeleton

    def _show_skeleton_now(self) -> None:
        skeleton = self._ensure_skeleton()
        skeleton.set_view(self._view_stack.currentIndex())
        skeleton.set_loading(True)

    def _on_list_loading(self, loading: bool) -> None:
        """목록 조회 시작/종료 — 조회가 길어질 때만 스켈레톤을 띄운다.

        아이콘·리스트·표 뷰(실제 영상 목록)가 아닌 화면(폴더·피드·채널 카드
        그리드)에서는 목록 스켈레톤을 띄우지 않는다 — 그 화면들은 별도 스켈레톤이
        필요하다면 각자 담당한다(Step 4 등).
        """
        self._ensure_skeleton()
        if loading:
            if self._view_stack.currentIndex() in (_VIEW_ICON, _VIEW_LIST, _VIEW_DETAIL):
                self._loading_timer.start()
        else:
            self._loading_timer.stop()
            self._list_skeleton.set_loading(False)
            self._refresh_list_overlay()

    def _on_list_loading_any(self, loading: bool) -> None:
        """`vm.loading_changed` 전용 슬롯 — 노드 키가 없는 검색 조회도 포함한다.

        예전에는 검색 조회(디바운스 300ms + 쿼리 시간)에 어떤 로딩 신호도 없어
        화면이 아무 말도 하지 않았다. `LibraryViewModel.loading_changed`는 노드 키
        유무와 무관하게(깊이 카운터로) 발행되므로, 이 슬롯 하나로 검색·카테고리
        조회를 모두 포함한다. 실제 표시/숨김 로직은 `_on_list_loading`과 같다.
        """
        self._on_list_loading(loading)

    def _refresh_list_overlay(self) -> None:
        """결과가 0건이면 왜 비었는지와 무엇을 하면 되는지 알려 준다."""
        overlay = self._ensure_overlay()
        if self._vm.videos:
            overlay.hide()
            return
        if self._search_box.text().strip():
            # 로컬에 없을 때가 오히려 'YouTube에는 뭐가 있나'를 가장 보고 싶은
            # 순간이다 — 아래 스트립이 그 낱말의 검색 결과로 채워지므로 알려 준다.
            overlay.show_message(
                "검색 결과가 없습니다.\n"
                "아래 '추천 영상' 띠에 이 낱말의 YouTube 검색 결과를 채웁니다."
            )
        elif self._active_tag_ids:
            overlay.show_message("이 태그에 해당하는 영상이 없습니다.")
        else:
            overlay.show_message(
                "이 목록에는 아직 영상이 없습니다.\n"
                "브라우저에서 주소를 끌어다 놓거나, 좌측 트리에 URL을 떨어뜨려 담아 보세요."
            )

    def _on_videos_changed(self) -> None:
        videos = self._vm.videos
        self._model.set_videos(videos)
        self._refresh_list_overlay()
        # 표(상세) 뷰는 행마다 위젯을 만들고 다운로드 여부까지 조회하므로
        # 실제로 보고 있을 때만 채운다. 숨겨져 있으면 표시 시점으로 미룬다.
        if self._view_stack.currentIndex() == _VIEW_DETAIL:
            self._refresh_table()
        else:
            self._table_dirty = True
        self._start_thumb_preload(videos)
        self._schedule_recommend_refresh()

    def _start_thumb_preload(self, videos: list) -> None:
        """현재 뷰 모드에 맞는 크기로 썸네일을 bg에서 프리로드한다."""
        # isVisible()은 위젯이 표시되기 전 False를 반환할 수 있으므로
        # currentWidget() 기준으로 활성 뷰를 판단한다.
        is_icon = self._view_stack.currentWidget() is not self._list_view
        w, h = (_TW_ICON, _TH_ICON) if is_icon else (_TW_LIST, _TH_LIST)
        items = [(dto.thumbnail_path, w, h) for dto in videos if dto.thumbnail_path]
        if not items:
            return
        self._thumb_load_gen += 1
        gen = self._thumb_load_gen
        # 이전 목록의 로더는 취소한다 — 이미 지나간 결과의 썸네일을 계속 디코딩하면
        # 검색어 입력 중 CPU를 붙잡아 키 입력이 밀린다(캐시된 배치는 이미 반영됨).
        for old in self._active_thumb_loaders:
            old.cancel()
        loader = _ThumbBgLoader(items)
        self._active_thumb_loaders.append(loader)
        # `_active_thumb_loaders`는 새 로더 시작 시 이전 로더를 cancel()하기 위한
        # 목록일 뿐 `gui.workers.wait_all()`이 알지 못한다 — 앱 종료
        # 시점에 이 로더가 아직 도는 채로 LibraryPanel이 파괴되면 실행 중인
        # QThread 파괴로 프로세스가 죽는다(gui/workers.py). track_thread로도
        # 등록해 closeEvent의 wait_all(3000)이 이 로더도 기다리게 한다.
        track_thread(loader)

        def _on_loader_done(done=loader) -> None:
            try:
                self._active_thumb_loaders.remove(done)
            except ValueError:
                logger.debug("썸네일 로더가 이미 목록에서 제거됨 — 무시")
            done.deleteLater()

        loader.batch_ready.connect(lambda b, g=gen: self._on_thumb_batch(b, g))
        loader.finished.connect(_on_loader_done)
        loader.start()

    def _on_thumb_batch(self, batch: list, gen: int) -> None:
        """_ThumbBgLoader 배치 완료 처리: 항상 캐시에 저장, 현재 gen만 UI 갱신."""
        paths_updated: set[str] = set()
        for path, w, h, img in batch:
            key = f"{path}@{w}x{h}"
            if _thumb_cache.get(key) is None:  # 중복 방어 (main thread에서만 write)
                _thumb_cache.put(key, QPixmap.fromImage(img))
            paths_updated.add(path)
        if gen == self._thumb_load_gen:
            self._model.notify_thumb_cached(paths_updated)

    def _on_tags_changed(self) -> None:
        self._all_tags = sorted(self._vm.tags, key=lambda t: t.name)
        # Drop active IDs that no longer exist (tag was deleted)
        existing = {t.id for t in self._all_tags}
        self._active_tag_ids &= existing
        self._refresh_tag_display()

    def _refresh_tag_display(self) -> None:
        from config.settings import load_hidden_tag_names  # noqa: PLC0415
        hidden_names = load_hidden_tag_names()
        filter_text = self._tag_filter_input.text().strip().lower()
        self._tag_list.blockSignals(True)
        self._tag_list.clear()
        for tag in self._all_tags:
            if tag.name in hidden_names:
                continue
            if filter_text and filter_text not in tag.name.lower():
                continue
            item = QListWidgetItem(f"#{tag.name}")
            item.setData(Qt.ItemDataRole.UserRole, tag.id)
            item.setData(Qt.ItemDataRole.UserRole + 1, tag.count)
            self._tag_list.addItem(item)
            if tag.id in self._active_tag_ids:
                item.setSelected(True)
        self._tag_list.blockSignals(False)
        self._refresh_active_tags_bar()

    def _on_tag_filter_text_changed(self) -> None:
        self._refresh_tag_display()

    def _refresh_active_tags_bar(self) -> None:
        self._refresh_breadcrumb()
        self._refresh_popular_tags()

    def _set_popular_tags_visible(self, visible: bool) -> None:
        """태그 섹션(인기/전체 태그)은 카테고리 선택 시에만 보인다. 재생목록·폴더·
        피드·채널 뷰에서는 숨겨 재생목록 트리가 그 공간을 차지하도록 한다."""
        if self._tag_section.isVisible() == visible:
            return
        # (스플리터 제거 후로는 태그 섹션 가시성만 토글하면 된다 — 로컬/YouTube
        #  트리는 일반 레이아웃이라 재분배로 인한 위치 변동이 없다.)
        self._tag_section.setVisible(visible)

    def _refresh_popular_tags(self) -> None:
        from config.settings import load_hidden_tag_names  # noqa: PLC0415
        hidden_names = load_hidden_tag_names()
        while self._popular_tags_layout.count():
            item = self._popular_tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        # 현재 트리 노드 스코프 태그(카테고리/재생목록). 비면 라이브러리 전체로 폴백.
        source = self._vm.scoped_tags or self._all_tags
        top_tags = sorted(
            (t for t in source if t.name not in hidden_names),
            key=lambda t: -t.count,
        )[:5]
        for tag in top_tags:
            selected = tag.id in self._active_tag_ids
            color = tag_color(tag.name)
            btn = _PopularTagButton(tag.name, tag.count, color, selected)
            btn.clicked.connect(lambda _, tid=tag.id: self._on_popular_tag_clicked(tid))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, b=btn, tid=tag.id, tname=tag.name: self._show_popular_tag_context_menu(pos, b, tid, tname)
            )
            self._popular_tags_layout.addWidget(btn)

    def _on_popular_tag_clicked(self, tag_id: UUID) -> None:
        if not self._is_restoring:
            self._push_nav_state()
        if tag_id in self._active_tag_ids:
            self._active_tag_ids.discard(tag_id)
        else:
            self._active_tag_ids.add(tag_id)
        self._tag_list.blockSignals(True)
        for i in range(self._tag_list.count()):
            item = self._tag_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == tag_id:
                item.setSelected(tag_id in self._active_tag_ids)
                break
        self._tag_list.blockSignals(False)
        self._vm.set_tag_filter(list(self._active_tag_ids))
        self._refresh_active_tags_bar()
        self._update_delegate_tags()
        if self._active_tag_ids:
            for _t_ in self._playlist_panel.trees:
                _t_.clearSelection()

    def _show_popular_tag_context_menu(self, pos, btn, tag_id: UUID, tag_name: str) -> None:
        from application.library.favorites import is_favorite  # noqa: PLC0415
        tag_id_str = str(tag_id)
        menu = QMenu(self)
        fav_label = "★ 즐겨찾기 제거" if is_favorite(tag_id_str, "tag") else "☆ 즐겨찾기 추가"
        fav_act = QAction(fav_label, self)
        fav_act.triggered.connect(lambda: self._toggle_favorite("tag", tag_id_str, tag_name))
        menu.addAction(fav_act)
        menu.exec(btn.mapToGlobal(pos))

    def _update_delegate_tags(self) -> None:
        names = [t.name for t in self._all_tags if t.id in self._active_tag_ids]
        self._icon_delegate.active_tag_names = names
        self._list_delegate.active_tag_names = names
        self._icon_view.viewport().update()
        self._list_view.viewport().update()

    def _on_tag_delete_requested(self, tag_id: UUID) -> None:
        tag = next((t for t in self._vm.tags if t.id == tag_id), None)
        if tag is None:
            return
        reply = QMessageBox.question(
            self, "태그 삭제",
            f"태그 '#{tag.name}'을(를) 삭제하시겠습니까?\n모든 영상에서 이 태그가 제거됩니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._vm.delete_tag(tag_id)

    def _refresh_table(self) -> None:
        def _fmt(s):
            if s is None:
                return "—"
            m, sec = divmod(s, 60)
            h, m = divmod(m, 60)
            return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"

        videos = self._vm.videos
        self._table_dirty = False
        # 영상/음원 배지는 한 번의 쿼리로 일괄 판정한다.
        # (행마다 get_video_detail 을 부르면 50행 × 수 쿼리 + 파일 stat 이
        #  메인 스레드에서 돌아 검색어 입력이 멈춘다.)
        dl_flags = self._vm.get_downloaded_flags([dto.url for dto in videos])
        self._table.setRowCount(len(videos))
        for row, dto in enumerate(videos):
            t = QTableWidgetItem(dto.title)
            t.setData(Qt.ItemDataRole.UserRole, dto.id)
            self._table.setItem(row, 0, t)
            self._table.setItem(row, 1, QTableWidgetItem(dto.channel_name))
            self._table.setItem(row, 2, QTableWidgetItem(_fmt(dto.duration_sec)))
            self._table.setItem(row, 3, QTableWidgetItem(self._cat_path(dto.category_id)))
            fav = QTableWidgetItem("★" if dto.favorite else "")
            fav.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 4, fav)
            wtc = QTableWidgetItem("✓" if dto.watched else "")
            wtc.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 5, wtc)
            # 등록 일시
            self._table.setItem(row, 6, QTableWidgetItem(dto.created_at or "—"))
            # 영상/음원 다운로드 여부 (일괄 조회 결과에서 조회)
            has_video, has_audio = dl_flags.get(dto.url, (False, False))
            v_item = QTableWidgetItem("✓" if has_video else "—")
            v_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 7, v_item)
            a_item = QTableWidgetItem("✓" if has_audio else "—")
            a_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, 8, a_item)
        self._table.resizeColumnsToContents()

    def _switch_view(self, view_id: int) -> None:
        if view_id in (_VIEW_ICON, _VIEW_LIST, _VIEW_DETAIL):
            # 앨범 보기에서 빠져나올 때 되돌아갈 목록 뷰를 기억한다.
            self._last_list_view = view_id
        self._view_stack.setCurrentIndex(view_id)
        btn = self._view_group.button(view_id)
        if btn is not None and not btn.isChecked():
            btn.setChecked(True)
        # 숨어 있는 동안 목록이 바뀌었으면 이제 채운다(지연 갱신).
        if view_id == _VIEW_DETAIL and self._table_dirty:
            self._refresh_table()

    def _on_view_stack_changed(self, view_id: int) -> None:
        """카드 그리드 뷰(폴더·구독 피드·채널)에서는 추천 스트립을 감춘다.

        그 화면들은 라이브러리 목록이 아니라 추천 씨앗이 어긋나고, 이미 카드
        그리드라 아래에 또 카드 띠를 두면 화면이 산만해진다.
        """
        # 추천 목록이 아직 준비되지 않았으면 목록 뷰에서도 감춘 채로 둔다
        # (준비되면 _reveal_recommend_strip이 올려준다).
        show = view_id not in (_VIEW_FOLDER, _VIEW_FEED, _VIEW_CHANNELS) and self._recommend_ready
        # isVisible()이 아니라 isHidden()으로 비교한다 — isVisible()은 조상이 아직
        # 표시되지 않았을 때도 False라, 첫 전환에서 setVisible(False)가 건너뛰어진다.
        if show == (not self._recommend_strip.isHidden()):
            return
        if not show:
            self._stop_recommend_anim()
        self._recommend_strip.setVisible(show)
        if show:
            self._sync_recommend_sizes(self._recommend_strip.is_expanded, save=False)

    def _on_cat_filter_changed(self, cat_id) -> None:
        self._push_nav_state()          # 전환 직전 화면 보존
        self._leave_detail_if_open()    # 상세 화면이면 목록으로 복귀
        self._current_cat_id = cat_id
        self._current_playlist_id = None
        self._current_folder_id = None
        # 폴더 카드 뷰/피드 뷰/채널 뷰에서 카테고리를 고르면 영상 리스트 뷰로 복귀
        if self._view_stack.currentIndex() in (_VIEW_FOLDER, _VIEW_FEED, _VIEW_CHANNELS):
            self._switch_view(_VIEW_ALBUMS if self._album_mode else self._last_list_view)
        self._active_tag_ids.clear()
        self._tag_list.blockSignals(True)
        self._tag_list.clearSelection()
        self._tag_list.blockSignals(False)
        self._refresh_active_tags_bar()
        self._update_delegate_tags()
        node_key = f"cat:{cat_id}" if cat_id is not None else "local_root"
        self._vm.set_category_filter(cat_id, node_key=node_key)  # also clears tag filter internally
        # 카테고리 스코프 인기 태그 갱신 + 패널 표시
        self._set_popular_tags_visible(True)
        self._vm.refresh_scoped_tags()
        # Update delegates so they know which category is selected (for subcategory label)
        self._icon_delegate.filter_cat_id = cat_id
        self._list_delegate.filter_cat_id = cat_id
        # 순서 편집 버튼 — 카테고리 선택 시에만 표시
        if cat_id is not None:
            self._btn_reorder.show()
            self.path_changed.emit(self._build_category_path(cat_id))
        else:
            self._btn_reorder.setChecked(False)
            self._btn_reorder.hide()
            self._model.set_reorder_mode(False)
            self.path_changed.emit("라이브러리")
        self._refresh_breadcrumb()
        # 음악 카테고리에서만 보기 유형에 '앨범'을 노출한다(카테고리마다 달라진다).
        self._update_view_options()
        if self._is_restoring:
            # 히스토리 복원 중엔 스냅샷이 앨범 여부를 결정한다(_restore_album_mode) —
            # 여기서 모드를 건드리면 되살리려던 앨범 화면을 도로 닫는다.
            if self._album_mode:
                self._load_albums()
        elif self._album_mode:
            # 트리에서 카테고리를 고른 것은 "이 카테고리를 보겠다"는 뜻이다 — 보던
            # 앨범(그리드·상세)에서 빠져나와 그 카테고리의 영상 목록을 보여 준다.
            # 앨범 화면에 머문 채 대상만 바뀌면, 특히 앨범 상세를 보던 중에는 갇힌
            # 느낌이 든다. 앨범으로는 💿 버튼으로 다시 들어간다(직전 화면은 위에서
            # 이미 히스토리에 쌓았으므로 뒤로가기로 앨범에 돌아올 수 있다).
            self._exit_album_mode()

    def _on_view_button_clicked(self, view_id: int) -> None:
        """보기 유형 버튼 — 앨범만 단순 뷰 전환이 아니라 모드 진입/이탈이 필요하다."""
        if view_id == _VIEW_ALBUMS:
            if not self._album_mode:
                self._enter_album_mode()
            return
        if self._album_mode:
            self._exit_album_mode()
        self._switch_view(view_id)

    def _update_view_options(self) -> None:
        """보기 유형 버튼 중 '앨범'을 음악 카테고리에서만 노출한다.

        앨범은 정렬이 아니라 **보기 방식**이다(같은 목록을 자켓 단위로 묶어 본다).
        음악이 아닌 카테고리로 옮기면 버튼을 감추고 앨범 모드도 함께 푼다 — 버튼이
        사라졌는데 화면만 앨범 그리드로 남으면 빠져나갈 방법이 없다.
        """
        want = self.album_view_available()
        self._btn_album.setVisible(want)
        if not want and self._album_mode:
            self._exit_album_mode()

    def _on_reorder_toggled(self, checked: bool) -> None:
        self._model.set_reorder_mode(checked)
        for view in (self._icon_view, self._list_view):
            if checked:
                view.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            else:
                view.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)

    def _on_tag_clicked(self, item: QListWidgetItem) -> None:
        if not self._is_restoring:
            self._push_nav_state()
        tag_id: UUID = item.data(Qt.ItemDataRole.UserRole)
        # With MultiSelection, isSelected() already reflects post-click state
        if item.isSelected():
            self._active_tag_ids.add(tag_id)
        else:
            self._active_tag_ids.discard(tag_id)
        self._vm.set_tag_filter(list(self._active_tag_ids))
        self._refresh_active_tags_bar()
        self._update_delegate_tags()
        self._refresh_breadcrumb()
        # 재생목록 컨텍스트에서는 트리 선택을 유지해 재생목록∩태그 교집합으로 필터링한다.
        # (재생목록이 아닌 뷰에서는 기존대로 트리 선택을 해제한다.)
        if self._active_tag_ids and self._current_playlist_id is None:
            for _t_ in self._playlist_panel.trees:
                _t_.clearSelection()

    def _on_active_tag_removed(self, tag_id: UUID) -> None:
        """Called when ✕ is clicked on a chip in the active tags bar."""
        if not self._is_restoring:
            self._push_nav_state()
        self._active_tag_ids.discard(tag_id)
        self._vm.set_tag_filter(list(self._active_tag_ids))
        self._tag_list.blockSignals(True)
        for i in range(self._tag_list.count()):
            item = self._tag_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == tag_id:
                item.setSelected(False)
                break
        self._tag_list.blockSignals(False)
        self._refresh_active_tags_bar()
        self._update_delegate_tags()
        self._refresh_breadcrumb()

    def _on_tag_filter_requested(self, tag_id: UUID, _tag_name: str) -> None:
        """Called when a tag chip is clicked in the preview pane or detail view."""
        if not self._is_restoring:
            self._push_nav_state()
        self._active_tag_ids = {tag_id}
        self._vm.set_tag_filter([tag_id])
        self._tag_list.blockSignals(True)
        self._tag_list.clearSelection()
        for i in range(self._tag_list.count()):
            item = self._tag_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == tag_id:
                item.setSelected(True)
                break
        self._tag_list.blockSignals(False)
        self._refresh_active_tags_bar()
        self._update_delegate_tags()
        for _t_ in self._playlist_panel.trees:
            _t_.clearSelection()
        if self._nav_stack.currentIndex() == 1:
            self._on_back_from_detail()

    def _on_sort_changed(self, index: int) -> None:
        data = self._sort_combo.itemData(index)
        if not isinstance(data, tuple) or len(data) != 2:
            # 항목 제거 등으로 인덱스가 -1이 되면 데이터가 없다 — 아무것도 하지 않는다.
            return
        sort_by, sort_asc = data
        self._vm.set_sort(sort_by, sort_asc)

    def _on_empty_clicked(self) -> None:
        pass  # 빈 공간 클릭 시 미리보기 패널 상태 유지

    def eventFilter(self, obj, event) -> bool:
        etype = event.type()
        if etype == QEvent.Type.Wheel:
            # Ctrl+휠 뷰 전환은 **목록 위에서만** 받는다 — 이 필터는 앱 전역에도
            # 걸려 있어(마우스 ‹/› 처리) 범위를 좁히지 않으면 트리·설정·플레이어의
            # Ctrl+휠(자막 크기 조절)까지 뷰를 바꿔 버린다.
            if (event.modifiers() & Qt.KeyboardModifier.ControlModifier
                    and self._is_list_surface(obj)):
                delta = event.angleDelta().y()
                self._cycle_view(1 if delta > 0 else -1)
                return True
        elif etype == QEvent.Type.MouseButtonPress:
            if self._handle_history_mouse(obj, event):
                return True
        return super().eventFilter(obj, event)

    def _is_list_surface(self, obj) -> bool:
        """영상 목록(또는 앨범 화면) 자체인지 — Ctrl+휠 뷰 전환의 적용 범위."""
        for widget in (self._icon_view, self._list_view, self._table,
                       self._album_grid, self._album_detail):
            if obj is widget:
                return True
            viewport = getattr(widget, "viewport", None)
            if viewport is not None and obj is viewport():
                return True
        return False

    def _cycle_view(self, direction: int) -> None:
        """Ctrl+휠로 뷰 타입을 순환 전환한다. direction=1: 이전, -1: 다음."""
        views = [_VIEW_ICON, _VIEW_LIST, _VIEW_DETAIL]
        current = self._view_stack.currentIndex()
        # 폴더 뷰(_VIEW_FOLDER)는 순환에서 제외
        idx = views.index(current) if current in views else 0
        new_id = views[(idx - direction) % len(views)]
        self._switch_view(new_id)

    def _on_hidden_tags_changed(self) -> None:
        """설정에서 숨김 태그가 변경되면 태그 표시 목록을 즉시 갱신한다."""
        self._refresh_tag_display()
        self._refresh_popular_tags()

    def _on_list_url_dropped(self, url: str) -> None:
        self._vm.add_video(url, self._current_cat_id)

    def _on_refresh_metadata(self, category_id) -> None:
        if self._refresh_dlg is not None:
            return  # already running
        self._refresh_dlg = QProgressDialog(
            "메타데이터 갱신 중...", None, 0, 100, self
        )
        self._refresh_dlg.setWindowTitle("메타데이터 일괄 갱신")
        self._refresh_dlg.setWindowModality(Qt.WindowModality.WindowModal)
        self._refresh_dlg.setMinimumDuration(0)
        self._refresh_dlg.setValue(0)
        self._refresh_dlg.show()
        self._vm.refresh_category_metadata(category_id)

    def _on_refresh_progress(self, current: int, total: int) -> None:
        if self._refresh_dlg is not None and total > 0:
            self._refresh_dlg.setValue(int(current / total * 100))

    def _on_refresh_finished(self, count: int) -> None:
        if self._refresh_dlg is not None:
            self._refresh_dlg.close()
            self._refresh_dlg = None

    def _on_item_activated(self, index: QModelIndex, view: QListView) -> None:
        """키보드 Enter(또는 더블클릭)로 열기 — 수정키 상태와 무관하게 연다.

        클릭 경로(`_on_item_clicked`)는 Shift 클릭을 다중 선택으로 남겨 둬야 하지만,
        Enter는 '지금 고른 것을 연다'는 뜻뿐이다.
        """
        dto = self._model.data(index, VideoListModel.DtoRole)
        if dto is not None:
            self._open_detail(dto.id)

    def _on_item_clicked(self, index: QModelIndex, view: QListView) -> None:
        """단일 클릭 → 상세화면 진입.
        Shift 클릭은 다중 선택·드래그용으로 유지."""
        mods = QApplication.keyboardModifiers()
        dto: VideoDTO | None = self._model.data(index, VideoListModel.DtoRole)
        if not dto:
            return
        if mods & Qt.KeyboardModifier.ShiftModifier:
            return
        self.video_selected.emit(dto)
        self._open_detail(dto.id)

    def _on_double_click(self, index: QModelIndex) -> None:
        dto: VideoDTO | None = self._model.data(index, VideoListModel.DtoRole)
        if dto:
            self._open_detail(dto.id)

    def _on_table_clicked(self, index: QModelIndex) -> None:
        mods = QApplication.keyboardModifiers()
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            return
        item = self._table.item(index.row(), 0)
        if item:
            vid_id = item.data(Qt.ItemDataRole.UserRole)
            if vid_id:
                self._open_detail(vid_id)

    def _on_table_double_click(self, index: QModelIndex) -> None:
        item = self._table.item(index.row(), 0)
        if item:
            vid_id = item.data(Qt.ItemDataRole.UserRole)
            if vid_id:
                self._open_detail(vid_id)

    def _show_table_menu(self, pos: QPoint) -> None:
        row = self._table.rowAt(pos.y())
        if row < 0 or row >= len(self._vm.videos):
            return
        self._build_video_menu(self._vm.videos[row], self._table.viewport().mapToGlobal(pos))

    def _on_bulk_add_tags(self, video_ids: list[UUID]) -> None:
        tag_str, ok = QInputDialog.getText(
            self, "태그 추가",
            f"{len(video_ids)}개 영상에 추가할 태그를 입력하세요 (쉼표로 구분):",
        )
        if ok and tag_str.strip():
            tag_names = [
                t.strip().lstrip("#")
                for t in tag_str.split(",")
                if t.strip().lstrip("#")
            ]
            if tag_names:
                self._vm.add_tags_bulk(video_ids, tag_names)
