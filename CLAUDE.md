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
| 번역 | `deep-translator` | 비한국어 가사 → 한글 자동 번역(무키 Google 웹번역, 미설치 시 graceful) |
| 클라우드 동기화 | `msal`, `keyring` | OneDrive(msal) 인증 + 자격증명 keyring 저장(부재 시 파일 폴백). Google Drive는 위 google-auth 재사용 |
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
│   ├── monitoring/                  # [Bounded Context] Channel subscription & monitoring
│   │   ├── entities.py              # ChannelSubscription
│   │   ├── value_objects.py         # MonitoringRule (keyword/duration filter)
│   │   ├── aggregates.py            # ChannelMonitorAggregate (root)
│   │   ├── repositories.py          # IChannelRepository
│   │   └── events.py                # NewVideoDetected
│   │
│   └── song/                        # [Bounded Context] 노래 정보 (Video와 1:1)
│       ├── value_objects.py         # LyricsLine(원문+한글번역), SongSourceRef
│       ├── entities.py              # SongInfo(가수·앨범·제목·발매년도·가사·is_song·manual_fields) + LyricsSource(출처 레지스트리)
│       ├── aggregates.py            # SongInfoAggregate — apply_fetched(수동편집 보존)·edit_field·edit_lyrics
│       ├── repositories.py          # ISongRepository (+ 가사 출처 CRUD)
│       ├── ports.py                 # ILyricsProvider·ITranslator(Protocol) + LyricsResult
│       └── events.py                # SongInfoUpdated
│   │
│   └── sync/                        # [Bounded Context] 클라우드 동기화 (레코드 단위 oplog CRDT) — 구현 중
│       ├── value_objects.py         # Op·OpKind·EntityKey·ClockEntry(lamport,install)·SnapshotManifest (NDJSON 직렬화) + FileEntry(rel_path·size·mtime·sha256 — 미디어 파일 동기화 메타)
│       └── services.py              # OpLogMerger(결정적 필드 LWW+tombstone)·NaturalKey 함수군·topo_order + plan_file_sync(순수 파일 동기화 계획: 로컬만→upload/원격만→download/sha다름→prefer정책, 삭제 전파 안 함)·FileSyncAction·FileSyncItem
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
│   ├── monitoring/
│   │   ├── commands.py              # SubscribeChannel, UnsubscribeChannel, SetMonitoringRule
│   │   └── queries.py               # GetSubscriptions
│   └── song/
│       ├── dtos.py                  # SongInfoDTO, LyricsLineDTO, LyricsSourceDTO
│       ├── commands.py              # FetchSongInfo(출처 체인+번역), UpdateSongField/Lyrics, SetSongFlag, 가사출처 CRUD
│       └── queries.py               # GetSongInfo, ListLyricsSources
│   └── sync/                        # 클라우드 동기화 유스케이스 — 구현 중
│       ├── ports.py                 # ICloudSyncProvider·IOplogStore·ISnapshotStore·ISecretStore (Protocol) + RemoteFile
│       ├── commands.py              # Push·Pull·SyncNow·ConnectProvider·DisconnectProvider·Compact 핸들러(스키마 게이트 포함). CompactHandler=DB→스냅샷 export→provider 업로드(snapshot/library.db+snapshot.json covered)+선택적 세그먼트 GC(기본 off)
│       └── queries.py               # GetSyncStatus → SyncStatusDTO
│
├── infrastructure/                  # Concrete implementations (invert dependencies)
│   ├── persistence/
│   │   ├── database.py              # SQLite 연결 + WAL 설정 + 스키마 마이그레이션
│   │   ├── sqlite_video_repository.py
│   │   ├── sqlite_download_repository.py
│   │   ├── sqlite_clip_repository.py
│   │   ├── sqlite_channel_repository.py
│   │   ├── sqlite_playlist_repository.py  # 재생목록 + 폴더 저장소
│   │   └── sqlite_song_repository.py      # song_info(가사 JSON) + lyrics_sources 저장소
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
│   ├── song/
│   │   ├── lyrics_providers.py      # LRCLIB(무키)·Genius·멜론·벅스·지니 가사 제공자 + build_default_providers (QThread에서만 호출). 네트워크 오류(타임아웃·연결실패)는 트레이스백 없이 WARNING으로만 남기고 None 반환→다음 출처로(`_log_provider_error`); 타임아웃 (connect 5s, read 8s)로 짧게 잡아 느린 출처를 빨리 건너뜀
│   │   └── translator.py            # deep-translator 래퍼(ITranslator) — 미설치/실패 시 원문 그대로(graceful)
│   ├── event_bus.py                 # In-process event dispatcher
│   └── sync/                        # 클라우드 동기화 인프라 (Phase 2~) — 구현 중
│       ├── keyring_secret_store.py  # ISecretStore (Windows Credential Manager, 백엔드 부재 시 파일 폴백)
│       ├── device.py                # install_id 영속 + LamportClock(tick/observe)
│       ├── local_oplog_store.py     # IOplogStore 로컬 구현 — <base>/<install>/NNNNNN.ndjson 세그먼트 append/read
│       ├── cloud_oplog_store.py     # IOplogStore 원격 — provider 위 oplog/<install>/*.ndjson + installs.json 레지스트리
│       ├── sync_state.py            # SyncState(consumed·pushed_head·provider_key)·SyncStateStore(DATA_DIR/sync/sync_state.json)
│       ├── snapshot_store.py        # ISnapshotStore — VACUUM INTO export / 검증·백업·교체 import + 스키마 게이트(SyncSchemaError)
│       ├── recorder.py              # OplogRecorder — 변경 필드 diff→op append + sync_* 레지스터 갱신. record_change/record_delete(엔티티)·record_link/record_unlink(조인 행, presence-aware)
│       ├── recording_repository.py  # 캡처 데코레이터 전 엔티티: RecordingVideoRepository(video + category[origin-id] + video_tag + category_video_order 링크)·RecordingSongRepository(nkey=영상URL)·RecordingClipRepository(origin-id, source_video ref)·RecordingDownloadRepository(origin-id)·RecordingPlaylistFolderRepository(origin-id)·RecordingPlaylistRepository(origin-id, folder ref + playlist_item 멤버십 링크). 경로 필드는 DB 상대경로 그대로 캡처(이식성)
│       ├── merge_applier.py         # MergeApplier — OpLogMerger로 승자 계산 후 자연키→UUID 해석·FK 재작성·위상 순서로 라이브 DB 직접 반영(FTS 트리거 정상 발화). 핸들러 registry: Category(origin-identity, name+parent ref, rename=필드변경, 동명충돌 병합)·Video·Song(nkey=영상URL)·VideoTag(link)·Clip·Download·PlaylistFolder·Playlist(folder ref)·PlaylistItem(link, 멤버십만-순서는 append)·CategoryVideoOrder(link) ApplyHandler + resolve_video/tag/category/playlist/folder. **배치 내 부모/자식 순서 무관**: 자식이 부모를 resolve할 때 sync_identity가 아직 persist 전이므로, 부모 핸들러가 `_register_identity`로 즉시 등록(category/tag는 resolve_*가 stub 생성). **링크 자연키는 `_LINK_SEP`(\x1e)로 조합** — 부모가 origin_key(내부 \x1f)여도 split이 안전
│       ├── file_syncer.py           # FileSyncer — 미디어/썸네일 바이트 동기화 엔진. scan_media_dirs(DATA_DIR 기준 rel_path·size+mtime 캐시로 sha256 재해시 회피·.part/DATA_DIR밖 제외) → plan_file_sync → provider로 upload/download. 원격 레이아웃 media/manifest.json(진실원천 sha256)+media/files/<rel>. 다운로드는 .part→os.replace 원자 확정, 원격 매니페스트 read-merge-write(동시추가 보존). on_progress(MediaSyncProgress)·should_cancel 콜백만 노출(QThread 배선은 Phase 5)
│       ├── rest_client.py           # RestClient — Bearer+verify=False+401 강제refresh 후 1회 재시도(youtube_api_adapter 패턴 추출). token_provider/force_refresh 콜백 주입, 세션 주입 가능(테스트)
│       ├── gdrive_provider.py       # GoogleDriveProvider(ICloudSyncProvider) — google-auth-oauthlib InstalledAppFlow(scope drive.file), 토큰 keyring(gdrive.token). Drive는 ID모델이라 remote_path를 앱루트 폴더트리(경로→id 캐시)로 에뮬레이션, resumable 업로드 세션(청크 PUT). **실계정 왕복 검증은 로컬 전용(미완)**
│       ├── onedrive_provider.py     # OneDriveProvider(ICloudSyncProvider) — msal PublicClientApplication+SerializableTokenCache(keyring, scope Files.ReadWrite+offline_access). Graph v1.0 경로주소지정(/me/drive/root:/<path>), 소형 PUT/대형 createUploadSession. msal 지연 import(미설치여도 모듈 import OK). **실계정 왕복 검증은 로컬 전용(미완)**
│       ├── folder_provider.py       # FolderProvider(ICloudSyncProvider) — **로컬 폴더를 클라우드 백엔드로**(OneDrive/Drive 데스크톱 동기화 폴더 지정 → OS 클라이언트가 실제 왕복). OAuth·API키 불필요라 **기본/권장 옵션**. 쓰기는 tmp→os.replace 원자 확정. 실 스택 end-to-end 테스트에도 사용(실계정 없이 전 경로 검증 가능)
│       ├── bootstrap.py             # bootstrap_if_fresh(pre-DB) — 신규 install(로컬 DB 미존재)만 스냅샷 다운로드→sha256 검증→import_snapshot(게이트+교체)→consumed=covered. 기존 DB 있으면 증분 pull에 맡김(스냅샷 교체로 로컬 상태 손실 방지)
│       └── sync_service.py          # SyncService — sync 스택 조립(secret·device·clock·store·applier·snapshot·recorder·provider) + 고수준 동작(sync_now·sync_media·compact·connect_folder/gdrive/onedrive·disconnect·status·make_recording_repos). pre_db_bootstrap()·build_secret_store()·build_provider(folder/gdrive/onedrive) 모듈 함수. **캡처 게이팅**: is_connected일 때만 make_recording_repos가 Recording* dict 반환(미연결이면 None→repo 무래핑)
│
├── gui/                             # Presentation layer (PyQt6, MVVM)
│   ├── single_instance.py           # SingleInstanceGuard — QLocalServer 기반 중복 실행 방지(main.py가 DB 열기 전 호출, 두 번째 인스턴스는 기존 창을 앞으로 부르고 종료)
│   ├── main_window.py               # 루트 윈도우, 사이드바 네비게이션(라이브러리·다운로드·채널 모니터링·통계), 패널 스택 — 구독 피드는 라이브러리 좌측 트리로 통합됨. **통계 채널 섹션 → 카테고리 드릴다운**: `StatsPanel.category_selected` → `_on_stats_category_selected`가 라이브러리로 전환·`navigate_to_category` 후 `_return_to_page=_PAGE_STATS` 예약. 라이브러리 뒤로가기를 소진하면(`LibraryPanel.back_exhausted`) `_on_library_back_exhausted`가 통계로 복귀(라이브러리 자체 히스토리를 먼저 되짚고 소진 시 통계). 다른 페이지로 이동하면 `_on_page_changed`가 예약을 무효화. **등록 후 자동 보강 상태 표시**: `enrich_started`→상태바 "가사 조회 중"/"요약 생성 중"(`_ENRICH_LABEL`), `enrich_finished`→완료(5초)/실패(8초). `kind="skipped"`+ok이면 메시지를 지운다. **사이드바 배경은 `_SideBar.paintEvent`에서 직접 칠한다** — 앱 레벨 QSS의 `QWidget { background-color }`가 위젯 레벨 스타일시트(ID 선택자 포함)를 덮어써 `bg_surface`가 적용되지 않았다(slate에서는 base/surface 차이가 3단위라 미발견). 따라서 사이드바 배경·우측 경계선 색을 바꿀 땐 QSS가 아니라 `paintEvent`를 수정할 것. **상단 ▶ 로고와 계정(인증) 버튼은 제거됨** — 로고는 기능 없는 장식이고, 계정 버튼은 클릭 동작이 바로 아래 기어 버튼과 완전히 동일한 중복이었다(`update_account_status()`도 호출처 없는 죽은 코드여서 함께 삭제, `_SVG_ACCOUNT` 상수도 제거)
│   ├── panels/
│   │   ├── library_panel.py         # 썸네일 그리드 + 카테고리/재생목록 트리 + 상세뷰 + YouTube 트리의 "구독 채널"/"전체 구독 피드" 노드. 영상 카드 **단일 클릭→상세화면**(미리보기 패널 제거됨, Ctrl/Shift 클릭은 다중선택 유지). 피드/채널 카드 단일 클릭→`_open_stream_detail`(스트리밍 상세). `_open_detail`/`_open_stream_detail`이 컨텍스트별 연관영상(RelatedItem)을 구성해 상세화면에 전달, 연관영상 클릭은 `_on_related_item_selected`로 재진입. **인기/전체 태그 패널(`_tag_section`)은 트리 하단에 일반 세로 레이아웃(`nav_container`)으로 쌓고 카테고리 선택 시에만 표시**(`_set_popular_tags_visible(True/False)`가 섹션 전체를 토글). 재생목록·폴더·섹션루트·피드·채널 선택 시엔 숨겨 트리가 그 공간을 차지한다. (QSplitter로 묶으면 자식 가시성 토글이 레이아웃 thrash→프리징을 유발해 일반 레이아웃으로 교체함.) **트리 노드 클릭 시 상세 화면이면 먼저 목록으로 복귀**(`_leave_detail_if_open`). **뒤로/앞으로 가기는 화면 단위 스냅샷 기반**(`_capture_screen`→`_nav_history`(뒤로)/`_nav_future`(앞으로), `_go_back`/`_go_forward`/`_restore_screen`): kind(category/playlist/folder/feed_all/channel/channels_root)+상세 payload까지 저장해 직전/다음 화면을 정확히 복원(분류 간 교차·상세→상세 연관영상 체인 포함). 마우스 ‹=`_go_back`, ›=`_go_forward`(eventFilter), 새 분기 이동 시 `_push_nav_state`가 `_nav_future` 비움. 복원 시 `_PlaylistPanel.select_snapshot`로 좌측 트리 강조·브레드크럼을 동기화(시그널 차단해 재실행 방지). 상세 뒤로가기 버튼도 `_on_detail_back_requested`→히스토리 복원. "전체 구독 피드"/개별 채널 클릭→피드 카드 그리드(_VIEW_FEED), "구독 채널" 노드 클릭→채널 아바타 카드 그리드(_VIEW_CHANNELS). **"구독 채널" 노드 우클릭 컨텍스트 메뉴 맨 위에 "⟳ 새로고침 (YouTube 구독 재동기화)"**(`_PlaylistTree.sync_subs_req`→`_PlaylistPanel.sync_subs_req`→`LibraryPanel._on_sync_subscriptions`): `_monitoring_vm.import_from_youtube()`로 YouTube 구독을 로컬 DB에 재동기화한다(구독 목록은 로컬 DB 스냅샷이라 유튜브에서 새로 구독한 채널은 이 새로고침 전엔 안 뜸). 완료 시 `subscriptions_changed`→`_refresh_unified_tree`(트리)와 `import_yt_finished`→`_on_subs_synced`(그리드가 열려 있으면 `_populate_channels_grid` 재구성)로 갱신, 실패는 `error_occurred`→`_on_subs_sync_error`가 상태 라벨에 표기. 그리드 채우기 로직은 `_populate_channels_grid`로 추출돼 노드 클릭·재동기화 완료 양쪽에서 재사용(뷰 전환·nav 히스토리는 `_on_channels_root_selected`만 담당). **좌측 채널 노드는 이름 오름차순 정렬**, 채널 카드는 핸들러가 최신 업로드 내림차순으로 정렬해 전달. 연관영상 meta에도 `_relative_time`으로 등록 시점 표기(로컬 ISO·피드 ISO/YYYYMMDD 모두). **좌측 트리 패널(`_PlaylistPanel`)은 로컬 섹션(상단 고정) + 접을 수 있는 YouTube 섹션 구조**: 이전 수직 `QSplitter`를 제거하고, 로컬 트리 아래에 **삼각형 토글 바(`_yt_bar`: `_yt_toggle_btn`▸/▾ + 빨간 "YouTube" 헤더 + ⟳동기화 + 📂+폴더)**를 두어 그 아래 `_yt_tree`(구독 트리)를 펼치거나 접는다(`_toggle_yt_section`). **YouTube 구독 트리는 기본 접힘(숨김)**. **모든 트리는 로드 후 `collapseAll()`로 최상위(1레벨) 항목만 보이고 하위는 접힌다**(`_PlaylistTree.load`). (메인 패널, ~5000줄 — 분할 검토 대상. `_PreviewPane`는 미사용 잔존). **트리 행은 `_TreeRowDelegate`가 그린다** — 둥근 pill 행·accent 14% 틴트 선택·카테고리 색상 점·우측 개수 뱃지·즐겨찾기 ★·행 높이 30px. 항목 팩토리(`_make_category`/`_make_folder`/`_make_unfiled`/`_make_root`/`_make_playlist`/`_make_channel`)가 `_NAME_ROLE`·`_COUNT_ROLE`·`_GLYPH_ROLE`·`_COLOR_ROLE`·`_STAR_ROLE`을 심고 델리게이트는 **롤만 읽는다**(로딩 스피너가 `setText`로 텍스트 뒤에 `⠋`를 덧붙이고 카테고리 이름에 괄호가 들어갈 수 있어 텍스트 파싱은 깨진다). **셰브론·들여쓰기 가이드선은 `drawBranches()` 오버라이드**에 그린다 — 델리게이트(아이템 영역)에 그리면 `QTreeView`가 branch 영역 클릭만 확장으로 처리하므로 펼침이 동작하지 않는다(`tests/gui/test_tree_rows.py`의 QTest 클릭 테스트가 이를 지킨다). 즐겨찾기는 `setBackground` 틴트가 델리게이트에 가려지므로 ★로 표시한다. **칩 색은 `chip_colors(tokens, selected, data_color)`로 토큰에서 파생**한다(과거 `paintEvent`에 `#2a3a4a` 등이 하드코딩돼 어떤 테마를 골라도 칩만 어두웠다 — 인기태그 버튼·태그목록·즐겨찾기 바 3곳). `count == 0` 경고 뱃지(`_BADGE_EMPTY_BG`)와 YouTube 강조색(`_YT_BRAND_RED`)은 의미·브랜드 색이라 테마와 무관하게 고정한다. **태그·카테고리 색상은 `tag_color(name)`**(zlib.crc32 기반) — 이전 `hash(name)`은 PYTHONHASHSEED로 프로세스마다 무작위화돼 앱을 켤 때마다 색이 바뀌었다. **"로컬" 루트 활성 표시**: `_PlaylistPanel.set_local_root_active()`가 `local_hdr`의 체크 상태(QSS `:checked`)를 관리하고, 헤더 클릭 시 두 트리 선택을 `blockSignals`로 감싸 해제한다(이중 실행 방지). 트리 노드 선택 시 비활성(`_connect_tree`가 `currentItemChanged` 배선), `select_snapshot` 복원 시 `matched is None`이면 활성. **검색 일치 속성 배지**는 `_paint_match_badges`가 그리드·리스트 델리게이트 양쪽에서 그린다(`MatchFieldsRole` → `MATCH_FIELD_LABELS`)
│   │   ├── download_panel.py        # 다운로드 큐 + 완료 이력 탭 (영상 파일만 표시·완료/실패 배지)
│   │   ├── feed_panel.py            # 피드 카드 부품(_FeedGrid·_FeedCard: 썸네일 좌하단 채널 배지·리사이즈 reflow, **단일 클릭→`video_clicked`(FeedVideoDTO) 방출**, 인라인 추가버튼 제거·우클릭 메뉴로 일원화) + 채널 카드 부품(_ChannelGrid·_ChannelCard: 아바타·구독자/영상수에 더해 **"최근 영상 N일 전"** 라벨=`latest_video_published_at`) + 연관영상 행에서 재사용하는 `_RoundedThumbLabel`·`_ThumbLoader` 정의 — library_panel/video_detail_panel이 재사용. `_FeedCard`·`_ChannelCard`는 `_relative_time`(YYYYMMDD·ISO·`Z` 처리)로 등록 시점을 상대시간 표기. (구버전 FeedPanel 컨테이너는 더 이상 사이드바 메뉴로 노출되지 않음)
│   │   ├── monitoring_panel.py      # 채널 구독 & 모니터링 규칙 관리
│   │   ├── stats_panel.py           # 라이브러리 통계 대시보드 + **채널별 카테고리 섹션**(`_make_channel_row`: 채널명·총 영상수 + 카테고리 경로 링크를 `_FlowLayout`으로 흐름 배치, 예 "IT > News (3)"). 링크 클릭 시 `category_selected(category_id)` 방출 → `MainWindow._on_stats_category_selected`가 라이브러리 해당 카테고리로 전환. **채널명은 URL이 있으면 클릭 시 브라우저로 열리는 링크(`_open_url`→`QDesktopServices`) + `📋` URL 복사 버튼(`_copy_url`, 복사 후 ✓ 잠깐 표시)**을 둔다. 데이터는 `LibraryStatsDTO.channel_stats`(list[`ChannelStatDTO`]→`ChannelCategoryStatDTO`); `ChannelStatDTO.channel_url`은 리포지토리 `get_channel_category_stats`가 반환한 channel_url 대표값(없으면 channel_id로 `youtube.com/channel/{id}` 구성)
│   │   ├── video_detail_panel.py    # YouTube 시청 페이지형 상세화면 — 좌(상단 행: `‹`뒤로+브레드크럼(`_crumb_bar`) 같은 줄 → **상단 고정 플레이어**(stretch 없이 16:9 자연 높이라 여백 없음; 창이 넓어지면 커지고 탭이 남는 공간 흡수) → **제목 행**(제목 `_title_lbl` + 우측 정렬 아이콘 `⟳`상세갱신·`🌐`브라우저) → **메타 행**(`_meta_layout`: 채널·조회수·등록일·재생시간 + 상태) → **하단 탭 3개**(stretch=1)) | 우(`_RelatedList` 연관영상). 탭: `_TAB_INFO`(설명)·`_TAB_SUMMARY`(요약, 헤더 행에 `⟳` 아이콘 갱신 버튼)·`_TAB_FILES`(다운로드/클립 병합 — 수직 `QSplitter`, 위=`_dl_tab` 아래=`_clip_tab_widget`). **설명 탭 레이아웃**(탭 자체 스크롤 없음 — 영속 위젯 세로 스택 `info_col`): `_tags_header`+`_tags_scroll`(태그) → `_tag_add_container`(태그 추가) → `_desc_header`+`_desc_view`(설명) → `_notes_header`+`_notes_edit`(메모) → 맨 아래 `addStretch(1)`. **태그**는 `_TagChip`(글자 길이만큼 Fixed 폭) + `_FlowLayout`(폭에 맞춰 줄바꿈하는 실제 `QLayout` 서브클래스)로 흐르고 `_tags_scroll`(QScrollArea)로 감싸 **최대 3줄까지만 보이고 초과분은 스크롤**한다(`_fit_tags_scroll`이 내용 높이에 맞추되 3줄로 상한). **설명**(`_desc_view` = `_AutoHeightBrowser`)은 내용 높이를 `sizeHint`로 노출해 **남는 세로 공간을 최대로 활용**(설명이 길수록 넓게)하고 공간이 부족할 때만 자체 스크롤한다 — 짧으면 내용 높이에 딱 맞고(맨 아래 stretch가 여백 흡수) 길면 영역을 최대로 차지(그때만 스크롤)하므로 스크롤이 최소화된다. **메모**(`_notes_edit` = `_AutoHeightPlainEdit`)는 설명 바로 아래에서 1~5줄 자동 높이로 **최소 높이가 항상 보장**된다(고정 높이라 설명이 아무리 길어도 안 밀림). `load`(로컬)/`load_stream`(스트리밍: 요약 탭+제목행 `⟳` 비활성) + `set_related`. `_build_info`는 `_meta_layout`만 `_clear_layout`로 재빌드하고 나머지(태그·설명·메모)는 **영속 위젯을 갱신**한다(`_tags_holder_layout`·`_tag_add_layout` clear 후 재구성, `_desc_view.setHtml`, 없으면 `setVisible(False)`). 제목은 `_title_lbl.setText()`, 메모는 `_notes_edit`로 세팅. 설명·요약은 `_render_timestamped_html`로 **마크다운 서식**(제목 `#`, 굵게 `**`/`__`, 기울임 `*`, 불릿 `-`/`*`/`•`/`·`, 번호 `1.`/`1)`, 선행 공백 들여쓰기)을 HTML로 렌더하며 타임스탬프(MM:SS/HH:MM:SS) seek 링크·URL 링크도 유지한다(`_on_summary_anchor_clicked`→`InlinePlayer.seek_to_ms` / 브라우저). URL은 escape/서식 적용 전에 분리해 보존한다. **`line_gap`(px) 인자로 줄마다 하단 여백을 준다** — 설명은 원문에 빈 줄 단락 구분이 있어 0(조밀)이지만, Gemini 요약은 개행이 촘촘해 `_SUMMARY_LINE_GAP`(=8)을 줘 단락·개행 간격을 벌려 읽기 편하게 한다(요약 렌더 3곳 모두 적용). **별도 "챕터" 섹션은 설명 속 타임라인과 중복되므로 제거하고 설명 하나로 병합**(기존 `_parse_chapters`·`_on_chapter_clicked` 삭제됨). `RelatedItem` dataclass + `item_selected` 시그널. **연관영상 행(`_RelatedRow`)**은 제목을 최대 3줄까지 표시(9pt, `AlignTop`, `maximumHeight=lineSpacing*3`)하고 채널명·조회수·등록시기는 7pt로 1pt 줄여 title과 사이에 stretch를 둬 **행 아래쪽에 배치**(제목 가림 최소화). 요약 탭은 `gemini_summary`를 표시(`_summary_edit`)/편집(`_summary_editor`) **`QStackedWidget`(`_summary_stack`)** 2단으로 두고 **표시 영역 더블클릭→편집 모드**(`eventFilter`가 `_summary_edit.viewport()`의 `MouseButtonDblClick` 감지→`_enter_summary_edit`), **편집기 포커스 아웃→저장**(`_commit_summary_edit`이 변경 시 `_summary_raw` 갱신·재렌더 후 `gemini_summary_saved` 방출). ⟳ 버튼으로 `_GeminiSummaryWorker`(QThread) → `GeminiExtractor` 호출 → `gemini_summary_saved` 방출. 요약 원문은 `_summary_raw`에 보관(편집 대상). 제목행 `⟳`(상세 정보 갱신)는 `detail_refresh_requested(video_id)` 방출 → `LibraryPanel._on_detail_refresh_requested`가 `_vm.refresh_video_metadata(video_id)`로 **YouTube(yt-dlp)에서 메타데이터를 백그라운드 재수집**하고 `set_refresh_busy(True)`(⟳ 비활성). 완료 시 VM이 `video_metadata_refreshed(video_id, ok)` 방출 → `_on_video_metadata_refreshed`가 현재 그 영상 상세가 열려 있으면(`current_detail_id()` 일치) `_reload_detail_in_place`로 DB 최신 상세를 재로드(nav 히스토리 미변경). **과거에는 `get_video_detail`로 DB만 재조회해 저장된 오래된/부실(예: `extract_flat` 캡처) 메타데이터가 그대로여서 유튜브 웹과 달랐음** — 이제 실제 재수집으로 제목·설명·조회수·게시일·태그·썸네일을 웹 기준으로 갱신한다. **탭3 `_TAB_SONG`("노래")**는 `_SongTab` 위젯: 가수/앨범/제목/발매년도(`_EditableField` — 더블클릭 시 QLineEdit 인라인 편집, Enter/포커스아웃 저장→`field_edited`; 레이블·값 모두 세로 중앙 정렬, 값은 **PlainText 렌더**라 `'`·`&`·`<` 등이 `&#x27;`처럼 엔티티로 오표기되지 않음), 가사(원문+한글 병행 표시; 표시 영역 더블클릭→편집 모드 QPlainTextEdit, 포커스아웃 저장→`lyrics_edited`), **번역 배치 전환 아이콘**(`_layout_btn` — "(더블클릭하여 편집)" 문구 오른쪽; 원문 아래↔원문 오른쪽 2열 토글, 비한국어 병행 가사일 때만 노출·세션 내 유지, **오른쪽 2열 배치는 행마다 교대 음영으로 경계 구분**), 출처 링크, **가사 검색 버튼(`_lyrics_refresh_btn` = `_SpinRefreshButton`) + 번역 버튼(`_translate_btn`, 가사 있을 때만 노출)** — 가사가 이미 있으면 검색 버튼은 **다음 출처**에서 순환 조회(`_on_lyrics_search_clicked`→`search_next_requested`→`SongViewModel.search_next_source`, 현재 출처 다음부터·끝에서 처음으로 순환), 가사 없으면 처음부터(`refresh_requested`). 번역 버튼은 현재 가사를 한글로 재번역(`translate_requested`→`translate_lyrics`, 조회와 분리된 독립 동작), "노래로 표시" 토글(`flag_toggled` — 켜면 **영상 제목 기준으로 가수·앨범·제목·발매년도만 채우고 가사는 조회하지 않음**), **가수·앨범 값 오른쪽 `»` 필터 아이콘**(`_EditableField` with_action — 값 있을 때만 노출, 클릭 시 `filter_requested(field,value)`→`song_filter_requested`→`LibraryPanel._on_song_filter_requested`가 `get_videos_by_song`으로 같은 가수/앨범 영상을 연관 목록 대신 나열하고 헤더를 "가수/앨범: XXX"로 교체). 스트리밍은 편집·조회 불가(안정적 id 없음)로 탭 비활성. 데이터는 위젯이 직접 조회하지 않고 `LibraryPanel`이 `SongViewModel`로 로드해 `set_song_info(dto)`/`set_song_busy(busy)`로 주입, 편집 신호는 `song_field_saved`/`song_lyrics_saved`/`song_refresh_requested`/`song_flag_toggled`로 재방출→`SongViewModel`이 저장. 가사 더블클릭 편집·편집기 포커스아웃은 요약과 동일하게 앱 레벨 `eventFilter`로 감지. **진입 시 재생 전 포스터**: `load`/`load_stream`에 `poster`(목록과 동일한 QPixmap, LibraryPanel이 `_load_thumb(thumbnail_path,…)`로 생성) + `autoplay` 인자 → `InlinePlayer.load(thumbnail_pixmap=…)`. **우측 목록은 재생목록**: `set_related(items, header=None)`이 payload 순서를 `_playlist`에 저장하고 현재 항목(`_current_key`)을 `_RelatedRow(is_current=…)`로 ▶+배경 강조. `InlinePlayer.playback_finished`(EndOfMedia) → `_on_playback_finished`가 다음 payload로 `play_next_requested` 방출 → `LibraryPanel._on_play_next`가 `_open_detail(autoplay=True)`로 자동재생(마지막이면 정지). 현재 영상도 목록에 포함(제외 조건 제거).
│   │   ├── settings_panel.py        # 전체 설정 패널 (다운로드 경로, 테마 등) + **가사 출처 관리**(`_LyricsSourcesSection`: `song_vm` 주입 시에만 표시) + **클라우드 동기화**(`_CloudSyncSection`: **폴더 방식이 기본**(안내 문구 + 폴더 경로 입력·찾아보기, OneDrive 환경변수 감지 시 `<OneDrive>/ovc-sync` 자동 채움) — 로그인·개발자설정 불필요. **"고급: 클라우드 API로 직접 연결(OAuth)" 체크박스**로 API provider(Google Drive/OneDrive) 드롭다운+Client ID/Secret을 펼침(`_advanced_check` 토글, 기본 숨김). 연결/해제/지금 동기화 버튼·상태 라벨. `sync_vm` 주입 시에만 표시). **숨김 태그 관리 섹션은 맨 아래**(긴 목록이 다른 설정 접근을 방해하지 않도록 재배치). **업데이트 UI는 헤더('설정' 라벨) 우측 컴팩트 위젯**(`_build_update_header`: 자동확인 토글 + 상태 라벨 `_upd_status_lbl` + 준비 시 `_upd_install_btn`)로 이동 — 기존 하단 큰 섹션 제거. `set_update_ready(dto)`가 상태를 '준비됨'으로 바꾸고 설치 버튼 노출, `_on_install_update`→`install_update_requested`. 일반 섹션에 **"등록 시 요약·가사 자동 채우기"** 체크박스(`_auto_enrich_check` → `auto_enrich_on_add`) + 안내 문구(요약은 YouTube 쿠키 필요·일괄 임포트 제외)
│   │   └── settings_dialog.py       # 간략 설정 다이얼로그 (레거시, 42줄)
│   ├── dialogs/
│   │   ├── youtube_auth_dialog.py   # YouTube OAuth 인증 플로우 다이얼로그
│   │   └── batch_download_dialog.py # 일괄 다운로드 URL 입력 다이얼로그
│   ├── widgets/
│   │   └── video_player.py          # 인라인 비디오 플레이어 위젯 (QMediaPlayer 기반). **하이브리드 스트리밍 화질**: YouTube 고화질은 영상+오디오 분리(DASH)라 QMediaPlayer 단일 URL로는 360p가 한계 → `_StreamWorker`가 두 모드 운용. "자동(빠른 재생)"·360p·240p는 muxed URL 즉시 스트리밍(merge=False); 1080p/720p/480p는 `bestvideo[avc1]+bestaudio[mp4a]`를 번들 ffmpeg로 임시 mp4에 병합 후 로컬 재생(merge=True, `ovc_stream_*` 임시 디렉터리는 stop/load/품질전환 시 정리). WMF 호환 위해 avc1(H.264)+m4a 우선. 화질 변경 시 `_on_quality_changed`가 현재 위치 저장→`mediaStatusChanged`(LoadedMedia/BufferedMedia·seekable)에서 이어보기 seek(고정 지연 seek 폐기로 네트워크 스트림에서도 견고). **컨트롤바 배경**은 `_bar_style()`의 `#ctrlbar` 반투명 그라디언트(영상이 비쳐 보임). **재생·볼륨 슬라이더는 `_TrackSlider(QSlider)`로 트랙·핸들을 `paintEvent`에서 QPainter로 직접 그린다** — 영상(`QGraphicsVideoItem`) 위에 겹쳐진 컨트롤바에서는 `QSlider::groove`/`::add-page` 서브컨트롤이 스타일시트 색을 무시하고 검게 렌더되는 Qt 제약이 있어(불투명 지정·정지 프레임에서도 재현; 위젯 배경·`sub-page` 등 직접 채움만 정상), 스타일시트 대신 직접 페인팅으로 라이트 트랙을 보장한다. 따라서 슬라이더 색을 바꿀 땐 `_bar_style`의 QSS가 아니라 `_TrackSlider`(`_TRACK_BG`·`progress_fg`·`text_primary`)를 수정할 것. **전체화면(`_FullscreenWindow`)·화면 속 화면(`_PipWindow`)은 공유 `QMediaPlayer`의 `setVideoOutput` 대상만 자기 `_VideoView`로 바꿔 분리 재생**한다(하나의 player라 위치·볼륨·상태 유지). **`_VideoView`(QGraphicsView)는 `FocusPolicy.NoFocus`** — QGraphicsView가 기본적으로 포커스를 쥐고 방향키(↑/↓/←/→)를 스크롤용으로 소비해 전체화면·PiP 창의 `keyPressEvent`가 볼륨(↑/↓)·탐색(←/→) 단축키를 못 받던 문제를 막는다(상위 창이 모든 키 처리). 두 창 모두 컨트롤바를 공개 속성 `bar`(`_ControlBar` 인스턴스)로 노출하며, **`bar` 신호는 외부(InlinePlayer)에서 반드시 배선**해야 버튼이 동작한다 — `_enter_fullscreen`/`_enter_pip`가 각각 `bar.play_toggled`~`quality_changed`를 인라인과 동일한 핸들러에 연결하고 초기 상태(재생시간·위치·재생여부·볼륨·음소거·화질)를 1회 반영하며, `_exit_fullscreen`/`_exit_pip`가 `durationChanged` 연결을 해제한다. 플레이어→분리창 바 동기화는 `_on_position`/`_on_playback_state`(위치·재생상태)와 `_change_volume`/`_toggle_mute`(볼륨·음소거)가 `_fs_win`/`_pip_win` 존재 시 팬아웃한다. PiP는 컨트롤바에 `_btn_pip`(⧉, `pip_toggled` 시그널, 단축키 `P`)로, 전체화면은 `_btn_fs`(⛶, `fullscreen_toggled` 시그널, 단축키 `F`)로 진입하며 `_enter_pip`/`_enter_fullscreen`은 서로 동시 분리를 허용하지 않아 진입 시 상대 창을 먼저 종료한다. PiP 활성 시 인라인은 `_show_pip_placeholder`로 "화면 속 화면으로 재생 중" 표시. `_PipWindow`는 프레임리스·항상 위, 영상 영역 드래그 이동(영상 `WA_TransparentForMouseEvents`)+`QSizeGrip` 리사이즈, 닫기/Esc/더블클릭/`_btn_pip`로 복귀. **분리 창 정리는 `stop()`/`load()`/`closeEvent`에서 출력 인라인 복귀 후 수행**(상세 이탈 시 `stop_player`→`stop` 경로로 자동 정리). **`load(...)`는 `thumbnail_pixmap` 포스터를 지원**(재생 전 index 0 `_thumb_label` 표시). **`playback_finished` 시그널**: `_on_media_status`에서 `EndOfMedia`(수동 stop과 구분되는 유일한 종료 지표)일 때 방출 → 상세화면 재생목록 자동 다음곡용.
│   ├── themes/
│   │   ├── manager.py               # ThemeManager 싱글턴 — 전역 QSS 교체, theme_changed 시그널
│   │   ├── tokens.py                # ThemeTokens dataclass + PRESETS 딕셔너리 — **기본 테마는 `mist`**(밝은 중간 톤): `bg_base #d9dee6` → `bg_surface #e7ebf1` → `bg_elevated #f8fafc`로 계층차를 12~18단위 확보한다. 기존 `slate`는 계층차가 3~7단위뿐이라 레이어 경계가 보이지 않았다. 다크 6종은 그대로 유지돼 설정에서 선택 가능
│   │   └── stylesheet.py            # build_qss(tokens) → QSS 문자열 생성
│   └── view_models/                 # UI 상태 — Application 레이어와 View 사이 브릿지
│       ├── library_vm.py            # LibraryViewModel — 영상 목록, 카테고리, 검색, 같은 가수/앨범 영상 조회(`get_videos_by_song` — `FindSongVideoIdsHandler`+`GetVideos(video_ids=)`). **등록 직후 자동 보강**: `_EnrichWorker`(QThread)로 `EnrichVideoHandler` 실행, `_pending_enrich` 큐로 **동시 1건** 직렬화(`_maybe_enrich`/`_drain_enrich`/`_release_enrich`), `enrich_started`/`enrich_finished` 시그널 방출. `_AddVideoWorker.finished_ok`이 `video_id`를 실어 보낸다. URL→ID 조회는 `get_video_id_by_url`
│       ├── download_vm.py           # DownloadViewModel — 다운로드 큐/이력 + 진행률
│       ├── feed_vm.py               # FeedViewModel — 전체 구독 피드(refresh) + 채널별 영상(load_channel) + 구독 채널 카드 정보(load_channel_infos) 로딩, shutdown() 워커 정리
│       ├── monitoring_vm.py         # MonitoringViewModel — 채널 구독 목록
│       ├── clip_vm.py               # ClipViewModel — 클립 목록 + 추출 작업
│       ├── playlist_vm.py           # PlaylistViewModel — 재생목록 관리
│       ├── song_vm.py               # SongViewModel — 노래 탭 상태(load/refresh를 `_SongFetchWorker`(QThread) 백그라운드 조회, 필드·가사 편집, 노래 토글, 가사 출처 관리). `search_next_source`(다음 출처 검색 — `from_source_name`으로 현재 출처 다음부터)·`translate_lyrics`(현재 가사 재번역, `_TranslateWorker`). **같은 영상 중복 조회 방지**(`_in_flight`), shutdown()
│       └── sync_vm.py               # SyncViewModel — 클라우드 동기화 UI 상태(설정 패널). SyncService를 `_SyncWorker`(push/pull+미디어)·`_ConnectWorker`(OAuth) QThread로 감쌈. 연결 시 QTimer로 주기 자동 동기화(start_auto_sync=기동 후 1회+주기). 시그널: status_changed·busy_changed·sync_finished·connection_changed·error_occurred. shutdown()
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

- **노래 정보(song 컨텍스트)** — Video와 1:1인 `SongInfo`(가수·앨범·제목·발매년도·가사·is_song). **노래 판별**은 yt-dlp `categories`에 "Music" 포함 또는 `track`/`artist`/`album` 존재로 자동 감지하며, 상세 탭의 "노래로 표시" 토글로 수동 지정도 가능하다. **가사 조회는 관리형 출처 레지스트리(`lyrics_sources` 테이블)를 priority 순으로 순회하는 체인**(`FetchSongInfoHandler._run_chain`) — 기본 LRCLIB(무키·안정)→지니→벅스→Genius→멜론 순으로 부족한 항목(가사·가수·앨범·제목)을 이어서 채운다(**국내곡은 지니·벅스가 원가사를 안정적으로 반환**해 앞에 둔다 — Genius가 기여자/번역 헤더 쓰레기로 '조회 성공' 처리돼 국내 사이트가 시도조차 안 되던 문제 완화. Genius 파서는 `N ContributorsTranslations…Lyrics` 머리말·`…Embed` 꼬리말을 제거함. 멜론은 가사가 AJAX 지연 로드라 정적 스크래핑 불가 → 최하위·graceful None. 기존 설치본은 `_migrate_song_sources_reorder`로 1회 재정렬). **다중 아티스트 폴백**: yt-dlp `artist`는 협업/피처링을 콤마 등으로 이어 붙이는데(예: "NIKI, Phil Collins"), 제공자는 정확한 아티스트명으로 매칭하므로 이 전체 문자열로는 조회가 실패한다. `_run_chain`은 각 제공자에 **전체 아티스트 → 주(첫) 아티스트(`_primary_artist` — 콤마/`;`/`/`/`&`/`feat`/`ft`/`with`/`x`로 분리) 순으로 재시도**해 유명곡 가사를 놓치지 않는다(표시용 아티스트 값은 원본 전체를 보존). **가사 검색 기준값은 현재 노래 정보에 입력된 값(가수·제목·앨범 — 수동 편집 포함)을 최우선**으로 쓴다. **사용자가 항목을 한 번이라도 수정했으면(`manual_fields` 존재) 입력된 값만으로 검색하고, 빈 항목은 채우지 않는다**(영상 제목을 song_title 기본값으로 억지로 넣어 검색이 실패하던 문제 해결 — 예: 가수를 비우면 제목만으로 검색). **수정한 적이 없을 때만(자동 첫 조회) 영상 제목을 파싱**해 부족분을 보완한다. 따라서 제목·가수를 고친 뒤 ⟳를 누르면 그 값으로 다시 검색한다. 새 출처를 추가하면 자동으로 체인에 편입돼 정보를 보강한다(설정 화면에서 관리). **비한국어 가사는 `deep-translator`로 한글을 병행 표기**(원문+번역 `LyricsLine`); 한국어 가사(한글 비율≥0.3 감지)나 번역기 미설치 시 원문만. **등록·"노래로 표시" 토글·상세 최초 진입 시엔 영상 제목 기준으로 메타데이터(가수·앨범·제목·발매년도)만 채운다**(가사 네트워크 조회 생략 — `FetchSongInfoCommand.fetch_lyrics=False`; `SongViewModel.toggle_song`/`load(dto 없을 때)`). **가사는 '가사' 레이블 옆 가사 검색 버튼을 눌러야만 조회**한다(자동 조회 안 함). 가사가 이미 있으면 검색 버튼은 **현재 출처의 다음 출처**부터 순환 조회하고(`FetchSongInfoCommand.from_source_name` → `_run_chain`이 그 출처 다음부터 회전, 끝→처음 순환; 출처명은 `src.name`으로 저장해 정확 매칭; `force_lyrics=True`로 수동편집 가드 우회해 새 가사로 교체), 가사가 없으면 처음부터 조회(`refresh`). 옆의 **번역 버튼**은 현재 등록된 가사를 한글로 (재)번역해 저장한다(`TranslateSongLyricsCommand`/`TranslateSongLyricsHandler` — 조회와 분리된 독립 동작, `SongInfoAggregate.set_lyrics_translations`로 출처 유지·수동표시 안 함, 한국어면 no-op). **사용자가 더블클릭 편집한 필드는 `manual_fields`에 기록돼 갱신 시 덮어쓰지 않는다**(`SongInfoAggregate.apply_fetched`가 manual 필드를 건너뜀). 가사 제공자·번역기는 `domain/song/ports.py`의 Protocol(`ILyricsProvider`·`ITranslator`)에 의존하고 composition root가 구체 구현을 주입한다. Genius·국내 사이트 스크래퍼는 사이트 구조 변경에 취약하므로(그래서 켜고/끄기·순서 조정 가능) 실패는 격리돼 다음 출처로 이어지고 등록/재생에 영향을 주지 않는다. **같은 가수/앨범 필터**: 노래 탭 가수·앨범 값의 `»` 아이콘 → `ISongRepository.find_video_ids_by(artist=/album=)`(is_song=1 매칭)로 video_id를 구해 기존 `GetVideos(video_ids=)`로 조회, 상세화면 우측 목록을 그 결과로 교체(헤더 "가수/앨범: XXX"). **상세 우측 목록은 재생목록**으로 동작 — 현재 영상 포함·강조, `InlinePlayer.playback_finished`(EndOfMedia)에 다음 항목 자동재생(끝이면 정지). 진입 시 재생 전에는 목록과 동일한 썸네일을 포스터로 보여준다. **가수/앨범 필터 재생목록에서 마우스 뒤로가기**는 `LibraryPanel._playlist_ctx`(items·header·prev_related·history)를 두고 `_playlist_back`으로 재생 이력(history 스택)을 되짚어 이전 재생 항목을 열고(재생 중이면 이어재생), 이력이 소진되면 진입 직전 "연관 영상" 목록으로 복귀한다(재생목록 내 이동은 `push_nav=False`라 화면 히스토리를 오염시키지 않음).
- **피드/채널 메타데이터 보강** — yt-dlp `extract_flat`은 구독 피드·채널 영상의 게시일·조회수를 주지 않으므로(영상 ID·길이만), `GetSubscriptionFeedHandler`·`GetChannelVideosHandler`가 YouTube Data API `videos.list`(`get_videos_channels`, part=snippet,statistics,contentDetails)로 `published_at`(ISO)·조회수·길이를 보강한다. 채널 카드의 "최근 영상" 시점은 채널 업로드 재생목록 첫 항목(`get_latest_upload_dates`, 채널당 1쿼터·스레드풀 병렬)으로 구한다. **`_yt_api`(OAuth) 미설정 시 graceful**: 시간 미표시 + 채널은 이름순 정렬.
- **GUI on main thread** — all network/download work runs in background `QThread`; results communicated via Qt signals.
- **yt-dlp progress hooks** → `DownloadProgress` value object → emitted as Qt signal to update progress bar.
- **Aggregates own state changes** — e.g., `VideoAggregate.mark_watched()` not `video.watched = True`.
- **Repositories are interfaces in `domain/`** — GUI and Application layers depend on abstractions; SQLite is an implementation detail.
- **Domain Events over direct calls** — when a download completes, `DownloadCompleted` event triggers library update and UI notification independently.
- **ffmpeg resolved via `get_ffmpeg_path()`** — checks `bin/` first (bundled), falls back to system PATH.
- **Ports over concrete infra in application** — application 레이어는 `EventBus`/`YtDlpAdapter`/`FfmpegAdapter`를 직접 import하지 않고 `domain/shared/ports.py`의 Protocol(`IEventBus`·`IMediaSource`·`IClipExtractor`)에 의존한다. 어댑터는 구조적 타이핑으로 이를 만족(상속 불필요)하며, 구체 인스턴스 주입은 composition root(`main.py`)가 담당한다. 작업별 진행률 훅이 필요한 다운로드처럼 인스턴스를 새로 만들어야 하는 경우는 **팩토리 콜백을 주입**한다(`make_downloader`, `yt_api_factory`).
- **자동 업데이트(백그라운드 다운로드 + 종료 시 설치)** — 시작 시 조용히 확인(`UpdateController.check_silently`, `AUTO_UPDATE_CHECK`+1시간 간격)해 새 버전이 있으면 **사용자 조작 없이 백그라운드로 다운로드**(`UpdateDownloadWorker`)한다. 완료되면 `gui/updater/pending.py:write_pending_update`가 `<tempdir>/ovc_pending_update.txt`(2줄: 인스톨러·exe) 마커를 기록하고(**앱 종료는 안 함**) `update_ready` 시그널을 방출 → `MainWindow`가 **설정 기어 버튼에 빨간 점 배지(`_NavButton.set_badge`)+"업데이트 준비 완료" 툴팁**을 표시하고 설정 헤더에 '지금 설치' 버튼을 노출한다. 실제 설치는 **앱을 닫을 때** `main.py` 종료 tail이 마커를 읽어 조용히 설치 후 재실행(설치는 실행 중 불가하므로). '지금 설치'는 `install_now`가 앱을 종료(마커가 이미 있으므로)해 즉시 설치를 유도한다. 다운로드 실패는 폴백으로 배지만 표시(다음 확인에서 재시도). 마커 기록은 `UpdateDialog`(수동 경로)와 공유한다.
- **Gemini AI 요약 자동 메모 저장** — `DownloadSettings.capture_gemini=True`이면 다운로드 완료 후 `GeminiExtractor`(Playwright sync API)가 YouTube 페이지에서 요약 텍스트를 추출하고, `AddVideoHandler`를 통해 라이브러리 영상 `notes` 필드에 저장한다(`initial_notes` — 기존 메모가 비어있을 때만 덮어씀). 추출 실패는 완전히 격리돼 다운로드 결과에 영향을 주지 않는다. `infrastructure/browser/gemini_extractor.py`는 반드시 QThread에서만 호출한다. **패키징(PyInstaller) 빌드에는 Playwright의 Chromium 바이너리가 번들되지 않는다**(spec이 playwright 브라우저를 수집하지 않음 → `BrowserType.launch: Executable doesn't exist …chrome-headless-shell.exe`). 따라서 `_launch_browser()`는 시스템 설치 브라우저를 `channel="chrome"`→`"msedge"` 순으로 우선 실행하고, 둘 다 없을 때만 번들 Chromium으로 폴백한다(대상 사용자 대부분이 Chrome/Edge 보유 → 150MB 브라우저 번들 회피). 쿠키 소스(인증)와 실행 브라우저는 별개다. **"질문하기" 버튼 클릭은 채팅 패널을 여는 것일 뿐 자동 요약이 아니다** — 실제 요약을 얻으려면 패널 안의 "동영상을 요약해 줘" 추천 칩을 다시 클릭해야 한다(`_click_and_extract`). 응답은 스트리밍으로 채워지므로 고정 지연 대신 칩을 감싸는 컨테이너(칩에서 6단계 조상으로 추정)의 `innerText`가 `_STABLE_REQUIRED_COUNT`회 연속 동일할 때까지 폴링해 완료를 판단한다(`_wait_for_stable_text`). 실패 시 `LOG_DIR/gemini_debug.png`·`gemini_debug.html`에 진단 스냅샷을 남긴다. **Gemini가 자동화 브라우저를 감지해 "문제가 발생했습니다" 오류로 요청을 거부하는 사례를 확인**했다 — 헤드리스 Chromium에 `--disable-blink-features=AutomationControlled` 인자와 `navigator.webdriver` 오버라이드 init script로 완화하고, 오류 문구(`_ERROR_PHRASE`) 감지 시 칩을 최대 `_MAX_ERROR_RETRIES`회 재클릭한다. **`get_by_text`로 잡은 요소가 텍스트 span/div일 뿐 실제 클릭 핸들러가 걸린 button이 아니어서 클릭이 씹히는 사례를 확인** — 클릭 전 `xpath=ancestor-or-self::button[1]`로 진짜 버튼 조상을 우선 사용하고, 클릭 전/후 패널 텍스트가 동일하면(=클릭 미반영) 재시도 후에도 그대로면 실패로 처리한다(정적 인사말을 성공으로 오인하지 않도록). **인증은 쿠키 파일(Netscape 포맷)로만 이루어진다.** 확보 우선순위: 1) 설정 화면 "구독 피드 — 브라우저 쿠키" 섹션의 "또는 쿠키 파일"(`YT_AUTH_COOKIEFILE`), 2) `data/auth/youtube_cookies.txt`(수동으로 파일을 두었을 때만 — `gui/dialogs/youtube_auth_dialog.py`의 `YouTubeAuthDialog`(Playwright 로그인으로 이 파일을 생성)는 **현재 앱 어디에서도 열리지 않는 미연결 코드**이니 존재하는 UI로 안내하지 말 것), 3) 같은 설정 섹션의 "브라우저"/"프로필" 드롭다운(`YT_AUTH_BROWSER`/`YT_AUTH_PROFILE`)을 `GeminiExtractor._export_browser_cookies()`가 yt-dlp `cookiesfrombrowser`로 임시 내보내기(Firefox 등 대부분 브라우저에서 동작; 임시 파일은 Netscape 헤더로 미리 초기화해야 yt-dlp의 cookiejar 최초 로드가 실패하지 않음). **Chrome v127+ 예외**: Chrome은 쿠키를 App-Bound Encryption으로 암호화해 프로필 직접 실행·프로필 파일 복사·yt-dlp `cookiesfrombrowser` 세 가지 방식 모두 외부 프로세스가 복호화할 수 없음을 확인했다(DPAPI 오류) — Chrome 사용자는 방법 1(쿠키 파일 직접 등록)만 유효하다.
- **영상 검색 (부분 일치)** — `SqliteVideoRepository._build_search_sql`이 **제목·태그·설명·메모·요약·노래(가수/앨범/제목/발매년도)·가사**를 부분 일치(`LIKE ... ESCAPE ''`)로 덮는다. 과거에는 `videos_fts`(FTS5)가 **제목·메모 두 열만** 덮었다. FTS5 대신 부분 일치를 쓰는 이유: ① 한글은 어미가 붙어 단어 단위 매칭이 자주 빗나간다 ② 어느 속성이 일치했는지 판정이 정확하다 ③ 규모가 작다(영상 수백 건). **가사는 절대 SQL `LIKE`로 다루지 않는다** — `lyrics_json`이 `[{"o":원문,"t":번역}]` 형태라 검색어 `o`·`t`가 JSON 키에 걸려 모든 노래를 오탐한다(회귀 테스트 `tests/integration/test_search_fields.py::TestLyricsJsonFalsePositive`로 고정). 일치 속성은 `match_fields_for(video_ids, text)`가 **현재 페이지 50건에만** 실행해 `MATCH_FIELD_KEYS` 순서로 반환하고, `VideoDTO.match_fields`로 실려 `VideoListModel.MatchFieldsRole`을 거쳐 그리드·리스트 델리게이트가 배지로 그린다(`_paint_match_badges`, 높이 `_MATCH_ROW_H`는 리플로우 방지를 위해 항상 확보). 한글 라벨(`MATCH_FIELD_LABELS`)은 GUI만 갖는다. `LIKE '%...%'`는 인덱스를 타지 않으므로 라이브러리가 수만 건이 되면 통합 FTS 테이블로 되돌리는 것이 맞다. `videos_fts`와 트리거는 `test_merge_applier.py`가 동기화 병합 후 발화를 검증하는 데 쓰므로 **제거하지 않았다**.
- **단일 인스턴스 가드** — `gui/single_instance.py`의 `SingleInstanceGuard`(QLocalServer/QLocalSocket)가 앱 중복 실행을 막는다. `main.py`가 **DB를 열기 전에** `try_acquire()`를 호출해 두 프로세스가 같은 DB를 동시에 건드리지 않게 하고, 이미 실행 중이면 기존 창을 앞으로 부른 뒤 조용히 종료한다. 서버 이름은 사용자별(`ovc-single-instance-<username>`)이며 비정상 종료로 남은 소켓은 `removeServer()`로 회수한다. **업데이트 후 2개 실행의 근본 원인은 `packaging/installer.iss`의 `[Run]`에 `skipifsilent`가 없어 무인 설치에서도 Inno가 앱을 실행한 것**이었다(배치의 `start`와 중복). **재실행 주체는 배치 하나로 고정한다** — 배치는 구버전 앱이 만들고 인스톨러는 신버전이라, 양쪽을 모두 막으면 다음다음 업데이트에서 아무도 앱을 실행하지 않는다.
- **등록 시 요약·가사 자동 보강** — **단건 등록**(`LibraryViewModel.add_video`)이 끝나면 `EnrichVideoHandler`(application/library/commands.py)가 `song_info.is_song`을 읽어 한쪽만 채운다: 노래 영상이면 `FetchSongInfoCommand(fetch_lyrics=True)`로 **가사만**(가수·앨범·제목·발매년도는 등록 시 이미 채워졌고 체인은 빈 값만 채우므로 실질적으로 가사만 추가된다), 아니면 `ISummarySource.extract`(=`GeminiExtractor`)로 **요약**(`gemini_summary`)을 채운다. **가사를 못 찾아도 요약으로 폴백하지 않는다.** 이미 값이 있거나 추출기가 미주입이면 `kind="skipped"`로 건너뛴다. 설정 `AUTO_ENRICH_ON_ADD`(기본 ON)로 끌 수 있다. **재생목록·채널 일괄 임포트는 대상이 아니다** — 그 경로들은 `AddVideoHandler`를 직접 호출하고 ViewModel을 지나지 않으므로 자연히 제외되며, Gemini가 영상당 브라우저를 띄워 수십 초 걸리기 때문에 의도된 제외다. 보강은 `_EnrichWorker`(QThread)에서 **동시 1건**으로 직렬화한다(`_pending_enrich` 큐 — 브라우저 병렬 실행 방지). 진행·실패는 `MainWindow` 상태바에 표시하고(`enrich_started`/`enrich_finished`), 완료 시 그 영상 상세가 열려 있으면 `_reload_detail_in_place`로 재로드한다(상세 DTO+노래 정보를 함께 다시 읽어 요약 탭·노래 탭 모두 반영). `ISummarySource`는 `domain/shared/ports.py`의 Protocol이라 application 레이어가 infrastructure를 직접 import하지 않으며, 반환형은 실제 구현에 맞춰 `str | None`(실패 시 falsy)이다. 모든 실패는 `EnrichVideoResult(ok=False)`로 변환돼 등록 결과에 영향을 주지 않는다.
- **클라우드 동기화 캡처 (레코드 단위 oplog CRDT, 구현 중)** — 변경은 **리포지토리 경계에서 캡처**한다: `RecordingVideoRepository`가 `SqliteVideoRepository`를 상속해 `save`/`delete`만 오버라이드하고, super()로 라이브 DB에 반영한 뒤 `OplogRecorder`가 (이전 행 vs 새 값) diff로 **바뀐 필드만** op에 담아 로컬 세그먼트(`DATA_DIR/sync/pending/<install>/NNNNNN.ndjson`)에 append한다. 병합 레지스터 상태는 **로컬 전용** 테이블 `sync_identity`(자연키↔로컬 UUID + presence)·`sync_field_clock`(필드별 (lamport,install) 승자)·`sync_applied_ops`(멱등)에 materialize한다(동기화 대상 아님, `db/schema.sql`에 정의, 컴팩션 시 로그로 재생성 가능). `database.py`의 `MIGRATION_IDS` 상수가 "이 코드가 아는 스키마 능력"이며, 원격 op/스냅샷의 `schema_ids`가 이 집합을 벗어나면 `SnapshotStore`가 `SyncSchemaError`로 차단한다("앱 업데이트 필요"). 자격증명·install_id·lamport는 **DB 밖**(keyring, 부재 시 파일 폴백)에 둔다 — 시작 pull이 DB를 열기 전 접근해야 하기 때문. view_count 등 churn 필드·description(지연 로드)는 현재 캡처 제외. 캡처 엔티티는 **Video + video_tag 링크 + song_info**(Phase D-1)까지 확장됐다: 링크(조인 행)는 자체 필드가 없어 `record_link`/`record_unlink`가 presence-aware로 기록하고 양 끝점을 refs로 실어 보낸다(presence-only op은 merge writes가 비어 미반영되므로 refs 필수). **태그는 별도 op 없이** video_tag LINK op의 tag 이름 ref로부터 apply 측 `resolve_tag`가 lazy 생성한다(bare 태그 op이 sync_identity에 dangling UUID를 만들지 않도록). song_info는 Video와 1:1이라 nkey=영상 URL 키. **category는 origin-identity(install+uuid)로 캡처**(Phase D-2a) — nkey가 rename에도 불변이라 rename이 필드 변경으로 올바르게 전파된다(이름경로 방식 폐기). video의 category 참조도 이름경로가 아니라 카테고리 origin nkey를 쓰며, apply 측 `resolve_category`는 origin nkey→로컬 UUID 해석(없으면 stub 생성해 배치 내 순서·FK 보장, 동명 카테고리 독립 생성 시 병합). clip·download는 origin-identity 단일 테이블(clip은 source_video ref). playlist·playlist_folder는 origin-identity, playlist_item·category_video_order·video_tag는 링크(멤버십만 동기화 — **수동 정렬 순서는 기기 로컬**, 적용 측이 append). **이제 전 엔티티 캡처/적용 완료(Phase D-2b)**. **캡처는 composition root(`main.py`)에 배선됨(Phase E) — 단 provider가 연결된 상태로 시작했을 때만** `SyncService.make_recording_repos`가 repo를 Recording*로 교체한다(미연결이면 무래핑 → 기존 앱 동작 무변경, oplog 미적재). 최초 연결 시 `SyncService`가 현재 DB를 스냅샷으로 push, 캡처는 다음 실행부터 활성. 시작 시 `pre_db_bootstrap()`(DB 열기 전)로 신규 기기는 스냅샷 부트스트랩, 기동 후 `sync_vm.start_auto_sync()`가 주기 push/pull+미디어 동기화.
- **미디어/썸네일 파일 동기화 (oplog와 별개 서브시스템, 구현 중)** — oplog는 **메타데이터만** 다루므로 실제 다운로드 파일·썸네일 바이트는 `infrastructure/sync/file_syncer.py`가 provider 위에서 별도로 왕복시킨다. **파일 identity의 진실원천 = sha256**(우리 `media/manifest.json`) — provider 네이티브 체크섬(Drive md5/OneDrive quickXorHash)은 교차 비교 불가라 안 쓴다. rel_path는 **DATA_DIR 기준 상대경로(POSIX)로 DB의 file_path 규약과 동일**해, 다운로드하면 `resolve_media_path`가 가리키는 위치에 바로 놓인다(DATA_DIR 밖 파일은 이식 불가라 스캔 제외 — Phase 0 규약과 일치). 재해시 회피: 이전 스캔 매니페스트를 캐시로 두고 size+mtime이 같으면 sha256 재사용. 계획은 순수 함수 `plan_file_sync`(로컬만→upload/원격만→download/sha다름→`prefer` 정책 "newer"(mtime 큰 쪽·동률 로컬)|"local"|"remote"), **삭제는 전파하지 않음**(어느 쪽에만 없는 건 미동기화로 봄). 다운로드는 `<name>.part`로 받은 뒤 `os.replace`로 원자 확정, 원격 매니페스트는 read-merge-write로 동시 추가 보존. `on_progress(MediaSyncProgress)`·`should_cancel` 콜백만 노출하고 **QThread 배선은 Phase 5(GUI)**가 감싼다. (원격 레이아웃: `media/manifest.json` + `media/files/<rel_path>`)
- **클라우드 provider 어댑터 (로컬 폴더 / Google Drive / OneDrive)** — `application/sync/ports.py`의 `ICloudSyncProvider` Protocol을 구조적으로 만족하는 세 백엔드. **`FolderProvider`(로컬 폴더=클라우드, 기본·권장)**: OneDrive/Drive 데스크톱 동기화 폴더를 가리키면 OS 클라이언트가 실제 왕복을 담당해 OAuth·API키가 필요 없다. `SyncState.folder_path`에 경로 영속, `provider_key="folder"`. 설정 UI에서 폴더 선택만으로 연결(`SyncService.connect_folder`). 이 provider로 **실 스택 end-to-end 테스트**(실 DB·캡처 repo·oplog·스냅샷 부트스트랩·실제 미디어 바이트)를 실계정 없이 수행한다(`tests/integration/test_folder_provider_e2e.py`, `tests/gui/test_sync_gui.py`). Google Drive/OneDrive API provider는 직접 연동을 원하는 사용자용. HTTP는 공용 `infrastructure/sync/rest_client.py`(requests + `verify=False` + 401 강제refresh 후 1회 재시도 — `youtube_api_adapter` 패턴 추출)로 하고, 토큰 획득/갱신은 provider별 콜백(`token_provider`/`force_refresh`)으로 주입한다. **Google Drive**는 파일 ID 모델이라 경로 기반 저장소(`oplog/...`, `media/...`)를 앱 루트 폴더 아래 폴더 트리로 **에뮬레이션**한다(경로→id 캐시로 중복 폴더 생성 방지), 인증은 `InstalledAppFlow`(scope `drive.file`), resumable 업로드 세션(청크 PUT, 308은 `allow_redirects=False`로 따라가지 않음). **OneDrive**는 Graph 경로 주소지정(`/me/drive/root:/<path>`)이라 훨씬 단순하며, msal `PublicClientApplication`+`SerializableTokenCache`(keyring 직렬화), 소형은 PUT `/content`·대형은 `createUploadSession`. 자격증명은 keyring(부재 시 파일)에 두고 `msal`은 지연 import라 미설치여도 모듈 import는 된다. **실계정 OAuth 왕복 검증은 로컬 전용(미완)** — 테스트는 in-memory fake HTTP로 401 재시도·경로/쿼리·URL 빌드·폴더트리·페이지네이션·텍스트/목록/삭제 왕복만 검증한다(`tests/integration/test_sync_providers.py`). provider **연결 UX**(설정 화면 OAuth 버튼)는 Phase 5.
- **컴팩션 + 스냅샷 부트스트랩 (구현 중)** — 오래된 op 로그를 무한히 재생하지 않도록 `CompactHandler`(application/sync/commands.py)가 현재 DB를 `snapshot_store.export_snapshot`(VACUUM INTO)으로 스냅샷 떠 provider에 `snapshot/library.db` + `snapshot/snapshot.json`(covered={install:seq}·schema_ids·db_sha256)로 발행한다. **covered = consumed ∪ {our_install: pushed_head}** — 스냅샷 DB가 반영한 각 install의 마지막 seq. 신규 기기는 시작 시 `infrastructure/sync/bootstrap.py:bootstrap_if_fresh`가 **DB를 열기 전(pre-DB)** 스냅샷을 받아 sha256 검증 후 `import_snapshot`(integrity+스키마 게이트+교체)하고 `consumed=covered`로 세팅한 뒤 이후 증분 pull한다. **부트스트랩은 로컬 DB가 없을 때만**(스냅샷 교체가 로컬 미병합 상태를 덮으므로) — 기존 기기가 뒤처지면 증분 pull로 따라잡는다. 세그먼트 **GC는 CompactHandler에서 기본 비활성**(`gc=False`): 스냅샷이 덮은 세그먼트를 지우면 뒤처진/휴면 install은 증분 pull로 회수 못 하고 스냅샷 부트스트랩에 의존하므로, 완전 안전 GC는 활성 install들의 consumed 워터마크 공유가 필요하다(열린 결정). 스냅샷 DB에는 sync_* 레지스터 테이블도 포함돼 새 기기가 일관된 필드 클럭·멱등 상태를 그대로 물려받는다.
- **미디어 경로 이식성 (머신 간 동기화 대비)** — `download_history.file_path`·`clips.file_path`·`clips.thumbnail_path`는 DB에 **DATA_DIR 기준 상대경로(POSIX 구분자)로 저장**하고, 런타임 엔티티에는 절대경로로 복원해 담는다. 변환은 **리포지토리 경계**에서만 일어난다 — `SqliteDownloadRepository`·`SqliteClipRepository`가 `save` 시 `config.settings.to_portable_path()`로 상대화, `_row_to_*` 로드 시 `resolve_media_path()`로 절대화한다(`delete_completed_duplicates`처럼 raw SQL로 경로를 읽는 지점도 resolve 적용). 따라서 application·gui·query 레이어는 예전과 동일하게 **절대경로**를 받으므로 수정할 필요가 없다. DATA_DIR 밖의 경로(사용자가 별도 위치 지정)는 이식 불가라 절대경로 그대로 보존한다. 기존 절대경로 DB는 `database.py`의 멱등 마이그레이션 `migrate_media_paths_relative`가 1회 정규화한다. (`videos.thumbnail_path`는 원래부터 `THUMBNAIL_DIR` 기준 상대경로라 이 규약 밖 — 읽는 쪽이 `Path(THUMBNAIL_DIR)/rel`로 결합.)
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
