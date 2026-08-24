from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from uuid import UUID

from typing import TYPE_CHECKING, Callable

from application.library.dtos import FeedVideoDTO, PlaylistDTO, PlaylistFolderDTO, PlaylistItemDTO
from domain.library.repositories import IPlaylistFolderRepository, IPlaylistRepository, IVideoRepository
from domain.shared.ports import IMediaSource

if TYPE_CHECKING:
    from application.library.dtos import ChannelInfoDTO
    from domain.monitoring.repositories import IChannelRepository

logger = logging.getLogger(__name__)


def _resolve_yt_api(yt_api, yt_api_provider: "Callable[[], object | None] | None"):
    """저장된 yt_api가 있으면 그대로, 없으면 provider로 지연 해석한다.

    composition root(main.py)가 시작 시 keyring에 접근하지 않도록 provider(예:
    ``_get_youtube_api``)를 대신 넘기면, 실제로 이 핸들러가 호출되는 시점에만
    YouTube 인증이 이뤄진다(lazy binding). yt_api를 직접 넘기는 기존 호출부·
    테스트는 그대로 동작한다.
    """
    if yt_api is not None:
        return yt_api
    if yt_api_provider is not None:
        return yt_api_provider()
    return None


# ── Query 데이터클래스 ───────────────────────────────────────────────────────

@dataclass
class GetPlaylistsQuery:
    source: str | None = None   # None = 전체, "local" | "youtube" = 필터


@dataclass
class GetPlaylistItemsQuery:
    playlist_id: UUID
    limit: int = 50
    offset: int = 0


@dataclass
class GetSubscriptionFeedQuery:
    limit: int = 100
    cookie_opts: dict | None = None


@dataclass
class GetChannelVideosQuery:
    channel_url: str
    limit: int = 30
    cookie_opts: dict | None = None


@dataclass
class GetRecommendationsQuery:
    """현재 보고 있는 목록을 씨앗으로 추천 후보를 조회한다.

    씨앗(제목·채널·태그)은 GUI가 현재 화면의 영상들에서 그대로 넘기고,
    검색어 파생 규칙은 도메인 순수 함수가 담당한다.

    ``search_text``가 있으면(검색창에 낱말이 입력된 상태) 씨앗 대신 그 낱말로
    YouTube를 검색한다 — 목록이 0건이어도 조회한다.
    """

    seed_titles: tuple[str, ...] = ()
    seed_channels: tuple[str, ...] = ()
    seed_tags: tuple[str, ...] = ()
    search_text: str = ""      # 사용자가 입력한 검색어(있으면 씨앗보다 우선)
    limit: int = 24            # 최종 반환 개수 상한
    per_query: int = 12        # 검색어 1개당 후보 수
    max_queries: int = 3
    exclude_urls: frozenset[str] = frozenset()
    cookie_opts: dict | None = None


# ── 핸들러 ──────────────────────────────────────────────────────────────────

class GetPlaylistsHandler:
    def __init__(self, playlist_repo: IPlaylistRepository) -> None:
        self._repo = playlist_repo

    def handle(self, query: GetPlaylistsQuery) -> list[PlaylistDTO]:
        playlists = self._repo.list_all()
        if query.source is not None:
            playlists = [p for p in playlists if p.source == query.source]
        return [
            PlaylistDTO(
                id=p.id,
                title=p.title,
                yt_playlist_id=p.yt_playlist_id,
                source=p.source,
                item_count=p.item_count,
                folder_id=p.folder_id,
                updated_at=p.updated_at.isoformat() if p.updated_at else None,
            )
            for p in playlists
        ]


class GetPlaylistItemsHandler:
    def __init__(
        self,
        playlist_repo: IPlaylistRepository,
        video_repo: IVideoRepository,
    ) -> None:
        self._playlist_repo = playlist_repo
        self._video_repo = video_repo

    def handle(self, query: GetPlaylistItemsQuery) -> list[PlaylistItemDTO]:
        all_items = self._playlist_repo.get_items(query.playlist_id)
        page = all_items[query.offset : query.offset + query.limit]
        result: list[PlaylistItemDTO] = []
        for video_id, position in page:
            agg = self._video_repo.get_by_id(video_id)
            if agg is None:
                continue
            v = agg.video
            result.append(
                PlaylistItemDTO(
                    playlist_id=query.playlist_id,
                    video_id=v.id,
                    position=position,
                    video_title=v.title,
                    thumbnail_path=v.thumbnail_path,
                    channel_name=v.channel.name if v.channel else "",
                    duration_sec=v.duration.seconds if v.duration else None,
                )
            )
        return result


@dataclass
class GetYouTubePlaylistsQuery:
    cookie_opts: dict | None = None


class GetYouTubePlaylistsHandler:
    """인증된 YouTube 계정의 재생목록 목록을 가져온다.

    OAuth API가 설정된 경우 YouTube Data API v3 우선 사용;
    미설정 시 yt-dlp 브라우저 쿠키 fallback.
    """

    def __init__(
        self,
        ytdlp: IMediaSource,
        yt_api=None,
        yt_api_provider: "Callable[[], object | None] | None" = None,
    ) -> None:
        self._ytdlp = ytdlp
        self._yt_api = yt_api
        self._yt_api_provider = yt_api_provider

    def handle(self, query: GetYouTubePlaylistsQuery) -> list[dict]:
        """반환: [{"id": "PLxxx", "title": "...", "count": N}, ...]"""
        yt_api = _resolve_yt_api(self._yt_api, self._yt_api_provider)
        api_exc = None
        if yt_api is not None:
            try:
                return yt_api.list_playlists()
            except Exception as e:
                api_exc = e  # yt-dlp fallback 후 여전히 빈 결과면 이 에러를 전파

        result = self._ytdlp.fetch_user_playlists(query.cookie_opts)
        if result:
            return result

        # yt-dlp도 빈 결과 → API 에러가 있으면 실제 원인 전파
        if api_exc:
            raise api_exc
        return []


class GetSubscriptionFeedHandler:
    """yt-dlp로 구독 피드를 가져오고 라이브러리 등록 여부를 표시."""

    def __init__(
        self,
        ytdlp: IMediaSource,
        video_repo: IVideoRepository,
        channel_repo: "IChannelRepository | None" = None,
        yt_api=None,  # YouTubeApiAdapter | None
        yt_api_provider: "Callable[[], object | None] | None" = None,
    ) -> None:
        self._ytdlp = ytdlp
        self._video_repo = video_repo
        # yt-dlp 플랫 추출은 구독 피드에서 채널 정보를 전혀 주지 않고 영상 ID만 준다.
        # 영상 ID로 YouTube API(videos.list)를 역조회해 채널명을 채우고,
        # API 미설정 시 구독 저장소의 channel_id→채널명 매핑으로 보강한다.
        self._channel_repo = channel_repo
        self._yt_api = yt_api
        self._yt_api_provider = yt_api_provider

    def handle(
        self,
        query: GetSubscriptionFeedQuery,
        on_progress=None,  # Optional[Callable[[list[FeedVideoDTO]], None]]
    ) -> list[FeedVideoDTO]:
        yt_api = _resolve_yt_api(self._yt_api, self._yt_api_provider)
        entries = self._ytdlp.fetch_subscription_feed(
            limit=query.limit,
            cookie_opts=query.cookie_opts,
        )
        # yt-dlp 쿠키 인증 없이 빈 결과인 경우 YouTube API로 fallback
        if not entries and yt_api is not None and self._channel_repo is not None:
            logger.debug("구독 피드 yt-dlp 결과 없음 — YouTube API로 fallback")
            try:
                channel_ids = [
                    agg.subscription.channel_id
                    for agg in self._channel_repo.list_active()
                    if agg.subscription.channel_id
                ]
                if channel_ids:
                    entries = yt_api.get_subscription_feed_via_api(
                        channel_ids, per_channel=3, limit=query.limit
                    )
            except Exception:
                logger.exception("YouTube API 피드 fallback 실패")

        # Phase 1: yt-dlp entries로 부분 DTO 즉시 방출 (views/dates 없음)
        # API 보강이 완료되기 전에 제목·URL·thumbnail_url은 이미 사용 가능.
        if on_progress and entries:
            # channel_id→채널명 매핑 (구독 저장소에서 빠르게 확보 가능)
            name_by_id_fast: dict[str, str] = {}
            if self._channel_repo is not None:
                for agg in self._channel_repo.list_active():
                    sub = agg.subscription
                    if sub.channel_id and sub.channel_name:
                        name_by_id_fast[sub.channel_id] = sub.channel_name
            partial: list[FeedVideoDTO] = []
            for e in entries:
                ch_id_fast = e.get("channel_id") or ""
                partial.append(FeedVideoDTO(
                    url=e.get("url") or "",
                    title=e.get("title") or "",
                    channel_name=e.get("channel_name") or name_by_id_fast.get(ch_id_fast, ""),
                    channel_id=ch_id_fast,
                    thumbnail_url=e.get("thumbnail") or "",
                    thumbnail_path="",
                    published_at="",
                    view_count=None,
                    duration_sec=e.get("duration_sec"),
                    in_library=False,
                    yt_video_id=e.get("yt_video_id") or e.get("id") or "",
                ))
            on_progress(partial)

        # Phase 2: YouTube API 보강
        # 영상 ID → 채널 정보 (YouTube API 역조회)
        ch_by_vid: dict[str, dict] = {}
        if yt_api is not None:
            vids = [e.get("yt_video_id") or e.get("id") or "" for e in entries]
            vids = [v for v in vids if v]
            if vids:
                try:
                    ch_by_vid = yt_api.get_videos_channels(vids)
                except Exception:
                    logger.exception("피드 영상 채널 정보 조회 실패")
        # channel_id → 채널명 (구독 저장소 fallback)
        name_by_id: dict[str, str] = {}
        if self._channel_repo is not None:
            for agg in self._channel_repo.list_active():
                sub = agg.subscription
                if sub.channel_id and sub.channel_name:
                    name_by_id[sub.channel_id] = sub.channel_name
        result: list[FeedVideoDTO] = []
        for e in entries:
            url = e.get("url") or ""
            in_library = self._video_repo.exists_by_url(url) if url else False
            vid = e.get("yt_video_id") or e.get("id") or ""
            api = ch_by_vid.get(vid, {})
            ch_id = e.get("channel_id") or api.get("channel_id") or ""
            ch_name = (
                e.get("channel_name")
                or api.get("channel_name")
                or name_by_id.get(ch_id, "")
            )
            # 플랫 추출은 게시일/조회수/길이를 비워 주므로 API 메타로 보강한다.
            view_count = e.get("view_count")
            if view_count is None:
                view_count = api.get("view_count")
            duration_sec = e.get("duration_sec")
            if duration_sec is None:
                duration_sec = api.get("duration_sec")
            result.append(
                FeedVideoDTO(
                    url=url,
                    title=e.get("title") or "",
                    channel_name=ch_name,
                    channel_id=ch_id,
                    thumbnail_url=e.get("thumbnail") or "",
                    thumbnail_path="",
                    published_at=e.get("published_at") or api.get("published_at") or "",
                    view_count=view_count,
                    duration_sec=duration_sec,
                    in_library=in_library,
                    yt_video_id=e.get("yt_video_id") or "",
                )
            )
        return result


class GetChannelVideosHandler:
    """yt-dlp로 특정 채널의 최신 영상을 가져오고 라이브러리 등록 여부를 표시.

    구독 피드 핸들러와 동일하게 ``FeedVideoDTO``를 반환해 렌더링을 공유한다.
    """

    def __init__(
        self,
        ytdlp: IMediaSource,
        video_repo: IVideoRepository,
        yt_api=None,  # YouTubeApiAdapter | None
        yt_api_provider: "Callable[[], object | None] | None" = None,
    ) -> None:
        self._ytdlp = ytdlp
        self._video_repo = video_repo
        self._yt_api = yt_api
        self._yt_api_provider = yt_api_provider

    def handle(
        self,
        query: GetChannelVideosQuery,
        on_progress=None,  # Optional[Callable[[list[FeedVideoDTO]], None]]
    ) -> list[FeedVideoDTO]:
        yt_api = _resolve_yt_api(self._yt_api, self._yt_api_provider)
        entries = self._ytdlp.fetch_channel_videos(
            channel_url=query.channel_url,
            limit=query.limit,
            cookie_opts=query.cookie_opts,
        )

        # Phase 1: yt-dlp entries로 부분 DTO 즉시 방출 (views/dates 없음)
        if on_progress and entries:
            partial: list[FeedVideoDTO] = []
            for e in entries:
                partial.append(FeedVideoDTO(
                    url=e.get("url") or "",
                    title=e.get("title") or "",
                    channel_name=e.get("channel_name") or "",
                    channel_id=e.get("channel_id") or "",
                    thumbnail_url=e.get("thumbnail") or "",
                    thumbnail_path="",
                    published_at="",
                    view_count=None,
                    duration_sec=e.get("duration_sec"),
                    in_library=False,
                    yt_video_id=e.get("yt_video_id") or e.get("id") or "",
                ))
            on_progress(partial)

        # Phase 2: 플랫 추출은 게시일/조회수를 비워 주므로 영상 ID로 API 메타를 보강한다.
        meta_by_vid: dict[str, dict] = {}
        if yt_api is not None:
            vids = [e.get("yt_video_id") or e.get("id") or "" for e in entries]
            vids = [v for v in vids if v]
            if vids:
                try:
                    meta_by_vid = yt_api.get_videos_channels(vids)
                except Exception:
                    logger.exception("채널 영상 메타데이터 조회 실패")
        result: list[FeedVideoDTO] = []
        for e in entries:
            url = e.get("url") or ""
            in_library = self._video_repo.exists_by_url(url) if url else False
            vid = e.get("yt_video_id") or e.get("id") or ""
            meta = meta_by_vid.get(vid, {})
            view_count = e.get("view_count")
            if view_count is None:
                view_count = meta.get("view_count")
            duration_sec = e.get("duration_sec")
            if duration_sec is None:
                duration_sec = meta.get("duration_sec")
            result.append(
                FeedVideoDTO(
                    url=url,
                    title=e.get("title") or "",
                    channel_name=e.get("channel_name") or meta.get("channel_name") or "",
                    channel_id=e.get("channel_id") or meta.get("channel_id") or "",
                    thumbnail_url=e.get("thumbnail") or "",
                    thumbnail_path="",
                    published_at=e.get("published_at") or meta.get("published_at") or "",
                    view_count=view_count,
                    duration_sec=duration_sec,
                    in_library=in_library,
                    yt_video_id=e.get("yt_video_id") or "",
                )
            )
        return result


class GetRecommendationsHandler:
    """현재 목록에서 파생한 검색어로 YouTube 추천 후보를 모은다.

    ``search.list(relatedToVideoId=)``가 폐지돼 '관련 영상'을 직접 받을 수 없으므로
    (자세한 배경은 ``domain/library/recommendation.py``), 목록 대표 검색어 몇 개로
    yt-dlp 검색을 돌려 후보를 합친다. 검색은 쿠키·API 키가 없어도 동작한다.

    이미 라이브러리에 있는 영상은 **결과에서 제외**한다 — 이 목록의 목적이
    '아직 없는 영상을 찾아 담기'이기 때문이다. 구독 피드 핸들러들과 같은
    ``FeedVideoDTO``를 반환해 카드 렌더링을 공유한다.

    ``query.search_text``가 있으면 씨앗을 짐작하지 않고 그 낱말로만 검색한다
    (검색창에 키워드를 넣으면 스트립이 그 키워드의 YouTube 검색 결과가 된다).
    """

    def __init__(
        self,
        ytdlp: IMediaSource,
        video_repo: IVideoRepository,
        yt_api=None,  # YouTubeApiAdapter | None
        yt_api_provider: "Callable[[], object | None] | None" = None,
    ) -> None:
        self._ytdlp = ytdlp
        self._video_repo = video_repo
        self._yt_api = yt_api
        self._yt_api_provider = yt_api_provider

    def handle(
        self,
        query: GetRecommendationsQuery,
        on_progress=None,  # Optional[Callable[[list[FeedVideoDTO]], None]]
    ) -> list[FeedVideoDTO]:
        from domain.library.recommendation import derive_seed_queries  # noqa: PLC0415

        queries = derive_seed_queries(
            titles=query.seed_titles,
            channels=query.seed_channels,
            tags=query.seed_tags,
            max_queries=query.max_queries,
            search_text=query.search_text,
        )
        if not queries:
            logger.debug("추천 씨앗 검색어가 없어 조회를 건너뛴다")
            return []

        # ── 후보 수집 (검색어별 실패는 격리) ──
        entries: list[dict] = []
        seen_ids: set[str] = set()
        seen_urls: set[str] = {u for u in query.exclude_urls if u}
        for q in queries:
            try:
                found = self._ytdlp.fetch_search_videos(
                    query=q, limit=query.per_query, cookie_opts=query.cookie_opts
                )
            except Exception:
                logger.exception("추천 검색 실패 (검색어=%r)", q)
                continue
            for e in found:
                url = e.get("url") or ""
                vid = e.get("yt_video_id") or e.get("id") or ""
                if not url or url in seen_urls or (vid and vid in seen_ids):
                    continue
                if self._video_repo.exists_by_url(url):
                    continue   # 이미 라이브러리에 있는 영상은 추천하지 않는다
                seen_urls.add(url)
                if vid:
                    seen_ids.add(vid)
                entries.append(e)
            if len(entries) >= query.limit:
                break
        entries = entries[: query.limit]
        if not entries:
            logger.info("추천 후보 없음 (검색어=%s)", queries)
            return []

        # Phase 1: 검색 결과만으로 부분 DTO 즉시 방출 (조회수·게시일 없음)
        if on_progress:
            on_progress([self._to_dto(e, {}) for e in entries])

        # Phase 2: 플랫 추출이 비워 둔 게시일/조회수를 영상 ID로 API 보강
        meta_by_vid: dict[str, dict] = {}
        yt_api = _resolve_yt_api(self._yt_api, self._yt_api_provider)
        if yt_api is not None:
            vids = [e.get("yt_video_id") or e.get("id") or "" for e in entries]
            vids = [v for v in vids if v]
            if vids:
                try:
                    meta_by_vid = yt_api.get_videos_channels(vids)
                except Exception:
                    logger.exception("추천 영상 메타데이터 조회 실패")

        result = [
            self._to_dto(e, meta_by_vid.get(e.get("yt_video_id") or e.get("id") or "", {}))
            for e in entries
        ]
        logger.info("추천 %d건 (검색어=%s)", len(result), queries)
        return result

    @staticmethod
    def _to_dto(e: dict, meta: dict) -> FeedVideoDTO:
        view_count = e.get("view_count")
        if view_count is None:
            view_count = meta.get("view_count")
        duration_sec = e.get("duration_sec")
        if duration_sec is None:
            duration_sec = meta.get("duration_sec")
        return FeedVideoDTO(
            url=e.get("url") or "",
            title=e.get("title") or "",
            channel_name=e.get("channel_name") or meta.get("channel_name") or "",
            channel_id=e.get("channel_id") or meta.get("channel_id") or "",
            thumbnail_url=e.get("thumbnail") or "",
            thumbnail_path="",
            published_at=e.get("published_at") or meta.get("published_at") or "",
            view_count=view_count,
            duration_sec=duration_sec,
            in_library=False,   # 라이브러리에 있는 항목은 위에서 걸러졌다
            yt_video_id=e.get("yt_video_id") or e.get("id") or "",
        )


@dataclass
class GetSubscribedChannelInfosQuery:
    # (channel_id, channel_name, channel_url) 튜플 목록 — GUI가 구독 목록에서 전달
    channels: list[tuple[str, str, str]]


class GetSubscribedChannelInfosHandler:
    """구독 채널 카드 정보 조회.

    YouTube API(channels.list)로 아바타·구독자수·영상수를 보강한다.
    API 미설정/실패 시에도 입력한 모든 채널을 이름·URL만으로 반환한다(graceful).
    """

    def __init__(
        self,
        yt_api=None,  # YouTubeApiAdapter | None
        yt_api_provider: "Callable[[], object | None] | None" = None,
    ) -> None:
        self._yt_api = yt_api
        self._yt_api_provider = yt_api_provider

    @staticmethod
    def _norm_channel_id(raw: str) -> str:
        """https://www.youtube.com/channel/UCxxx 형식이면 UCxxx만 추출."""
        m = re.search(r"/channel/(UC[A-Za-z0-9_-]+)", raw)
        return m.group(1) if m else raw

    def handle(self, query: GetSubscribedChannelInfosQuery) -> list["ChannelInfoDTO"]:
        from application.library.dtos import ChannelInfoDTO  # noqa: PLC0415

        yt_api = _resolve_yt_api(self._yt_api, self._yt_api_provider)

        # DB에 URL 형식으로 저장된 channel_id를 UCxxx 형식으로 정규화
        norm_map = {cid: self._norm_channel_id(cid) for cid, _, _ in query.channels}

        info_by_id: dict[str, dict] = {}
        if yt_api is not None:
            ids = list({norm for norm in norm_map.values() if norm.startswith("UC")})
            if ids:
                try:
                    info_by_id = yt_api.list_channels(ids)
                except Exception:
                    logger.exception("구독 채널 정보 조회 실패")
                    info_by_id = {}

        # 채널별 최신 업로드 영상의 게시 시각(업로드 재생목록 첫 항목)
        latest_by_id: dict[str, str] = {}
        if yt_api is not None and info_by_id:
            uploads = {
                cid: v.get("uploads_playlist_id", "")
                for cid, v in info_by_id.items()
                if v.get("uploads_playlist_id")
            }
            if uploads:
                try:
                    latest_by_id = yt_api.get_latest_upload_dates(uploads)
                except Exception:
                    logger.exception("채널 최신 업로드 시각 조회 실패")

        result: list[ChannelInfoDTO] = []
        seen_ids: set[str] = set()
        for cid, name, url in query.channels:
            norm_id = norm_map.get(cid, cid)
            if norm_id in seen_ids:
                continue  # 같은 UC ID 중복(URL 형식 + UCxxx 동시 저장) 건너뜀
            seen_ids.add(norm_id)
            info = info_by_id.get(norm_id, {})
            result.append(
                ChannelInfoDTO(
                    channel_id=norm_id,
                    channel_name=info.get("title") or name,
                    channel_url=url,
                    thumbnail_url=info.get("thumbnail") or "",
                    subscriber_count=info.get("subscriber_count"),
                    video_count=info.get("video_count"),
                    latest_video_published_at=latest_by_id.get(norm_id) or None,
                )
            )
        # 정렬: 최신 영상 게시일 내림차순(최신 먼저), 게시일 없는 채널은 뒤로.
        # 파이썬 정렬은 안정적이라, 먼저 이름 오름차순으로 정렬해 두면 게시일이
        # 같거나 없는 채널끼리는 이름 오름차순이 유지된다.
        result.sort(key=lambda c: c.channel_name.lower())
        result.sort(key=lambda c: c.latest_video_published_at or "", reverse=True)
        return result


@dataclass
class GetPlaylistFoldersQuery:
    source: str | None = None   # None = 전체, "local" | "youtube" = 필터


class GetPlaylistFoldersHandler:
    def __init__(self, folder_repo: IPlaylistFolderRepository) -> None:
        self._repo = folder_repo

    def handle(self, query: GetPlaylistFoldersQuery) -> list[PlaylistFolderDTO]:
        folders = self._repo.list_by_source(query.source)
        return [PlaylistFolderDTO(id=f.id, name=f.name, source=f.source) for f in folders]
