"""NavigationMixin — LibraryPanel의 navigation 영역.

    LibraryPanel에 섞여 들어가는 mixin이라 `self._vm`·`self._view_stack` 같은
    패널 상태를 그대로 쓴다(런타임 클래스는 여전히 하나다). 파일을 나눈 목적은
    "이 동작이 어디 있나"를 파일 이름으로 찾게 하는 것이다.
"""

from __future__ import annotations

import logging
from uuid import UUID

from PyQt6.QtCore import (
    Qt,
)



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

from gui.anim import fade_switch

logger = logging.getLogger(__name__)


class NavigationMixin:
    """화면 히스토리(뒤로/앞으로)와 브레드크럼.

    화면을 스냅샷(`_capture_screen`)으로 저장했다가 그대로 복원한다 — 카테고리·재생목록·
    피드·앨범·상세까지 한 규칙으로 다룬다.
    """

    def _build_breadcrumb_segments(self, cat_id) -> list:
        """(이름, click_val) 리스트 반환. 루트 '로컬'은 항상 포함.
        cat_id가 있을 때 '로컬' click_val="root" → 클릭 시 카테고리 root(전체) 이동.
        이미 root에 있으면(cat_id=None) 마지막 세그먼트라 비클릭."""
        if cat_id is None:
            # 이미 루트 → "로컬"은 마지막이므로 click_val=None (비클릭)
            return [("로컬", None)]
        segments: list = [("로컬", "root")]
        cats_by_id = {c.id: c for c in self._vm.categories}
        parts: list = []
        current = cat_id
        while current:
            c = cats_by_id.get(current)
            if c is None:
                break
            parts.append((c.name, c.id))
            current = c.parent_id
        parts.reverse()
        return segments + parts

    def _build_playlist_breadcrumb_segments(self, playlist_id) -> list:
        """재생목록 ID로부터 클릭 가능한 경로 세그먼트 리스트를 생성한다.
        click_val: "root" → 전체, ("folder", uuid) → 폴더 뷰, None → 비클릭(마지막)"""
        if not self._playlist_vm:
            return []
        pl = next((p for p in self._playlist_vm.playlists if p.id == playlist_id), None)
        if not pl:
            return []
        if pl.source == "youtube":
            prefix, root_val = "YouTube", "section:youtube"
        else:
            prefix, root_val = "로컬", "root"
        segs = [(prefix, root_val)]
        if pl.folder_id:
            folder = next((f for f in self._playlist_vm.folders if f.id == pl.folder_id), None)
            if folder:
                segs.append((folder.name, ("folder", folder.id)))
        segs.append((pl.title, None))
        return segs

    def _build_folder_breadcrumb_segments(self, folder_id) -> list:
        """폴더 ID로부터 클릭 가능한 경로 세그먼트 리스트를 생성한다."""
        if not self._playlist_vm:
            return []
        folder = next((f for f in self._playlist_vm.folders if f.id == folder_id), None)
        if not folder:
            return []
        if folder.source == "youtube":
            prefix, root_val = "YouTube", "section:youtube"
        else:
            prefix, root_val = "로컬", "root"
        return [(prefix, root_val), (folder.name, None)]

    def _refresh_breadcrumb(self) -> None:
        # 구독 채널/피드 뷰는 _current_playlist_id/_current_folder_id가 None이라
        # 카테고리 분기로 빠지므로(stale 경로), 뷰 기반으로 먼저 처리한다.
        view = self._view_stack.currentIndex()
        if view == _VIEW_CHANNELS:
            self._breadcrumb_bar.update_path(
                [("YouTube", "section:youtube"), ("구독 채널", None)], [])
            return
        if view == _VIEW_FEED:
            if self._feed_show_channel:
                segments = [("YouTube", "section:youtube"), ("전체 구독 피드", None)]
            else:
                name = self._channel_name_for_url(self._current_channel_url) or "채널"
                segments = [("YouTube", "section:youtube"),
                            ("구독 채널", "channels_root"), (name, None)]
            self._breadcrumb_bar.update_path(segments, [])
            return
        if self._current_playlist_id is not None:
            segments = self._build_playlist_breadcrumb_segments(self._current_playlist_id)
            self._breadcrumb_bar.update_path(segments, [])
        elif self._current_folder_id is not None:
            segments = self._build_folder_breadcrumb_segments(self._current_folder_id)
            self._breadcrumb_bar.update_path(segments, [])
        else:
            segments = self._build_breadcrumb_segments(self._current_cat_id)
            tag_pairs = [(t.id, t.name) for t in self._all_tags if t.id in self._active_tag_ids]
            self._breadcrumb_bar.update_path(segments, tag_pairs)

    def _on_breadcrumb_nav(self, val) -> None:
        """브레드크럼 세그먼트 클릭 → 카테고리·폴더·섹션루트 분기 처리."""
        if isinstance(val, tuple) and len(val) == 2 and val[0] == "folder":
            self._on_folder_selected(val[1])
        elif isinstance(val, UUID):
            self._on_cat_filter_changed(val)
        elif val == "channels_root":
            self._on_channels_root_selected()
        elif isinstance(val, str) and val.startswith("section:"):
            # "section:youtube" 또는 "section:local" → 섹션 루트 뷰 (폴더+미분류 카드)
            self._on_section_root_selected(val.split(":", 1)[1])
        else:
            # "root" → 로컬 카테고리 전체 영상 (카테고리 필터 해제)
            self._on_cat_filter_changed(None)

    def navigate_to_category(self, cat_id) -> None:
        """외부(MainWindow 등)에서 특정 카테고리로 이동 요청 시 호출."""
        self._on_cat_filter_changed(cat_id)

    def _on_detail_back_requested(self) -> None:
        """상세 화면 뒤로가기(마우스 뒤로가기·‹ 버튼) — 재생목록 모드면 재생 이력을
        되짚고, 아니면 화면 히스토리 기반으로 직전 화면을 복원한다."""
        if self._playlist_ctx is not None:
            self._playlist_back()
            return
        if self._nav_history:
            self._go_back()
        else:
            self._on_back_from_detail()

    def _on_back_from_detail(self) -> None:
        self._playlist_ctx = None   # 상세를 완전히 벗어남 — 재생목록 모드 해제
        self._detail_widget.stop_player()
        # 목록으로 복귀는 살짝 띄우며 바꾼다(영상 화면으로 갈 때는 즉시 전환).
        fade_switch(self._nav_stack, 0)

    def _capture_screen(self) -> dict:
        """현재 화면을 완전 스냅샷으로 캡처한다(트리 노드 종류 + 뷰 + 태그)."""
        view_idx = self._view_stack.currentIndex()
        if view_idx == _VIEW_CHANNELS:
            kind = "channels_root"
        elif view_idx == _VIEW_FEED:
            kind = "feed_all" if self._feed_show_channel else "channel"
        elif view_idx == _VIEW_FOLDER:
            kind = "folder"
        elif self._current_playlist_id is not None:
            kind = "playlist"
        else:
            kind = "category"
        return {
            "kind": kind,
            "cat_id": self._current_cat_id,
            "playlist_id": self._current_playlist_id,
            "folder_id": self._current_folder_id,
            "channel_url": self._current_channel_url,
            "nav_idx": self._nav_stack.currentIndex(),
            "detail_payload": self._current_detail_payload,
            # 앨범 보기는 같은 카테고리 위의 '다른 화면'이라 kind로는 구분되지 않는다 —
            # 모드와 열려 있던 앨범 키를 따로 싣는다(nav_idx가 앨범 상세를 가리킨다).
            "album_mode": self._album_mode,
            "album_key": self._current_album_key,
            "tag_ids": frozenset(self._active_tag_ids),
        }

    def _push_nav_state(self) -> None:
        """전환 직전 화면을 히스토리 스택에 저장한다(복원 중에는 무시).

        사용자가 새 분기로 이동하는 것이므로 앞으로가기 스택은 무효화한다
        (브라우저 표준 동작)."""
        if self._is_restoring:
            return
        self._nav_history.append(self._capture_screen())
        if len(self._nav_history) > 50:
            self._nav_history.pop(0)
        self._nav_future.clear()

    def _restore_list_screen(self, snap: dict) -> None:
        """스냅샷의 트리 노드(kind)로 실제 이동한다."""
        kind = snap.get("kind", "category")
        if kind == "playlist":
            self._on_playlist_selected_from_tree(snap.get("playlist_id"))
        elif kind == "folder":
            self._on_folder_selected(snap.get("folder_id"))
        elif kind == "feed_all":
            self._on_feed_all_selected()
        elif kind == "channel":
            self._on_channel_selected(snap.get("channel_url") or "")
        elif kind == "channels_root":
            self._on_channels_root_selected()
        else:  # category
            self._on_cat_filter_changed(snap.get("cat_id"))

    def _screen_matches(self, snap: dict) -> bool:
        """상세 화면 아래에 깔린 현재 목록이 스냅샷과 동일한 노드인지(재로딩 회피용)."""
        view_idx = self._view_stack.currentIndex()
        kind = snap.get("kind")
        list_views = (_VIEW_ICON, _VIEW_LIST, _VIEW_DETAIL)
        if kind == "feed_all":
            return view_idx == _VIEW_FEED and self._feed_show_channel
        if kind == "channel":
            return (view_idx == _VIEW_FEED and not self._feed_show_channel
                    and self._current_channel_url == (snap.get("channel_url") or ""))
        if kind == "channels_root":
            return view_idx == _VIEW_CHANNELS
        if kind == "folder":
            return view_idx == _VIEW_FOLDER and self._current_folder_id == snap.get("folder_id")
        if kind == "playlist":
            return view_idx in list_views and self._current_playlist_id == snap.get("playlist_id")
        if snap.get("album_mode"):
            # 앨범 상세 아래에는 앨범 그리드가 깔려 있다(일반 목록 뷰가 아니다).
            list_views = (*list_views, _VIEW_ALBUMS)
        return (view_idx in list_views and self._current_playlist_id is None
                and self._current_cat_id == snap.get("cat_id"))

    def _close_overlay_screens(self) -> None:
        """목록 위에 덮여 있는 화면(영상 상세·앨범 상세)을 닫고 목록 컨테이너로 돌아온다."""
        idx = self._nav_stack.currentIndex()
        if idx == 1:
            self._on_back_from_detail()
        elif idx == _NAV_ALBUM_DETAIL:
            self._close_album_detail()

    def _restore_screen(self, snap: dict) -> None:
        """스냅샷에 따라 직전 화면을 정확히 복원한다."""
        self._is_restoring = True
        try:
            target_detail = (snap.get("nav_idx") == 1
                             and snap.get("detail_payload") is not None)
            target_album = (snap.get("nav_idx") == _NAV_ALBUM_DETAIL
                            and bool(snap.get("album_key")))
            overlay_open = self._nav_stack.currentIndex() in (1, _NAV_ALBUM_DETAIL)

            # 상세(영상·앨범) 아래에 그대로 깔려 있던 직전 목록으로 복귀 —
            # 재로딩 없이 덮개만 걷는다.
            if (not target_detail and not target_album and overlay_open
                    and bool(snap.get("album_mode")) == self._album_mode
                    and self._screen_matches(snap)):
                self._close_overlay_screens()
                self._restore_tags(snap)
                self._playlist_panel.select_snapshot(snap)
                return

            # 그 외엔 목록 화면을 실제로 재구성한다
            self._close_overlay_screens()
            self._restore_list_screen(snap)
            self._restore_tags(snap)
            # 좌측 트리 강조를 복원된 노드에 맞춰 동기화(경로 표현 자연스럽게)
            self._playlist_panel.select_snapshot(snap)
            # 앨범 그리드/일반 목록 중 어느 화면이었는지 되살린다(상세보다 먼저 — 앨범
            # 상세는 그 그리드 위에 열린다)
            self._restore_album_mode(snap)

            # 직전이 상세였다면(연관영상 체인) 올바른 목록 위에 상세를 다시 연다
            if target_detail:
                self._reopen_detail(snap["detail_payload"])
            elif target_album and self._album_mode:
                self._on_album_clicked(snap["album_key"])
        finally:
            self._is_restoring = False

    def _restore_tags(self, snap: dict) -> None:
        """화면 복원 뒤 태그 필터를 덮어쓴다(핸들러가 태그를 비울 수 있으므로)."""
        saved_tags: frozenset = snap.get("tag_ids", frozenset())
        if not saved_tags:
            return
        self._active_tag_ids = set(saved_tags)
        self._vm.set_tag_filter(list(self._active_tag_ids))
        self._tag_list.blockSignals(True)
        self._tag_list.clearSelection()
        for i in range(self._tag_list.count()):
            item = self._tag_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) in self._active_tag_ids:
                item.setSelected(True)
        self._tag_list.blockSignals(False)
        self._refresh_active_tags_bar()
        self._update_delegate_tags()
        self._icon_view.viewport().update()
        self._list_view.viewport().update()

    def _go_back(self) -> None:
        """히스토리에서 직전 화면을 꺼내 복원한다. 현재 화면은 앞으로가기 스택에 보존."""
        if not self._nav_history:
            # 라이브러리 내부 기록이 비었으면 외부(예: 통계에서 진입) 복귀를 위임한다.
            self.back_exhausted.emit()
            return
        self._nav_future.append(self._capture_screen())
        snap = self._nav_history.pop()
        self._restore_screen(snap)

    def _go_forward(self) -> None:
        """앞으로가기 스택에서 다음 화면을 꺼내 복원한다. 현재 화면은 뒤로가기 스택에 보존."""
        if not self._nav_future:
            return
        self._nav_history.append(self._capture_screen())
        snap = self._nav_future.pop()
        self._restore_screen(snap)
