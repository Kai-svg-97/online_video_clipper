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
- 영상 검색은 **부분 일치(LIKE)** 로 제목·태그·설명·메모·요약·노래·가사를 덮는다.
  `videos_fts`(FTS5)는 검색에 쓰지 않지만, 동기화 병합 후 트리거 발화를 검증하는
  `tests/integration/test_merge_applier.py`가 사용하므로 유지한다.
- 기존 DB와의 하위 호환성 유지 — 컬럼 추가는 `ALTER TABLE ... ADD COLUMN` 방식(마이그레이션 버전 증가).
- 썸네일은 파일 경로로만 저장 — BLOB 저장 금지.
- `LIMIT/OFFSET` 없는 `SELECT *` 쿼리 금지.

### Common Patterns
```sql
-- 부분 일치 검색 (여러 속성을 UNION 으로 덮는다)
SELECT v.* FROM videos v
WHERE v.id IN (
    SELECT id FROM videos WHERE title LIKE ? ESCAPE '\'
    UNION SELECT vt.video_id FROM video_tags vt JOIN tags t ON t.id = vt.tag_id
           WHERE t.name LIKE ? ESCAPE '\'
)
LIMIT 50 OFFSET 0;
-- 가사는 lyrics_json 을 파싱해 비교한다 — JSON 키("o","t")에 LIKE 가 걸려
-- 검색어 o·t 가 모든 노래를 오탐하기 때문이다.

-- 페이지네이션 필수
SELECT * FROM videos ORDER BY created_at DESC LIMIT 50 OFFSET ?;
```

## Dependencies

### Internal
- `infrastructure/persistence/database.py` — 이 스키마를 로드하는 구현체

<!-- MANUAL: -->
