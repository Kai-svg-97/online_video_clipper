<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# application

## Purpose
애플리케이션 레이어. CQRS 패턴으로 구성된 커맨드(Command)·쿼리(Query) 핸들러 모음.
도메인 포트(`domain/shared/ports.py`)에만 의존하며, infrastructure 구체 클래스를 직접 import하지 않는다.
각 Bounded Context별로 `commands.py`와 `queries.py`로 분리된다.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | 패키지 마커 |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `library/` | 영상·카테고리·태그·재생목록·스마트폴더 커맨드/쿼리 핸들러 (see `library/AGENTS.md`) |
| `download/` | 다운로드 시작·취소·이력 조회 핸들러 + 이벤트 브릿지 (see `download/AGENTS.md`) |
| `clip/` | 클립 추출·삭제·조회 핸들러 (see `clip/AGENTS.md`) |
| `monitoring/` | 채널 구독·규칙·구독 피드 핸들러 (see `monitoring/AGENTS.md`) |

## For AI Agents

### Working In This Directory
- `IEventBus`, `IMediaSource`, `IClipExtractor` 포트에만 의존 — infrastructure import 금지.
- 작업별 진행률 콜백이 필요하면 `MediaSourceFactory` 콜백을 생성자에 주입.
- 핸들러 생성자는 `main.py`(Composition Root)에서만 조립한다.
- DTO(`dtos.py`)는 레이어 경계를 넘기는 데이터 계약 — domain 엔티티를 직접 반환하지 말 것.

### Testing Requirements
- `tests/unit/application/` — Mock으로 포트 대체하여 핸들러 로직만 검증.

### Common Patterns
```python
# 핸들러는 포트 인터페이스만 받는다
class StartDownloadHandler:
    def __init__(self, queue: IDownloadQueue, repo: IDownloadRepo,
                 make_downloader: MediaSourceFactory, bus: IEventBus): ...

# 쿼리 결과는 DTO로 반환
@dataclass
class VideoDTO:
    id: str
    title: str
    ...
```

## Dependencies

### Internal
- `domain/` — 엔티티·값객체·애그리거트·레포지터리 인터페이스
- `domain/shared/ports.py` — IEventBus, IMediaSource, IClipExtractor

<!-- MANUAL: -->
