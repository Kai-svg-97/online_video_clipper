"""FeedViewMixin — LibraryPanel의 feed 영역.

    LibraryPanel에 섞여 들어가는 mixin이라 `self._vm`·`self._view_stack` 같은
    패널 상태를 그대로 쓴다(런타임 클래스는 여전히 하나다). 파일을 나눈 목적은
    "이 동작이 어디 있나"를 파일 이름으로 찾게 하는 것이다.
"""

from __future__ import annotations

import logging

from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gui.panels.video_detail_panel import (
    RelatedItem,
)
from gui.view_models.feed_vm import CHANNELS_ROOT_KEY, FEED_ALL_KEY


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


class FeedViewMixin:
    """구독 피드·구독 채널 화면과 YouTube 동기화."""

    def _channel_name_for_url(self, url: str) -> str:
        """구독 URL로 채널 표시명을 조회한다(브레드크럼용)."""
        if not url or self._monitoring_vm is None:
            return ""
        for s in self._monitoring_vm.subscriptions:
            if s.channel_url == url:
                return s.channel_name
        return ""

    def _feed_related_items(self, clicked) -> list[RelatedItem]:
        feed = self._feed_vm.feed if self._feed_vm else []
        # 현재 영상도 포함(재생목록처럼) — 같은 채널 우선, 없으면 전체 피드
        same = [f for f in feed if f.channel_id and f.channel_id == clicked.channel_id]
        pool = same if same else list(feed)
        # 게시일 내림차순(최신 먼저)으로 정렬 — 피드 원본 순서가 채널별로 뭉쳐
        # 있어 무작위로 보이던 문제 교정. 게시일 없는 항목은 안정 정렬로 뒤에 둔다.
        pool = sorted(pool, key=lambda f: _pub_sort_key(f.published_at), reverse=True)
        return [self._related_from_feed(f) for f in pool[:30]]

    def _related_from_feed(self, f) -> RelatedItem:
        """FeedVideoDTO(구독 피드·추천) → 우측 목록 1행."""
        meta = []
        if f.view_count:
            meta.append(f"조회수 {f.view_count:,}회")
        rel = _relative_time(f.published_at)
        if rel:
            meta.append(rel)
        return RelatedItem(
            key=f.yt_video_id or f.url,
            title=f.title,
            channel=f.channel_name,
            duration_sec=f.duration_sec,
            meta_text="  ·  ".join(meta),
            payload=f,
            thumb_path=f.thumbnail_path or "",
            thumb_url=f.thumbnail_url or "",
            yt_video_id=f.yt_video_id or "",
        )

    def _on_sync_all_yt(self) -> None:
        """YouTube 재생목록 전체를 동기화한다."""
        if self._playlist_vm is None:
            return
        yt_pls = [pl for pl in self._playlist_vm.playlists if pl.source == "youtube" and pl.yt_playlist_id]
        if not yt_pls:
            QMessageBox.information(self, "동기화", "동기화할 YouTube 재생목록이 없습니다.")
            return
        for pl in yt_pls:
            self._playlist_vm.import_youtube_playlist(pl.yt_playlist_id)

    def _on_push_to_youtube(self, playlist_id, move: bool) -> None:
        if self._playlist_vm is None:
            return
        action = "이동" if move else "복사"
        reply = QMessageBox.question(
            self,
            f"YouTube로 {action}",
            f"이 재생목록을 YouTube에 {action}하시겠습니까?\n"
            + ("(로컬 항목이 YouTube 재생목록으로 전환됩니다)" if move
               else "(로컬 재생목록은 유지되고 YouTube에 새 재생목록이 생성됩니다)"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._playlist_vm.push_to_youtube(playlist_id, move=move)

    def _build_feed_view(self) -> QWidget:
        """feed_panel의 카드 그리드를 재사용한 구독/채널 피드 뷰를 만든다."""
        from gui.panels.feed_panel import _FeedGrid  # noqa: PLC0415
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self._feed_status = QLabel()
        self._feed_status.setContentsMargins(12, 6, 12, 6)
        self._feed_status.setWordWrap(True)
        self._feed_status.hide()
        v.addWidget(self._feed_status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._feed_grid = _FeedGrid()
        scroll.setWidget(self._feed_grid)
        v.addWidget(scroll, stretch=1)

        self._feed_grid.download_requested.connect(self._on_feed_card_download)
        self._feed_grid.add_to_category_requested.connect(self._on_feed_card_to_category)
        self._feed_grid.add_to_playlist_requested.connect(self._on_feed_card_to_playlist)
        return container

    def _build_channels_view(self) -> QWidget:
        """구독 채널 목록(아바타 카드) 그리드 뷰."""
        from gui.panels.feed_panel import _ChannelGrid  # noqa: PLC0415
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self._channels_status = QLabel()
        self._channels_status.setContentsMargins(12, 6, 12, 6)
        self._channels_status.setWordWrap(True)
        self._channels_status.hide()
        v.addWidget(self._channels_status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._channel_grid = _ChannelGrid()
        scroll.setWidget(self._channel_grid)
        v.addWidget(scroll, stretch=1)

        self._channel_grid.channel_clicked.connect(self._on_channel_selected)
        return container

    def _on_channels_root_selected(self) -> None:
        """"구독 채널" 노드 클릭 — 등록된 채널을 아바타 카드 그리드로 표시."""
        if self._feed_vm is None:
            return
        self._push_nav_state()
        self._leave_detail_if_open()
        self._current_playlist_id = None
        self._current_folder_id = None
        self._current_cat_id = None
        self._set_popular_tags_visible(False)
        self._view_stack.setCurrentIndex(_VIEW_CHANNELS)
        self._populate_channels_grid()
        self._refresh_breadcrumb()

    def _populate_channels_grid(self) -> None:
        """현재 구독 목록으로 채널 카드 그리드를 채운다(예비 카드 → 캐시/API 보강).

        _on_channels_root_selected(노드 클릭)와 _on_subs_synced(재동기화 완료) 양쪽에서
        재사용한다 — 뷰 전환·nav 히스토리는 건드리지 않는다.
        """
        if self._feed_vm is None:
            return
        subs = self._monitoring_vm.subscriptions if self._monitoring_vm is not None else []
        channels = [(s.channel_id, s.channel_name, s.channel_url) for s in subs]

        if not channels:
            self._channel_grid.set_channels([])
            self._channels_status.setText("구독 중인 채널이 없습니다.")
            self._channels_status.setVisible(True)
            return

        # Phase 1: DB 정보만으로 예비 카드 즉시 표시 (API 없이)
        from application.library.dtos import ChannelInfoDTO  # noqa: PLC0415
        preliminary = sorted(
            [
                ChannelInfoDTO(
                    channel_id=s.channel_id,
                    channel_name=s.channel_name,
                    channel_url=s.channel_url,
                    thumbnail_url="",
                    subscriber_count=None,
                    video_count=None,
                    latest_video_published_at=None,
                )
                for s in subs
            ],
            key=lambda c: c.channel_name.lower(),
        )
        self._channels_status.setVisible(False)
        self._channel_grid.set_channels(preliminary)

        # Phase 2: API 보강 — 캐시 히트 시 즉시 채우고 스피너 없이 조용히 갱신,
        # 미스 시엔 "구독 채널" 노드에 스피너 띄우고 보강.
        cached = self._feed_vm.get_cached(CHANNELS_ROOT_KEY)
        if cached:
            self._channel_grid.update_cards(cached)
            self._feed_vm.load_channel_infos(channels, silent=True)
        else:
            self._feed_vm.load_channel_infos(channels)

    def _on_sync_subscriptions(self) -> None:
        """구독 채널 컨텍스트 메뉴 '새로고침' — YouTube 구독 목록을 재동기화한다.

        import_from_youtube가 YouTube에서 구독 전체를 다시 조회해 로컬 DB에 반영하면,
        MonitoringViewModel이 subscriptions_changed(→트리 갱신)와 import_yt_finished
        (→그리드 갱신)를 방출한다.
        """
        if self._monitoring_vm is None:
            return
        if self._view_stack.currentIndex() == _VIEW_CHANNELS:
            self._channels_status.setText("YouTube 구독 채널을 동기화하는 중…")
            self._channels_status.setVisible(True)
        self._monitoring_vm.import_from_youtube()

    def _on_subs_synced(self, count: int) -> None:
        """구독 재동기화 완료 — 채널 그리드가 열려 있으면 새 목록으로 다시 채운다."""
        if self._view_stack.currentIndex() == _VIEW_CHANNELS:
            self._populate_channels_grid()

    def _on_subs_sync_error(self, message: str) -> None:
        """구독 재동기화 실패 — 채널 그리드가 열려 있으면 사유를 표시한다."""
        if self._view_stack.currentIndex() == _VIEW_CHANNELS:
            self._channels_status.setText(f"구독 동기화 실패: {message}")
            self._channels_status.setVisible(True)

    def _on_channel_infos_changed(self) -> None:
        if self._feed_vm is None:
            return
        if self._view_stack.currentIndex() != _VIEW_CHANNELS:
            return
        infos = self._feed_vm.channel_infos
        if not infos:
            self._channels_status.setText("채널 정보를 가져오지 못했습니다.")
            self._channels_status.show()
            return
        self._channels_status.hide()
        self._channel_grid.update_cards(infos)   # 예비 카드 in-place 갱신 (카드 재생성 없음)

    def _show_feed_view(self, status: str | None = None) -> None:
        if status:
            self._feed_status.setText(status)
            self._feed_status.show()
        else:
            self._feed_status.hide()
        self._view_stack.setCurrentIndex(_VIEW_FEED)

    def _on_channel_selected(self, channel_url: str) -> None:
        """구독 채널 노드 클릭 — 해당 채널 영상을 피드 그리드에 로드."""
        if self._feed_vm is None or not channel_url:
            return
        self._push_nav_state()
        self._leave_detail_if_open()
        self._current_playlist_id = None
        self._current_folder_id = None
        self._current_cat_id = None
        self._current_channel_url = channel_url
        self._feed_show_channel = False   # 이미 채널을 아는 화면이라 채널명 숨김
        self._set_popular_tags_visible(False)
        self._current_feed_key = channel_url
        cached = self._feed_vm.get_cached(channel_url)
        if cached:
            # 채널별 캐시 히트: 즉시 표시 + 스피너 없이 조용히 백그라운드 갱신
            self._feed_grid.set_feed(cached, show_channel=False)
            self._show_feed_view()
            self._feed_vm.load_channel(channel_url, silent=True)
        else:
            self._show_feed_view("로딩 중…")
            self._feed_vm.load_channel(channel_url)
        self._refresh_breadcrumb()

    def _on_feed_all_selected(self) -> None:
        """전체 구독 피드 노드 클릭 — 모든 구독 채널 최신 영상을 로드."""
        if self._feed_vm is None:
            return
        self._push_nav_state()
        self._leave_detail_if_open()
        self._current_playlist_id = None
        self._current_folder_id = None
        self._current_cat_id = None
        self._feed_show_channel = True    # 여러 채널이 섞이므로 채널명 표시
        self._set_popular_tags_visible(False)
        self._current_feed_key = FEED_ALL_KEY
        cached = self._feed_vm.get_cached(FEED_ALL_KEY)
        if cached:
            # 전체 피드 캐시 히트: 즉시 표시 + 스피너 없이 조용히 백그라운드 갱신
            self._feed_grid.set_feed(cached, show_channel=True)
            self._show_feed_view()
            self._feed_vm.refresh(silent=True)
        else:
            self._show_feed_view("로딩 중…")
            self._feed_vm.refresh()
        self._refresh_breadcrumb()

    def _on_feed_batch_appended(self, batch: list) -> None:
        pass   # feed_batch_ready 시그널로 대체됨

    def _on_feed_changed(self) -> None:
        pass   # feed_key_changed 시그널로 대체됨

    def _on_feed_loading_changed(self, loading: bool) -> None:
        # 스피너는 loading_key_changed 전담; 상태 텍스트만 유지
        if loading and self._view_stack.currentIndex() == _VIEW_FEED:
            if not self._feed_vm.get_cached(self._current_feed_key):
                self._feed_status.setText("로딩 중…")
                self._feed_status.show()

    def _on_feed_loading_key_changed(self, key: str, loading: bool) -> None:
        """loading_key_changed 핸들러 — 해당 키 노드에 스피너 즉시 전환."""
        item = self._playlist_panel.find_yt_item_by_key(key)
        self._playlist_panel.set_yt_node_loading(key, item, loading)

    def _on_feed_key_changed(self, key: str, items: list) -> None:
        """채널 로딩 완료 — 현재 표시 중인 key와 일치할 때만 그리드 갱신."""
        if key != self._current_feed_key:
            return   # 백그라운드 채널 완료 — 캐시에만 저장됨
        show_channel = (key == FEED_ALL_KEY)
        self._feed_grid.set_feed(items, show_channel=show_channel)
        if self._view_stack.currentIndex() == _VIEW_FEED:
            self._feed_status.hide() if items else self._show_feed_view("영상이 없습니다.")

    def _on_feed_batch_ready(self, key: str, batch: list) -> None:
        """부분 결과 배치 — 현재 key 첫 로딩 시만 점진적으로 카드를 추가한다."""
        if key != self._current_feed_key:
            return
        if self._feed_vm.get_cached(key):
            return   # 재방문: feed_key_changed가 전체 교체
        if self._view_stack.currentIndex() != _VIEW_FEED:
            return
        show_channel = (key == FEED_ALL_KEY)
        self._feed_grid.append_feed(batch, show_channel=show_channel)
        self._feed_status.hide()

    def _on_feed_error(self, msg: str) -> None:
        idx = self._view_stack.currentIndex()
        if idx not in (_VIEW_FEED, _VIEW_CHANNELS):
            return
        ml = msg.lower()
        if "could not copy" in ml or ("database" in ml and "lock" in ml):
            display = (
                "Chrome이 실행 중입니다 — Chrome을 완전히 종료 후 재시도하거나,\n"
                "설정 > YouTube 계정에서 브라우저를 Firefox로 변경하세요."
            )
        elif "복호화" in msg or "dpapi" in ml or "failed to decrypt" in ml:
            # ytdlp_adapter가 이미 한국어 안내문으로 변환한 DPAPI 메시지를 그대로 표시
            display = msg
        elif "cookie" in ml or "쿠키" in msg:
            display = (
                "쿠키 인증 실패 — 설정 > YouTube 계정에서 Firefox로 변경하거나\n"
                "Chrome을 완전히 종료 후 재시도하세요."
            )
        elif "sign in" in ml or "로그인" in msg:
            display = "YouTube 로그인 필요 — 설정 > YouTube 계정에서 로그인하세요."
        else:
            display = f"오류: {msg[:200]}"
        status = self._feed_status if idx == _VIEW_FEED else self._channels_status
        status.setText(display)
        status.show()

    def _on_feed_card_download(self, url: str, title: str) -> None:
        from domain.download.value_objects import DownloadSettings  # noqa: PLC0415
        self.download_requested.emit(url, title, DownloadSettings())
