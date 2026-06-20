<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# application/download

## Purpose
다운로드 Bounded Context의 애플리케이션 레이어. 다운로드 시작·취소, 큐/이력 조회, 도메인 이벤트→애플리케이션 콜백 변환을 담당한다.

## Key Files

| File | Description |
|------|-------------|
| `commands.py` | `StartDownloadHandler`, `CancelDownloadHandler` |
| `queries.py` | `GetDownloadQueueHandler`, `GetDownloadHistoryHandler` |
| `event_bridge.py` | `DownloadEventBridge` — 도메인 이벤트를 애플리케이션 레벨 콜백으로 변환 |
| `dtos.py` | `DownloadJobDTO`, `DownloadProgressDTO` |

## For AI Agents

### Working In This Directory
- `StartDownloadHandler`는 `MediaSourceFactory` 콜백을 받아 작업마다 새 `YtDlpAdapter` 인스턴스 생성 — 진행률 콜백 격리.
- `CancelDownloadHandler`: 협조적 취소 훅이 없으면 `terminate()` + `wait()` 패턴 사용.
- `DownloadEventBridge`는 `EventBus`에 구독하여 `DownloadCompleted`/`DownloadFailed` 이벤트를 ViewModel이 처리할 수 있는 형태로 변환.

## Dependencies

### Internal
- `domain/download/` — DownloadQueueAggregate, IDownloadRepository
- `domain/shared/ports.py` — IEventBus, MediaSourceFactory

<!-- MANUAL: -->
