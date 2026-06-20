<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# infrastructure

## Purpose
인프라 레이어. 도메인 레포지터리 인터페이스의 구체 구현체와 외부 서비스 어댑터 모음.
SQLite 영속성, yt-dlp 다운로더, ffmpeg 클립 추출, YouTube OAuth/API, 인프로세스 이벤트 버스를 제공한다.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | 패키지 마커 |
| `event_bus.py` | 동기식 인프로세스 도메인 이벤트 디스패처 (`IEventBus` 구현) |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `persistence/` | SQLite 레포지터리 구현체 + DB 연결·마이그레이션 (see `persistence/AGENTS.md`) |
| `downloader/` | yt-dlp 래퍼 — 메타데이터·다운로드·피드 조회 (`IMediaSource` 구현) (see `downloader/AGENTS.md`) |
| `ffmpeg/` | ffmpeg 클립 추출·썸네일 생성 어댑터 (`IClipExtractor` 구현) (see `ffmpeg/AGENTS.md`) |
| `youtube/` | YouTube OAuth 토큰 관리 + Data API v3 래퍼 (see `youtube/AGENTS.md`) |
| `auth/` | 브라우저 프로필 탐지 + Playwright OAuth 쿠키 추출 (see `auth/AGENTS.md`) |

## For AI Agents

### Working In This Directory
- 어댑터는 **구조적 타이핑**으로 포트를 만족 — `IMediaSource` 등을 상속하지 않아도 된다.
- 새 어댑터 추가 시 `domain/shared/ports.py`의 프로토콜 시그니처를 확인 후 구현.
- 레포지터리는 반드시 `LIMIT/OFFSET` 페이지네이션 사용 (기본 50개).
- `.fetchall()` 금지 — 커서 이터레이션 사용.
- 모든 예외는 `logger.exception(...)` 으로 흔적 남길 것 (조용한 삼킴 금지).

### Testing Requirements
- `tests/integration/` — 실제 SQLite DB에 접근하는 통합 테스트.
- Mock DB 사용 금지 (prod 마이그레이션 불일치 방지).

### Common Patterns
```python
# 구조적 타이핑 — 상속 없이 프로토콜 만족
class YtDlpAdapter:
    def fetch_metadata(self, url: str) -> dict: ...
    def download(self, url: str, settings: DownloadSettings, ...) -> Path: ...
    # IMediaSource 메서드만 구현하면 됨
```

## Dependencies

### Internal
- `domain/` — 레포지터리 인터페이스, 값객체
- `domain/shared/ports.py` — 포트 프로토콜

### External
- `sqlite3` (stdlib) — FTS5 전문검색 포함
- `yt-dlp` — 1000+ 사이트 다운로드
- `ffmpeg-python` — 클립 추출
- `google-api-python-client` — YouTube Data API
- `playwright` — OAuth 쿠키 추출

<!-- MANUAL: -->
