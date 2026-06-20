<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# tests/unit

## Purpose
순수 유닛 테스트. 외부 I/O(파일, DB, 네트워크) 없이 도메인 로직과 애플리케이션 핸들러를 검증한다.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | 패키지 마커 |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `domain/` | 도메인 엔티티·값객체·애그리거트 테스트 (see `domain/AGENTS.md`) |
| `application/` | 애플리케이션 핸들러 테스트 — Mock으로 포트 대체 (see `application/AGENTS.md`) |

## For AI Agents

### Working In This Directory
- 외부 의존성은 Mock으로 대체 — `unittest.mock.MagicMock` 또는 pytest fixtures.
- DB, 파일 시스템, 네트워크 접근 금지.
- 테스트 파일명: `test_<모듈명>.py`.

<!-- MANUAL: -->
