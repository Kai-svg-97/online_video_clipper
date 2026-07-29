<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# infrastructure/persistence

## Purpose
SQLite 기반 영속성 레이어. DB 연결·WAL 설정·스키마 마이그레이션과 각 Bounded Context별 레포지터리 구현체를 제공한다.

## Key Files

| File | Description |
|------|-------------|
| `database.py` | `Database` — SQLite 연결, WAL 모드, `db/schema.sql` 로드, 버전별 마이그레이션 |
| `sqlite_video_repository.py` | `SqliteVideoRepository` — `IVideoRepository` 구현, FTS5 전문검색 포함 |
| `sqlite_download_repository.py` | `SqliteDownloadRepository` — 완료된 다운로드 이력 영속화 |
| `sqlite_clip_repository.py` | `SqliteClipRepository` — 클립 CRUD |
| `sqlite_channel_repository.py` | `SqliteChannelRepository` — 구독 채널 CRUD |
| `sqlite_playlist_repository.py` | `SqlitePlaylistRepository`, `SqlitePlaylistFolderRepository` — 재생목록·폴더 |

## For AI Agents

### Working In This Directory
- **`.fetchall()` 금지** — 커서 이터레이터로 처리.
- 모든 목록 쿼리에 `LIMIT/OFFSET` 필수 (기본 50).
- 썸네일은 파일 경로만 저장 — BLOB 금지.
- 스키마 변경 시 `database.py` 마이그레이션 로직도 함께 수정 (버전 증가).
- `description`, `notes` 필드는 `GetVideoDetailHandler` 호출 시에만 로드.
- `SqliteVideoRepository.search()`는 부분 일치(LIKE + ESCAPE) UNION 서브쿼리를 쓴다.
  가사는 `lyrics_json`을 파싱해 비교한다 — JSON 키(`"o"`,`"t"`)에 LIKE 가 걸려
  검색어 `o`·`t` 가 모든 노래를 오탐하기 때문이다.
- 일치 속성은 `match_fields_for(video_ids, text)`가 현재 페이지에만 실행해 반환한다.

### Common Patterns
```python
# 커서 이터레이터 — fetchall() 대신
with self._db.conn() as conn:
    cursor = conn.execute("SELECT * FROM videos LIMIT ? OFFSET ?", (limit, offset))
    return [self._row_to_dto(row) for row in cursor]

# WAL 모드 — database.py가 초기화 시 설정
conn.execute("PRAGMA journal_mode=WAL")
```

## Dependencies

### Internal
- `domain/library/repositories.py`, `domain/download/repositories.py` 등 — 인터페이스
- `config/settings.py` — `DATABASE_PATH`

### External
- `sqlite3` (stdlib) — FTS5 포함

<!-- MANUAL: -->
