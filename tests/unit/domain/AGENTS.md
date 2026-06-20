<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# tests/unit/domain

## Purpose
도메인 레이어 유닛 테스트. 엔티티·값객체·애그리거트의 순수 비즈니스 로직을 외부 I/O 없이 검증한다.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | 패키지 마커 |
| `test_library.py` | `Video`, `Category`, `Tag`, `VideoAggregate` 동작 검증 |
| `test_clip.py` | `Clip`, `TimeRange`, `ClipAggregate` 검증 |
| `test_download.py` | `DownloadJob`, `JobStatus`, `DownloadQueueAggregate` 검증 |
| `test_quality_label.py` | 화질 레이블 값객체 파싱·포맷 검증 |
| `test_url_normalization.py` | `VideoUrl` 정규화 로직 — youtu.be, 파라미터 제거 등 엣지케이스 |

## For AI Agents

### Working In This Directory
- 외부 의존성 없음 — `import` 금지 목록: `sqlite3`, `requests`, `yt_dlp`, `PyQt6`.
- `VideoUrl` 정규화 테스트는 다양한 URL 형식 엣지케이스 포함 (`test_url_normalization.py`).
- 새 값객체·애그리거트 추가 시 해당 테스트 파일도 함께 생성.

### Common Patterns
```python
def test_video_url_normalizes_youtu_be():
    url = VideoUrl("https://youtu.be/abc123?si=xyz")
    assert url.value == "https://www.youtube.com/watch?v=abc123"

def test_mark_watched_emits_event():
    agg = VideoAggregate.load(video, tags=[])
    agg.mark_watched()
    events = agg.collect_events()
    assert any(isinstance(e, VideoUpdated) for e in events)
```

## Dependencies

### Internal
- `domain/` — 검증 대상 모듈들

<!-- MANUAL: -->
