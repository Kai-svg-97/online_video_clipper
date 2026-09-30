"""목록 필터 — 검색어·복합 필터·저장된 검색·카테고리/재생목록/태그·정렬.

필터를 바꾸는 메서드는 상태만 고치고 `_refresh_videos()`(listing.py)로 재조회한다.
"""
from __future__ import annotations

import logging
from uuid import UUID

from application.library.commands import SetCategoryVideoOrderCommand
from application.library.queries import GetCategoryVideoOrderQuery
from gui.text.messages import describe_error

logger = logging.getLogger(__name__)


class FilterMixin:
    """조회 조건을 모아 두고 바뀔 때만 목록을 다시 읽는다."""

    def set_search_text(self, text: str) -> None:
        """검색어를 적용한다. 실제로 바뀐 경우에만 재조회한다.

        IME 조합·공백 입력처럼 strip 결과가 같은 입력이 반복될 때 워커를 새로
        띄우지 않도록 막는다(호출 측은 별도로 디바운스한다).
        """
        text = text.strip()
        if text == self._search_text:
            return
        self._search_text = text
        self._current_page = 0
        self._refresh_videos()

    def set_advanced_filters(
        self,
        *,
        published_from: str = "",
        published_to: str = "",
        channel_name: str = "",
        downloaded: bool | None = None,
        favorite_only: bool = False,
        watched: bool | None = None,
        min_duration_sec: int | None = None,
        max_duration_sec: int | None = None,
    ) -> None:
        """복합 필터를 한 번에 적용한다(바뀐 게 없으면 재조회하지 않는다).

        **하나씩 거는 setter 를 두지 않는다.** 화면에서 여러 칸을 동시에 바꾸는데
        칸마다 조회가 나가면 같은 목록을 네다섯 번 읽는다.
        """
        new_state = (
            published_from, published_to, channel_name, downloaded,
            favorite_only, watched, min_duration_sec, max_duration_sec,
        )
        if new_state == self.advanced_filters:
            return
        (
            self._filter_published_from, self._filter_published_to,
            self._filter_channel, self._filter_downloaded,
            self._filter_favorite_only, self._filter_watched,
            self._filter_min_duration, self._filter_max_duration,
        ) = new_state
        self._current_page = 0
        self._refresh_videos()

    @property
    def advanced_filters(self) -> tuple:
        """지금 걸린 복합 필터 — 화면이 '몇 개 걸렸나'를 표시한다."""
        return (
            self._filter_published_from, self._filter_published_to,
            self._filter_channel, self._filter_downloaded,
            self._filter_favorite_only, self._filter_watched,
            self._filter_min_duration, self._filter_max_duration,
        )

    @property
    def advanced_filter_count(self) -> int:
        """걸린 필터 개수 — 0이면 화면이 배지를 숨긴다."""
        pf, pt, ch, dl, fav, watched, lo, hi = self.advanced_filters
        return sum(
            1 for v in (pf, pt, ch, dl, fav or None, watched, lo, hi)
            if v not in (None, "", False)
        )

    def clear_advanced_filters(self) -> None:
        self.set_advanced_filters()

    # ── 저장된 검색 ───────────────────────────────────────────────
    #
    # 자주 쓰는 조건에 이름을 붙여 두고 한 번에 되부른다. **조건은 프리셋 키로**
    # 저장한다 — "최근 1주"를 날짜 값으로 굳히면 다음 달에 그 주로 얼어붙는다
    # (domain/library/saved_search.py).

    @property
    def can_save_searches(self) -> bool:
        return self._list_saved is not None and self._save_search is not None

    def saved_searches(self) -> list:
        """저장된 검색 목록(기능이 없으면 빈 목록)."""
        return self._list_saved.handle() if self._list_saved else []

    def save_search(self, name: str, **conditions) -> object | None:
        """지금 조건을 이름 붙여 저장한다. 조건이 하나도 없으면 저장하지 않는다.

        이름 중복 처리·빈 조건 거부 같은 **정책은 응용 계층**에 있다 — 나중에 다른
        진입점이 생겨도 같은 규칙을 타게 하기 위해서다.
        """
        if self._save_search is None:
            return None
        from application.library.saved_search_commands import (  # noqa: PLC0415
            SaveSearchCommand,
        )

        return self._save_search.handle(SaveSearchCommand(name=name, **conditions))

    def delete_saved_search(self, search_id: UUID) -> None:
        if self._delete_saved is not None:
            self._delete_saved.handle(search_id)

    def rename_saved_search(self, search_id: UUID, name: str) -> None:
        if self._rename_saved is not None:
            self._rename_saved.handle(search_id, name)

    def set_category_filter(self, category_id: UUID | None, node_key: str | None = None) -> None:
        self._filter_category_id = category_id
        # category_id 없음("로컬"/전체) → 카테고리 영상 전체만 표시
        self._filter_categorized_only = category_id is None
        self._filter_tag_ids = []
        self._filter_playlist_id = None
        self._filter_playlist_video_ids = []
        self._current_page = 0
        if category_id is not None:
            self._refresh_videos(
                on_done=lambda: self._apply_category_order(category_id),
                node_key=node_key,
            )
        else:
            self._refresh_videos(node_key=node_key)

    def _apply_category_order(self, category_id: UUID) -> None:
        """저장된 카테고리 순서가 있으면 영상 목록을 그 순서로 재정렬한다."""
        if self._get_category_order is None or not self._videos:
            return
        try:
            ordered_ids = self._get_category_order.handle(
                GetCategoryVideoOrderQuery(category_id=category_id)
            )
            if not ordered_ids:
                return
            order_map = {vid: pos for pos, vid in enumerate(ordered_ids)}
            unordered_fallback = len(ordered_ids)
            self._videos = sorted(
                self._videos,
                key=lambda dto: order_map.get(dto.id, unordered_fallback),
            )
            self.videos_changed.emit()
        except Exception:
            logger.exception("카테고리 영상 순서 적용 실패")

    def reorder_category_videos(self, category_id: UUID, video_ids: list[UUID]) -> None:
        """카테고리 내 영상 순서를 저장하고 현재 목록에 즉시 반영한다."""
        if self._set_category_order is None:
            return
        try:
            self._set_category_order.handle(
                SetCategoryVideoOrderCommand(category_id=category_id, video_ids=video_ids)
            )
            self._apply_category_order(category_id)
        except Exception as exc:
            self.error_occurred.emit(describe_error(exc))

    @property
    def active_playlist_id(self) -> "UUID | None":
        return self._filter_playlist_id

    def set_playlist_filter(self, playlist_id: UUID | None, node_key: str | None = None) -> None:
        """재생목록 필터 — None이면 필터 해제.

        재생목록 영상 id 조회(GetPlaylistItemsQuery)는 _refresh_videos의 워커 스레드 안에서
        수행해 메인 스레드(클릭)를 막지 않는다.
        """
        self._filter_playlist_id = playlist_id
        self._filter_playlist_video_ids = []
        self._filter_category_id = None
        # 재생목록 뷰는 video_ids로 필터 — 카테고리 미지정 영상도 보여야 하므로 해제
        self._filter_categorized_only = False
        # 태그 필터는 비우지 않는다 — 재생목록∩태그 교집합으로 함께 적용된다.
        self._current_page = 0
        self._refresh_videos(node_key=node_key)

    def set_tag_filter(self, tag_ids: list[UUID]) -> None:
        self._filter_tag_ids = tag_ids
        self._current_page = 0
        self._refresh_videos()

    def set_sort(self, sort_by: str, sort_asc: bool) -> None:
        """정렬 기준을 변경하고 영상 목록을 갱신한다."""
        self._sort_by = sort_by
        self._sort_asc = sort_asc
        self._current_page = 0
        self._refresh_videos()
