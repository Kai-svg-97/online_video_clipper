"""채널 구독·모니터링 유스케이스 조립."""

from __future__ import annotations

from application.monitoring.commands import (
    ImportYouTubeSubscriptionsHandler,
    SetMonitoringRuleHandler,
    SubscribeChannelHandler,
    UnsubscribeChannelHandler,
)
from application.monitoring.queries import GetSubscriptionsHandler

from bootstrap.context import MonitoringHandlers, Repositories, Services


def build(repos: Repositories, services: Services) -> MonitoringHandlers:
    channel = repos.channel
    subscribe = SubscribeChannelHandler(channel, services.event_bus, services.media_source)
    return MonitoringHandlers(
        subscribe=subscribe,
        unsubscribe=UnsubscribeChannelHandler(channel, services.event_bus),
        set_rule=SetMonitoringRuleHandler(channel),
        get_subscriptions=GetSubscriptionsHandler(channel),
        import_youtube_subscriptions=ImportYouTubeSubscriptionsHandler(
            subscribe, services.media_source, yt_api_provider=services.youtube_api
        ),
    )
