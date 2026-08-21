"""RecommendStripMixin — LibraryPanel의 recommend 영역.

    LibraryPanel에 섞여 들어가는 mixin이라 `self._vm`·`self._view_stack` 같은
    패널 상태를 그대로 쓴다(런타임 클래스는 여전히 하나다). 파일을 나눈 목적은
    "이 동작이 어디 있나"를 파일 이름으로 찾게 하는 것이다.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import (
    QEasingCurve,
    QVariantAnimation,
)

import config.settings as _settings


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


class RecommendStripMixin:
    """목록 아래 추천 영상 스트립 — 조회 디바운스와 등장/퇴장 연출.

    준비되기 전에는 감췄다가 결과가 오면 아래에서 올라오고, 새 조회가 시작되면 다시
    접힌다. 스플리터 높이를 직접 다루는 코드가 모여 있다.
    """

    def _recommend_seeds(self) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        """현재 목록에서 (제목, 채널, 태그) 씨앗을 뽑는다."""
        videos = self._vm.videos[:_RECOMMEND_SEED_LIMIT]
        titles = tuple(v.title for v in videos if v.title)
        channels = tuple(v.channel_name for v in videos if v.channel_name)
        tags = tuple(t for v in videos for t in (v.tag_names or ()))
        return titles, channels, tags

    def _schedule_recommend_refresh(self) -> None:
        """목록 변경 후 추천 갱신을 예약한다(디바운스)."""
        if self._recommend_vm is None or not self._recommend_strip.is_expanded:
            return
        # 카드 그리드 뷰(폴더·피드·채널)는 라이브러리 목록이 아니라 씨앗이 어긋난다.
        if self._view_stack.currentIndex() in (_VIEW_FOLDER, _VIEW_FEED, _VIEW_CHANNELS):
            return
        self._recommend_timer.start()

    def _recommend_search_text(self) -> str:
        """스트립을 채울 검색어 — 검색창에 입력된 낱말(없으면 빈 문자열).

        검색어가 있으면 씨앗을 짐작하지 않고 **그 낱말의 YouTube 검색 결과**로
        스트립을 채운다(사용자가 이미 무엇을 찾는지 말했다).
        """
        box = getattr(self, "_search_box", None)   # 화면 조립 중 호출 대비
        return box.text().strip() if box is not None else ""

    def _refresh_recommendations(self, force: bool = False) -> None:
        if self._recommend_vm is None or not self._recommend_strip.is_expanded:
            return
        search_text = self._recommend_search_text()
        if search_text:
            # 검색 모드에서는 씨앗을 넘기지 않는다 — 검색어만이 조회를 결정하므로,
            # 목록이 바뀌어도(예: 스트립에서 한 건 담아 목록이 늘어도) 캐시가
            # 유지되어 같은 검색을 다시 돌리지 않는다.
            titles, channels, tags = (), (), ()
            self._recommend_strip.set_title(f'"{search_text}" YouTube 검색 결과')
        else:
            titles, channels, tags = self._recommend_seeds()
            self._recommend_strip.set_title()
            if not titles and not channels and not tags:
                self._recommend_strip.set_items([])
                self._recommend_strip.set_status("목록이 비어 있어 추천할 기준이 없습니다.")
                self._reveal_recommend_strip(False)
                return
        self._recommend_strip.set_status("")
        # 새 씨앗으로 조회를 시작한다 — 결과가 올 때까지 다시 감춘다(직전 카테고리의
        # 추천이 새 목록의 추천인 것처럼 남아 있지 않도록).
        self._hide_recommend_strip()
        self._recommend_strip.set_more_exhausted(False)
        self._recommend_vm.load(
            seed_titles=titles,
            seed_channels=channels,
            seed_tags=tags,
            search_text=search_text,
            limit=_RECOMMEND_COUNT,
            force=force,
        )

    def _on_recommend_refresh_clicked(self) -> None:
        self._recommend_timer.stop()
        self._refresh_recommendations(force=True)

    def _sync_recommend_sizes(self, expanded: bool, save: bool = True) -> None:
        """스플리터 높이 배분을 접힘 상태에 맞춘다.

        ``setChildrenCollapsible(False)``라 본문을 숨겨도 스플리터가 배분한 높이는
        그대로 남는다(빈 공간). 접을 때 헤더 높이만 남기고, 펼칠 때 직전 높이를
        복원한다.
        """
        sizes = self._centre_splitter.sizes()
        total = sum(sizes) or self._centre_splitter.height()
        header = self._recommend_strip.HEADER_H
        if total <= header:
            return
        if expanded:
            h = min(self._recommend_height, max(total - 120, header))
        else:
            if len(sizes) == 2 and sizes[1] > header + 20:
                self._recommend_height = sizes[1]   # 다음에 펼칠 때 복원할 높이
                if save:
                    _settings.save_setting("recommend_strip_height", int(sizes[1]))
            h = header
        self._centre_splitter.setSizes([max(total - h, 0), h])

    def _on_recommend_expanded(self, expanded: bool) -> None:
        _settings.save_setting("recommend_strip_expanded", expanded)
        self._sync_recommend_sizes(expanded)
        if expanded and self._recommend_strip.count() == 0:
            self._refresh_recommendations()

    def _on_recommend_partial(self, items: list) -> None:
        # 검색 직후의 부분 결과(조회수·게시일 없음)를 먼저 보여준다.
        self._recommend_strip.set_items(items)

    def _on_recommend_items(self, items: list) -> None:
        self._recommend_strip.set_items(items)
        if items:
            self._recommend_strip.set_status("")
        elif self._recommend_search_text():
            self._recommend_strip.set_status("이 검색어로 YouTube에서 찾은 영상이 없습니다.")
        else:
            self._recommend_strip.set_status("추천할 영상을 찾지 못했습니다.")
        self._reveal_recommend_strip(bool(items))
        # 상세화면이 열려 있으면 우측 목록 아래 추천 구역도 함께 갱신한다.
        if self._nav_stack.currentIndex() == 1:
            self._detail_widget.set_recommendations(self._recommend_related_items())

    # ── 미리 받기(무한 스크롤) ───────────────────────────────────────────
    # 스트립이 오른쪽 끝에 닿기 **전에** 다음 묶음을 요청한다. 이미 보여 준 URL을
    # 함께 넘겨야 같은 영상이 두 번 걸리지 않는다(핸들러가 그 목록을 걸러 낸다).

    def _on_recommend_more(self) -> None:
        if self._recommend_vm is None or not self._recommend_ready:
            return   # 첫 조회가 끝나기 전에는 더 받을 것도 없다
        shown = frozenset(
            dto.url for dto in self._recommend_vm.items if getattr(dto, "url", "")
        )
        self._recommend_vm.load_more(exclude_urls=shown)

    def _on_recommend_more_ready(self, items: list) -> None:
        self._recommend_strip.append_items(items)
        # 상세가 열려 있으면 우측 추천 구역도 함께 늘린다(같은 결과를 공유한다).
        if self._nav_stack.currentIndex() == 1:
            self._detail_widget.set_recommendations(self._recommend_related_items())

    def _on_recommend_exhausted(self) -> None:
        """더 나올 것이 없다 — 스크롤할 때마다 같은 검색을 반복하지 않는다."""
        self._recommend_strip.set_more_exhausted(True)

    def _on_recommend_error(self, msg: str) -> None:
        logger.warning("추천 영상 조회 실패: %s", msg)
        self._recommend_strip.set_status("추천을 받지 못했습니다.")
        self._reveal_recommend_strip(False)

    def _reveal_recommend_strip(self, has_items: bool) -> None:
        """조회가 끝난 뒤 스트립을 노출한다.

        결과가 없거나 실패했을 때도 헤더 높이만큼은 띄운다 — 완전히 숨기면
        ⟳(다시 받기)와 접기 토글에 닿을 방법이 사라진다.
        """
        if self._recommend_ready:
            return
        self._recommend_ready = True
        if self._view_stack.currentIndex() in (_VIEW_FOLDER, _VIEW_FEED, _VIEW_CHANNELS):
            return   # 이 화면들은 원래 스트립을 감춘다(목록 뷰로 돌아올 때 표시됨)
        strip = self._recommend_strip
        target = self._recommend_height if (has_items and strip.is_expanded) else strip.HEADER_H
        self._animate_recommend_in(target)

    def _hide_recommend_strip(self) -> None:
        """새 조회를 시작할 때 다시 감춘다 — 준비되면 아래에서 올라온다.

        카테고리를 바꾸면 씨앗이 통째로 달라져 지금 걸린 카드는 새 목록과 무관하다.
        조회가 끝날 때까지 남겨 두면 '이미 준비된 추천'처럼 보이므로, 결과가 올 때까지
        접어 둔다(등장과 같은 연출의 역순).
        """
        if not self._recommend_ready:
            return
        self._recommend_ready = False
        strip = self._recommend_strip
        if strip.isHidden():
            return
        # 사용자가 핸들로 맞춰 둔 높이를 기억했다가 다시 올라올 때 그대로 복원한다.
        sizes = self._centre_splitter.sizes()
        if len(sizes) == 2 and strip.is_expanded and sizes[1] > strip.HEADER_H + 20:
            self._recommend_height = sizes[1]
        self._animate_recommend_out()

    def _animate_recommend_in(self, target: int) -> None:
        """스트립 높이를 0→target으로 늘려 아래에서 올라오는 것처럼 보이게 한다.

        스플리터는 자식의 ``maximumHeight``를 존중하므로(그리고 그 값이
        ``qSmartMinSize``의 상한이 되어 최소 높이도 함께 눌린다) ``setSizes``만으로는
        0에서 시작할 수 없다. 그래서 maximumHeight를 애니메이션하고, 끝나면 원래
        값(_QWIDGET_MAX_H)으로 되돌려 사용자가 핸들로 다시 조절할 수 있게 한다.
        """
        strip = self._recommend_strip
        splitter = self._centre_splitter
        target = max(int(target), strip.HEADER_H)
        # 접히는 중이었다면 그 높이에서 이어 올라간다(0으로 튀지 않게).
        start = 0 if strip.isHidden() else min(max(strip.height(), 0), target)
        self._stop_recommend_anim()
        total = sum(splitter.sizes()) or splitter.height()
        if total <= target + 80:
            # 공간이 부족하면 연출 없이 그냥 편다(찌그러진 애니메이션 방지).
            strip.setVisible(True)
            self._sync_recommend_sizes(strip.is_expanded, save=False)
            return
        strip.setMaximumHeight(start)
        strip.setVisible(True)

        def _done() -> None:
            strip.setMaximumHeight(_QWIDGET_MAX_H)
            splitter.setSizes([max(total - target, 0), target])
            self._recommend_anim = None

        self._start_recommend_anim(start, target, total, _done)

    def _animate_recommend_out(self) -> None:
        """스트립을 아래로 접으며 감춘다(등장 연출의 역순)."""
        strip = self._recommend_strip
        splitter = self._centre_splitter
        start = max(strip.height(), 0)
        self._stop_recommend_anim()
        total = sum(splitter.sizes()) or splitter.height()
        if start <= 0 or total <= start:
            strip.setVisible(False)      # 아직 배치 전 — 연출할 높이가 없다
            return

        def _done() -> None:
            strip.setVisible(False)
            strip.setMaximumHeight(_QWIDGET_MAX_H)
            self._recommend_anim = None

        self._start_recommend_anim(start, 0, total, _done)

    def _start_recommend_anim(self, start: int, end: int, total: int, on_done) -> None:
        """스트립 높이(maximumHeight + 스플리터 배분)를 start→end로 움직인다."""
        strip = self._recommend_strip
        splitter = self._centre_splitter

        def _step(value) -> None:
            h = int(value)
            strip.setMaximumHeight(h)
            splitter.setSizes([max(total - h, 0), h])

        anim = QVariantAnimation(self)
        anim.setStartValue(int(start))
        anim.setEndValue(int(end))
        anim.setDuration(_RECOMMEND_REVEAL_MS)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(_step)
        anim.finished.connect(on_done)
        self._recommend_anim = anim
        anim.start()

    def _stop_recommend_anim(self) -> None:
        anim = self._recommend_anim
        self._recommend_anim = None
        if anim is not None:
            anim.stop()
            self._recommend_strip.setMaximumHeight(_QWIDGET_MAX_H)

    def _recommend_related_items(self) -> list:
        """현재 추천 결과를 상세화면 우측 목록용 RelatedItem으로 변환한다.

        스트립과 같은 결과를 재사용한다 — 상세를 열 때마다 따로 조회하면 네트워크
        비용이 배가 되고, 추천 뷰모델이 하나뿐이라 스트립의 목록까지 뒤엎게 된다.
        """
        if self._recommend_vm is None:
            return []
        return [
            self._related_from_feed(f)
            for f in self._recommend_vm.items[:_DETAIL_RECOMMEND_COUNT]
        ]

    def _on_recommend_to_category(self, url: str) -> None:
        """추천 카드 우클릭 '카테고리에 추가' — 드래그하지 않고도 담을 수 있게.

        ``selected_id``는 **메서드**다 — 예전엔 괄호 없이 써서 항상 참이었고, 카테고리
        id 자리에 바운드 메서드가 그대로 넘어갔다(등록 실패).
        """
        ok, cat_id = self._pick_category()
        if ok:
            self._vm.add_video(url, cat_id)
