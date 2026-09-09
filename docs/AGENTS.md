<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# docs

## Purpose
개발자·운영자용 외부 문서. **아키텍처 참조**(파일 맵·설계 결정), 플랫폼별 패키징
가이드, 기능 설계 사양 문서가 포함된다.

## Key Files

| File | Description |
|------|-------------|
| `README.md` | 개발자 문서 인덱스 |
| `packaging-windows.md` | Windows 빌드 및 배포 단계별 가이드 |
| `packaging-linux.md` | Linux AppImage 빌드 가이드 |
| `packaging-macos.md` | macOS 빌드 가이드 |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `architecture/` | **아키텍처 참조** — `file-map.md`(파일별 책임)·`design-decisions.md`(설계 근거·실측 함정)·`memory-profiling.md`. 예전에는 CLAUDE.md 안에 있었고(1,106줄/208KB), 매 세션 컨텍스트 부담을 줄이려 분리했다 |
| `superpowers/` | AI 에이전트 작업 플랜·스펙 문서 (자동 생성) |

## For AI Agents

### Working In This Directory
- 패키징 변경 시 해당 플랫폼 문서 업데이트.
- **`architecture/file-map.md`는 코드와 함께 고친다** — 파일을 추가·삭제·이름 변경하면
  즉시 반영한다(CLAUDE.md의 필수 갱신 규칙). 코드보다 먼저 낡는 문서가 되면 세션 시작
  시 1차 참조로 쓸 수 없다.
- **`architecture/design-decisions.md`에는 "왜"와 "실제로 밟은 함정"을 남긴다** —
  실측으로 확인한 사실은 반드시 기록한다(같은 함정을 다시 밟지 않기 위한 문서다).
- `superpowers/` 내 플랜·스펙 파일은 AI 에이전트가 자동 생성 — 수동 편집 시 주의.

<!-- MANUAL: -->
