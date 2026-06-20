<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# domain/monitoring

## Purpose
채널 구독 & 모니터링 Bounded Context. 구독 채널을 추적하고, 키워드·길이 필터 규칙을 기반으로 신규 영상을 감지한다.

## Key Files

| File | Description |
|------|-------------|
| `entities.py` | `ChannelSubscription` — 채널 ID·URL·이름, `MonitoringRule`, 활성화 여부, 마지막 체크 시각 |
| `value_objects.py` | `MonitoringRule` — 키워드 필터, 최소/최대 길이 필터 |
| `aggregates.py` | `ChannelMonitorAggregate` |
| `repositories.py` | `IChannelRepository` |
| `events.py` | `NewVideoDetected` |

## For AI Agents

### Working In This Directory
- 모니터링 폴링은 채널 하나씩 순차 처리 — 전체 피드를 메모리에 누적하지 말 것.
- `MonitoringRule` 기본값 = 모든 영상 허용 (키워드 없음, 길이 제한 없음).

## Dependencies

### Internal
- 없음

<!-- MANUAL: -->
