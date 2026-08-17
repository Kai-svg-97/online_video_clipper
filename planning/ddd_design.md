# DDD 설계 문서

## Ubiquitous Language (공통 언어)

| 도메인 용어 | 설명 | 코드 식별자 |
|-------------|------|------------|
| Video | 유튜브 또는 외부 플랫폼의 단일 영상 | `Video` |
| Library | 사용자가 관리하는 영상 컬렉션 전체 | `VideoAggregate` |
| Category | 영상을 분류하는 계층형 그룹 | `Category` |
| Tag | 영상에 붙이는 자유 형식 레이블 | `Tag` |
| Favorite | 즐겨찾기로 표시된 영상 | `Video.favorite` |
| Download Job | 단일 영상/플레이리스트의 다운로드 작업 | `DownloadJob` |
| Download Queue | 실행 중/대기 중인 다운로드 작업 목록 | `DownloadQueueAggregate` |
| Clip | 영상의 특정 구간을 추출한 파일 | `Clip` |
| Time Range | 클립의 시작/종료 시각 | `TimeRange` |
| Channel Subscription | 신규 영상 모니터링을 위한 채널 등록 | `ChannelSubscription` |
| Monitoring Rule | 자동 다운로드 조건 (키워드, 재생시간 등) | `MonitoringRule` |

---

## Bounded Contexts

### 1. Library Context (핵심 도메인)

가장 중요한 도메인. 사용자의 영상 라이브러리 관리.

**Aggregate Root:** `VideoAggregate`

**Entities:**
- `Video` — id, url, title, channel, duration, publishedAt, viewCount, watched, notes, description, createdAt, updatedAt
- `Category` — id, name, parentId (계층 구조)
- `Tag` — id, name

**Value Objects:**
- `VideoUrl` — URL 유효성 검증 포함
- `ChannelInfo` — name, url, channelId
- `Duration` — 초 단위, 포맷 변환 메서드 포함

**Domain Events:**
- `VideoAdded(video_id, url, title)`
- `VideoUpdated(video_id, changed_fields)`
- `VideoDeleted(video_id)`
- `VideoMarkedWatched(video_id)`

**Repository Interface:**
```python
class IVideoRepository(ABC):
    def save(self, video: VideoAggregate) -> None: ...
    def get_by_id(self, video_id: UUID) -> VideoAggregate | None: ...
    def search(self, query: SearchQuery) -> list[VideoAggregate]: ...
    def delete(self, video_id: UUID) -> None: ...
```

**Domain Services:**
- `DuplicateDetectionService` (`domain/library/services.py`) — URL 중복 검출
- `derive_seed_queries(titles, channels, tags, max_queries)` (`domain/library/recommendation.py`)
  — 지금 보고 있는 목록에서 **추천 검색어**를 뽑는 순수 함수. YouTube Data API v3의
  `search.list(relatedToVideoId=)`가 폐지돼 '관련 영상'을 API로 직접 받을 수 없으므로,
  제목 대표 키워드(문서빈도 기준)→최다 태그→최다 채널 순으로 최대 N개 검색어를 만든다.
  I/O가 없어 규칙을 단위 테스트로 고정한다(`tests/unit/domain/test_recommendation.py`).

---

### 2. Download Context

다운로드 큐 및 이력 관리.

**Aggregate Root:** `DownloadQueueAggregate`

**Entities:**
- `DownloadJob` — id, videoId, status (pending/running/done/failed), retryCount, createdAt

**Value Objects:**
- `DownloadSettings` — quality, format, subtitleLangs, includeThumbnail
- `DownloadProgress` — percent, speedBps, etaSec, downloadedBytes
- `Quality` — Enum: 2160p, 1080p, 720p, 480p, 360p, best, worst
- `Format` — Enum: mp4, mkv, webm, mp3, m4a

**Domain Events:**
- `DownloadStarted(job_id, video_id)`
- `DownloadProgressUpdated(job_id, progress)`
- `DownloadCompleted(job_id, video_id, file_path)`
- `DownloadFailed(job_id, video_id, error)`

**Repository Interface:**
```python
class IDownloadRepository(ABC):
    def save_job(self, job: DownloadJob) -> None: ...
    def get_queue(self) -> list[DownloadJob]: ...
    def get_history(self, limit: int) -> list[DownloadJob]: ...
```

---

### 3. Clip Context

ffmpeg 기반 구간 추출.

**Aggregate Root:** `ClipAggregate`

**Entities:**
- `Clip` — id, sourceVideoId, filePath, thumbnailPath, title, createdAt

**Value Objects:**
- `TimeRange` — startSec, endSec, 유효성 검증 (start < end)

**Domain Events:**
- `ClipCreated(clip_id, source_video_id, time_range)`

---

### 4. Monitoring Context

채널 구독 및 신규 영상 자동 감지.

**Aggregate Root:** `ChannelMonitorAggregate`

**Entities:**
- `ChannelSubscription` — id, channelId, channelName, channelUrl, lastCheckedAt

**Value Objects:**
- `MonitoringRule` — keywords: list[str], minDurationSec, maxDurationSec, autoDownload: bool, downloadSettings

**Domain Events:**
- `NewVideoDetected(channel_id, video_url, title)`
- `ChannelSubscribed(channel_id)`
- `ChannelUnsubscribed(channel_id)`

---

### 5. Song Context

노래 영상의 가수·앨범·제목·가사 정보 관리. Library의 Video와 1:1(식별자 = video_id).

**Aggregate Root:** `SongInfoAggregate`

**Entities:**
- `SongInfo` — video_id, is_song, artist, album, song_title, release_year, lyrics_lines, lyrics_language, **`lyrics_offset_ms: int`**(영상별 자막 싱크 보정값, ±30초), source, manual_fields, updated_at.
  **`is_synced` 프로퍼티**는 시각이 있는 줄이 1개 이상인지 알려주며 자막·싱크 기능의 활성 조건이다.
- `LyricsSource` — id, name, provider_key, base_url, enabled, priority (가사 조회 출처 관리형 레지스트리)

**Value Objects:**
- `LyricsLine` — original, translation (비한국어 노래는 원문+한글 병행), **`start_ms: int | None`** — 줄 시작 시각. `None`이면 시간 정보 없음(LRC 싱크 가사 출처에서만 채워짐)
- `SongSourceRef` — name, url (가사를 실제로 가져온 출처)

**Domain Events:**
- `SongInfoUpdated(video_id, changed_fields)`

**Ports (domain/song/ports.py):**
- `ILyricsProvider` — `fetch(artist, title, duration) -> LyricsResult | None` (구현: LRCLIB·Genius·멜론·벅스·지니)
- `ITranslator` — `translate(texts, target='ko') -> list[str]`, `detect_language(text) -> str` (구현: deep-translator)

**핵심 규칙:**
- **노래 판별**: yt-dlp `categories`에 "Music" 또는 `track`/`artist`/`album` 존재 → 자동, "노래로 표시" 토글 → 수동.
- **조회 체인**: `FetchSongInfoHandler`가 활성 `LyricsSource`를 priority 순으로 순회하며 부족한 항목을 채운다. 새 출처 추가 시 자동 편입.
- **후보 목록 검색은 별도 유스케이스**: `SearchLyricsCandidatesHandler`는 활성 출처를 **전부** 훑어 후보(`LyricsCandidateDTO`)를 모으기만 하고 **애그리게이트를 건드리지 않는다**(읽기 전용). 반영은 사용자가 고른 뒤 `ApplyLyricsCandidateHandler`가 `SongInfoAggregate.apply_fetched(force_lyrics=True)`로 수행한다 — "조회"와 "상태 변경"을 분리해, 목록을 띄우는 것만으로 저장된 가사가 바뀌지 않게 한다. 검색 기준값·아티스트 폴백·번역 줄 생성은 체인과 같은 모듈 함수를 공유한다.
- **번역**: 비한국어 가사에 한글 병행. 한국어/번역기 미설치 시 원문만(graceful).
- **수동 편집 보존**: 사용자가 편집한 필드는 `manual_fields`에 기록돼 갱신 시 덮어쓰지 않는다(`apply_fetched`).
- **등록 시 메타데이터만, 가사는 상세 진입 시 조회**: 대량 임포트가 네트워크로 막히지 않게 함(`FetchSongInfoCommand.fetch_lyrics`).
- **자막 싱크 보정은 애그리게이트를 통해서만**: `SongInfoAggregate.set_lyrics_offset(ms)`가 오프셋 변경(±30초 clamp 포함)을 담당한다. `edit_lyrics`(가사 수동 편집)는 줄 수가 같을 때만 기존 타이밍(`start_ms`)을 유지하고, 줄 구성이 바뀌면 신뢰할 수 없으므로 폐기한다.

---

### 6. Sync Context (클라우드 동기화 — 구현 중)

여러 PC 간 라이브러리·미디어를 OneDrive/Google Drive로 동기화한다. **레코드 단위 병합(oplog CRDT)** 방식: 각 변경을 op 로그로 남겨 어느 기기의 추가·수정도 무손실 병합하고, 적용 순서와 무관하게 결정적으로 수렴한다.

**진실원천 불변식:** 클라우드의 마스터 DB는 로그로부터 재생성되는 **파생 스냅샷**일 뿐이며, 각 기기는 **자기 install-id 폴더의 로그에만 append**한다(파일 쓰기 경합 원천 제거).

**Value Objects (domain/sync/value_objects.py):**
- `Op` — 한 건의 변경 연산(op_id·install_id·lamport·entity·nkey·kind·fields·field_lamport·refs·schema_ids). NDJSON 한 줄로 직렬화.
- `OpKind` — UPSERT/DELETE/LINK/UNLINK (present 여부 파생).
- `EntityKey` — (엔티티, 자연키). 로컬 UUID가 아닌 머신 독립 자연키로 식별.
- `ClockEntry` — (lamport, install_id) Lamport 논리시계. 전순서·필드 LWW 판정 기준.
- `SnapshotManifest` — 컴팩션 스냅샷 메타(covered={install:seq}·schema_ids·db_sha256).

**Domain Services (domain/sync/services.py):**
- `OpLogMerger` — op 배치를 현재 레지스터 상태에 병합하는 결정적 reducer(존재 레지스터 + 필드/참조 레지스터, 필드 단위 LWW, tombstone).
- `NaturalKey` 함수군 — `video_key`(정규화 URL)·`category_key`(이름 경로)·`tag_key`·`channel_key`·`link_key`·`origin_key`(자연키 없는 엔티티용 install+uuid).
- `topo_order` — FK 안전 적용 순서(부모→자식).

**Ports (application/sync/ports.py):**
- `ICloudSyncProvider` — 클라우드 blob store(OneDrive/GDrive) 파일 CRUD.
- `IOplogStore` — op 로그 세그먼트 append/read(로컬·원격).
- `ISnapshotStore` — DB 스냅샷 export(VACUUM INTO)/import + 컴팩션.
- `ISecretStore` — OS keyring(DB 밖 — pre-DB pull에서 접근).

**핵심 규칙:**
- **필드 단위 LWW**: 필드별 `(lamport, install_id)` 큰 쪽이 승자 → 서로 다른 필드 동시 편집은 모두 보존.
- **tombstone**: DELETE는 존재 레지스터에 부재 기록. 더 높은 lamport의 재-add만 부활.
- **자연키 식별 + FK 재작성**: 적용 시 자연키→로컬 UUID 매핑(applier, 인프라 단계)으로 중복 제거·참조 해석.
- **스키마 게이트**: op의 `schema_ids`가 로컬 코드가 아는 마이그레이션 집합에 없으면 "앱 업데이트 필요"로 차단.

---

## Context Map

```
┌─────────────────┐     VideoAdded      ┌──────────────────┐
│  Library        │ ─────────────────►  │  Download        │
│  Context        │                     │  Context         │
│  (Core Domain)  │ ◄───────────────── │                  │
└─────────────────┘  DownloadCompleted  └──────────────────┘
        ▲                                        │
        │ NewVideoDetected                       │ DownloadCompleted
        │                                        ▼
┌─────────────────┐                     ┌──────────────────┐
│  Monitoring     │                     │  Clip            │
│  Context        │                     │  Context         │
│                 │                     │                  │
└─────────────────┘                     └──────────────────┘
```

- **Library ↔ Download**: `VideoAdded` 이벤트로 다운로드 트리거 가능; `DownloadCompleted`로 Library의 `video.download` 상태 갱신
- **Monitoring → Library**: `NewVideoDetected` 이벤트로 Library에 Video 자동 추가
- **Library → Clip**: Clip은 Library의 Video를 참조 (sourceVideoId)

---

## Application Services (Use Cases)

### Library
| Command/Query | 설명 |
|---------------|------|
| `AddVideoCommand` | URL로 영상 메타데이터 조회 후 라이브러리에 추가 |
| `ImportPlaylistCommand` | 플레이리스트 URL → 전체 영상 일괄 추가 |
| `UpdateVideoCommand` | 태그, 카테고리, 메모 수정 |
| `DeleteVideoCommand` | 영상 삭제 (파일 삭제 여부 옵션) |
| `SearchVideosQuery` | FTS5 + 복합 필터 검색 |
| `GetVideoByIdQuery` | 상세 정보 조회 |
| `GetRecommendationsQuery` | 현재 목록(제목·채널·태그) 씨앗 → 파생 검색어로 추천 후보 조회 (라이브러리에 이미 있는 영상은 제외) |

### Download
| Command/Query | 설명 |
|---------------|------|
| `StartDownloadCommand` | DownloadSettings로 Job 생성 후 큐 추가 |
| `CancelDownloadCommand` | 진행 중인 Job 취소 |
| `RetryDownloadCommand` | 실패한 Job 재시도 |
| `GetDownloadQueueQuery` | 현재 큐 상태 조회 |

### Clip
| Command/Query | 설명 |
|---------------|------|
| `ExtractClipCommand` | TimeRange 지정 → ffmpeg 구간 추출 |
| `GetClipsQuery` | 특정 Video의 클립 목록 |

### Monitoring
| Command/Query | 설명 |
|---------------|------|
| `SubscribeChannelCommand` | 채널 URL 등록 |
| `SetMonitoringRuleCommand` | 자동 다운로드 조건 설정 |
| `CheckChannelsCommand` | 폴링 실행 (스케줄러 호출) |

---

## 레이어 의존성 규칙

```
GUI (PyQt6 panels + ViewModels)
    ↓  calls
Application (Commands / Queries)
    ↓  calls
Domain (Aggregates, Entities, Value Objects, Repository Interfaces)
    ↑  implements
Infrastructure (SQLite Repositories, yt-dlp, ffmpeg adapters)
```

- `domain/` 은 Python 표준 라이브러리 외 **어떤 외부 패키지도 import 금지**
- `infrastructure/` 는 `domain/` 인터페이스를 구현하되 `gui/` 를 import 금지
- `gui/` 는 `domain/` 을 직접 호출 금지 — 반드시 `application/` 경유
- **`application/` 은 `infrastructure/` 를 import 금지** — 구체 어댑터(EventBus, YtDlpAdapter, FfmpegAdapter) 대신 `domain/shared/ports.py`의 Protocol(`IEventBus`·`IMediaSource`·`IClipExtractor`)에 의존한다. 어댑터는 구조적 타이핑으로 포트를 만족하고, 구체 인스턴스/팩토리는 `main.py`가 주입한다.

### Ports (domain/shared/ports.py)

교차 컨텍스트로 쓰이는 인프라 능력을 도메인 Protocol로 추상화한다:

| Port | 의미 | 구현체 |
| --- | --- | --- |
| `IEventBus` | 인프로세스 도메인 이벤트 디스패처 | `infrastructure.event_bus.EventBus` |
| `IMediaSource` | 동영상 메타데이터·다운로드·재생목록/구독 조회 | `infrastructure.downloader.ytdlp_adapter.YtDlpAdapter` |
| `IClipExtractor` | ffmpeg 클립/썸네일 추출 | `infrastructure.ffmpeg.ffmpeg_adapter.FfmpegAdapter` |

`MediaSourceFactory`(진행률 콜백→`IMediaSource`)는 작업별 진행률 훅이 필요한 다운로드용 팩토리 타입이다.

`IMediaSource`는 `fetch_subscription_feed`(전체 구독 피드)·`fetch_subscribed_channels`(구독 채널 목록, yt-dlp 페이지네이션 적용)에 더해 **`fetch_channel_videos(channel_url, limit, cookie_opts)`** (특정 채널 최신 영상)을 제공한다. 이를 사용하는 application use case는 `application/library/playlist_queries.py`의 **`GetChannelVideosQuery`/`GetChannelVideosHandler`** 이며, 전체 피드 핸들러와 동일하게 `FeedVideoDTO`를 반환해 GUI 카드 렌더링을 공유한다. GUI에서는 라이브러리 좌측 YouTube 트리의 "구독 채널"/"전체 구독 피드" 노드가 `FeedViewModel.load_channel`/`refresh`를 호출해 메인 영역에 피드 카드를 표시한다(별도 구독 피드 메뉴는 제거됨).

또한 `IMediaSource`는 **`fetch_search_videos(query, limit, cookie_opts)`** (YouTube 검색 상위 N건)을 제공한다 — yt-dlp `ytsearchN:` 의사 URL을 쓰므로 쿠키·API 키 없이 동작한다. 이를 사용하는 use case는 `GetRecommendationsQuery`/`GetRecommendationsHandler`이며, 검색어 파생은 위 `derive_seed_queries`(도메인)에 위임하고 핸들러는 후보 수집·중복 제거·라이브러리 제외·API 메타 보강만 담당한다. 반환형은 피드와 동일한 `FeedVideoDTO`라 카드 렌더링을 공유한다. GUI는 `RecommendViewModel`(`gui/view_models/recommend_vm.py`)이 이를 QThread로 감싸고 `RecommendStrip`(영상 목록 아래 접이식 스트립)이 표시한다.

> 예외: `gui/`의 로그인 플로우(`youtube_auth_dialog`, `main_window`)는 `infrastructure.auth`를 직접 참조한다. playwright 구동·쿠키 파일 작성이 본질적으로 인프라라 composition-root 인접의 수용된 경계로 둔다.
