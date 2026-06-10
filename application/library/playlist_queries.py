from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from typing import TYPE_CHECKING

from application.library.dtos import FeedVideoDTO, PlaylistDTO, PlaylistFolderDTO, PlaylistItemDTO
from domain.library.repositories import IPlaylistFolderRepository, IPlaylistRepository, IVideoRepository
from domain.shared.ports import IMediaSource

if TYPE_CHECKING:
    from application.library.dtos import ChannelInfoDTO
    from domain.monitoring.repositories import IChannelRepository

logger = logging.getLogger(__name__)


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

    def __init__(self, ytdlp: IMediaSource, yt_api=None) -> None:
        self._ytdlp = ytdlp
        self._yt_api = yt_api

    def handle(self, query: GetYouTubePlaylistsQuery) -> list[dict]:
        """반환: [{"id": "PLxxx", "title": "...", "count": N}, ...]"""
        api_exc = None
        if self._yt_api is not None:
            try:
                return self._yt_api.list_playlists()
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
    ) -> None:
        self._ytdlp = ytdlp
        self._video_repo = video_repo
        # yt-dlp 플랫 추출은 구독 피드에서 채널 정보를 전혀 주지 않고 영상 ID만 준다.
        # 영상 ID로 YouTube API(videos.list)를 역조회해 채널명을 채우고,
        # API 미설정 시 구독 저장소의 channel_id→채널명 매핑으로 보강한다.
        self._channel_repo = channel_repo
        self._yt_api = yt_api

    def handle(self, query: GetSubscriptionFeedQuery) -> list[FeedVideoDTO]:
        entries = self._ytdlp.fetch_subscription_feed(
            limit=query.limit,
            cookie_opts=query.cookie_opts,
        )
        # 영상 ID → 채널 정보 (YouTube API 역조회)
        ch_by_vid: dict[str, dict] = {}
        if self._yt_api is not None:
            vids = [e.get("yt_video_id") or e.get("id") or "" for e in entries]
            vids = [v for v in vids if v]
            if vids:
                try:
                    ch_by_vid = self._yt_api.get_videos_channels(vids)
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
            result.append(
                FeedVideoDTO(
                    url=url,
                    title=e.get("title") or "",
                    channel_name=ch_name,
                    channel_id=ch_id,
                    thumbnail_url=e.get("thumbnail") or "",
                    thumbnail_path="",
                    published_at=e.get("published_at") or "",
                    view_count=e.get("view_count"),
                    duration_sec=e.get("duration_sec"),
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
    ) -> None:
        self._ytdlp = ytdlp
        self._video_repo = video_repo

    def handle(self, query: GetChannelVideosQuery) -> list[FeedVideoDTO]:
        entries = self._ytdlp.fetch_channel_videos(
            channel_url=query.channel_url,
            limit=query.limit,
            cookie_opts=query.cookie_opts,
        )
        result: list[FeedVideoDTO] = []
        for e in entries:
            url = e.get("url") or ""
            in_library = self._video_repo.exists_by_url(url) if url else False
            result.append(
                FeedVideoDTO(
                    url=url,
                    title=e.get("title") or "",
                    channel_name=e.get("channel_name") or "",
                    channel_id=e.get("channel_id") or "",
                    thumbnail_url=e.get("thumbnail") or "",
                    thumbnail_path="",
                    published_at=e.get("published_at") or "",
                    view_count=e.get("view_count"),
                    duration_sec=e.get("duration_sec"),
                    in_library=in_library,
                    yt_video_id=e.get("yt_video_id") or "",
                )
            )
        return result


@dataclass
class GetSubscribedChannelInfosQuery:
    # (channel_id, channel_name, channel_url) 튜플 목록 — GUI가 구독 목록에서 전달
    channels: list[tuple[str, str, str]]


class GetSubscribedChannelInfosHandler:
    """구독 채널 카드 정보 조회.

    YouTube API(channels.list)로 아바타·구독자수·영상수를 보강한다.
    API 미설정/실패 시에도 입력한 모든 채널을 이름·URL만으로 반환한다(graceful).
    """

    def __init__(self, yt_api=None) -> None:  # YouTubeApiAdapter | None
        self._yt_api = yt_api

    def handle(self, query: GetSubscribedChannelInfosQuery) -> list["ChannelInfoDTO"]:
        from application.library.dtos import ChannelInfoDTO  # noqa: PLC0415

        info_by_id: dict[str, dict] = {}
        if self._yt_api is not None:
            ids = [cid for cid, _, _ in query.channels if cid.startswith("UC")]
            if ids:
                try:
                    info_by_id = self._yt_api.list_channels(ids)
                except Exception:
                    logger.exception("구독 채널 정보 조회 실패")
                    info_by_id = {}

        result: list[ChannelInfoDTO] = []
        for cid, name, url in query.channels:
            info = info_by_id.get(cid, {})
            result.append(
                ChannelInfoDTO(
                    channel_id=cid,
                    channel_name=info.get("title") or name,
                    channel_url=url,
                    thumbnail_url=info.get("thumbnail") or "",
                    subscriber_count=info.get("subscriber_count"),
                    video_count=info.get("video_count"),
                )
            )
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
