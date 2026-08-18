"""DetailNavigationMixin — LibraryPanel의 detail 영역.

    LibraryPanel에 섞여 들어가는 mixin이라 `self._vm`·`self._view_stack` 같은
    패널 상태를 그대로 쓴다(런타임 클래스는 여전히 하나다). 파일을 나눈 목적은
    "이 동작이 어디 있나"를 파일 이름으로 찾게 하는 것이다.
"""

from __future__ import annotations

import logging
import re
from uuid import UUID


from application.library.dtos import VideoDTO
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

logger = logging.getLogger(__name__)


class DetailNavigationMixin:
    """영상 상세 진입/이탈과 재생목록(자동 다음곡) 연결.

    로컬 영상과 스트리밍 영상 두 갈래를 같은 화면으로 열고, 연관 영상·가수/앨범 필터·
    앨범 재생이 모두 `_playlist_ctx` 하나로 이어진다.
    """

    def _open_detail(
        self, video_id: UUID, autoplay: bool = False,
        related: list | None = None, header: str | None = None, push_nav: bool = True,
        resume_ms: int = 0, stay_on_list: bool = False,
    ) -> None:
        """로컬 영상 상세화면을 연다.

        related가 None이면 일반 진입 — 현재 목록으로 연관 목록을 구성하고 재생목록 모드를
        해제한다. related가 주어지면(재생목록 내 이동) 그 목록/헤더를 유지한다.
        push_nav=False면 화면 히스토리를 남기지 않는다(재생목록 내 이동).
        stay_on_list=True면 상세로 화면을 바꾸지 않고 위젯에만 싣는다 — 미니바로
        듣는 중 자동 다음곡이 화면을 뺏지 않게 하기 위한 것이다."""
        detail = self._vm.get_video_detail(video_id)
        if detail is None:
            return
        if push_nav and not self._is_restoring:
            self._push_nav_state()
        if related is None:
            # 일반 진입 — 재생목록 컨텍스트 해제 + 현재 목록(현재 영상 포함) 구성
            self._playlist_ctx = None
            related = [self._related_from_video(v) for v in self._vm.videos][:30]
        tag_ids = {t.name: t.id for t in self._vm.tags}
        cat_path = self._vm.get_category_path_with_ids(detail.category_id) if detail.category_id else []
        # 재생 전 포스터 = 목록에서 보던 썸네일(동일 캐시)
        poster = (
            _load_thumb(detail.thumbnail_path, _TW_ICON, _TH_ICON)
            if detail.thumbnail_path else None
        )
        # 이어보기 — 호출부가 위치를 지정하지 않으면 저장된 지점에서 이어 본다.
        # (재생은 자동으로 시작하지 않는다 — 목록에서 눌렀을 뿐인데 소리가 나면 놀란다.)
        resume_ms = resume_ms or getattr(detail, "last_position_ms", 0) or 0
        self._detail_widget.load(detail, tag_ids, resume_ms=resume_ms, related=related,
                                 category_path=cat_path or None, poster=poster,
                                 autoplay=autoplay, related_header=header)
        self._detail_widget.set_recommendations(self._recommend_related_items())
        self._current_detail_payload = video_id
        self._remember_now_playing(detail.title, detail.channel_name or "", poster)
        self._remember_related_for_mini(related, header)
        if stay_on_list:
            # 미니바 재생 중 — 화면은 목록에 두고 재생만 다음 곡으로 넘긴다.
            self._refresh_mini_track()
        else:
            self._clear_mini_player(stop=False)   # 상세를 보는 동안엔 띠가 필요 없다
            self._nav_stack.setCurrentIndex(1)
        self._vm.request_thumbnail_refresh(video_id, detail.url)
        if self._song_vm is not None:
            self._song_vm.load(video_id)

    def _open_stream_detail(
        self, feed_dto, autoplay: bool = False,
        related: list | None = None, header: str | None = None, push_nav: bool = True,
        stay_on_list: bool = False,
    ) -> None:
        """구독 피드/채널의 스트리밍 영상 상세화면을 연다.

        related가 None이면 일반 진입(같은 채널 최근 영상, 현재 영상 포함)이며 재생목록
        모드를 해제한다. related가 주어지면 그 목록/헤더를 유지(재생목록 내 이동)."""
        if self._feed_vm is None:
            return
        if push_nav and not self._is_restoring:
            self._push_nav_state()
        if related is None:
            self._playlist_ctx = None
            related = self._feed_related_items(feed_dto)
        self._detail_widget.load_stream(feed_dto, related=related, related_header=header,
                                        poster=None)
        self._detail_widget.set_recommendations(self._recommend_related_items())
        self._current_detail_payload = feed_dto
        self._remember_now_playing(feed_dto.title, feed_dto.channel_name or "", None)
        self._remember_related_for_mini(related, header)
        if stay_on_list:
            self._refresh_mini_track()
        else:
            self._clear_mini_player(stop=False)
            self._nav_stack.setCurrentIndex(1)

    def _on_related_item_selected(self, payload) -> None:
        """연관 영상/재생목록 클릭 — 재생목록 모드면 이력에 쌓고 재생, 아니면 일반 진입."""
        from application.library.dtos import FeedVideoDTO  # noqa: PLC0415
        if self._playlist_ctx is not None:
            self._playlist_ctx["history"].append(payload)
            self._open_playlist_payload(payload, autoplay=True)
            return
        if isinstance(payload, UUID):
            self._open_detail(payload)
        elif isinstance(payload, FeedVideoDTO):
            self._open_stream_detail(payload)

    def _on_play_next(self, payload) -> None:
        """재생목록 자동재생 — 다음 항목을 로드하고 바로 재생한다.

        미니바로 듣는 중이면 **화면을 바꾸지 않는다** — 목록을 둘러보는 중에 곡이
        끝났다고 상세 화면이 튀어나오면 하던 일을 방해한다.
        """
        from application.library.dtos import FeedVideoDTO  # noqa: PLC0415
        if self._now_playing is not None:
            self._play_next_in_mini(payload)
            return
        if self._playlist_ctx is not None:
            self._playlist_ctx["history"].append(payload)
            self._open_playlist_payload(payload, autoplay=True)
            return
        if isinstance(payload, UUID):
            self._open_detail(payload, autoplay=True)
        elif isinstance(payload, FeedVideoDTO):
            self._open_stream_detail(payload, autoplay=True)

    def _on_song_filter_requested(self, field: str, value: str) -> None:
        """노래 탭의 가수/앨범 » 클릭 — 같은 가수/앨범 영상을 재생목록으로 나열한다."""
        if not value:
            return
        videos = self._vm.get_videos_by_song(field, value)
        items = [self._related_from_video(v) for v in videos][:100]
        if not items:
            return
        header = (f"가수: {value}" if field == "artist" else f"앨범: {value}")
        if self._playlist_ctx is None:
            # 진입 — 현재 '연관 영상' 목록과 진입 영상을 보존
            prev_related = [self._related_from_video(v) for v in self._vm.videos][:30]
            self._playlist_ctx = {
                "items": items,
                "header": header,
                "prev_related": prev_related,
                "history": [self._current_detail_payload],
            }
        else:
            # 이미 재생목록 모드 — 새 필터로 교체(prev_related 보존)
            self._playlist_ctx["items"] = items
            self._playlist_ctx["header"] = header
            self._playlist_ctx["history"] = [self._current_detail_payload]
        self._detail_widget.set_related(items, header=header)

    def _related_from_video(self, v: VideoDTO) -> RelatedItem:
        meta = []
        if v.view_count:
            meta.append(f"조회수 {v.view_count:,}회")
        rel = _relative_time(v.published_at)
        if rel:
            meta.append(rel)
        # YouTube URL에서 영상 ID 추출 — 썸네일 파일이 없을 때 CDN 폴백용
        yt_vid_id = ""
        thumb_url = ""
        if v.url:
            m = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", v.url)
            if not m:
                m = re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", v.url)
            if m:
                yt_vid_id = m.group(1)
                thumb_url = f"https://i.ytimg.com/vi/{yt_vid_id}/hqdefault.jpg"
        return RelatedItem(
            key=str(v.id),
            title=v.title,
            channel=v.channel_name,
            duration_sec=v.duration_sec,
            meta_text="  ·  ".join(meta),
            payload=v.id,
            thumb_path=v.thumbnail_path or "",
            thumb_url=thumb_url,
            yt_video_id=yt_vid_id,
        )

    def _on_detail_tags_updated(self, video_id: UUID, tags: list) -> None:
        """Called when user manually adds a tag in the detail view."""
        self._vm.update_video_tags(video_id, tags)

    def _on_detail_downloads_refresh(self, video_id: object) -> None:
        """다운로드 완료 후 상세화면의 다운로드 파일 탭을 갱신한다."""
        from uuid import UUID as _UUID  # noqa: PLC0415
        if not isinstance(video_id, _UUID):
            return
        try:
            detail = self._vm.get_video_detail(video_id)
            if detail is not None:
                self._detail_widget.refresh_downloads(detail.downloads, detail.failed_downloads)
        except Exception:
            logger.exception("다운로드 탭 갱신 실패: %s", video_id)
        if self._nav_stack.currentIndex() == 1:
            detail = self._vm.get_video_detail(video_id)
            if detail:
                tag_ids = {t.name: t.id for t in self._vm.tags}
                related = [self._related_from_video(v) for v in self._vm.videos][:30]
                poster = (
                    _load_thumb(detail.thumbnail_path, _TW_ICON, _TH_ICON)
                    if detail.thumbnail_path else None
                )
                self._detail_widget.load(detail, tag_ids, related=related, poster=poster)
                if self._song_vm is not None:
                    self._song_vm.load(video_id)

    def _on_detail_refresh_requested(self, video_id: object) -> None:
        """제목행 ⟳ — YouTube(yt-dlp)에서 메타데이터를 재수집(백그라운드)한다.

        기존에는 DB만 재조회해 저장된 오래된/부실한 정보가 그대로여서 유튜브 웹과
        달랐다. 이제 실제로 재수집해 DB를 갱신하고, 완료 시
        `video_metadata_refreshed` 신호로 상세를 제자리 재로드한다.
        """
        if not isinstance(video_id, UUID):
            return
        self._detail_widget.set_refresh_busy(True)
        self._vm.refresh_video_metadata(video_id)

    def _on_video_metadata_refreshed(self, video_id: object, ok: bool) -> None:
        """메타데이터 재수집 완료 — 현재 그 영상 상세가 열려 있으면 제자리 재로드."""
        self._detail_widget.set_refresh_busy(False)
        if not isinstance(video_id, UUID):
            return
        # 갱신 도중 다른 화면/영상으로 이동했으면 재로드하지 않는다.
        if self._detail_widget.current_detail_id() != video_id:
            return
        self._reload_detail_in_place(video_id)

    def _on_enrich_finished(self, url: str, kind: str, ok: bool, detail: str) -> None:
        """등록 후 자동 보강 완료 — 그 영상 상세가 열려 있으면 제자리 재로드.

        요약 추출은 수십 초가 걸려 그 사이 사용자가 영상을 열어 볼 수 있다.
        _reload_detail_in_place가 상세 DTO와 노래 정보를 함께 다시 읽으므로
        요약 탭·노래 탭 어느 쪽이 채워졌든 반영된다.
        """
        if not ok:
            return
        video_id = self._detail_widget.current_detail_id()
        if video_id is None:
            return
        enriched_id = self._vm.get_video_id_by_url(url)
        if enriched_id != video_id:
            return
        self._reload_detail_in_place(video_id)

    def _reload_detail_in_place(self, video_id: UUID) -> None:
        """DB의 최신 상세를 다시 읽어 상세 위젯에 재로드한다(nav 히스토리 미변경)."""
        try:
            detail = self._vm.get_video_detail(video_id)
            if detail is None:
                return
            tag_ids = {t.name: t.id for t in self._vm.tags}
            related = [self._related_from_video(v) for v in self._vm.videos][:30]
            cat_path = (
                self._vm.get_category_path_with_ids(detail.category_id)
                if detail.category_id else []
            )
            poster = (
                _load_thumb(detail.thumbnail_path, _TW_ICON, _TH_ICON)
                if detail.thumbnail_path else None
            )
            self._detail_widget.load(
                detail, tag_ids, related=related, category_path=cat_path or None,
                poster=poster,
            )
            if self._song_vm is not None:
                self._song_vm.load(video_id)
        except Exception:
            logger.exception("상세 정보 재로드 실패: %s", video_id)

    def _leave_detail_if_open(self) -> None:
        """상세 화면이 열려 있으면 목록 컨테이너로 복귀한다.

        영상 상세(인덱스 1)뿐 아니라 **앨범 상세(인덱스 2)**도 함께 닫는다 — 트리에서
        다른 노드를 골랐는데 앨범 상세가 그대로 떠 있으면 목록만 바뀌고 화면은 그대로라
        먹통처럼 보인다.
        """
        idx = self._nav_stack.currentIndex()
        if idx == 1:
            self._on_back_from_detail()
        elif idx == _NAV_ALBUM_DETAIL:
            self._on_album_back()

    def _reopen_detail(self, payload) -> None:
        """히스토리 복원 시 직전 상세 화면을 다시 연다."""
        from application.library.dtos import FeedVideoDTO  # noqa: PLC0415
        if isinstance(payload, UUID):
            self._open_detail(payload)
        elif isinstance(payload, FeedVideoDTO):
            self._open_stream_detail(payload)

    def _on_detail_category_requested(self, payload) -> None:
        """상세화면 📁 버튼/잠금 안내판 — 카테고리를 골라 담는다."""
        from application.library.dtos import FeedVideoDTO  # noqa: PLC0415
        ok, cat_id = self._pick_category()
        if not ok:
            return
        if isinstance(payload, UUID):
            self._vm.assign_category(payload, cat_id)
            # 브레드크럼(카테고리 경로)을 즉시 반영한다.
            self._reload_detail_in_place(payload)
            return
        if not isinstance(payload, FeedVideoDTO):
            return
        url = getattr(payload, "url", "")
        if not url:
            return
        existing = self._vm.get_video_id_by_url(url)
        if existing is not None:
            # 이미 라이브러리에 있는 영상을 스트리밍으로 보고 있었다 — 이동만 하고 전환.
            self._vm.assign_category(existing, cat_id)
            self._switch_to_local_detail(existing)
            return
        self._pending_category_url = url
        self._vm.add_video(url, cat_id)

    def _on_video_added_for_detail(self, url: str) -> None:
        """등록 완료 — 상세에서 담기를 눌렀던 영상이면 로컬 상세로 갈아탄다."""
        if not url or url != self._pending_category_url:
            return
        self._pending_category_url = ""
        video_id = self._vm.get_video_id_by_url(url)
        if video_id is None:
            logger.warning("등록 직후 영상 id를 찾지 못했다: %s", url)
            return
        self._switch_to_local_detail(video_id)

    def _switch_to_local_detail(self, video_id: UUID) -> None:
        """스트리밍 상세 → 같은 영상의 로컬 상세로 전환(재생 위치·재생 여부 유지)."""
        if self._nav_stack.currentIndex() != 1:
            return   # 이미 상세를 떠났다 — 등록만 하고 끝
        resume = self._detail_widget.player_position_ms()
        playing = self._detail_widget.is_playing()
        self._open_detail(video_id, autoplay=playing, push_nav=False, resume_ms=resume)

    def _on_playlists_changed(self) -> None:
        self._refresh_unified_tree()

    def _on_playlist_move(self, playlist_id, folder_id) -> None:
        if self._playlist_vm is None:
            return
        self._playlist_vm.move_playlist_to_folder(playlist_id, folder_id)

    def _on_playlist_selected_from_tree(self, playlist_id) -> None:
        """트리에서 재생목록 선택 — 폴더 카드 뷰에 있다면 정상 뷰로 복귀 후 필터 적용."""
        self._push_nav_state()
        self._leave_detail_if_open()
        node_key = f"pl:{playlist_id}" if playlist_id is not None else None
        self._vm.set_playlist_filter(playlist_id, node_key=node_key)
        self._icon_view.set_playlist_context(playlist_id)
        self._list_view.set_playlist_context(playlist_id)
        if self._view_stack.currentIndex() in (_VIEW_FOLDER, _VIEW_FEED, _VIEW_CHANNELS):
            self._switch_view(_VIEW_ALBUMS if self._album_mode else self._last_list_view)
        self._current_playlist_id = playlist_id
        self._current_folder_id = None
        # 재생목록 선택 시에는 태그 섹션을 숨겨 트리가 더 넓게 보이도록 한다
        self._set_popular_tags_visible(False)
        self._refresh_breadcrumb()

    def _on_playlist_reordered(self, playlist_id: UUID, ordered_ids: list[UUID]) -> None:
        if self._playlist_vm is None:
            return
        self._playlist_vm.reorder_playlist(playlist_id, ordered_ids)
