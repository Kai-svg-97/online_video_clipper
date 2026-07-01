# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Python-based GUI desktop application for downloading and scraping online videos (YouTube and other platforms), with rich browsing and search capabilities. Built following **Domain-Driven Design (DDD)** methodology.

---

## Development Methodology: DDD

All development follows DDD principles:

- **Ubiquitous Language** — use domain terms consistently in code, comments, and docs (see `planning/ddd_design.md`)
- **Bounded Contexts** — each domain is isolated; cross-context communication via Domain Events or Application Services only
- **Layered Architecture** — strict dependency rule: `gui → application → domain ← infrastructure`
- **Aggregates** — only modify state through Aggregate Root methods; never directly mutate child entities
- **Repository Pattern** — `domain/` defines interfaces; `infrastructure/` provides concrete implementations
- **Domain Events** — side effects (e.g., UI refresh, file ops) are triggered by events, not inline logic

> When adding a feature: define the domain model first (entities, value objects, aggregates), then application use cases, then infrastructure, then GUI.

---

## Tech Stack

| Layer | Library | Notes |
| ----- | ------- | ----- |
| GUI | `PyQt6` | Main thread only; MVVM pattern with ViewModels |
| Downloader | `yt-dlp` | Supports 1000+ sites |
| HTTP / Scraping | `requests`, `beautifulsoup4` | Static pages |
| JS-heavy scraping | `playwright` | Preferred over Selenium |
| Video processing | `ffmpeg-python` | Merging, trimming, format conversion |
| Local storage | SQLite via `sqlite3` (stdlib) | FTS5 for full-text search |
| YouTube API | `google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2` | OAuth 2.0 인증 + YouTube Data API v3 |
| Config | `PyYAML` | 테마 등 사용자 설정 영속화 |
| Dev / Test | `pytest`, `pytest-qt` | GUI 스모크 테스트 포함 (`tests/gui/`) |
| Dev / Build | `ruff`, `pyinstaller` | 린트·포맷·패키징 |

---

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py

# Run tests
pytest

# Run unit tests only
pytest tests/unit/

# Run integration tests only
pytest tests/integration/

# Run GUI smoke tests only
pytest tests/gui/ -v

# Lint
ruff check .

# Format
ruff format .
```

---

## Architecture (DDD Layered)

```text
online_video_clipper/
├── main.py                          # Entry point
├── requirements.txt
├── requirements-dev.txt             # PyInstaller, ruff, pytest (not bundled)
├── config/
│   └── settings.py                  # User preferences; uses platformdirs for data paths
├── utils/
│   ├── resources.py                 # get_resource_path() — handles dev vs. PyInstaller bundle
│   └── logging_config.py            # setup_logging() — 회전 파일(LOG_DIR/app.log)+콘솔 로거 (진입점에서 1회 호출)
│
├── bin/                             # Bundled binaries (not in VCS — downloaded by build script)
│   ├── ffmpeg.exe                   # Windows build
│   └── ffmpeg                       # Linux build
│
├── assets/                          # Icons, images bundled into the package
│   └── icon.ico
│
├── packaging/
│   ├── online_video_clipper.spec    # PyInstaller spec (Windows + Linux)
│   ├── installer.iss                # Inno Setup script (Windows .exe installer)
│   └── appimage/                    # AppImage recipe (Linux)
│
├── scripts/
│   ├── build_windows.ps1            # PowerShell: runs PyInstaller → Inno Setup
│   └── build_linux.sh               # Bash: runs PyInstaller → appimagetool
│
├── domain/                          # Pure domain layer — NO external dependencies
│   ├── shared/                      # 교차 컨텍스트 공유 추상화
│   │   └── ports.py                 # IEventBus·IMediaSource·IClipExtractor(Protocol) — application이 의존하는 포트
│   ├── library/                     # [Bounded Context] Core: video library management
│   │   ├── entities.py              # Video, Category, Tag
│   │   ├── value_objects.py         # VideoUrl, Duration, Timestamp, ChannelInfo
│   │   ├── aggregates.py            # VideoAggregate (root)
│   │   ├── repositories.py          # IVideoRepository (interface)
│   │   ├── services.py              # Domain services (e.g., duplicate detection)
│   │   └── events.py                # VideoAdded, VideoUpdated, VideoDeleted
│   │
│   ├── download/                    # [Bounded Context] Download queue & history
│   │   ├── entities.py              # DownloadJob
│   │   ├── value_objects.py         # DownloadSettings, DownloadProgress, Format, Quality
│   │   ├── aggregates.py            # DownloadQueueAggregate (root)
│   │   ├── repositories.py          # IDownloadRepository
│   │   ├── services.py
│   │   └── events.py                # DownloadStarted, DownloadCompleted, DownloadFailed
│   │
│   ├── clip/                        # [Bounded Context] Clip extraction
│   │   ├── entities.py              # Clip
│   │   ├── value_objects.py         # TimeRange
│   │   ├── aggregates.py            # ClipAggregate (root)
│   │   ├── repositories.py          # IClipRepository
│   │   └── events.py                # ClipCreated
│   │
│   └── monitoring/                  # [Bounded Context] Channel subscription & monitoring
│       ├── entities.py              # ChannelSubscription
│       ├── value_objects.py         # MonitoringRule (keyword/duration filter)
│       ├── aggregates.py            # ChannelMonitorAggregate (root)
│       ├── repositories.py          # IChannelRepository
│       └── events.py                # NewVideoDetected
│
├── application/                     # Application layer — use cases (commands & queries)
│   ├── library/
│   │   ├── commands.py              # AddVideo, UpdateVideo, DeleteVideo, ImportPlaylist
│   │   └── queries.py               # GetVideos, SearchVideos, GetVideoById
│   ├── download/
│   │   ├── commands.py              # StartDownload, CancelDownload, RetryDownload
│   │   └── queries.py               # GetDownloadQueue, GetDownloadHistory
│   ├── clip/
│   │   ├── commands.py              # ExtractClip, DeleteClip
│   │   └── queries.py               # GetClips
│   └── monitoring/
│       ├── commands.py              # SubscribeChannel, UnsubscribeChannel, SetMonitoringRule
│       └── queries.py               # GetSubscriptions
│
├── infrastructure/                  # Concrete implementations (invert dependencies)
│   ├── persistence/
│   │   ├── database.py              # SQLite 연결 + WAL 설정 + 스키마 마이그레이션
│   │   ├── sqlite_video_repository.py
│   │   ├── sqlite_download_repository.py
│   │   ├── sqlite_clip_repository.py
│   │   ├── sqlite_channel_repository.py
│   │   └── sqlite_playlist_repository.py  # 재생목록 + 폴더 저장소
│   ├── downloader/
│   │   └── ytdlp_adapter.py         # yt-dlp 래퍼 — domain.shared.ports.IMediaSource를 구조적으로 만족
│   ├── ffmpeg/
│   │   └── ffmpeg_adapter.py        # ffmpeg wrapper for clip extraction
│   ├── browser/
│   │   └── gemini_extractor.py      # Playwright 기반 YouTube Gemini AI 요약 추출기 (QThread에서만 호출)
│   ├── auth/
│   │   └── youtube_auth.py          # 브라우저 프로필 탐지 + Netscape 쿠키 추출 (playwright 로그인)
│   ├── youtube/
│   │   ├── oauth_adapter.py         # OAuth 2.0 토큰 발급/갱신
│   │   └── youtube_api_adapter.py   # YouTube Data API v3 래퍼 (requests.Session)
│   └── event_bus.py                 # In-process event dispatcher
│
├── gui/                             # Presentation layer (PyQt6, MVVM)
│   ├── main_window.py               # 루트 윈도우, 사이드바 네비게이션(라이브러리·다운로드·채널 모니터링·통계), 패널 스택 — 구독 피드는 라이브러리 좌측 트리로 통합됨
│   ├── panels/
│   │   ├── library_panel.py         # 썸네일 그리드 + 카테고리/재생목록 트리 + 상세뷰 + YouTube 트리의 "구독 채널"/"전체 구독 피드" 노드. 영상 카드 **단일 클릭→상세화면**(미리보기 패널 제거됨, Ctrl/Shift 클릭은 다중선택 유지). 피드/채널 카드 단일 클릭→`_open_stream_detail`(스트리밍 상세). `_open_detail`/`_open_stream_detail`이 컨텍스트별 연관영상(RelatedItem)을 구성해 상세화면에 전달, 연관영상 클릭은 `_on_related_item_selected`로 재진입. **인기/전체 태그 패널(`_tag_section`)은 트리 하단에 일반 세로 레이아웃(`nav_container`)으로 쌓고 카테고리 선택 시에만 표시**(`_set_popular_tags_visible(True/False)`가 섹션 전체를 토글). 재생목록·폴더·섹션루트·피드·채널 선택 시엔 숨겨 트리가 그 공간을 차지한다. (QSplitter로 묶으면 자식 가시성 토글이 레이아웃 thrash→프리징을 유발해 일반 레이아웃으로 교체함.) **트리 노드 클릭 시 상세 화면이면 먼저 목록으로 복귀**(`_leave_detail_if_open`). **뒤로/앞으로 가기는 화면 단위 스냅샷 기반**(`_capture_screen`→`_nav_history`(뒤로)/`_nav_future`(앞으로), `_go_back`/`_go_forward`/`_restore_screen`): kind(category/playlist/folder/feed_all/channel/channels_root)+상세 payload까지 저장해 직전/다음 화면을 정확히 복원(분류 간 교차·상세→상세 연관영상 체인 포함). 마우스 ‹=`_go_back`, ›=`_go_forward`(eventFilter), 새 분기 이동 시 `_push_nav_state`가 `_nav_future` 비움. 복원 시 `_PlaylistPanel.select_snapshot`로 좌측 트리 강조·브레드크럼을 동기화(시그널 차단해 재실행 방지). 상세 뒤로가기 버튼도 `_on_detail_back_requested`→히스토리 복원. "전체 구독 피드"/개별 채널 클릭→피드 카드 그리드(_VIEW_FEED), "구독 채널" 노드 클릭→채널 아바타 카드 그리드(_VIEW_CHANNELS). **좌측 채널 노드는 이름 오름차순 정렬**, 채널 카드는 핸들러가 최신 업로드 내림차순으로 정렬해 전달. 연관영상 meta에도 `_relative_time`으로 등록 시점 표기(로컬 ISO·피드 ISO/YYYYMMDD 모두). (메인 패널, ~5000줄 — 분할 검토 대상. `_PreviewPane`는 미사용 잔존)
│   │   ├── download_panel.py        # 다운로드 큐 + 완료 이력 탭 (영상 파일만 표시·완료/실패 배지)
│   │   ├── feed_panel.py            # 피드 카드 부품(_FeedGrid·_FeedCard: 썸네일 좌하단 채널 배지·리사이즈 reflow, **단일 클릭→`video_clicked`(FeedVideoDTO) 방출**, 인라인 추가버튼 제거·우클릭 메뉴로 일원화) + 채널 카드 부품(_ChannelGrid·_ChannelCard: 아바타·구독자/영상수에 더해 **"최근 영상 N일 전"** 라벨=`latest_video_published_at`) + 연관영상 행에서 재사용하는 `_RoundedThumbLabel`·`_ThumbLoader` 정의 — library_panel/video_detail_panel이 재사용. `_FeedCard`·`_ChannelCard`는 `_relative_time`(YYYYMMDD·ISO·`Z` 처리)로 등록 시점을 상대시간 표기. (구버전 FeedPanel 컨테이너는 더 이상 사이드바 메뉴로 노출되지 않음)
│   │   ├── monitoring_panel.py      # 채널 구독 & 모니터링 규칙 관리
│   │   ├── stats_panel.py           # 라이브러리 통계 대시보드
│   │   ├── video_detail_panel.py    # YouTube 시청 페이지형 상세화면 — 좌(큰 플레이어+제목/메타/태그/챕터/설명+하단 탭:다운로드·메모·클립·요약) | 우(`_RelatedList` 연관영상). `load`(로컬)/`load_stream`(스트리밍, 메모·클립·요약 비활성) + `set_related`. 설명에서 `_parse_chapters`로 타임스탬프 추출→클릭 시 `InlinePlayer.seek_to_ms`. `RelatedItem` dataclass + `item_selected` 시그널. 요약 탭은 `gemini_summary` 필드를 표시하며 ⟳ 버튼으로 `_GeminiSummaryWorker`(QThread) 실행 → `GeminiExtractor` 호출 → `gemini_summary_saved` 시그널 방출.
│   │   ├── settings_panel.py        # 전체 설정 패널 (다운로드 경로, 테마 등)
│   │   └── settings_dialog.py       # 간략 설정 다이얼로그 (레거시, 42줄)
│   ├── dialogs/
│   │   ├── youtube_auth_dialog.py   # YouTube OAuth 인증 플로우 다이얼로그
│   │   └── batch_download_dialog.py # 일괄 다운로드 URL 입력 다이얼로그
│   ├── widgets/
│   │   └── video_player.py          # 인라인 비디오 플레이어 위젯 (QMediaPlayer 기반). **하이브리드 스트리밍 화질**: YouTube 고화질은 영상+오디오 분리(DASH)라 QMediaPlayer 단일 URL로는 360p가 한계 → `_StreamWorker`가 두 모드 운용. "자동(빠른 재생)"·360p·240p는 muxed URL 즉시 스트리밍(merge=False); 1080p/720p/480p는 `bestvideo[avc1]+bestaudio[mp4a]`를 번들 ffmpeg로 임시 mp4에 병합 후 로컬 재생(merge=True, `ovc_stream_*` 임시 디렉터리는 stop/load/품질전환 시 정리). WMF 호환 위해 avc1(H.264)+m4a 우선. 화질 변경 시 `_on_quality_changed`가 현재 위치 저장→`mediaStatusChanged`(LoadedMedia/BufferedMedia·seekable)에서 이어보기 seek(고정 지연 seek 폐기로 네트워크 스트림에서도 견고)
│   ├── themes/
│   │   ├── manager.py               # ThemeManager 싱글턴 — 전역 QSS 교체, theme_changed 시그널
│   │   ├── tokens.py                # ThemeTokens dataclass + PRESETS 딕셔너리
│   │   └── stylesheet.py            # build_qss(tokens) → QSS 문자열 생성
│   └── view_models/                 # UI 상태 — Application 레이어와 View 사이 브릿지
│       ├── library_vm.py            # LibraryViewModel — 영상 목록, 카테고리, 검색
│       ├── download_vm.py           # DownloadViewModel — 다운로드 큐/이력 + 진행률
│       ├── feed_vm.py               # FeedViewModel — 전체 구독 피드(refresh) + 채널별 영상(load_channel) + 구독 채널 카드 정보(load_channel_infos) 로딩, shutdown() 워커 정리
│       ├── monitoring_vm.py         # MonitoringViewModel — 채널 구독 목록
│       ├── clip_vm.py               # ClipViewModel — 클립 목록 + 추출 작업
│       └── playlist_vm.py           # PlaylistViewModel — 재생목록 관리
│
├── db/
│   └── schema.sql                   # SQLite schema (FTS5 for search)
│
└── tests/
    ├── unit/
    │   └── domain/                  # Pure domain logic tests (no I/O)
    └── integration/                 # Tests hitting SQLite, yt-dlp, ffmpeg
```

---

## Key Design Decisions

- **피드/채널 메타데이터 보강** — yt-dlp `extract_flat`은 구독 피드·채널 영상의 게시일·조회수를 주지 않으므로(영상 ID·길이만), `GetSubscriptionFeedHandler`·`GetChannelVideosHandler`가 YouTube Data API `videos.list`(`get_videos_channels`, part=snippet,statistics,contentDetails)로 `published_at`(ISO)·조회수·길이를 보강한다. 채널 카드의 "최근 영상" 시점은 채널 업로드 재생목록 첫 항목(`get_latest_upload_dates`, 채널당 1쿼터·스레드풀 병렬)으로 구한다. **`_yt_api`(OAuth) 미설정 시 graceful**: 시간 미표시 + 채널은 이름순 정렬.
- **GUI on main thread** — all network/download work runs in background `QThread`; results communicated via Qt signals.
- **yt-dlp progress hooks** → `DownloadProgress` value object → emitted as Qt signal to update progress bar.
- **Aggregates own state changes** — e.g., `VideoAggregate.mark_watched()` not `video.watched = True`.
- **Repositories are interfaces in `domain/`** — GUI and Application layers depend on abstractions; SQLite is an implementation detail.
- **Domain Events over direct calls** — when a download completes, `DownloadCompleted` event triggers library update and UI notification independently.
- **ffmpeg resolved via `get_ffmpeg_path()`** — checks `bin/` first (bundled), falls back to system PATH.
- **Ports over concrete infra in application** — application 레이어는 `EventBus`/`YtDlpAdapter`/`FfmpegAdapter`를 직접 import하지 않고 `domain/shared/ports.py`의 Protocol(`IEventBus`·`IMediaSource`·`IClipExtractor`)에 의존한다. 어댑터는 구조적 타이핑으로 이를 만족(상속 불필요)하며, 구체 인스턴스 주입은 composition root(`main.py`)가 담당한다. 작업별 진행률 훅이 필요한 다운로드처럼 인스턴스를 새로 만들어야 하는 경우는 **팩토리 콜백을 주입**한다(`make_downloader`, `yt_api_factory`).
- **Gemini AI 요약 자동 메모 저장** — `DownloadSettings.capture_gemini=True`이면 다운로드 완료 후 `GeminiExtractor`(Playwright sync API)가 YouTube 페이지에서 Gemini Ask 버튼을 클릭해 요약 텍스트를 추출하고, `AddVideoHandler`를 통해 라이브러리 영상 `notes` 필드에 저장한다(`initial_notes` — 기존 메모가 비어있을 때만 덮어씀). 추출 실패는 완전히 격리돼 다운로드 결과에 영향을 주지 않는다. `infrastructure/browser/gemini_extractor.py`는 반드시 QThread에서만 호출한다. **인증은 쿠키 파일(Netscape 포맷)로만 이루어진다.** 확보 우선순위: 1) `YT_AUTH_COOKIEFILE`, 2) `youtube_auth_dialog.py`의 "새 계정으로 로그인…"(Playwright가 로그인 세션의 살아있는 쿠키를 직접 추출 — 복호화 불필요) 플로우로 저장된 `data/auth/youtube_cookies.txt`, 3) `YT_AUTH_BROWSER`/`YT_AUTH_PROFILE`(브라우저 계정 탭)을 `GeminiExtractor._export_browser_cookies()`가 yt-dlp `cookiesfrombrowser`로 임시 내보내기(Firefox 등 대부분 브라우저에서 동작). **Chrome v127+ 예외**: Chrome은 쿠키를 App-Bound Encryption으로 암호화해 프로필 직접 실행·프로필 파일 복사·yt-dlp `cookiesfrombrowser` 세 가지 방식 모두 외부 프로세스가 복호화할 수 없음을 확인했다(DPAPI 오류) — Chrome 사용자는 방법 1·2만 유효하다.
- **GUI→infra 예외 경계** — `gui/main_window.py`·`gui/dialogs/youtube_auth_dialog.py`는 `infrastructure.auth`를 직접 참조한다. `gui/panels/video_detail_panel.py`의 `_GeminiSummaryWorker`는 `infrastructure.browser.gemini_extractor.GeminiExtractor`를 지연 import한다. 로그인/Gemini 추출 플로우가 playwright 구동 등 **본질적으로 인프라**라 포트로 감싸도 런타임 의존이 사라지지 않으므로, composition-root 인접의 **수용된 경계**로 둔다(application 레이어는 이런 예외가 없어야 함).

## 에러 처리 & 로깅 규칙 (mandatory)

- 진입점(`main.py`)에서 `utils.logging_config.setup_logging()`을 1회 호출한다(회전 파일 `LOG_DIR/app.log` + 콘솔).
- 모듈마다 `logger = logging.getLogger(__name__)`를 정의한다.
- **예외를 조용히 삼키지 말 것.** `except Exception: pass`/조용한 폴백이 필요하면(네트워크·API·DB 실패를 폴백 처리할 때) 반드시 `logger.exception("맥락")`으로 흔적을 남긴다. idempotent하게 무시해도 되는 경우만 `logger.debug(...)`.
- 예외를 UI로 표출하는 뷰모델 패턴(`error_occurred.emit(str(exc))`)은 이미 가시적이므로 그대로 둔다.
- 백그라운드 워커를 만드는 뷰모델은 `shutdown()`을 제공하고 `MainWindow.closeEvent`에서 호출해 종료 시 워커를 정리한다. yt-dlp 다운로드처럼 협조적 취소 훅이 없으면 `terminate()` 후 `wait()`로 종료를 보장한다.

## Memory Optimization Rules (target: low-spec PCs, ~4 GB RAM)

These are **mandatory coding constraints**, not suggestions.

### Thumbnail Grid

- Use `QListView` + custom `QAbstractItemModel` with a delegate — **never** `QListWidget` with pre-loaded items.
- Only fetch and decode thumbnails for items **currently visible** in the viewport (virtual scrolling).
- Keep an LRU cache of max **100 `QPixmap` objects per render size**; evict oldest on overflow. (캐시 키에 표시 크기가 포함되므로 — 아이콘 그리드·리스트·상세뷰 3종 — 전체 상한은 `LRU_THUMBNAIL_MAX × 렌더 크기 종류 수`. `library_panel.py`의 `_thumb_cache` 참조.)
- Scale thumbnails to display size (e.g., 160×90) **at load time** — never store full-resolution `QImage` in memory after conversion.
- Set `QPixmapCache.setCacheLimit(30720)` (30 MB) on startup.

### SQLite Queries

- All repository queries **must** use `LIMIT` / `OFFSET` pagination — default page size 50.
- Never call `.fetchall()` on the `videos` table; iterate with a cursor.
- Load `description` and `notes` fields **only** when the detail panel is opened (`GetVideoByIdQuery`), not in list queries.
- Thumbnails are stored as **file paths** in the DB — never as BLOBs.

### Domain / Value Objects

- Apply `__slots__` to all Value Objects (e.g., `VideoUrl`, `TimeRange`, `DownloadProgress`) to reduce per-instance memory.
- Use generator expressions instead of list comprehensions when processing query result sets.

### Background Tasks

- Playlist/channel import은 **반드시 워커 `QThread`에서 실행**하고, 진행 상황을 항목 단위(또는 ≤50개 청크 단위)로 `on_progress` 콜백 → Qt 시그널로 방출해 메인 스레드 이벤트 루프를 막지 않는다. (DB에서 재처리하는 메타데이터 갱신은 `RefreshCategoryMetadataHandler`처럼 `LIMIT/OFFSET` 50개 청크로 순회하여 전체를 메모리에 올리지 않는다.)
- Completed `DownloadJob` objects are removed from the in-memory queue immediately after the `DownloadCompleted` event fires.
- Monitoring polls one channel at a time sequentially; do not accumulate full feed results in memory.

### Startup

- Do **not** pre-load thumbnails or metadata on startup; the grid populates lazily on first render.
- SQLite WAL mode on — reduces contention without extra memory buffers.

---

## Packaging Rules (must follow for Windows/Linux distribution)

- **All resource paths** go through `utils/resources.get_resource_path()` — handles both dev (`Path(__file__)`) and PyInstaller bundle (`sys._MEIPASS`).
- **User data paths** (DB, logs, downloads) use `platformdirs.user_data_dir()` — never write to the app install directory.
- `bin/` is **git-ignored** — ffmpeg binaries are downloaded by build scripts, not committed.
- Build scripts live in `scripts/`; PyInstaller spec(`online_video_clipper.spec`)와 Inno Setup script(`installer.iss`)는 `packaging/`에 있다. (`build/`는 PyInstaller가 생성하는 빌드 산출물 디렉토리이므로 소스 위치와 혼동하지 말 것.)
- See `planning/packaging_plan.md` for full build instructions and checklist.

---

## Requirement & Planning Updates

**These updates are MANDATORY — never skip them, even for small changes.**

| What changed | Where to record it |
| --- | --- |
| New coding rule, constraint, or workflow instruction | This file (`CLAUDE.md`) |
| New/changed feature requirement | `planning/youtube_content_manager_prd.md` |
| New bounded context, aggregate, entity, value object | `planning/ddd_design.md` |
| Architecture or layer structure change | This file (`CLAUDE.md`) |
| Build / packaging change | `planning/packaging_plan.md` |
| GUI 파일 추가 · 삭제 · 이름 변경 | 이 파일(`CLAUDE.md`)의 `gui/` 파일 맵 즉시 수정 |

> Instructions that only live in the conversation are lost across sessions. Record them here **before or alongside** implementation — not as follow-up cleanup.

---

## 커밋 규칙 (mandatory)

- **코드 수정이 생기면 항상 적절한 커밋 메시지와 함께 커밋한다.** 작업(기능/버그픽스/리팩터)이 끝나 검증까지 마치면 사용자가 따로 요청하지 않아도 변경을 커밋한다.
- 커밋 메시지는 **무엇을·왜** 바꿨는지 드러나게 한국어로 작성한다(`feat:`/`fix:`/`chore:` 등 접두 + 핵심 변경 불릿). 관련 문서(CLAUDE.md, planning/) 변경도 같은 커밋에 포함한다.
- git 작업(커밋·푸시·PR·브랜치 정리)은 Haiku 모델로 수행한다.
- 푸시는 사용자가 명시적으로 요청할 때만 한다.

---

## GUI 수정 작업 규칙

### GUI 변경 후 반드시 `/verify` 실행

GUI 파일(`gui/` 하위 어느 파일이든)을 수정한 경우, 코드 변경 완료 후 반드시 `/verify` 스킬을 호출해 앱을 실제로 실행하고 변경 결과를 확인한다. 코드가 컴파일 오류 없이 실행되고 해당 패널이 정상적으로 뜨는지 확인한 뒤 완료 보고한다.

### GUI 수정 요청 시 포함해야 할 정보

요청 형식을 지킬수록 반복 수정 횟수가 줄어든다:

```
패널/파일: gui/panels/library_panel.py (LibraryPanel)
현재 동작: [단계별 재현] 예) 영상 클릭 → 상세 패널 열림 → X 버튼 클릭 → 아무 반응 없음
기대 동작: X 버튼 클릭 시 상세 패널 닫힘
오류 메시지: (터미널/콘솔 출력 있으면 붙여넣기)
스크린샷: (가능하면 첨부)
```

최소한 **파일명 + 현재 동작 + 기대 동작** 세 가지는 포함한다.

### 코드 분석 효율화

- 세션 시작 시 위 `gui/` 파일 맵을 1차 참조한다 — 파일 맵에 없는 경우에만 탐색 에이전트를 호출한다.
- `gui/` 내 어느 파일을 수정해야 하는지 모를 때는 파일 맵에서 책임 설명을 먼저 확인한다.

---

## 언어 정책

- 모든 대화 응답, 문서(CLAUDE.md, planning/), 코드 주석은 **한국어**로 작성한다.
- 예외(영어 유지): 코드 식별자(함수명·클래스명·변수명), 라이브러리·프레임워크 명칭, SQL 키워드, 셸 명령어 등 기술적으로 영어가 필수인 요소.

---

## Platform Support Notes

- Target OS: Windows (primary), macOS/Linux (secondary)
- Requires Python 3.10+
- ffmpeg binary must be on PATH or bundled in `bin/`
