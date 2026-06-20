<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# tests

## Purpose
전체 테스트 스위트. 유닛·통합·GUI 스모크 세 계층으로 분리된다.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | 패키지 마커 |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `unit/` | 순수 도메인·애플리케이션 로직 유닛 테스트 (외부 I/O 없음) (see `unit/AGENTS.md`) |
| `integration/` | SQLite·yt-dlp·ffmpeg 등 실제 인프라에 접근하는 통합 테스트 (see `integration/AGENTS.md`) |
| `gui/` | PyQt6 GUI 스모크 테스트 — pytest-qt 사용 (see `gui/AGENTS.md`) |

## For AI Agents

### Working In This Directory
- **통합 테스트에서 Mock DB 금지** — 실제 SQLite 사용 (prod 마이그레이션 불일치 방지).
- 유닛 테스트는 외부 I/O 없이 순수 Python만 사용.
- GUI 스모크 테스트는 패널 초기화·표시 여부만 확인 — 상세 기능 테스트 불필요.

### Testing Requirements
```bash
pytest                      # 전체
pytest tests/unit/ -v       # 유닛만
pytest tests/integration/ -v  # 통합만 (네트워크 필요할 수 있음)
pytest tests/gui/ -v        # GUI 스모크 (디스플레이 필요)
```

## Dependencies

### External
- `pytest` — 테스트 프레임워크
- `pytest-qt` — PyQt6 GUI 테스트 픽스처

<!-- MANUAL: -->
