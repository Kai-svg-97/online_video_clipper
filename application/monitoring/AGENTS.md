<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# application/monitoring

## Purpose
채널 모니터링 Bounded Context의 애플리케이션 레이어. 채널 구독/해제, 모니터링 규칙 설정, 구독 목록 조회, YouTube 구독 일괄 가져오기를 담당한다.

## Key Files

| File | Description |
|------|-------------|
| `commands.py` | `SubscribeChannelHandler`, `UnsubscribeChannelHandler`, `SetMonitoringRuleHandler`, `ImportYouTubeSubscriptionsHandler` |
| `queries.py` | `GetSubscriptionsHandler` |
| `dtos.py` | `ChannelSubscriptionDTO`, `MonitoringRuleDTO` |

## For AI Agents

### Working In This Directory
- `ImportYouTubeSubscriptionsHandler`: OAuth 우선, fallback으로 yt-dlp 사용.
- 모니터링 폴링은 채널 하나씩 순차 처리 — 전체 피드 메모리 누적 금지.

## Dependencies

### Internal
- `domain/monitoring/` — ChannelMonitorAggregate, IChannelRepository
- `domain/shared/ports.py` — IEventBus, IMediaSource

<!-- MANUAL: -->
