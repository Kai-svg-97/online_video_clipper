<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# domain/clip

## Purpose
클립 추출 Bounded Context. 로컬 영상 파일에서 시간 범위를 지정해 클립을 생성한다.
`ClipAggregate`가 루트이며, `TimeRange` 값객체로 시작/종료 시각을 관리한다.

## Key Files

| File | Description |
|------|-------------|
| `entities.py` | `Clip` — 소스 영상 ID, 제목, 파일 경로, 썸네일 경로, `TimeRange` |
| `value_objects.py` | `TimeRange` — 시작·종료 밀리초, 유효성 검증 |
| `aggregates.py` | `ClipAggregate` — 클립 생성·수정 메서드 |
| `repositories.py` | `IClipRepository` |
| `events.py` | `ClipCreated` |

## For AI Agents

### Working In This Directory
- `TimeRange`는 밀리초 단위 — `__slots__` 적용.
- 클립은 소스 영상의 로컬 파일 경로가 있어야 추출 가능.

### Key Value Objects
| VO | __slots__ | Purpose |
|----|-----------|---------|
| `TimeRange` | `start_ms, end_ms` | 클립 시간 범위 (ms) |

## Dependencies

### Internal
- 없음

<!-- MANUAL: -->
