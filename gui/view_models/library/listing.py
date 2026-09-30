"""영상 목록 조회 — 캐시·페이지·동시 워커 상한·로딩 신호.

필터 상태(`_filter_*`·`_search_text`·정렬)는 `filters.py`가 바꾸고, 여기서는 그
상태를 **호출 시점에 캡처해** 워커 스레드에서 조회한다.
"""
from __future__ import annotations

from uuid import UUID

from application.library.playlist_queries import GetPlaylistItemsQuery
from application.library.queries import GetVideosQuery, SearchVideosQuery
from config.settings import DEFAULT_PAGE_SIZE
from gui.view_models.library.workers import _ListVideosWorker

_VIDEO_CACHE_MAX = 20  # 최대 20개 쿼리 결과를 LRU 캐시에 보관


class VideoListMixin:
    """영상 목록을 백그라운드에서 읽어 `_videos`에 싣는다."""

    def load(self) -> None:
        """초기 로드 (categories 제외 — 백그라운드로 이동)."""
        self._current_page = 0
        self._refresh_videos()
        # _refresh_categories() 제거 — load_categories() 백그라운드 호출로 이동 (Phase 2 Step 2)
        self._refresh_tags()
        # refresh_scoped_tags()는 categories가 로드된 후 호출됨

    @property
    def has_more(self) -> bool:
        """더 읽을 쪽이 남았는가 — 화면이 '끝'을 알릴지 판단한다."""
        return self._has_more

    @property
    def is_list_loading(self) -> bool:
        return self._list_inflight > 0

    def load_next_page(self) -> bool:
        """다음 쪽을 이어 붙인다. 읽을 게 없거나 이미 읽는 중이면 False.

        **스스로 막아야 한다.** 무한 스크롤은 바닥 근처에서 신호가 연달아 오므로,
        호출부가 막아 주기를 기대하면 같은 쪽을 여러 번 읽고 목록에 중복이 쌓인다.
        """
        if not self._has_more or self._list_inflight:
            return False
        self._current_page += 1
        self._refresh_videos(append=True)
        return True

    def _cache_key(self) -> str:
        """현재 필터 상태를 문자열 캐시 키로 직렬화한다.

        재생목록은 video_ids가 아니라 재생목록 UUID(_filter_playlist_id)로 식별한다.
        (video_ids 조회를 워커 스레드로 옮겼기 때문에 캐시 키 계산 시점엔 아직 비어 있을 수 있음.)
        """
        cat = str(self._filter_category_id) if self._filter_category_id else ""
        tag = ",".join(sorted(str(t) for t in self._filter_tag_ids))
        pl  = str(self._filter_playlist_id) if self._filter_playlist_id else ""
        # **복합 필터도 키에 넣는다.** 빠뜨리면 필터를 바꿔도 같은 키가 나와
        # 이전 결과가 그대로 다시 표시된다("필터가 안 먹는다"로 보인다).
        adv = (
            f"{self._filter_published_from}~{self._filter_published_to}"
            f"|ch={self._filter_channel}"
            f"|dl={self._filter_downloaded}"
            f"|fav={self._filter_favorite_only}"
            f"|watched={self._filter_watched}"
            f"|dur={self._filter_min_duration}-{self._filter_max_duration}"
        )
        return (
            f"cat={cat}|tag={tag}|pl={pl}"
            f"|sort={self._sort_by}:{self._sort_asc}"
            f"|q={self._search_text}"
            f"|cat_only={self._filter_categorized_only}"
            f"|adv={adv}"
        )

    def _refresh_videos(
        self, append: bool = False, on_done=None, bust_cache: bool = False,
        node_key: str | None = None,
    ) -> None:
        """영상 목록을 백그라운드 스레드에서 비동기로 갱신한다.

        on_done: 갱신 완료 후 메인 스레드에서 호출할 콜백(선택).
        bust_cache: True이면 캐시를 무효화하고 반드시 DB를 재쿼리한다(뮤테이션 호출 시).
        node_key: 트리 노드별 스피너용 키(선택) — 워커 시작/종료 시 loading_key_changed 방출.
        세대 토큰(_list_gen)으로 연속 빠른 전환 시 오래된 결과 UI 반영을 막지만,
        완료된 결과는 항상 캐시에 저장해 나중에 동일 노드 재방문 시 즉시 로드할 수 있다.
        동시 실행 워커는 _max_workers로 제한하고 초과분은 _pending_list 큐에 보관한다.
        """
        if bust_cache:
            self._video_cache.clear()

        # 1쪽을 넘겨 읽은 상태에서는 캐시를 쓰지 않는다 — 캐시는 '첫 쪽'만 담는
        # 구조라, 재조회 결과(여러 쪽 분량)를 같은 키로 넣으면 크기가 뒤섞인다.
        ck = None if (append or self._current_page) else self._cache_key()
        if ck and ck in self._video_cache:
            # 캐시 히트 — 스피너 없이 즉시 표시
            self._videos = list(self._video_cache[ck])
            self._has_more = len(self._videos) >= DEFAULT_PAGE_SIZE
            self.videos_changed.emit()
            if on_done:
                on_done()
            return

        self._list_gen += 1
        gen = self._list_gen

        if append:
            offset, limit = self._current_page * DEFAULT_PAGE_SIZE, DEFAULT_PAGE_SIZE
        else:
            # **이어 붙인 것까지 통째로 다시 읽는다.** 삭제·태그 변경 등은 쪽 번호를
            # 되돌리지 않고 이 함수를 부르는데, 그때 현재 쪽만 읽으면 목록이
            # 151번째부터로 튄다(무한 스크롤을 붙이기 전에는 늘 0쪽이라 안 드러났다).
            offset, limit = 0, DEFAULT_PAGE_SIZE * (self._current_page + 1)
        # 필터 상태를 호출 시점에 캡처 — fetch는 워커 스레드에서 실행된다.
        search_text = self._search_text
        filter_category_id = self._filter_category_id
        filter_playlist_id = self._filter_playlist_id
        explicit_video_ids = list(self._filter_playlist_video_ids)
        tag_ids = list(self._filter_tag_ids)
        categorized_only_base = self._filter_categorized_only
        # 필터도 호출 시점에 캡처한다 — `fetch`는 워커 스레드에서 실행된다.
        advanced = dict(
            published_from=self._filter_published_from,
            published_to=self._filter_published_to,
            channel_name=self._filter_channel,
            downloaded=self._filter_downloaded,
            favorite_only=self._filter_favorite_only,
            watched=self._filter_watched,
            min_duration_sec=self._filter_min_duration,
            max_duration_sec=self._filter_max_duration,
        )
        sort_by, sort_asc = self._sort_by, self._sort_asc

        def fetch() -> list:
            category_ids: list[UUID] = (
                self._resolve_category_ids(filter_category_id)
                if filter_category_id is not None
                else []
            )
            # 재생목록 영상 id 조회를 워커 안에서 수행(메인 스레드 차단 방지)
            video_ids = explicit_video_ids
            if (
                filter_playlist_id is not None
                and not video_ids
                and self._get_playlist_items is not None
            ):
                items = self._get_playlist_items.handle(
                    GetPlaylistItemsQuery(playlist_id=filter_playlist_id, limit=500)
                )
                video_ids = [item.video_id for item in items]
            categorized_only = (
                categorized_only_base
                and filter_category_id is None
                and filter_playlist_id is None
            )
            common = dict(
                category_ids=category_ids,
                tag_ids=tag_ids,
                video_ids=video_ids,
                categorized_only=categorized_only,
                limit=limit,
                offset=offset,
                sort_by=sort_by,
                sort_asc=sort_asc,
                **advanced,
            )
            if search_text:
                return self._search_videos.handle(SearchVideosQuery(text=search_text, **common))
            return self._get_videos.handle(GetVideosQuery(**common))

        self._enqueue_list(fetch, append, gen, ck, on_done, node_key, limit)

    def _enqueue_list(self, fetch, append, gen, ck, on_done, node_key, req_limit) -> None:
        """워커 슬롯이 있으면 즉시 실행, 아니면 큐에 보관(상한 32)."""
        if len(self._list_workers) < self._max_workers:
            self._run_list(fetch, append, gen, ck, on_done, node_key, req_limit)
        else:
            if len(self._pending_list) >= 32:
                self._pending_list.popleft()
            self._pending_list.append(
                (fetch, append, gen, ck, on_done, node_key, req_limit)
            )

    def _run_list(self, fetch, append, gen, ck, on_done, node_key, req_limit) -> None:
        self._list_inflight += 1
        if self._list_inflight == 1:
            self.loading_changed.emit(True)
        if node_key:
            self.loading_key_changed.emit(node_key, True)
        worker = _ListVideosWorker(fetch, append)

        def _on_ok(videos: list, app: bool) -> None:
            # 항상 캐시에 저장 — gen 불일치(구 노드 로딩)여도 결과는 보관해
            # 나중에 동일 노드 재방문 시 즉시 로드할 수 있도록 한다.
            if ck and not app:
                self._video_cache[ck] = list(videos)
                while len(self._video_cache) > _VIDEO_CACHE_MAX:
                    self._video_cache.popitem(last=False)
            if gen != self._list_gen:
                return  # UI 반영은 현재 gen만
            # 요청한 만큼 꽉 채워 왔으면 다음 쪽이 있을 수 있다. 덜 왔으면 끝이다.
            self._has_more = len(videos) >= req_limit
            if app:
                self._videos.extend(videos)
            else:
                self._videos = videos
            self.videos_changed.emit()
            if on_done:
                on_done()

        worker.finished_ok.connect(_on_ok)
        worker.finished_err.connect(self.error_occurred)
        worker.finished.connect(lambda w=worker, k=node_key: self._drain_list(w, k))
        self._list_workers.append(worker)
        self._start_worker(worker)

    def _drain_list(self, worker, node_key) -> None:
        if worker in self._list_workers:
            self._list_workers.remove(worker)
        if node_key:
            self.loading_key_changed.emit(node_key, False)
        self._list_inflight = max(0, self._list_inflight - 1)
        if self._list_inflight == 0:
            self.loading_changed.emit(False)
        while len(self._list_workers) < self._max_workers and self._pending_list:
            fetch, append, gen, ck, on_done, nk, rl = self._pending_list.popleft()
            self._run_list(fetch, append, gen, ck, on_done, nk, rl)
