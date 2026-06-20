<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# application/clip

## Purpose
클립 Bounded Context의 애플리케이션 레이어. ffmpeg 기반 클립 추출, 클립 삭제, 클립 목록 조회를 제공한다.

## Key Files

| File | Description |
|------|-------------|
| `commands.py` | `ExtractClipHandler`, `DeleteClipHandler` |
| `queries.py` | `GetClipsHandler` |
| `dtos.py` | `ClipDTO` |

## For AI Agents

### Working In This Directory
- `ExtractClipHandler`는 `IClipExtractor` 포트를 통해 ffmpeg 어댑터를 호출 — 직접 import 금지.
- 클립 추출은 백그라운드 스레드에서 실행되어야 함 — 메인 스레드 블로킹 금지.

## Dependencies

### Internal
- `domain/clip/` — ClipAggregate, IClipRepository
- `domain/shared/ports.py` — IEventBus, IClipExtractor

<!-- MANUAL: -->
