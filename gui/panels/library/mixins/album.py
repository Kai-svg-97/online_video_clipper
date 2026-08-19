"""AlbumViewMixin — LibraryPanel의 album 영역.

    LibraryPanel에 섞여 들어가는 mixin이라 `self._vm`·`self._view_stack` 같은
    패널 상태를 그대로 쓴다(런타임 클래스는 여전히 하나다). 파일을 나눈 목적은
    "이 동작이 어디 있나"를 파일 이름으로 찾게 하는 것이다.
"""

from __future__ import annotations

import logging


from gui.panels.video_detail_panel import (
    RelatedItem,
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


class AlbumViewMixin:
    """앨범 보기 — 자켓 그리드·앨범 상세·수록곡 담기·앨범 재생.

    앨범은 저장 단위가 아니라 노래 정보에서 파생되는 묶음이라(domain/song/album.py),
    여기서는 '보기 유형 💿 진입 → 그리드 → 상세 → 재생/담기' 흐름만 다룬다.
    """

    def album_view_available(self) -> bool:
        """앨범 보기 버튼을 쓸 수 있는 화면인지(음악 계열 카테고리 + 앨범 VM 주입)."""
        return self._album_vm is not None and self._is_music_category(self._current_cat_id)

    def _album_category_ids(self) -> list:
        """앨범 보기 대상 카테고리 — 현재 카테고리 + **모든 하위**.

        음악 라이브러리는 보통 'Music > 가수 > 곡' 구조라, 루트에서 앨범을 보면 하위에
        있는 곡이 전부 빠진다. 앨범은 카테고리 경계보다 '어떤 노래를 갖고 있나'가 중요해
        하위까지 포함한다(일반 목록 뷰는 기존대로 해당 카테고리만 보여 준다).
        """
        if self._current_cat_id is None:
            return []
        children: dict = {}
        for cat in self._vm.categories:
            children.setdefault(cat.parent_id, []).append(cat.id)
        out = [self._current_cat_id]
        queue = [self._current_cat_id]
        seen = {self._current_cat_id}
        while queue:
            node = queue.pop()
            for child in children.get(node, []):
                if child in seen:        # 데이터가 순환해도 멈춘다
                    continue
                seen.add(child)
                out.append(child)
                queue.append(child)
        return out

    def _enter_album_mode(self) -> None:
        if self._album_vm is None:
            return
        self._push_nav_state()   # 앨범 그리드에서 뒤로 = 직전 목록 화면
        self._album_mode = True
        self._btn_album.setChecked(True)
        self._leave_detail_if_open()
        self._switch_view(_VIEW_ALBUMS)
        self._album_grid.set_status("앨범을 구성하는 중…")
        self._load_albums()
        # 앨범 값이 빈 노래는 외부 조회로 추정해 채운다(백그라운드, 실패는 재조회 안 함).
        self._album_vm.resolve_unknown_albums(
            category_id=self._current_cat_id, category_ids=self._album_category_ids()
        )

    def _exit_album_mode(self) -> None:
        self._album_mode = False
        self._current_album_key = None
        if self._album_vm is not None:
            self._album_vm.cancel_fill()
        if self._nav_stack.currentIndex() == _NAV_ALBUM_DETAIL:
            self._close_album_detail()
        if self._view_stack.currentIndex() == _VIEW_ALBUMS:
            # 앨범 버튼도 보기 그룹의 일원이라 checkedId()로 되돌리면 다시 앨범이다 —
            # 앨범 이전에 보던 목록 뷰로 복귀한다.
            self._switch_view(self._last_list_view)

    def _load_albums(self) -> None:
        if self._album_vm is None:
            return
        self._album_vm.load_albums(
            category_id=self._current_cat_id, category_ids=self._album_category_ids()
        )

    def _on_albums_changed(self, albums: list) -> None:
        if not self._album_mode:
            return
        self._album_grid.set_albums(albums)
        self._album_grid.set_status(
            "" if albums else "이 카테고리에는 앨범으로 묶을 노래가 없습니다."
        )

    def _on_album_clicked(self, album_key: str) -> None:
        """앨범 카드 클릭 — 상세를 연다(수록곡은 외부 조회라 백그라운드)."""
        if self._album_vm is None:
            return
        self._push_nav_state()   # 앨범 상세에서 뒤로 = 앨범 그리드
        self._current_album_key = album_key
        self._album_detail.set_detail(None, crumb="앨범 정보를 가져오는 중…")
        self._album_detail.set_busy(True)
        fade_switch(self._nav_stack, _NAV_ALBUM_DETAIL)
        self._album_vm.load_detail(
            album_key, category_id=self._current_cat_id,
            category_ids=self._album_category_ids(),
        )

    def _on_album_detail_ready(self, detail) -> None:
        if not self._album_mode:
            return
        crumb = self._build_category_path(self._current_cat_id) if self._current_cat_id else ""
        self._album_detail.set_detail(detail, crumb=crumb)
        self._album_detail.set_busy(False)
        # 라이브러리에 없는 수록곡은 열자마자 백그라운드로 찾아 채운다(사용자 조작 없이).
        if detail is not None and detail.missing_count and self._album_vm is not None:
            self._album_detail.set_status(
                f"{self._album_detail.status_text()}  ·  빠진 곡 찾는 중…"
            )
            self._album_vm.fill_missing_tracks(
                detail.key, category_id=self._current_cat_id,
                category_ids=self._album_category_ids(),
            )

    def _on_album_track_filled(self, track) -> None:
        self._album_detail.apply_filled_track(track)

    def _on_album_track_delete_requested(self, track) -> None:
        """수정 모드의 ✕ — 잘못 붙은 자동 매핑을 지운다(DB 삭제뿐이라 즉시 처리)."""
        if self._album_vm is not None:
            self._album_vm.remove_track_link(track.disc_no, track.track_no)

    def _on_album_track_removed(self, track) -> None:
        self._album_detail.apply_filled_track(track)

    def _on_album_fill_finished(self, count: int) -> None:
        if count:
            self._album_detail.set_status(
                f"{self._album_detail.status_text()}  ·  {count}곡 자동 매핑"
            )

    def _on_album_error(self, msg: str) -> None:
        logger.warning("앨범 조회 실패: %s", msg)
        self._album_grid.set_status("앨범 정보를 가져오지 못했습니다.")
        self._album_detail.set_busy(False)

    def _close_album_detail(self) -> None:
        """앨범 상세를 닫고 목록 컨테이너로 돌아온다(히스토리는 건드리지 않는다)."""
        # 목록으로 복귀는 살짝 띄우며 바꾼다(영상 화면으로 갈 때는 즉시 전환).
        fade_switch(self._nav_stack, 0)
        self._current_album_key = None
        if self._album_vm is not None:
            self._album_vm.cancel_fill()
            self._album_vm.cancel_add()

    def _on_album_add_all(self, detail) -> None:
        """수록곡 헤더의 '＋ 현재 카테고리에 등록' — 자동 매핑 곡을 지금 카테고리에 담는다."""
        if self._album_vm is None or detail is None:
            return
        self._album_detail.set_add_busy(True)
        self._album_detail.set_status("카테고리에 담는 중…")
        self._album_vm.add_tracks_to_category(detail, category_id=self._current_cat_id)

    def _on_album_add_progress(self, done: int, total: int) -> None:
        self._album_detail.set_status(f"카테고리에 담는 중… {done}/{total}곡")

    def _on_album_tracks_added(self, count: int) -> None:
        """담기 완료 — 목록과 앨범 상세를 다시 읽어 '내 등록'으로 바뀌게 한다."""
        self._album_detail.set_add_busy(False)
        if not count:
            self._album_detail.set_status("담을 곡이 없습니다.")
            return
        self._album_detail.set_status(f"{count}곡을 카테고리에 담았습니다.")
        self._vm.load()          # 라이브러리 목록·카테고리 개수 갱신
        if self._current_album_key:
            self._album_vm.load_detail(
                self._current_album_key, category_id=self._current_cat_id,
                category_ids=self._album_category_ids(),
            )

    def _on_album_back(self) -> None:
        """앨범 상세의 ‹ 버튼 — 영상 상세와 같이 화면 히스토리를 되짚는다."""
        if self._nav_history:
            self._go_back()
        else:
            self._close_album_detail()

    def _on_album_unknown_resolved(self, count: int) -> None:
        if count and self._album_mode:
            self._load_albums()   # 앨범을 찾은 곡들이 제 묶음으로 옮겨 간다

    def _on_album_refresh(self, album_key: str) -> None:
        if self._album_vm is None or not album_key:
            return
        self._album_detail.set_busy(True)
        self._album_vm.load_detail(
            album_key, category_id=self._current_cat_id,
            category_ids=self._album_category_ids(), refresh=True,
        )

    def _on_album_fill_requested(self, album_key: str) -> None:
        if self._album_vm is None or not album_key:
            return
        self._album_vm.fill_missing_tracks(
            album_key, category_id=self._current_cat_id,
            category_ids=self._album_category_ids(),
        )

    def _album_related_items(self, detail) -> list:
        """앨범 수록곡을 상세화면 재생목록(RelatedItem) 항목으로 바꾼다.

        로컬 곡은 video_id를, 자동 매핑 곡은 FeedVideoDTO를 payload로 싣는다 —
        상세화면의 기존 재생목록 경로(_open_playlist_payload)가 두 종류를 모두 다룬다.
        """
        from application.library.dtos import FeedVideoDTO  # noqa: PLC0415
        from application.song.album_dtos import (  # noqa: PLC0415
            TRACK_ORIGIN_AUTO,
            TRACK_ORIGIN_LIBRARY,
        )

        items = []
        for track in detail.tracks:
            if track.origin == TRACK_ORIGIN_LIBRARY and track.video_id is not None:
                video = next((v for v in self._vm.videos if v.id == track.video_id), None)
                if video is not None:
                    items.append(self._related_from_video(video))
                    continue
                # 현재 페이지에 없는 곡(다른 페이지·다른 정렬) — 최소 정보로 행을 만든다.
                items.append(RelatedItem(
                    key=str(track.video_id),
                    title=track.title,
                    channel=track.artist,
                    duration_sec=track.duration_sec,
                    meta_text="내 등록",
                    payload=track.video_id,
                    thumb_path=track.thumbnail_path,
                ))
            elif track.origin == TRACK_ORIGIN_AUTO and track.stream_url:
                dto = FeedVideoDTO(
                    url=track.stream_url,
                    title=track.stream_title or track.title,
                    channel_name=track.stream_channel or track.artist,
                    channel_id="",
                    thumbnail_url=(
                        f"https://i.ytimg.com/vi/{track.stream_yt_id}/hqdefault.jpg"
                        if track.stream_yt_id else ""
                    ),
                    thumbnail_path="",
                    published_at="",
                    view_count=None,
                    duration_sec=track.duration_sec,
                    in_library=False,
                    yt_video_id=track.stream_yt_id,
                )
                items.append(self._related_from_feed(dto))
        return items

    def _on_play_album(self, detail) -> None:
        """앨범 재생 — 수록곡을 재생목록으로 삼아 첫 곡부터 이어 재생한다."""
        items = self._album_related_items(detail)
        if not items:
            return
        self._start_album_playlist(detail, items, items[0].payload)

    def _on_album_track_clicked(self, track) -> None:
        """수록곡 클릭 — 그 곡부터 앨범을 이어 재생한다."""
        detail = self._album_vm.detail if self._album_vm is not None else None
        if detail is None:
            return
        items = self._album_related_items(detail)
        payload = None
        for item in items:
            if track.video_id is not None and item.payload == track.video_id:
                payload = item.payload
                break
            if track.stream_url and getattr(item.payload, "url", "") == track.stream_url:
                payload = item.payload
                break
        if payload is None:
            return
        self._start_album_playlist(detail, items, payload)

    def _start_album_playlist(self, detail, items: list, payload) -> None:
        """앨범 재생목록 컨텍스트를 세우고 지정한 곡을 연다.

        기존 '가수/앨범 필터' 재생목록과 같은 구조(_playlist_ctx)를 쓰므로 자동 다음곡·
        마우스 뒤로가기 되짚기가 그대로 동작한다.
        """
        # 재생목록 진입은 `push_nav=False`로 상세를 열기 때문에, 여기서 앨범 상세 화면을
        # 직접 쌓아 둬야 재생 이력을 다 되짚은 뒤 뒤로가기가 앨범 상세로 돌아온다.
        self._push_nav_state()
        self._playlist_ctx = {
            "items": items,
            "header": f"앨범: {detail.album_title}",
            "prev_related": items,
            "history": [payload],
        }
        self._open_playlist_payload(payload, autoplay=True)

    def _restore_album_mode(self, snap: dict) -> None:
        """스냅샷의 앨범 보기 모드를 복원한다(정렬 콤보를 통해 기존 경로를 그대로 탄다).

        모드 전환을 직접 수행하지 않고 콤보 선택을 바꾸는 이유는, 진입/이탈에 따라오는
        일들(뷰 전환·목록 조회·앨범 추정)이 모두 그 경로에 걸려 있기 때문이다.
        """
        want = bool(snap.get("album_mode"))
        if want == self._album_mode:
            if want and self._view_stack.currentIndex() != _VIEW_ALBUMS:
                # 목록 복원이 일반 뷰로 되돌렸을 수 있다 — 앨범 그리드를 다시 띄운다.
                self._switch_view(_VIEW_ALBUMS)
            return
        self._update_view_options()
        if want:
            if not self.album_view_available():
                return   # 앨범을 열 수 없는 카테고리 — 일반 목록으로 둔다
            self._enter_album_mode()
        else:
            self._exit_album_mode()
