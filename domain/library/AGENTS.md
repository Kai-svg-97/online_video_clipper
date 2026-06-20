<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# domain/library

## Purpose
핵심 Bounded Context — 영상 라이브러리 관리. 영상, 카테고리, 태그, 재생목록, 재생목록 폴더 도메인 모델을 정의한다.
`VideoAggregate`가 루트이며, 모든 영상 상태 변경은 이를 통해서만 이루어진다.

## Key Files

| File | Description |
|------|-------------|
| `entities.py` | `Video`, `Category`, `Tag`, `Playlist`, `PlaylistFolder` 엔티티 |
| `value_objects.py` | `VideoUrl`(URL 정규화·추출), `Duration`(초 단위), `ChannelInfo`(채널 ID·이름·URL) |
| `aggregates.py` | `VideoAggregate` — 루트, `mark_watched()`, `assign_category()` 등 상태 변경 메서드 |
| `repositories.py` | `IVideoRepository` 인터페이스 + `SearchQuery` 데이터클래스 |
| `services.py` | 도메인 서비스 — 중복 탐지 등 단일 애그리거트로 처리 불가한 로직 |
| `events.py` | `VideoAdded`, `VideoUpdated`, `VideoDeleted` 도메인 이벤트 |

## For AI Agents

### Working In This Directory
- `VideoUrl`은 YouTube URL을 `https://www.youtube.com/watch?v=ID` 형태로 정규화 — `youtu.be`, `list=`, `si=` 파라미터 제거.
- `extract_youtube_video_id(url)`는 `value_objects.py`에 정의 — application/infrastructure 어디서든 재사용 가능.
- 새 엔티티 추가 시 `repositories.py`에 해당 인터페이스 메서드도 추가.
- `description` 필드는 상세 조회(`GetVideoByIdQuery`) 시에만 로드 — 목록 쿼리에서 제외.

### Common Patterns
```python
# URL 정규화는 VideoUrl 생성자가 자동 처리
url = VideoUrl("https://youtu.be/abc123?si=xyz")
# → "https://www.youtube.com/watch?v=abc123"

# Aggregate를 통한 상태 변경
agg = VideoAggregate.load(video, tags=[])
agg.mark_watched()
events = agg.collect_events()
```

### Key Value Objects
| VO | __slots__ | Purpose |
|----|-----------|---------|
| `VideoUrl` | `_value` | URL 정규화 + 검증 |
| `Duration` | `_seconds` | 초 단위 저장, `formatted()` 반환 |
| `ChannelInfo` | `name, url, channel_id` | 채널 식별자 묶음 |

## Dependencies

### Internal
- 없음 — 도메인 레이어는 다른 레이어에 의존하지 않음

<!-- MANUAL: -->
