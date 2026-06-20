<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# domain/download

## Purpose
다운로드 Bounded Context. 다운로드 작업 큐와 이력을 관리한다.
`DownloadQueueAggregate`가 인메모리 큐를 소유하며, 완료된 `DownloadJob`은 즉시 제거된다.

## Key Files

| File | Description |
|------|-------------|
| `entities.py` | `DownloadJob` — URL, 제목, 설정, 상태(`JobStatus`), 진행률, 파일 경로 |
| `value_objects.py` | `DownloadSettings`(포맷·화질·경로), `DownloadProgress`(진행률·속도·ETA), `Format`, `Quality` |
| `aggregates.py` | `DownloadQueueAggregate` — 큐 추가·상태변경·취소 |
| `repositories.py` | `IDownloadRepository` — 완료된 이력 영속화 |
| `events.py` | `DownloadStarted`, `DownloadCompleted`, `DownloadFailed` |

## For AI Agents

### Working In This Directory
- `JobStatus`: `PENDING → RUNNING → COMPLETED/FAILED/CANCELLED`
- 완료된 `DownloadJob`은 `DownloadCompleted` 이벤트 발행 직후 큐에서 제거 (메모리 최적화).
- `DownloadProgress`에 `__slots__` 적용 필수 — 진행률 콜백이 매우 자주 호출됨.

### Key Value Objects
| VO | Purpose |
|----|---------|
| `DownloadSettings` | 포맷(mp4/webm), 화질(best/720p 등), 출력 경로 |
| `DownloadProgress` | percent, speed, eta, total_bytes |

## Dependencies

### Internal
- 없음

<!-- MANUAL: -->
