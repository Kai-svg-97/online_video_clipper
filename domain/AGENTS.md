<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# domain

## Purpose
순수 도메인 레이어. 비즈니스 로직의 핵심으로, **외부 라이브러리 의존성이 없어야 한다**.
4개의 Bounded Context(library·download·clip·monitoring)와 교차 컨텍스트 공유 추상화(`shared/`)로 구성된다.
모든 상태 변경은 Aggregate Root 메서드를 통해서만 이루어진다.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | 패키지 마커 |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `library/` | [Bounded Context] 핵심 — 영상 라이브러리·카테고리·태그·재생목록 관리 (see `library/AGENTS.md`) |
| `download/` | [Bounded Context] 다운로드 큐 & 이력 (see `download/AGENTS.md`) |
| `clip/` | [Bounded Context] 클립 추출 (see `clip/AGENTS.md`) |
| `monitoring/` | [Bounded Context] 채널 구독 & 모니터링 (see `monitoring/AGENTS.md`) |
| `shared/` | 교차 컨텍스트 공유 포트(Protocol) — application 레이어가 의존 (see `shared/AGENTS.md`) |

## For AI Agents

### Working In This Directory
- **금지**: `import requests`, `import sqlite3`, `import PyQt6` 등 외부·인프라 의존성 import.
- 값객체(Value Object)에는 반드시 `__slots__` 적용 (메모리 최적화 규칙).
- 새 Bounded Context 추가 시: `entities.py`, `value_objects.py`, `aggregates.py`, `repositories.py`, `events.py` 파일을 모두 생성.
- 컨텍스트 간 통신은 Domain Event 또는 Application Service를 통해서만.

### Testing Requirements
- 유닛 테스트: `tests/unit/domain/` — 외부 I/O 없이 순수 Python으로 검증.

### Common Patterns
```python
# Aggregate Root 메서드로만 상태 변경
video_agg.mark_watched()   # ✅
video_agg.video.watched = True  # ❌

# Value Object에 __slots__
@dataclass
class VideoUrl:
    __slots__ = ("value",)
    value: str
```

## Dependencies

### Internal
- 다른 레이어에 의존하지 않음 — 가장 안쪽 레이어.

<!-- MANUAL: -->
