<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# online_video_clipper

## Purpose
YouTube 및 1000+ 사이트의 온라인 영상을 다운로드·스크랩·관리하는 Python GUI 데스크톱 앱.
**Domain-Driven Design(DDD)** 기반의 레이어드 아키텍처로 구성되며,
`gui → application → domain ← infrastructure` 의존성 규칙을 엄격히 준수한다.

## Key Files

| File | Description |
|------|-------------|
| `main.py` | Composition root — 모든 어댑터·핸들러·ViewModel을 조립하고 `MainWindow`를 실행 |
| `requirements.txt` | 런타임 의존성 (PyQt6, yt-dlp, ffmpeg-python, google-api-python-client 등) |
| `requirements-dev.txt` | 개발/빌드 전용 의존성 (ruff, pytest, pyinstaller) |
| `CLAUDE.md` | AI 에이전트용 프로젝트 지침 (DDD 규칙, 코딩 제약, 커밋 규칙 등) |
| `DESIGN.md` | 시각적 디자인 레퍼런스 |
| `README.md` | 프로젝트 소개 및 사용법 |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `domain/` | 순수 도메인 레이어 — 엔티티·값객체·애그리거트·도메인이벤트 (see `domain/AGENTS.md`) |
| `application/` | 애플리케이션 레이어 — CQRS 커맨드·쿼리 핸들러 (see `application/AGENTS.md`) |
| `infrastructure/` | 인프라 레이어 — SQLite·yt-dlp·ffmpeg·YouTube API 구현체 (see `infrastructure/AGENTS.md`) |
| `gui/` | 프레젠테이션 레이어 — PyQt6 MVVM (see `gui/AGENTS.md`) |
| `config/` | 사용자 설정 (경로·테마·다운로드 옵션) (see `config/AGENTS.md`) |
| `utils/` | 공통 유틸리티 (리소스 경로, 로깅) (see `utils/AGENTS.md`) |
| `db/` | SQLite 스키마 SQL (see `db/AGENTS.md`) |
| `tests/` | 유닛·통합·GUI 스모크 테스트 (see `tests/AGENTS.md`) |
| `assets/` | 아이콘 등 번들 정적 자산 (see `assets/AGENTS.md`) |
| `packaging/` | PyInstaller spec + Inno Setup/AppImage 레시피 (see `packaging/AGENTS.md`) |
| `scripts/` | Windows/Linux 빌드 스크립트 (see `scripts/AGENTS.md`) |
| `planning/` | DDD 설계 문서·PRD·패키징 계획 (see `planning/AGENTS.md`) |
| `docs/` | 패키징 가이드 및 사양 문서 (see `docs/AGENTS.md`) |

## For AI Agents

### Working In This Directory
- `main.py`는 **Composition Root** — 의존성 주입의 유일한 진입점이다. 새 핸들러·어댑터를 추가하면 이 파일에서만 조립한다.
- 레이어 경계를 절대 무너뜨리지 말 것: `domain/`은 외부 라이브러리 import 금지, `application/`은 infrastructure 직접 import 금지.
- GUI 파일 수정 후 반드시 `/verify` 스킬로 앱 실행 확인.
- 새 기능·컨텍스트 추가 시 `CLAUDE.md`의 문서 업데이트 규칙 테이블을 따를 것.

### Testing Requirements
```bash
pytest                  # 전체
pytest tests/unit/      # 유닛만
pytest tests/integration/  # 통합만
pytest tests/gui/ -v    # GUI 스모크
```

### Common Patterns
- 새 bounded context = `domain/<ctx>/` + `application/<ctx>/` + `infrastructure/` 구현체 + `gui/view_models/<ctx>_vm.py` 순서로 작성.
- 팩토리 콜백 주입: 다운로드처럼 작업별 인스턴스가 필요하면 `lambda cb: Adapter(on_progress=cb)` 형태로 `main.py`에서 주입.
- 모든 백그라운드 작업은 `QThread` + Qt 시그널 방식.

## Dependencies

### External
- `PyQt6` — GUI 프레임워크
- `yt-dlp` — 영상 다운로드·메타데이터
- `ffmpeg-python` — 클립 추출·포맷 변환
- `google-api-python-client`, `google-auth-oauthlib` — YouTube Data API v3
- `PyYAML` — 설정 영속화
- `requests`, `beautifulsoup4` — HTTP 스크래핑
- `playwright` — JS 렌더링 필요한 스크래핑·OAuth 쿠키 추출

<!-- MANUAL: -->
