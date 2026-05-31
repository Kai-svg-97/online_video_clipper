from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from domain.monitoring.aggregates import ChannelMonitorAggregate
from domain.monitoring.repositories import IChannelRepository
from domain.monitoring.value_objects import MonitoringRule
from infrastructure.event_bus import EventBus


@dataclass
class SubscribeChannelCommand:
    channel_url: str
    rule: MonitoringRule | None = None


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
        event_bus: EventBus,
        ytdlp_adapter=None,
    ) -> None:
        self._repo = repo
        self._bus = event_bus
        self._ytdlp = ytdlp_adapter

    def handle(self, cmd: SubscribeChannelCommand) -> ChannelMonitorAggregate:
        channel_id = cmd.channel_url
        channel_name = cmd.channel_url

        if self._ytdlp:
            try:
                info = self._ytdlp.fetch_metadata(cmd.channel_url)
                channel_id = info.get("channel_id") or info.get("uploader_id") or cmd.channel_url
                channel_name = info.get("uploader") or info.get("channel") or cmd.channel_url
            except Exception:
                pass

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
    def __init__(self, repo: IChannelRepository, event_bus: EventBus) -> None:
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
                self._subscribe.handle(SubscribeChannelCommand(channel_url=url))
                count += 1
            except Exception:
                pass  # 중복 구독 등 오류 무시
        return count
