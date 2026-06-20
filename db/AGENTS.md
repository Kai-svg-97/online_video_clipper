<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# db

## Purpose
SQLite 데이터베이스 스키마 정의. `infrastructure/persistence/database.py`가 이 파일을 읽어 DB 초기화·마이그레이션을 수행한다.

## Key Files

| File | Description |
|------|-------------|
| `schema.sql` | 전체 테이블 DDL — FTS5 전문검색, 트리거, 인덱스 포함 |

## For AI Agents

### Working In This Directory
- 스키마 변경 시 `infrastructure/persistence/database.py`의 마이그레이션 로직도 함께 수정.
- FTS5 가상 테이블(`videos_fts`)을 통해 제목·설명·채널 전문검색 지원.
- 기존 DB와의 하위 호환성 유지 — 컬럼 추가는 `ALTER TABLE ... ADD COLUMN` 방식(마이그레이션 버전 증가).
- 썸네일은 파일 경로로만 저장 — BLOB 저장 금지.
- `LIMIT/OFFSET` 없는 `SELECT *` 쿼리 금지.

### Common Patterns
```sql
-- FTS5 전문검색
SELECT v.* FROM videos v
JOIN videos_fts f ON v.id = f.rowid
WHERE videos_fts MATCH ?
LIMIT 50 OFFSET 0;

-- 페이지네이션 필수
SELECT * FROM videos ORDER BY created_at DESC LIMIT 50 OFFSET ?;
```

## Dependencies

### Internal
- `infrastructure/persistence/database.py` — 이 스키마를 로드하는 구현체

<!-- MANUAL: -->
