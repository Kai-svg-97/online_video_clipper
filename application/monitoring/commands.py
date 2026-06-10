from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from domain.monitoring.aggregates import ChannelMonitorAggregate
from domain.monitoring.repositories import IChannelRepository
from domain.monitoring.value_objects import MonitoringRule
from domain.shared.ports import IEventBus

logger = logging.getLogger(__name__)


@dataclass
class SubscribeChannelCommand:
    channel_url: str
    rule: MonitoringRule | None = None
    # 사전 식별된 채널 정보(예: YouTube API 구독 목록). 주어지면 yt-dlp 메타데이터
    # 조회를 생략해 일괄 가져오기 시 채널당 네트워크 호출을 없앤다.
    channel_id: str | None = None
    channel_name: str | None = None


@dataclass
class UnsubscribeChannelCommand:
    subscription_id: UUID


@dataclass
class SetMonitoringRuleCommand:
    subscription_id: UUID
    rule: MonitoringRule


class SubscribeChannelHandler:
    def __init__(
        self,
        repo: IChannelRepository,
        event_bus: IEventBus,
        ytdlp_adapter=None,
    ) -> None:
        self._repo = repo
        self._bus = event_bus
        self._ytdlp = ytdlp_adapter

    def handle(self, cmd: SubscribeChannelCommand) -> ChannelMonitorAggregate:
        channel_id = cmd.channel_id or cmd.channel_url
        channel_name = cmd.channel_name or cmd.channel_url

        # id가 주어지지 않은 수동 URL 구독에서만 메타데이터를 1회 조회한다.
        # 일괄 가져오기는 API/yt-dlp가 이미 id·name을 제공하므로 조회를 건너뛴다.
        if cmd.channel_id is None and self._ytdlp:
            try:
                info = self._ytdlp.fetch_metadata(cmd.channel_url)
                channel_id = info.get("channel_id") or info.get("uploader_id") or cmd.channel_url
                channel_name = (
                    cmd.channel_name
                    or info.get("uploader")
                    or info.get("channel")
                    or cmd.channel_url
                )
            except Exception:
                logger.exception("채널 메타데이터 조회 실패")

        # 멱등성: 이미 구독 중인 채널이면 기존 구독을 그대로 반환한다.
        # (channel_id는 UNIQUE이므로 새 UUID로 재삽입하면 IntegrityError가 난다.)
        existing = self._repo.get_by_channel_id(channel_id)
        if existing is not None:
            return existing

        agg = ChannelMonitorAggregate.create(
            channel_id=channel_id,
            channel_name=channel_name,
            channel_url=cmd.channel_url,
            rule=cmd.rule,
        )
        self._repo.save(agg)
        self._bus.publish_all(agg.pull_events())
        return agg


class UnsubscribeChannelHandler:
    def __init__(self, repo: IChannelRepository, event_bus: IEventBus) -> None:
        self._repo = repo
        self._bus = event_bus

    def handle(self, cmd: UnsubscribeChannelCommand) -> None:
        agg = self._repo.get_by_id(cmd.subscription_id)
        if agg is None:
            return
        agg.deactivate()
        self._repo.save(agg)
        self._bus.publish_all(agg.pull_events())


class SetMonitoringRuleHandler:
    def __init__(self, repo: IChannelRepository) -> None:
        self._repo = repo

    def handle(self, cmd: SetMonitoringRuleCommand) -> None:
        agg = self._repo.get_by_id(cmd.subscription_id)
        if agg is None:
            raise KeyError(f"Subscription {cmd.subscription_id} not found")
        agg.update_rule(cmd.rule)
        self._repo.save(agg)


@dataclass
class ImportYouTubeSubscriptionsCommand:
    cookie_opts: dict | None = None


class ImportYouTubeSubscriptionsHandler:
    """YouTube 구독 채널을 일괄 모니터링 등록.

    OAuth API가 설정된 경우 YouTube Data API v3 우선 사용;
    미설정 시 yt-dlp 브라우저 쿠키 fallback.
    """

    def __init__(
        self,
        subscribe_handler: SubscribeChannelHandler,
        ytdlp_adapter=None,
        yt_api=None,   # YouTubeApiAdapter | None
    ) -> None:
        self._subscribe = subscribe_handler
        self._ytdlp = ytdlp_adapter
        self._yt_api = yt_api

    def handle(self, cmd: ImportYouTubeSubscriptionsCommand) -> int:
        # OAuth API 우선
        if self._yt_api is not None:
            try:
                channels = self._yt_api.list_subscriptions()
            except Exception:
                logger.exception("구독 채널 목록 API 조회 실패")
                channels = []
        elif self._ytdlp is not None:
            channels = self._ytdlp.fetch_subscribed_channels(cmd.cookie_opts)
        else:
            return 0

        count = 0
        for ch in channels:
            url = ch.get("url") or ""
            if not url:
                continue
            try:
                self._subscribe.handle(
                    SubscribeChannelCommand(
                        channel_url=url,
                        channel_id=ch.get("id") or None,
                        channel_name=ch.get("name") or None,
                    )
                )
                count += 1
            except Exception:
                logger.exception("채널 구독 등록 실패")  # 중복 구독 등 오류 무시
        return count
