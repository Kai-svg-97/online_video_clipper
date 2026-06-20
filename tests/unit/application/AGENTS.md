<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# tests/unit/application

## Purpose
애플리케이션 핸들러 유닛 테스트. Mock으로 포트(IEventBus, IMediaSource 등)를 대체하여 핸들러의 오케스트레이션 로직만 검증한다.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | 패키지 마커 |
| `test_refresh_handler.py` | `RefreshCategoryMetadataHandler` — LIMIT/OFFSET 청크 처리 및 이벤트 발행 검증 |

## For AI Agents

### Working In This Directory
- 포트는 `unittest.mock.MagicMock` 또는 간단한 Fake 객체로 대체.
- 실제 DB나 네트워크 호출 금지.
- 새 핸들러 추가 시 대응하는 테스트 파일(`test_<handler_name>.py`) 생성.

### Common Patterns
```python
def test_start_download_handler_creates_job():
    mock_bus = MagicMock(spec=IEventBus)
    mock_repo = MagicMock(spec=IDownloadRepository)
    mock_factory = lambda cb: MagicMock(spec=IMediaSource)
    handler = StartDownloadHandler(queue, mock_repo, mock_factory, mock_bus)
    handler.handle(StartDownloadCommand(url="https://..."))
    mock_bus.publish_all.assert_called_once()
```

## Dependencies

### Internal
- `application/` — 검증 대상 핸들러들
- `domain/shared/ports.py` — Mock 스펙

<!-- MANUAL: -->
