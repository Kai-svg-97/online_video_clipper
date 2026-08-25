"""SidebarTreeMixin — LibraryPanel의 sidebar 영역.

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
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from application.library.dtos import VideoDTO
from domain.library.repositories import MUSIC_ROOT_CATEGORY_NAMES


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


class SidebarTreeMixin:
    """좌측 트리(카테고리·재생목록·폴더·즐겨찾기) 조작."""

    def _on_categories_changed(self) -> None:
        self._refresh_unified_tree()

    def _refresh_unified_tree(self) -> None:
        """카테고리 또는 재생목록이 변경될 때 통합 트리를 갱신한다."""
        subs = self._monitoring_vm.subscriptions if self._monitoring_vm is not None else []
        if self._playlist_vm is not None:
            self._playlist_panel.refresh(
                self._playlist_vm.playlists,
                self._playlist_vm.folders,
                self._vm.categories,
                subscriptions=subs,
            )
        else:
            self._playlist_panel.refresh([], [], self._vm.categories, subscriptions=subs)
        self._favorites_bar.refresh(self._get_fav_counts())

    def _apply_sidebar_tree_style(self) -> None:
        tok = _t()
        # 행 배경·선택 표시·셰브론은 모두 _TreeRowDelegate와 _PlaylistTree.drawBranches()가
        # 직접 그린다. 따라서 여기서는 ::item / ::branch 배경·이미지 규칙을 두지 않는다
        # (두면 델리게이트가 그린 위에 QSS가 겹쳐 그려질 위험이 있고, 실제로는 우회되어
        #  죽은 CSS가 된다). 컨테이너 속성만 남긴다.
        branch_style = """
            QTreeWidget {
                background: transparent;
                border: none;
                outline: none;
            }
        """
        hdr_style = f"""
            QLabel#playlist_section_header {{
                font-size: 9pt;
                font-weight: 700;
                color: {tok.text_secondary};
                padding: 4px 6px 2px 4px;
                background: transparent;
            }}
            QPushButton#playlist_section_header_local {{
                font-size: 9pt;
                font-weight: 700;
                color: {tok.text_muted};
                letter-spacing: 0.6px;
                padding: 4px 6px 2px 4px;
                background: transparent;
                border: none;
                text-align: left;
            }}
            QPushButton#playlist_section_header_local:hover {{
                color: {tok.text_primary};
                background: transparent;
            }}
            QPushButton#playlist_section_header_local:checked {{
                color: {tok.accent};
                background: {tok.bg_overlay};
                border-radius: 4px;
            }}
            QPushButton#playlist_section_header_yt_btn {{
                font-size: 9pt;
                font-weight: 700;
                color: {_YT_BRAND_RED};
                letter-spacing: 0.6px;
                padding: 2px 4px;
                background: transparent;
                border: none;
                text-align: left;
            }}
            QPushButton#playlist_section_header_yt_btn:hover {{
                color: {_YT_BRAND_RED_HOVER};
                text-decoration: underline;
            }}
            QWidget#yt_toggle_bar {{
                border-top: 1px solid {tok.border};
                background: {tok.bg_overlay};
            }}
            QToolButton#yt_toggle_arrow {{
                color: {_YT_BRAND_RED};
                font-size: 10pt;
                border: none;
                background: transparent;
            }}
            QToolButton#yt_toggle_arrow:hover {{
                color: {_YT_BRAND_RED_HOVER};
            }}
        """
        local_tree, yt_tree = self._playlist_panel.trees
        local_tree.setStyleSheet(branch_style)   # 로컬: branch indicator 있음
        yt_tree.setStyleSheet(branch_style)      # YouTube: "구독 채널" 등 자식 노드에 펼침 세모 표시
        self._playlist_panel.setStyleSheet(hdr_style)

    def _on_favorite_clicked(self, fav_type: str, fav_id: str) -> None:
        """즐겨찾기 바 항목 클릭 — 해당 카테고리/재생목록/태그를 활성화한다.

        카테고리·재생목록은 좌측 트리에 대응 노드가 있으므로, 트리 노드를 직접
        클릭했을 때와 똑같이 그 노드를 선택 표시하고 보이는 위치까지 스크롤한다
        (`select_snapshot`이 시그널을 차단해 핸들러가 두 번 돌지 않는다).
        태그는 트리 노드가 없고 현재 카테고리 안에서 거는 필터라 트리 선택을
        그대로 둔다.
        """
        try:
            uid = UUID(fav_id)
        except (ValueError, AttributeError):
            return
        if fav_type == "category":
            self._on_cat_filter_changed(uid)
            self._playlist_panel.select_snapshot({"kind": "category", "cat_id": uid})
        elif fav_type == "playlist":
            self._on_playlist_selected_from_tree(uid)
            self._playlist_panel.select_snapshot({"kind": "playlist", "playlist_id": uid})
        elif fav_type == "tag":
            if not self._is_restoring:
                self._push_nav_state()
            self._active_tag_ids = {uid}
            self._vm.set_tag_filter([uid])
            self._refresh_active_tags_bar()
            self._update_delegate_tags()

    def _toggle_favorite(self, fav_type: str, fav_id: str, name: str) -> None:
        from application.library.favorites import FavoriteItem, add_favorite, is_favorite, remove_favorite  # noqa: PLC0415
        if is_favorite(fav_id, fav_type):
            remove_favorite(fav_id, fav_type)
        else:
            add_favorite(FavoriteItem(type=fav_type, id=fav_id, name=name))
        self._favorites_bar.refresh(self._get_fav_counts())
        self._refresh_unified_tree()

    def _get_fav_counts(self) -> dict[str, int]:
        """즐겨찾기 바에 표시할 항목별 영상/아이템 수를 반환한다.

        카테고리는 직속 영상 수와 모든 하위 카테고리 영상 수를 합산한다.
        """
        counts: dict[str, int] = {}

        # 카테고리: 직속 카운트 + 하위 카테고리 재귀 합산
        cat_direct: dict[str, int] = {str(cat.id): cat.video_count for cat in self._vm.categories}
        children_map: dict[str, list[str]] = {}
        for cat in self._vm.categories:
            parent_key = str(cat.parent_id) if cat.parent_id else ""
            children_map.setdefault(parent_key, []).append(str(cat.id))

        def _subtree_count(cat_id_str: str) -> int:
            total = cat_direct.get(cat_id_str, 0)
            for child in children_map.get(cat_id_str, []):
                total += _subtree_count(child)
            return total

        for cat in self._vm.categories:
            counts[f"category:{cat.id}"] = _subtree_count(str(cat.id))

        for t in self._all_tags:
            counts[f"tag:{t.id}"] = t.count
        if self._playlist_vm is not None:
            for pl in self._playlist_vm.playlists:
                counts[f"playlist:{pl.id}"] = pl.item_count
        return counts

    def _on_fav_unfav_requested(self, fav_type: str, fav_id: str, name: str) -> None:
        """즐겨찾기 바의 카운트 배지 클릭 → 해제 확인 후 제거."""
        reply = QMessageBox.question(
            self, "즐겨찾기 해제",
            f"'{name}'을(를) 즐겨찾기에서 제거하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._toggle_favorite(fav_type, fav_id, name)

    def _cat_path(self, cat_id: UUID | None) -> str:
        if cat_id is None:
            return ""
        cats_by_id = {c.id: c for c in self._vm.categories}
        parts: list[str] = []
        current = cats_by_id.get(cat_id)
        while current:
            parts.insert(0, current.name)
            current = cats_by_id.get(current.parent_id) if current.parent_id else None
        return " > ".join(parts)

    def current_category_id(self) -> UUID | None:
        return self._current_cat_id

    def _build_category_path(self, cat_id) -> str:
        """카테고리 ID로부터 전체 경로 문자열을 생성한다. 예: '로컬 > Game > Hardware > PS5'"""
        cats_by_id = {c.id: c for c in self._vm.categories}
        parts: list[str] = []
        current = cat_id
        while current:
            c = cats_by_id.get(current)
            if c is None:
                break
            parts.append(c.name)
            current = c.parent_id
        parts.reverse()
        return "로컬 > " + " > ".join(parts) if parts else "라이브러리"

    def _is_music_category(self, cat_id) -> bool:
        """이 카테고리의 최상위 조상 이름이 음악 계열인지(Music/Song/음악/노래/뮤직).

        판정 기준은 도메인 상수(MUSIC_ROOT_CATEGORY_NAMES)를 그대로 쓴다 — 가사 검색
        범위와 같은 규칙이어야 "가사는 되는데 앨범은 안 뜨는" 어긋남이 없다.
        """
        if cat_id is None:
            return False
        by_id = {c.id: c for c in self._vm.categories}
        node = by_id.get(cat_id)
        depth = 0
        while node is not None and depth < 32:   # 데이터가 순환해도 멈추도록 가드
            parent = by_id.get(node.parent_id) if node.parent_id else None
            if parent is None:
                return (node.name or "").strip().lower() in MUSIC_ROOT_CATEGORY_NAMES
            node = parent
            depth += 1
        return False

    def _on_category_reordered(self, video_ids: list) -> None:
        if self._current_cat_id is not None:
            self._vm.reorder_category_videos(self._current_cat_id, video_ids)
        self._icon_view.viewport().update()
        self._list_view.viewport().update()

    def _open_playlist_payload(self, payload, autoplay: bool) -> None:
        """재생목록 컨텍스트를 유지한 채 payload(로컬/스트리밍) 상세를 연다."""
        from application.library.dtos import FeedVideoDTO  # noqa: PLC0415
        ctx = self._playlist_ctx
        if ctx is None:
            return
        if isinstance(payload, UUID):
            self._open_detail(payload, autoplay=autoplay, related=ctx["items"],
                              header=ctx["header"], push_nav=False)
        elif isinstance(payload, FeedVideoDTO):
            self._open_stream_detail(payload, autoplay=autoplay, related=ctx["items"],
                                     header=ctx["header"], push_nav=False)

    def _playlist_back(self) -> None:
        """재생목록 모드에서 마우스 뒤로가기 — 이전에 재생한 항목으로 되짚는다.

        이력이 더 없으면 재생목록 진입 직전의 '연관 영상' 목록으로 복귀한다."""
        ctx = self._playlist_ctx
        if ctx is None:
            return
        hist = ctx["history"]
        if len(hist) > 1:
            hist.pop()
            prev = hist[-1]
            self._open_playlist_payload(prev, autoplay=self._detail_widget.is_playing())
        else:
            # 이력 소진 → 연관 영상 목록 복귀(상세는 진입 영상 그대로 유지)
            self._detail_widget.set_related(ctx["prev_related"], header="연관 영상")
            self._playlist_ctx = None

    def _on_add_category(self, parent_id) -> None:
        name, ok = QInputDialog.getText(self, "카테고리 추가", "카테고리 이름:")
        if ok and name.strip():
            self._vm.create_category(name.strip(), parent_id=parent_id)

    def _on_rename_category(self, category_id) -> None:
        cats = self._vm.categories
        current_name = next((c.name for c in cats if c.id == category_id), "")
        new_name, ok = QInputDialog.getText(
            self, "카테고리 이름 변경", "새 이름:", text=current_name
        )
        if ok and new_name.strip():
            self._vm.rename_category(category_id, new_name.strip())

    def _on_category_reparented(self, cat_id: UUID, new_parent_id) -> None:
        self._vm.reparent_category(cat_id, new_parent_id)

    def _on_delete_category(self, category_id) -> None:
        cats = self._vm.categories
        name = next((c.name for c in cats if c.id == category_id), "")
        reply = QMessageBox.question(
            self, "카테고리 삭제",
            f"'{name}' 카테고리를 삭제하시겠습니까?\n영상은 '미분류'로 이동됩니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._vm.delete_category(category_id)

    def _on_url_dropped(self, url: str, category_id) -> None:
        self._vm.add_video(url, category_id)

    def _pick_category(self) -> tuple[bool, object]:
        """카테고리 선택 다이얼로그 — (확인 여부, category_id | None)."""
        from gui.panels.feed_panel import _CategoryPickDialog  # noqa: PLC0415
        cats = self._vm.categories
        if not cats:
            # 카테고리가 하나도 없으면 미분류로 담는다(다이얼로그가 빈 채로 뜨지 않게).
            return True, None
        dlg = _CategoryPickDialog(cats, self)
        if not dlg.exec():
            return False, None
        return True, dlg.selected_id()

    def _on_video_moved(self, video_id: UUID, category_id) -> None:
        self._vm.assign_category(video_id, category_id)

    def _toggle_video_favorite(self, dto: VideoDTO) -> None:
        from application.library.commands import UpdateVideoCommand
        try:
            self._vm._update_video.handle(
                UpdateVideoCommand(video_id=dto.id, favorite=not dto.favorite)
            )
            self._vm._refresh_videos()
        except Exception as exc:
            self._vm.error_occurred.emit(str(exc))

    def _on_delete_playlist(self, playlist_id: UUID) -> None:
        if self._playlist_vm is None:
            return
        reply = QMessageBox.question(
            self, "재생목록 삭제",
            "이 재생목록을 삭제하시겠습니까?\n(라이브러리의 영상은 유지됩니다)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._playlist_vm.delete_playlist(playlist_id)
            self._vm.set_playlist_filter(None)

    def _on_rename_playlist(self, playlist_id: UUID) -> None:
        if self._playlist_vm is None:
            return
        pls = self._playlist_vm.playlists
        current = next((p.title for p in pls if p.id == playlist_id), "")
        title, ok = QInputDialog.getText(
            self, "재생목록 이름 변경", "새 이름:", text=current
        )
        if ok and title.strip():
            self._playlist_vm.rename_playlist(playlist_id, title.strip())

    def _on_folder_create(self, source: str) -> None:
        if self._playlist_vm is None:
            return
        name, ok = QInputDialog.getText(self, "새 폴더", "폴더 이름:")
        if ok and name.strip():
            self._playlist_vm.create_folder(name.strip(), source)

    def _on_folder_rename(self, folder_id, old_name: str) -> None:
        if self._playlist_vm is None:
            return
        name, ok = QInputDialog.getText(
            self, "폴더 이름 변경", "새 이름:", text=old_name
        )
        if ok and name.strip():
            self._playlist_vm.rename_folder(folder_id, name.strip())

    def _on_folder_delete(self, folder_id) -> None:
        if self._playlist_vm is None:
            return
        reply = QMessageBox.question(
            self, "폴더 삭제",
            "폴더를 삭제하시겠습니까?\n(폴더 안의 재생목록은 미분류로 이동됩니다)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._playlist_vm.delete_folder(folder_id)

    def _on_yt_playlist_to_category(self, yt_playlist_id: str, cat_id) -> None:
        """YouTube 재생목록을 드래그앤드랍으로 카테고리에 드랍 — 영상 임포트."""
        if not yt_playlist_id:
            return
        cookie_opts = self._playlist_vm.get_ytdlp_cookie_opts() if self._playlist_vm else {}
        self._vm.import_youtube_to_category(yt_playlist_id, cat_id, cookie_opts)

    def _on_local_playlist_to_category(self, playlist_id, parent_cat_id) -> None:
        """로컬 재생목록의 영상 전체를 재생목록 이름의 새 카테고리로 복사한다."""
        if self._playlist_vm is None:
            return
        try:
            playlist_id = UUID(str(playlist_id)) if not isinstance(playlist_id, UUID) else playlist_id
        except (ValueError, AttributeError):
            return

        playlist = next((pl for pl in self._playlist_vm.playlists if pl.id == playlist_id), None)
        if playlist is None:
            return

        video_ids = self._vm.get_playlist_video_ids(playlist_id)
        if not video_ids:
            QMessageBox.information(
                self, "재생목록 복사",
                f"재생목록 '{playlist.title}'에 영상이 없습니다.",
            )
            return

        self._vm.create_category(playlist.title, parent_id=parent_cat_id)

        new_cat = next(
            (c for c in self._vm.categories if c.name == playlist.title and c.parent_id == parent_cat_id),
            None,
        )
        if new_cat is None:
            return

        self._vm.assign_category_bulk(video_ids, new_cat.id)

    def _on_copy_yt_to_local(self, yt_playlist_id: str) -> None:
        """YouTube 재생목록의 영상들을 선택한 카테고리로 가져온다."""
        if not yt_playlist_id:
            return
        categories = self._vm.categories
        if not categories:
            QMessageBox.information(
                self, "카테고리 없음",
                "카테고리가 없습니다.\n카테고리 트리에서 먼저 카테고리를 만들어 주세요.",
            )
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("가져올 카테고리 선택")
        dlg.setMinimumWidth(360)
        dlg.setMinimumHeight(440)
        dlg_layout = QVBoxLayout(dlg)
        dlg_layout.setSpacing(8)

        lbl = QLabel("YouTube 재생목록 영상들을 가져올 카테고리를 선택하세요:")
        lbl.setWordWrap(True)
        dlg_layout.addWidget(lbl)

        # QTreeWidget으로 카테고리 계층 구조를 실제 트리 형태로 표시
        tw = QTreeWidget()
        tw.setHeaderHidden(True)
        tw.setIndentation(18)
        tw.setAnimated(True)
        tw.setRootIsDecorated(True)
        tw.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        tok = _t()
        tw.setStyleSheet(
            f"QTreeWidget {{"
            f"  background:{tok.bg_surface};"
            f"  border:1px solid {tok.border};"
            f"  border-radius:4px;"
            f"  font-size:9pt;"
            f"}}"
            f"QTreeWidget::item {{"
            f"  padding:4px 2px;"
            f"  color:{tok.text_primary};"
            f"}}"
            f"QTreeWidget::item:selected {{"
            f"  background:{tok.accent};"
            f"  color:{tok.text_on_accent};"
            f"}}"
            f"QTreeWidget::item:hover:!selected {{"
            f"  background:{tok.bg_overlay};"
            f"}}"
        )

        # BFS로 메인 카테고리 트리와 동일한 순서로 구축
        tw_items: dict = {}

        def _child_count(cat_id) -> int:
            return sum(1 for c in categories if c.parent_id == cat_id)

        roots = [c for c in categories if c.parent_id is None]
        for c in roots:
            count = _child_count(c.id)
            label = f"🏷  {c.name}  ({count})" if count > 0 else f"🏷  {c.name}"
            ti = QTreeWidgetItem([label])
            ti.setData(0, Qt.ItemDataRole.UserRole, c.id)
            tw.addTopLevelItem(ti)
            tw_items[c.id] = ti

        queue = list(roots)
        while queue:
            parent_cat = queue.pop(0)
            parent_ti = tw_items[parent_cat.id]
            for c in categories:
                if c.parent_id == parent_cat.id:
                    count = _child_count(c.id)
                    label = f"🏷  {c.name}  ({count})" if count > 0 else f"🏷  {c.name}"
                    ti = QTreeWidgetItem([label])
                    ti.setData(0, Qt.ItemDataRole.UserRole, c.id)
                    parent_ti.addChild(ti)
                    tw_items[c.id] = ti
                    queue.append(c)

        tw.expandAll()
        if tw.topLevelItemCount() > 0:
            tw.setCurrentItem(tw.topLevelItem(0))

        dlg_layout.addWidget(tw, 1)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        dlg_layout.addWidget(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        sel = tw.currentItem()
        if sel is None:
            return
        category_id = sel.data(0, Qt.ItemDataRole.UserRole)

        # 로컬에 이미 가져온 재생목록 데이터를 사용 (YouTube 재다운로드 없음)
        if self._playlist_vm is not None:
            local_pl = next(
                (pl for pl in self._playlist_vm.playlists if pl.yt_playlist_id == yt_playlist_id),
                None,
            )
            if local_pl is not None:
                video_ids = self._vm.get_playlist_video_ids(local_pl.id)
                if video_ids:
                    self._vm.assign_category_bulk(video_ids, category_id)
                    QMessageBox.information(
                        self, "복사 완료",
                        f"영상 {len(video_ids)}개를 카테고리로 복사했습니다.",
                    )
                    return
                QMessageBox.information(
                    self, "알림",
                    f"재생목록 '{local_pl.title}'에 영상이 없습니다.",
                )
                return

        # 로컬 캐시 없으면 YouTube에서 가져오기
        cookie_opts = self._playlist_vm.get_ytdlp_cookie_opts() if self._playlist_vm else {}
        self._vm.import_youtube_to_category(yt_playlist_id, category_id, cookie_opts)

    def _on_yt_import_finished(self, count: int) -> None:
        if count > 0:
            QMessageBox.information(
                self, "가져오기 완료",
                f"YouTube 재생목록에서 영상 {count}개를 카테고리로 가져왔습니다.",
            )

    def _on_sync_yt_playlist(self, yt_playlist_id: str) -> None:
        if self._playlist_vm is None or not yt_playlist_id:
            return
        self._playlist_vm.import_youtube_playlist(yt_playlist_id)

    def _on_remove_video_from_playlist(self, video_id, playlist_id) -> None:
        if self._playlist_vm is None:
            return
        self._playlist_vm.remove_video_from_playlist(playlist_id, video_id)
        self._vm.set_playlist_filter(playlist_id)  # 목록 갱신

    def _on_move_video_to_playlist(self, video_id, src_pl_id, tgt_pl_id) -> None:
        if self._playlist_vm is None:
            return
        self._playlist_vm.move_video_to_playlist(video_id, src_pl_id, tgt_pl_id)
        self._vm.set_playlist_filter(src_pl_id)  # 현재 재생목록 뷰 갱신

    def _on_video_move_to_playlist_from_dnd(self, vid_id_str: str, src_pl_str: str, tgt_pl_id) -> None:
        """DnD로 영상을 다른 재생목록으로 이전."""
        if self._playlist_vm is None:
            return
        from uuid import UUID  # noqa: PLC0415
        try:
            video_id = UUID(vid_id_str)
            src_pl_id = UUID(src_pl_str) if src_pl_str else None
        except (ValueError, AttributeError):
            return
        self._playlist_vm.move_video_to_playlist(video_id, src_pl_id, tgt_pl_id)
        if src_pl_id is not None:
            self._vm.set_playlist_filter(src_pl_id)

    def _on_local_loading_key_changed(self, key: str, loading: bool) -> None:
        """로컬 트리 노드(카테고리/재생목록) 스피너 즉시 전환.

        목록 스켈레톤(_on_list_loading_any)은 `vm.loading_changed`(깊이 카운터)에
        직접 연결돼 있어 여기서 부르지 않는다 — 노드별 신호는 이 스피너 전용이다.
        겹치는 조회에서 먼저 끝난 노드가 이 신호로 스켈레톤을 꺼버리면, 아직 진행
        중인 다른 조회의 스켈레톤까지 사라지는 문제가 있었다.
        """
        item = self._playlist_panel.find_local_item_by_key(key)
        self._playlist_panel.set_local_node_loading(key, item, loading)

    def _on_feed_card_to_category(self, url: str) -> None:
        self._vm.add_video(url)

    def _on_feed_card_to_playlist(self, url: str) -> None:
        # 재생목록 선택 UI가 없으므로 우선 라이브러리에 등록한다.
        self._vm.add_video(url)

    def _on_folder_selected(self, folder_id) -> None:
        """폴더 클릭 — 폴더 내 재생목록을 카드 그리드로 표시한다.
        folder_id=None이면 '미분류' 디렉터리 뷰."""
        if self._playlist_vm is None:
            return
        self._push_nav_state()
        self._leave_detail_if_open()
        folder_pls = [pl for pl in self._playlist_vm.playlists if pl.folder_id == folder_id]
        self._folder_view.load(folder_pls, get_first_item=self._vm.get_playlist_first_item)
        self._view_stack.setCurrentIndex(_VIEW_FOLDER)
        self._vm.set_playlist_filter(None)
        self._current_folder_id = folder_id
        self._current_playlist_id = None
        self._set_popular_tags_visible(False)   # 폴더(재생목록 묶음) 뷰에서도 숨김
        self._refresh_breadcrumb()

    def _on_unfiled_selected(self, source: str) -> None:
        """미분류 클릭 — 해당 섹션의 폴더 없는 재생목록을 카드 그리드로 표시한다."""
        self._on_folder_selected(None)

    def _on_section_root_selected(self, source: str) -> None:
        """섹션 루트('로컬'/'YouTube') 클릭 — 해당 섹션의 폴더 + 미분류 카드를 표시한다.
        (경로 바에서 'YouTube' 세그먼트 클릭 시 호출)"""
        if self._playlist_vm is None:
            return
        folders = [f for f in self._playlist_vm.folders if f.source == source]
        unfiled_pls = [pl for pl in self._playlist_vm.playlists
                       if pl.source == source and pl.folder_id is None]
        self._folder_view.load(
            playlists=[],
            get_first_item=self._vm.get_playlist_first_item,
            folders=folders,
            show_unfiled=True,
            unfiled_count=len(unfiled_pls),
        )
        self._view_stack.setCurrentIndex(_VIEW_FOLDER)
        self._vm.set_playlist_filter(None)
        # 섹션 루트 — 폴더도 재생목록도 아닌 상태
        self._current_folder_id = None
        self._current_playlist_id = None
        self._set_popular_tags_visible(False)
        # 경로 바: "YouTube" 또는 "로컬" 단독 (클릭 안 되는 마지막 세그먼트)
        label = "YouTube" if source == "youtube" else "로컬"
        self._breadcrumb_bar.update_path([(label, None)], [])
        self._breadcrumb_bar.show()

    def _on_folder_playlist_selected(self, playlist_id) -> None:
        """폴더 뷰에서 카드 클릭 — 해당 재생목록을 선택하고 정상 뷰로 돌아간다."""
        self._playlist_panel.select_playlist(playlist_id)
        self._vm.set_playlist_filter(playlist_id)
        self._icon_view.set_playlist_context(playlist_id)
        self._list_view.set_playlist_context(playlist_id)
        self._switch_view(_VIEW_ALBUMS if self._album_mode else self._last_list_view)   # 이전 뷰 모드로 복귀
        self._current_playlist_id = playlist_id
        self._current_folder_id = None
        self._refresh_breadcrumb()

    def _confirm_bulk_remove_from_playlist(self, video_ids: list, playlist_id) -> None:
        """재생목록에서 다중 영상 일괄 제거 확인 다이얼로그."""
        if self._playlist_vm is None:
            return
        reply = QMessageBox.question(
            self, "일괄 제거",
            f"{len(video_ids)}개 영상을 재생목록에서 제거하시겠습니까?\n"
            "(YouTube 재생목록이면 YouTube에도 반영됩니다)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for vid_id in video_ids:
            try:
                self._playlist_vm.remove_video_from_playlist(playlist_id, vid_id)
            except Exception:
                logger.exception("재생목록에서 영상 일괄 제거 실패")
        self._vm.set_playlist_filter(playlist_id)

    def _on_bulk_copy_to_playlist(self, video_ids: list, playlist_id) -> None:
        """다중 영상을 재생목록으로 복사한다."""
        if self._playlist_vm is None:
            return
        count = 0
        for vid_id in video_ids:
            try:
                self._playlist_vm.add_video_to_playlist(playlist_id, vid_id)
                count += 1
            except Exception:
                logger.exception("재생목록으로 영상 일괄 복사 실패")
        if count > 0:
            QMessageBox.information(self, "복사 완료", f"{count}개 영상을 재생목록에 복사했습니다.")

    def _on_import_yt_playlist(self) -> None:
        if self._playlist_vm is None:
            return
        # YouTube 계정 재생목록 목록 먼저 가져오기
        self._playlist_vm.yt_playlists_ready.connect(self._on_yt_playlists_ready, Qt.ConnectionType.SingleShotConnection)
        self._playlist_vm.fetch_youtube_playlists()

    def _on_yt_playlists_ready(self, playlists: list) -> None:
        if not playlists:
            # 목록이 없으면 수동 입력 fallback
            import urllib.parse  # noqa: PLC0415
            pl_id, ok = QInputDialog.getText(
                self, "YouTube 재생목록 가져오기",
                "계정 재생목록을 찾지 못했습니다.\nYouTube 재생목록 ID 또는 URL을 직접 입력하세요:",
            )
            if not ok or not pl_id.strip():
                return
            yt_id = pl_id.strip()
            if "list=" in yt_id:
                import urllib.parse  # noqa: PLC0415
                parsed = urllib.parse.urlparse(yt_id)
                params = urllib.parse.parse_qs(parsed.query)
                yt_id = params.get("list", [yt_id])[0]
            self._playlist_vm.import_youtube_playlist(yt_id)
            return

        # 재생목록 선택 다이얼로그
        from PyQt6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QScrollArea  # noqa: PLC0415
        dlg = QDialog(self)
        dlg.setWindowTitle("YouTube 재생목록 가져오기")
        dlg.setMinimumWidth(400)
        dlg.setMinimumHeight(360)
        layout = QVBoxLayout(dlg)

        lbl = QLabel(f"YouTube 계정에서 재생목록 {len(playlists)}개를 찾았습니다.\n가져올 재생목록을 선택하세요:")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        check_container = QWidget()
        check_layout = QVBoxLayout(check_container)
        check_layout.setContentsMargins(4, 4, 4, 4)
        check_layout.setSpacing(4)

        checkboxes: list[tuple[QCheckBox, str]] = []  # (checkbox, yt_playlist_id)
        for pl in playlists:
            pl_id = pl.get("id") or ""
            pl_title = pl.get("title") or pl_id
            pl_count = pl.get("count") or 0
            label = f"{pl_title}  ({pl_count}개)"
            cb = QCheckBox(label)
            cb.setChecked(True)
            check_layout.addWidget(cb)
            checkboxes.append((cb, pl_id))

        check_layout.addStretch()
        scroll.setWidget(check_container)
        layout.addWidget(scroll, 1)

        sel_row = QHBoxLayout()
        btn_all = QPushButton("전체 선택")
        btn_none = QPushButton("전체 해제")
        btn_all.setFixedWidth(80)
        btn_none.setFixedWidth(80)
        btn_all.clicked.connect(lambda: [cb.setChecked(True) for cb, _ in checkboxes])
        btn_none.clicked.connect(lambda: [cb.setChecked(False) for cb, _ in checkboxes])
        sel_row.addWidget(btn_all)
        sel_row.addWidget(btn_none)
        sel_row.addStretch()
        layout.addLayout(sel_row)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        selected_ids = [pl_id for cb, pl_id in checkboxes if cb.isChecked() and pl_id]
        for yt_id in selected_ids:
            self._playlist_vm.import_youtube_playlist(yt_id)

    def _on_import_yt_playlist_manual(self) -> None:
        if self._playlist_vm is None:
            return
        import urllib.parse  # noqa: PLC0415
        pl_id, ok = QInputDialog.getText(
            self, "YouTube 재생목록 가져오기",
            "YouTube 재생목록 ID 또는 URL을 입력하세요:",
        )
        if not ok or not pl_id.strip():
            return
        yt_id = pl_id.strip()
        if "list=" in yt_id:
            parsed = urllib.parse.urlparse(yt_id)
            params = urllib.parse.parse_qs(parsed.query)
            yt_id = params.get("list", [yt_id])[0]
        self._playlist_vm.import_youtube_playlist(yt_id)
