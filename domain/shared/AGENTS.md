<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-06-20 | Updated: 2026-06-20 -->

# domain/shared

## Purpose
교차 컨텍스트 공유 추상화. application 레이어가 infrastructure를 직접 참조하지 않도록
`Protocol` 기반 포트(Port) 인터페이스를 정의한다.
infrastructure 어댑터들은 구조적 타이핑으로 이 포트를 만족시킨다.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | 패키지 마커 |
| `ports.py` | `IEventBus`, `IMediaSource`, `IClipExtractor`, `MediaSourceFactory` Protocol 정의 |

## For AI Agents

### Working In This Directory
- 새 인프라 의존이 application 레이어에 필요하면 이 파일에 Protocol 추가.
- Protocol 메서드 시그니처 변경 시 infrastructure 어댑터도 함께 업데이트.
- `MediaSourceFactory = Callable[[Callable], IMediaSource]` — 다운로드 작업별 인스턴스 생성용 팩토리 타입.

### Key Protocols
| Protocol | Implementation | Purpose |
|----------|---------------|---------|
| `IEventBus` | `infrastructure.event_bus.EventBus` | 도메인 이벤트 발행·구독 |
| `IMediaSource` | `infrastructure.downloader.ytdlp_adapter.YtDlpAdapter` | 영상 메타데이터·다운로드·피드 |
| `IClipExtractor` | `infrastructure.ffmpeg.ffmpeg_adapter.FfmpegAdapter` | 클립·썸네일 추출 |

## Dependencies

### Internal
- `domain/clip/value_objects.py` — `TimeRange`
- `domain/download/value_objects.py` — `DownloadSettings`

<!-- MANUAL: -->
