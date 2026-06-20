<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# tests/integration

## Purpose
통합 테스트. 실제 SQLite DB, yt-dlp, ffmpeg 등 인프라에 접근하여 레포지터리·어댑터의 실제 동작을 검증한다.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | 패키지 마커 |
| `test_sqlite_video_repository.py` | `SqliteVideoRepository` CRUD·FTS5·페이지네이션 테스트 |
| `test_channel_subscription.py` | `SqliteChannelRepository` 구독 CRUD 테스트 |
| `test_upsert.py` | upsert(중복 URL 처리) 동작 검증 |

## For AI Agents

### Working In This Directory
- **Mock DB 금지** — 실제 SQLite를 임시 파일로 생성.
- 네트워크가 필요한 테스트는 외부 서비스 가용 여부에 따라 skip 처리.
- 각 테스트는 독립적인 DB 픽스처 사용 (`tmp_path` 또는 인메모리 `:memory:`).

### Common Patterns
```python
@pytest.fixture
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    d.initialize()
    return d
```

## Dependencies

### Internal
- `infrastructure/persistence/` — 레포지터리 구현체
- `infrastructure/persistence/database.py` — Database

<!-- MANUAL: -->
