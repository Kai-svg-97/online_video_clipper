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
│   │   └── ports.py                 # IEventBus·IMediaSource·IClipExtractor·ILibraryPackageWriter·ILibraryPackageReader(Protocol) — application이 의존하는 포트
│   ├── library/                     # [Bounded Context] Core: video library management
│   │   ├── entities.py              # Video, Category, Tag
│   │   ├── value_objects.py         # VideoUrl, Duration, Timestamp, ChannelInfo
│   │   ├── aggregates.py            # VideoAggregate (root)
│   │   ├── repositories.py          # IVideoRepository (interface)
│   │   ├── services.py              # Domain services (e.g., duplicate detection)
│   │   ├── recommendation.py        # derive_seed_queries() — 현재 목록(제목·태그·채널)에서 YouTube 추천 검색어를 뽑는 순수 함수(제목 키워드는 문서빈도 기준). **`search_text`가 있으면 그 낱말만 검색어로 쓴다**(검색창 입력이 짐작을 대체한다). I/O 없음
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
│       ├── value_objects.py         # LyricsLine(원문+한글번역+`start_ms: int | None` — LRC 타이밍, 없으면 자막 비활성), SongSourceRef
│       ├── entities.py              # SongInfo(가수·앨범·제목·발매년도·가사·is_song·manual_fields·`lyrics_offset_ms`(자막 싱크 보정)·`is_synced` 프로퍼티(시각 있는 줄 존재 여부)) + LyricsSource(출처 레지스트리)
│       ├── aggregates.py            # SongInfoAggregate — apply_fetched(수동편집 보존)·edit_field·edit_lyrics(줄 수 같으면 기존 타이밍 유지)·set_lyrics_offset(±30초 clamp, 공개 상수 `MAX_LYRICS_OFFSET_MS`)
│       ├── repositories.py          # ISongRepository (+ 가사 출처 CRUD)
│       ├── album.py                 # 앨범 그루핑 순수 규칙 — normalize_name·make_album_key(자리표시자 "null" 제외)·album_key_artist(키 형식을 아는 유일한 곳)·group_songs_into_albums·match_track_to_songs·**earliest_registered**(앨범 식별의 앵커 = 가장 먼저 등록한 곡)·**pick_official_audio**(자동 채우기 후보 검증 — 커버·리액션·1시간 루프·동명이곡 배제. **가수 일치는 점수가 아니라 통과 조건**)·link_artist_matches(저장된 매핑 재검증). I/O 없음
│       ├── album_repository.py      # IAlbumRepository + AlbumCacheRecord·AlbumTrackLink (파생 캐시 저장소 인터페이스)
│       ├── ports.py                 # ILyricsProvider(`fetch` 1건)·**ILyricsSearchProvider**(`search` 다건 — 후보 목록용 선택 확장)·ITranslator(Protocol) + LyricsResult(`popularity`=출처 조회수 0이면 지표 없음, `duration_sec`=곡 길이) + `DEFAULT_LYRICS_SEARCH_LIMIT`(출처당 후보 상한, 0=무제한)
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
│       ├── dtos.py                  # SongInfoDTO, LyricsLineDTO, LyricsSourceDTO, **LyricsCandidateDTO**(가사 검색 후보 1건 — 출처·가수·제목·첫 줄·싱크여부 + 채택용 lines/timings 동봉)
│       ├── commands.py              # FetchSongInfo(출처 체인+번역), **SearchLyricsCandidates**(전 출처 훑기, 도착 순 콜백)·**ApplyLyricsCandidate**(고른 후보 반영), UpdateSongField/Lyrics, SetSongFlag, 가사출처 CRUD. 공용 헬퍼 `resolve_search_basis`(검색 기준값)·`artist_search_candidates`(전체→주 아티스트)·`build_lyrics_lines`(번역 포함 줄 생성)를 체인/후보 양쪽이 공유
│       ├── album_dtos.py            # AlbumCardDTO·AlbumTrackDTO·AlbumDetailDTO + TRACK_ORIGIN_LIBRARY/AUTO/MISSING
│       ├── album_queries.py         # GetAlbums(네트워크 없음)·GetAlbumDetail(외부 조회+캐시)·FillAlbumTracks(빠진 곡 yt-dlp 검색)·ResolveUnknownAlbums(앨범 추정)
│       └── queries.py               # GetSongInfo, ListLyricsSources
│   └── sync/                        # 클라우드 동기화 유스케이스 — 구현 중
│       ├── ports.py                 # ICloudSyncProvider·IOplogStore·ISnapshotStore·ISecretStore (Protocol) + RemoteFile
│       ├── commands.py              # Push·Pull·SyncNow·ConnectProvider·DisconnectProvider·Compact 핸들러(스키마 게이트 포함). CompactHandler=DB→스냅샷 export→provider 업로드(snapshot/library.db+snapshot.json covered)+선택적 세그먼트 GC(기본 off)
│       └── queries.py               # GetSyncStatus → SyncStatusDTO
│   └── transfer/                    # 라이브러리 가져오기/내보내기(카테고리 단위 zip 패키지)
│       ├── dtos.py                  # ImportCategoryOptionDTO·ImportPreviewDTO·ImportFieldDiffDTO·ImportConflictDTO(s)·ImportResultDTO·ExportResultDTO
│       └── commands.py              # ExportLibraryHandler·PreviewImportHandler·DetectImportConflictsHandler·ImportLibraryHandler — 값 해석(zip)은 domain.shared.ports의 ILibraryPackageWriter/Reader에 위임
│
├── infrastructure/                  # Concrete implementations (invert dependencies)
│   ├── persistence/
│   │   ├── database.py              # SQLite 연결 + WAL 설정 + 스키마 마이그레이션
│   │   ├── sqlite_video_repository.py
│   │   ├── sqlite_download_repository.py
│   │   ├── sqlite_clip_repository.py
│   │   ├── sqlite_channel_repository.py
│   │   ├── sqlite_playlist_repository.py  # 재생목록 + 폴더 저장소
│   │   ├── sqlite_song_repository.py      # song_info(가사 JSON) + lyrics_sources 저장소
│   │   └── sqlite_album_repository.py     # album_cache·album_track_links·album_lookup_state (앨범 파생 캐시 — 동기화 대상 아님)
│   ├── downloader/
│   │   └── ytdlp_adapter.py         # yt-dlp 래퍼 — domain.shared.ports.IMediaSource를 구조적으로 만족
│   ├── ffmpeg/
│   │   └── ffmpeg_adapter.py        # ffmpeg wrapper for clip extraction
│   ├── browser/
│   │   └── gemini_extractor.py      # Playwright 기반 YouTube Gemini AI 요약 추출기 (QThread에서만 호출)
│   ├── auth/
│   │   └── youtube_auth.py          # 브라우저 프로필 탐지 + Netscape 쿠키 추출 (playwright 로그인)
│   ├── youtube/
│   │   ├── oauth_adapter.py         # OAuth 2.0 Desktop/PKCE 인증 플로우(무인자 `run_auth_flow()`) + keyring 우선 토큰 저장(레거시 SQLite 1회 마이그레이션) + 정상 TLS 검증 리프레시
│   │   ├── oauth_client_config.py   # 번들/로컬 Desktop OAuth 클라이언트 JSON 탐색·검증(`find_youtube_oauth_config`) — 값은 절대 반환/로그하지 않음
│   │   └── youtube_api_adapter.py   # YouTube Data API v3 래퍼 (requests.Session)
│   ├── song/
│   │   ├── lyrics_providers.py      # LRCLIB(무키)·Genius·멜론·벅스·지니 가사 제공자 + build_default_providers (QThread에서만 호출). **모든 제공자가 `search()`(다건)를 구현**하고 `fetch()`는 `search(limit=1)` 위임이다 — 두 경로의 폴백 범위가 어긋나 "후보 목록엔 뜨는데 체인 검색은 못 찾는" 일이 없게. LRCLIB은 `/api/get`(정확)→`/api/search`(가수+제목)→`/api/search`(제목만) 순으로 훑어 **다른 가수의 같은 제목 곡**까지 모으고, Genius·국내 3사는 검색 페이지에서 곡 id를 `_first_id`로 **전부** 뽑아(예전엔 `re.search`로 첫 개만) 곡마다 상세 페이지를 긁는다(요청 수 = limit이라 상한이 성능을 좌우). 국내 3사 상세 파서는 가사뿐 아니라 **가수·제목도 뽑는다** — 안 뽑으면 후보 행이 전부 같은 값으로 보여 고를 수가 없다. 곡 하나가 실패해도 나머지 후보는 계속 모으고, 중복은 `_dedupe_key`(가수·제목·첫 줄)로 제거한다. **정렬**: Genius는 검색 응답의 `stats.pageviews`로 **조회수 내림차순 정렬을 페이지 요청 *전에*** 한다(limit이 곧 요청 수라, 나중에 정렬하면 인기 곡이 상한 밖으로 밀려 조회조차 안 된다). LRCLIB은 인기 지표가 없어 **영상 길이에 가까운 순**(`_sort_by_duration_match`)으로 정렬하며, 자르기는 정렬 뒤에 한다(먼저 자르면 정답이 날아간다 — 목록 API라 다 모아도 추가 요청이 없어 공짜다). 국내 3사는 **검색 결과 순서 자체가 그 사이트의 랭킹**이므로 재정렬하지 않고 `popularity=0`으로 둔다. 네트워크 오류(타임아웃·연결실패)는 트레이스백 없이 WARNING으로만 남기고 None 반환→다음 출처로(`_log_provider_error`); 타임아웃 (connect 5s, read 8s)로 짧게 잡아 느린 출처를 빨리 건너뜀
│   │   ├── album_providers.py       # ITunesAlbumProvider(무키) — 앨범 자켓·발매일·장르·수록곡. **lookup에 country를 붙이면 수록곡이 통째로 빠진다**(실측)
│   │   ├── translator.py            # deep-translator 래퍼(ITranslator) — 미설치/실패 시 원문 그대로(graceful)
│   │   └── lrc.py                   # LRC(가사 타이밍) 파서 — `parse_lrc(text) -> [(시작ms|None, 가사)]`. 다중 타임스탬프 전개·`[offset:]` 반영·메타 태그 제거. 순수 함수라 단위 테스트로 규칙을 고정
│   ├── subtitle/                    # 영상 자막(YouTube 캡션) — QThread에서만 호출
│   │   ├── parsers.py               # json3·WebVTT → (시작ms, 끝ms, 텍스트). 순수 함수. 자동 자막의 단어 타이밍 태그 제거 + **밀려 올라가며 반복되는 같은 문장 합치기**(안 하면 화면에 겹쳐 보인다)
│   │   └── youtube_subtitles.py     # 트랙 목록(`list_tracks`)·내려받기(`fetch_cues`)·자동 번역(`translated` → URL에 `tlang=`). **자동 자막 목록에서 번역본(`tlang=` 있는 항목)을 걸러 낸다** — 안 걸러 내면 수백 개가 나열돼 메뉴를 쓸 수 없다(실측 312개). 원본 자동 자막 키는 `en-en` 꼴이라 `en`으로 정규화해 수동 자막과 중복되지 않게 한다
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
│   └── transfer/
│       └── portable_package.py      # ZipLibraryPackageWriter·ZipLibraryPackageReader — manifest.json+data.json+thumbnails/ zip. 값 해석(THUMBNAIL_DIR 절대경로 결합)은 여기서만 한다
│
├── gui/                             # Presentation layer (PyQt6, MVVM)
│   ├── anim.py                      # 짧은 등장 연출 — `fade_in`(비동기 도착 썸네일)·`fade_switch`(화면 전환). **영상이 있는 화면에는 걸지 않는다**(QGraphicsOpacityEffect는 픽스맵 합성이라 비디오 서피스가 검게 비거나 깜빡인다). 효과는 끝나면 반드시 떼어 낸다
│   ├── toast.py                     # 오른쪽 아래 토스트 알림 — 완료 소식만(진행 중은 상태바 담당). 위로 쌓기·클릭 닫기·자동 소멸·상한 4개
│   ├── smooth_scroll.py             # 휠 스크롤 부드럽게 — 픽셀 스크롤 + 180ms 보간. **수정키 휠은 가로채지 않는다**(Ctrl+휠=뷰 전환, Ctrl+Shift+휠=자막 조절). **가로 전용 띠(추천 스트립 등) 판정은 "세로 스크롤 범위가 있는가"가 아니라 "세로 스크롤바 정책이 `ScrollBarAlwaysOff`인가"로 한다**(`_SmoothScroller._pick_bar`) — 카드 높이가 뷰포트보다 몇 px만 커도(폰트 렌더링 차이 등) 숨은 세로 막대에 근소한 범위가 생겨, 예전엔 휠마다 그 막대가 움직이며 화면이 위아래로 덜거덕거렸다(실제 신고 — 추천 영상 스트립). 정책이 꺼져 있으면 범위와 무관하게 가로로 고정한다. `apply_smooth_scroll_tree(panel)`을 화면 조립 뒤 한 번 호출
│   ├── workers.py                   # 실행 중 QThread 안전 보유/은퇴 — `track_thread`(부모 분리 + 레지스트리 보유)·`retire_thread`(**신호 이름**으로 해제 후 끝까지 보유)·`wait_all`(종료 시 대기). 끝난 워커는 참조만 놓는다(deleteLater 금지 — 들고 있는 쪽에서 RuntimeError). **실행 중인 QThread가 파괴되면 Qt가 프로세스를 죽인다**(실측: exit 0xC0000409)
│   ├── single_instance.py           # SingleInstanceGuard — QLocalServer 기반 중복 실행 방지(main.py가 DB 열기 전 호출, 두 번째 인스턴스는 기존 창을 앞으로 부르고 종료)
│   ├── main_window.py               # 루트 윈도우, 사이드바 네비게이션(라이브러리·다운로드·채널 모니터링·통계), 패널 스택 — 구독 피드는 라이브러리 좌측 트리로 통합됨. **통계 채널 섹션 → 카테고리 드릴다운**: `StatsPanel.category_selected` → `_on_stats_category_selected`가 라이브러리로 전환·`navigate_to_category` 후 `_return_to_page=_PAGE_STATS` 예약. 라이브러리 뒤로가기를 소진하면(`LibraryPanel.back_exhausted`) `_on_library_back_exhausted`가 통계로 복귀(라이브러리 자체 히스토리를 먼저 되짚고 소진 시 통계). 다른 페이지로 이동하면 `_on_page_changed`가 예약을 무효화. **등록 후 자동 보강 상태 표시**: `enrich_started`→상태바 "가사 조회 중"/"요약 생성 중"(`_ENRICH_LABEL`), `enrich_finished`→완료(5초)/실패(8초). `kind="skipped"`+ok이면 메시지를 지운다. **사이드바 배경은 `_SideBar.paintEvent`에서 직접 칠한다** — 앱 레벨 QSS의 `QWidget { background-color }`가 위젯 레벨 스타일시트(ID 선택자 포함)를 덮어써 `bg_surface`가 적용되지 않았다(slate에서는 base/surface 차이가 3단위라 미발견). 따라서 사이드바 배경·우측 경계선 색을 바꿀 땐 QSS가 아니라 `paintEvent`를 수정할 것. **상단 ▶ 로고와 계정(인증) 버튼은 제거됨** — 로고는 기능 없는 장식이고, 계정 버튼은 클릭 동작이 바로 아래 기어 버튼과 완전히 동일한 중복이었다(`update_account_status()`도 호출처 없는 죽은 코드여서 함께 삭제, `_SVG_ACCOUNT` 상수도 제거)
│   ├── panels/
│   │   ├── library_panel.py         # **화면 조립(`_setup_ui`)·배선(`_connect_signals`)만** 담당하고 나머지는 아래 `library/` 패키지로 나뉘었다(7,593→863줄). 썸네일 그리드 + 카테고리/재생목록 트리 + 상세뷰 + YouTube 트리의 "구독 채널"/"전체 구독 피드" 노드. 영상 카드 **단일 클릭→상세화면**(미리보기 패널 제거됨, Ctrl/Shift 클릭은 다중선택 유지). 피드/채널 카드 단일 클릭→`_open_stream_detail`(스트리밍 상세). `_open_detail`/`_open_stream_detail`이 컨텍스트별 연관영상(RelatedItem)을 구성해 상세화면에 전달, 연관영상 클릭은 `_on_related_item_selected`로 재진입. **인기/전체 태그 패널(`_tag_section`)은 트리 하단에 일반 세로 레이아웃(`nav_container`)으로 쌓고 카테고리 선택 시에만 표시**(`_set_popular_tags_visible(True/False)`가 섹션 전체를 토글). 재생목록·폴더·섹션루트·피드·채널 선택 시엔 숨겨 트리가 그 공간을 차지한다. (QSplitter로 묶으면 자식 가시성 토글이 레이아웃 thrash→프리징을 유발해 일반 레이아웃으로 교체함.) **트리 노드 클릭 시 상세 화면이면 먼저 목록으로 복귀**(`_leave_detail_if_open`). **뒤로/앞으로 가기는 화면 단위 스냅샷 기반**(`_capture_screen`→`_nav_history`(뒤로)/`_nav_future`(앞으로), `_go_back`/`_go_forward`/`_restore_screen`): kind(category/playlist/folder/feed_all/channel/channels_root)+상세 payload까지 저장해 직전/다음 화면을 정확히 복원(분류 간 교차·상세→상세 연관영상 체인 포함). **마우스 ‹/›는 화면이 보이는 동안 앱 전역 이벤트 필터가 받는다**(`NavigationMixin.showEvent`/`hideEvent`+`_handle_history_mouse`) — 예전엔 목록 뷰·앨범 위젯에만 필터를 걸어 좌측 트리·피드 카드·태그 패널·빈 공간에서는 조용히 죽었다(위젯을 추가할 때마다 배선을 잊으면 또 죽는다). 판정 기준은 위젯 목록이 아니라 **같은 창 안의 클릭인가**이며, 모달 대화상자가 떠 있으면 넘기지 않는다. 상세 화면(`_nav_stack` 1) 위에서의 ‹는 `_on_detail_back_requested`로 보낸다 — 상세 위젯도 자체 앱 필터로 같은 곳에 보내므로 **어느 필터가 먼저 도느냐와 무관하게** 결과가 같다(›는 상세 위젯이 처리하지 않아 여기서 받는다). 목록·앨범 위젯의 위젯 단위 필터는 **Ctrl+휠 뷰 전환** 때문에 남아 있고, 그래서 휠 분기는 `_is_list_surface(obj)`로 범위를 좁힌다 — 전역 필터가 된 채로 두면 트리·플레이어의 Ctrl+휠(자막 크기)까지 뷰를 바꾼다. 새 분기 이동 시 `_push_nav_state`가 `_nav_future` 비움. 복원 시 `_PlaylistPanel.select_snapshot`로 좌측 트리 강조·브레드크럼을 동기화(시그널 차단해 재실행 방지). 상세 뒤로가기 버튼도 `_on_detail_back_requested`→히스토리 복원. "전체 구독 피드"/개별 채널 클릭→피드 카드 그리드(_VIEW_FEED), "구독 채널" 노드 클릭→채널 아바타 카드 그리드(_VIEW_CHANNELS). **"구독 채널" 노드 우클릭 컨텍스트 메뉴 맨 위에 "⟳ 새로고침 (YouTube 구독 재동기화)"**(`_PlaylistTree.sync_subs_req`→`_PlaylistPanel.sync_subs_req`→`LibraryPanel._on_sync_subscriptions`): `_monitoring_vm.import_from_youtube()`로 YouTube 구독을 로컬 DB에 재동기화한다(구독 목록은 로컬 DB 스냅샷이라 유튜브에서 새로 구독한 채널은 이 새로고침 전엔 안 뜸). 완료 시 `subscriptions_changed`→`_refresh_unified_tree`(트리)와 `import_yt_finished`→`_on_subs_synced`(그리드가 열려 있으면 `_populate_channels_grid` 재구성)로 갱신, 실패는 `error_occurred`→`_on_subs_sync_error`가 상태 라벨에 표기. 그리드 채우기 로직은 `_populate_channels_grid`로 추출돼 노드 클릭·재동기화 완료 양쪽에서 재사용(뷰 전환·nav 히스토리는 `_on_channels_root_selected`만 담당). **좌측 채널 노드는 이름 오름차순 정렬**, 채널 카드는 핸들러가 최신 업로드 내림차순으로 정렬해 전달. 연관영상 meta에도 `_relative_time`으로 등록 시점 표기(로컬 ISO·피드 ISO/YYYYMMDD 모두). **좌측 트리 패널(`_PlaylistPanel`)은 로컬 섹션(상단 고정) + 접을 수 있는 YouTube 섹션 구조**: 이전 수직 `QSplitter`를 제거하고, 로컬 트리 아래에 **삼각형 토글 바(`_yt_bar`: `_yt_toggle_btn`▸/▾ + 빨간 "YouTube" 헤더 + ⟳동기화 + 📂+폴더)**를 두어 그 아래 `_yt_tree`(구독 트리)를 펼치거나 접는다(`_toggle_yt_section`). **YouTube 구독 트리는 기본 접힘(숨김)**. **모든 트리는 로드 후 `collapseAll()`로 최상위(1레벨) 항목만 보이고 하위는 접힌다**(`_PlaylistTree.load`). **트리 행은 `_TreeRowDelegate`가 그린다** — 둥근 pill 행·accent 14% 틴트 선택·카테고리 색상 점·우측 개수 뱃지·즐겨찾기 ★·행 높이 30px. **개수 뱃지가 최우측 고정, ★은 그 왼쪽**이다 — 예전엔 ★이 최우측이라 즐겨찾기 행만 뱃지가 밀려 숫자 열이 들쑥날쑥했다(`tests/gui/test_tree_rows.py::TestBadgeAlignment`가 실제 픽셀로 고정). 항목 팩토리(`_make_category`/`_make_folder`/`_make_unfiled`/`_make_root`/`_make_playlist`/`_make_channel`)가 `_NAME_ROLE`·`_COUNT_ROLE`·`_GLYPH_ROLE`·`_COLOR_ROLE`·`_STAR_ROLE`을 심고 델리게이트는 **롤만 읽는다**(로딩 스피너가 `setText`로 텍스트 뒤에 `⠋`를 덧붙이고 카테고리 이름에 괄호가 들어갈 수 있어 텍스트 파싱은 깨진다). **셰브론·들여쓰기 가이드선은 `drawBranches()` 오버라이드**에 그린다 — 델리게이트(아이템 영역)에 그리면 `QTreeView`가 branch 영역 클릭만 확장으로 처리하므로 펼침이 동작하지 않는다(`tests/gui/test_tree_rows.py`의 QTest 클릭 테스트가 이를 지킨다). 즐겨찾기는 `setBackground` 틴트가 델리게이트에 가려지므로 ★로 표시한다. **칩 색은 `chip_colors(tokens, selected, data_color)`로 토큰에서 파생**한다(과거 `paintEvent`에 `#2a3a4a` 등이 하드코딩돼 어떤 테마를 골라도 칩만 어두웠다 — 인기태그 버튼·태그목록·즐겨찾기 바 3곳). `count == 0` 경고 뱃지(`_BADGE_EMPTY_BG`)와 YouTube 강조색(`_YT_BRAND_RED`)은 의미·브랜드 색이라 테마와 무관하게 고정한다. **태그·카테고리 색상은 `tag_color(name)`**(zlib.crc32 기반) — 이전 `hash(name)`은 PYTHONHASHSEED로 프로세스마다 무작위화돼 앱을 켤 때마다 색이 바뀌었다. **"로컬" 루트 활성 표시**: `_PlaylistPanel.set_local_root_active()`가 `local_hdr`의 체크 상태(QSS `:checked`)를 관리하고, 헤더 클릭 시 두 트리 선택을 `blockSignals`로 감싸 해제한다(이중 실행 방지). 트리 노드 선택 시 비활성(`_connect_tree`가 `currentItemChanged` 배선), `select_snapshot` 복원 시 `matched is None`이면 활성. **검색 일치 속성 배지**는 `_paint_match_badges`가 그리드·리스트 델리게이트 양쪽에서 그린다(`MatchFieldsRole` → `MATCH_FIELD_LABELS`). **검색창 입력은 `_search_timer`로 디바운스**하고(`_on_search_text_changed`/`_apply_search_text`, Enter·지우기는 즉시), **표(상세) 뷰 `_refresh_table`은 그 뷰가 보일 때만** 채운다(`_table_dirty` + `_switch_view` 지연 갱신, 배지는 `_vm.get_downloaded_flags` 일괄 조회). 자세한 배경은 아래 "검색 입력 응답성" 항목 참조. **영상 목록 아래에 추천 영상 스트립**(`_centre_splitter` = 수직 `QSplitter`, 위=`_view_stack` 아래=`RecommendStrip`) — 핸들을 끌어 높이 조절, 스트립 헤더 삼각형으로 본문만 접기. 스플리터 **자식 자체를 숨기지 않으므로** 과거 태그 섹션에서 겪은 레이아웃 thrash가 없다. `setChildrenCollapsible(False)`라 본문을 숨겨도 배분된 높이는 남으므로 `_sync_recommend_sizes(expanded)`가 접을 때 헤더 높이만 남기고 펼칠 때 직전 높이를 복원한다(접힘 상태·높이는 `recommend_strip_expanded`/`recommend_strip_height` 설정에 저장). 자동 갱신은 `_on_videos_changed`→`_schedule_recommend_refresh`(`_recommend_timer`, `_RECOMMEND_DEBOUNCE_MS`=900ms 디바운스)이며 **접혀 있으면 조회하지 않는다**(네트워크 절약). 씨앗은 `_recommend_seeds()`가 현재 페이지 앞 `_RECOMMEND_SEED_LIMIT`(20)건의 제목·채널·태그로 구성한다. `_on_view_stack_changed`가 카드 그리드 뷰(폴더·피드·채널)에서 스트립을 숨기며, 이때 가시성 비교는 `isVisible()`이 아니라 **`isHidden()`**으로 해야 한다(조상이 아직 표시되지 않았으면 `isVisible()`은 항상 False라 첫 전환이 건너뛰어진다). **스트립은 추천 목록이 준비되기 전까지 감춰져 있다**(`_recommend_ready`) — 최종 결과가 오면 `_reveal_recommend_strip`→`_animate_recommend_in`이 높이 0→목표로 키워 아래에서 올라오게 하고, 새 조회가 시작되면 `_hide_recommend_strip`→`_animate_recommend_out`이 다시 접어 감춘다. 목록 뷰로 돌아올 때의 표시 판정에도 `_recommend_ready`가 함께 걸린다(자세한 배경은 아래 "추천 영상 스트립" 항목). 상세화면을 열 때는 `_recommend_related_items()`로 같은 결과를 `VideoDetailWidget.set_recommendations`에 넘겨 우측 목록 아래에 붙인다(FeedVideoDTO→RelatedItem 변환은 피드 목록과 공유하는 `_related_from_feed`)
│   │   ├── library/                 # ⬆ library_panel의 부품·동작 (분할 결과)
│   │   │   ├── constants.py         # 뷰 인덱스(_VIEW_*)·MIME·아이템 롤·썸네일 크기·의미 색. **로직 없음**(부품끼리 서로 임포트하지 않게 하는 허브)
│   │   │   ├── formatting.py        # `_relative_time`·`_fmt_views`·`tag_color`(zlib.crc32 — 실행마다 색이 바뀌지 않게)·`chip_colors`·`_url_from_mime`(브라우저별 URL MIME 흡수)
│   │   │   ├── thumbnails.py        # `_ThumbnailCache`(표시 크기별 LRU)·`_load_thumb`·`_ThumbBgLoader`. 전역 캐시 인스턴스가 여기 있다
│   │   │   ├── models.py            # `VideoListModel`(가상 스크롤)·`_VideoListView`
│   │   │   ├── delegates.py         # 그리드·리스트·트리 행·태그 칩 페인팅(`_IconDelegate`·`_ListDelegate`·`_TreeRowDelegate`·`_paint_match_badges`)
│   │   │   ├── tag_widgets.py       # 인기 태그 버튼·즐겨찾기 바·태그 목록·활성 태그 바
│   │   │   ├── cards.py             # 폴더 안 재생목록 카드 그리드(`_FolderContentsView` 등)
│   │   │   ├── splitter.py          # 좌측 패널 접기 핸들
│   │   │   ├── overlay.py           # 목록 위 상태 안내판(**결과 없음** 3종만) — 레이아웃 자리를 차지하지 않고 클릭을 통과시킨다. `_OverlayResizer`(부모 크기 추적)는 `skeleton_list.py`도 재사용. '조회 중' 표시는 v1.22.0부터 `skeleton_list.py`의 스켈레톤이 대신한다(텍스트와 스켈레톤이 동시에 뜨면 안 되므로 이 파일은 더 이상 로딩 상태를 그리지 않는다)
│   │   │   ├── skeleton_list.py     # 영상 목록(그리드·리스트·표) 로딩 스켈레톤(`ListSkeleton`, v1.22.0 체감 성능 개선 Phase 1 Step 3) — `gui/widgets/skeleton.py`의 `SkeletonRow`를 뷰포트에 맞춰 카드/행 개수만큼(고정 상한 아님) 배치한다. `set_view(view_id)`로 아이콘(카드: 썸네일+제목+메타 블록 3개)/리스트(썸네일+텍스트줄 4개)/표(행 스트라이프 1개) 배치를 고르고 `set_loading(bool)`로 표시/숨김. 숨길 때 자식 블록을 전부 `deleteLater`(숨은 채 도는 타이머 없음)
│   │   │   ├── tree.py              # **위젯 조립·시그널·행 그리기·선택/탐색만** 담당하고 부피가 큰 동작은 아래 `tree_mixins/`로 나뉘었다(1,490→683줄). `_PlaylistTree`·`_PlaylistPanel`·`_BreadcrumbBar` — 좌측 내비 트리. **`select_for_snapshot`은 선택 후 `scrollToItem(PositionAtCenter)`까지 한다** — `setCurrentItem`도 스크롤은 하지만 `EnsureVisible`이라 노드를 뷰포트 경계까지만 밀어 아래쪽 끝에 걸치게 둔다(실측: 340px 뷰포트에서 중심보다 145px 아래). 즐겨찾기 바·뒤로가기로 이동했을 때 트리의 어디로 갔는지 한눈에 보이도록 가운데 놓는다. 회귀 테스트 `tests/gui/test_favorites_tree_sync.py`가 "보이기만 하는 것"과 "가운데 오는 것"을 실제 픽셀로 구분한다
│   │   │   ├── tree_mixins/        # ⬆ tree.py의 동작 묶음 (분할 결과) — 런타임 클래스는 하나(mixin 합성)라 상태 공유 방식은 분할 전과 같다
│   │   │   │   ├── spinner.py       # 노드 로딩 스피너. 원래 텍스트는 `_ORIG_TEXT_ROLE`에 보관한다(델리게이트가 텍스트를 파싱하지 않는 이유)
│   │   │   │   ├── items.py         # 트리 로드(로컬·YouTube 섹션) + 아이템 팩토리(`_make_category`/`_make_playlist`/…). 팩토리가 롤을 심고 델리게이트는 롤만 읽는다
│   │   │   │   ├── dnd.py           # 드래그앤드롭(영상·재생목록·폴더 이동 + 브라우저 URL 드롭). 가장 컸던 덩어리(`dropEvent` 145줄)
│   │   │   │   └── context_menu.py  # 우클릭 메뉴 — 동작을 직접 하지 않고 `_PlaylistTree` 시그널만 방출한다
│   │   │   └── mixins/              # LibraryPanel 동작 묶음 — 런타임 클래스는 하나(상태 공유 방식 불변)
│   │   │       ├── album.py         # 앨범 보기(그리드·상세·담기·재생)
│   │   │       ├── mini_player.py   # 지금 재생 중 미니바 상태(재생 유지·복귀·자동 다음곡)
│   │   │       ├── recommend.py     # 추천 스트립(디바운스 조회·등장/퇴장 연출)
│   │   │       ├── navigation.py    # 화면 히스토리(스냅샷 복원)·브레드크럼
│   │   │       ├── detail.py        # 상세 진입/이탈·재생목록(자동 다음곡)
│   │   │       ├── sidebar.py       # 좌측 트리 조작(카테고리·재생목록·폴더·즐겨찾기). **즐겨찾기 바 클릭은 트리 선택까지 동기화한다** — `_on_favorite_clicked`가 필터를 걸고 나서 `_playlist_panel.select_snapshot({"kind":…})`으로 대응 노드를 선택 표시한다(뒤로가기 복원과 **같은 경로**를 재사용하므로 강조·스크롤 규칙이 한 곳에만 있다). 예전엔 목록만 바뀌고 트리는 반응이 없어 지금 어느 카테고리를 보는지 트리에서 알 수 없었다(실제 신고). 태그 즐겨찾기는 트리 노드가 없고 현재 카테고리 안에서 거는 필터라 트리 선택을 건드리지 않는다
│   │   │       ├── feed.py          # 구독 피드/채널 화면·YouTube 동기화
│   │   │       ├── video_list.py    # 검색·정렬·뷰 전환·태그 패널·썸네일 프리로드. **목록 로딩 스켈레톤**: `_on_list_loading_any`(`vm.loading_changed` 전용, 검색 포함)와 `_on_list_loading`(노드 키 트리 스피너와 짝을 이루던 기존 경로)이 같은 스켈레톤 표시 로직을 공유한다 — 자세한 배경은 아래 "목록·검색 로딩 스켈레톤" 항목 참고
│   │   │       ├── context_menu.py  # 영상 우클릭 메뉴(단일·다중)·삭제 확인
│   │   │       └── shortcuts.py     # 키보드 단축키 — Ctrl+F(검색)·Esc(덮인 화면부터 걷기)·Alt+←/→(히스토리)·F5(새로고침)·Ctrl+1~4(보기 전환). 범위는 `WidgetWithChildrenShortcut`이라 다른 페이지에서는 발동하지 않는다
│   │   ├── download_panel.py        # 다운로드 큐 + 완료 이력 탭 (영상 파일만 표시·완료/실패 배지). **이 패널의 상세 위젯에는 song_vm이 배선돼 있지 않아** 노래 탭·가사 자막이 동작하지 않는다(기존 상태 — 가사 자막 기능은 라이브러리 패널로 범위가 한정됨)
│   │   ├── feed_panel.py            # 피드 카드 부품(_FeedGrid·_FeedCard: 썸네일 좌하단 채널 배지·리사이즈 reflow, **단일 클릭→`video_clicked`(FeedVideoDTO) 방출**, 인라인 추가버튼 제거·우클릭 메뉴로 일원화) + 채널 카드 부품(_ChannelGrid·_ChannelCard: 아바타·구독자/영상수에 더해 **"최근 영상 N일 전"** 라벨=`latest_video_published_at`) + 연관영상 행에서 재사용하는 `_RoundedThumbLabel`·`_ThumbLoader` 정의 — library_panel/video_detail_panel이 재사용. `_FeedCard`·`_ChannelCard`는 `_relative_time`(YYYYMMDD·ISO·`Z` 처리)로 등록 시점을 상대시간 표기. **`_FeedCard`는 `thumb_size`(작은 카드)·`draggable`(URL 드래그) 옵션을 받는다** — 드래그는 `text/uri-list`+`text/plain`으로 브라우저 URL 드래그와 **완전히 같은 MIME**을 만들어 카테고리 트리의 기존 URL 드롭 경로를 그대로 재사용한다(받는 쪽에 추천 전용 처리가 없다). 드래그가 시작되면 `_dragged` 플래그로 릴리스 시 클릭(상세 진입)을 억제한다. 카드가 드래그 이벤트를 받으려면 `mousePressEvent`가 `event.accept()`해야 한다(수락하지 않으면 move/release가 부모로 전파돼 드래그가 조용히 죽는다). + **`RecommendStrip`(추천 영상 스트립)**: 헤더 바(▾/▸ 접기 토글 + '추천 영상' + 상태 라벨 + ⟳ 다시 받기)와 가로 스크롤 카드 행. `set_items`/`append_items`/`set_loading`/`set_status`/`set_expanded(notify=False)`/`count()` 제공. 접으면 본문(`_scroll`)만 숨기고 헤더는 남긴다(= 다시 펼칠 수 있는 split bar). library_panel이 수직 `QSplitter`의 아래쪽 자식으로 넣는다. (구버전 FeedPanel 컨테이너는 더 이상 사이드바 메뉴로 노출되지 않음)
│   │   ├── monitoring_panel.py      # 채널 구독 & 모니터링 규칙 관리
│   │   ├── stats_panel.py           # 라이브러리 통계 대시보드 + **채널별 카테고리 섹션**(`_make_channel_row`: 채널명·총 영상수 + 카테고리 경로 링크를 `_FlowLayout`으로 흐름 배치, 예 "IT > News (3)"). 링크 클릭 시 `category_selected(category_id)` 방출 → `MainWindow._on_stats_category_selected`가 라이브러리 해당 카테고리로 전환. **채널명은 URL이 있으면 클릭 시 브라우저로 열리는 링크(`_open_url`→`QDesktopServices`) + `📋` URL 복사 버튼(`_copy_url`, 복사 후 ✓ 잠깐 표시)**을 둔다. 데이터는 `LibraryStatsDTO.channel_stats`(list[`ChannelStatDTO`]→`ChannelCategoryStatDTO`); `ChannelStatDTO.channel_url`은 리포지토리 `get_channel_category_stats`가 반환한 channel_url 대표값(없으면 channel_id로 `youtube.com/channel/{id}` 구성). **모든 색은 테마 토큰에서 온다**(`_card_qss`·`_BarChart(tokens)`·`_danger_color`) — 예전엔 카드 배경이 `#1e1e2e`로 박혀 있어 밝은 테마에서 어두운 카드 위에 어두운 글씨가 얹혀 아무것도 안 보였다. 카드·차트는 위젯 스타일시트/QPainter로 직접 칠하므로 전역 QSS 교체만으로는 안 바뀐다 → `theme_changed`에 `_refresh()`를 연결해 다시 그린다(`_clear_content`가 중첩 레이아웃까지 재귀 제거)
│   │   ├── video_detail_panel.py    # **화면 뼈대와 로드 진입점만** 담당하고 나머지는 아래 `detail/` 패키지로 나뉘었다(2,999→693줄). YouTube 시청 페이지형 상세화면 — 좌(상단 행: `‹`뒤로+브레드크럼(`_crumb_bar`) 같은 줄 → **상단 고정 플레이어**(stretch 없이 16:9 자연 높이라 여백 없음; 창이 넓어지면 커지고 탭이 남는 공간 흡수) → **제목 행**(제목 `_title_lbl` + 우측 정렬 아이콘 `📁`카테고리 지정·`⟳`상세갱신·`🌐`브라우저) → **메타 행**(`_meta_layout`: 채널·조회수·등록일·재생시간 + 상태) → **하단 탭 3개**(stretch=1)) | 우(`_RelatedList` 연관영상). 탭: `_TAB_INFO`(설명)·`_TAB_SUMMARY`(요약, 헤더 행에 `⟳` 아이콘 갱신 버튼)·`_TAB_FILES`(다운로드/클립 병합 — 수직 `QSplitter`, 위=`_dl_tab` 아래=`_clip_tab_widget`). **설명 탭 레이아웃**(탭 자체 스크롤 없음 — 영속 위젯 세로 스택 `info_col`): `_tags_header`+`_tags_scroll`(태그) → `_tag_add_container`(태그 추가) → `_desc_header`+`_desc_view`(설명) → `_notes_header`+`_notes_edit`(메모) → 맨 아래 `addStretch(1)`. **태그**는 `_TagChip`(글자 길이만큼 Fixed 폭) + `_FlowLayout`(폭에 맞춰 줄바꿈하는 실제 `QLayout` 서브클래스)로 흐르고 `_tags_scroll`(QScrollArea)로 감싸 **최대 3줄까지만 보이고 초과분은 스크롤**한다(`_fit_tags_scroll`이 내용 높이에 맞추되 3줄로 상한). **설명**(`_desc_view` = `_AutoHeightBrowser`)은 내용 높이를 `sizeHint`로 노출해 **남는 세로 공간을 최대로 활용**(설명이 길수록 넓게)하고 공간이 부족할 때만 자체 스크롤한다 — 짧으면 내용 높이에 딱 맞고(맨 아래 stretch가 여백 흡수) 길면 영역을 최대로 차지(그때만 스크롤)하므로 스크롤이 최소화된다. **메모**(`_notes_edit` = `_AutoHeightPlainEdit`)는 설명 바로 아래에서 1~5줄 자동 높이로 **최소 높이가 항상 보장**된다(고정 높이라 설명이 아무리 길어도 안 밀림). `load`(로컬)/`load_stream`(스트리밍: 요약 탭+제목행 `⟳` 비활성) + `set_related`. `_build_info`는 `_meta_layout`만 `_clear_layout`로 재빌드하고 나머지(태그·설명·메모)는 **영속 위젯을 갱신**한다(`_tags_holder_layout`·`_tag_add_layout` clear 후 재구성, `_desc_view.setHtml`, 없으면 `setVisible(False)`). 제목은 `_title_lbl.setText()`, 메모는 `_notes_edit`로 세팅. 설명·요약은 `_render_timestamped_html`로 **마크다운 서식**(제목 `#`, 굵게 `**`/`__`, 기울임 `*`, 불릿 `-`/`*`/`•`/`·`, 번호 `1.`/`1)`, 선행 공백 들여쓰기)을 HTML로 렌더하며 타임스탬프(MM:SS/HH:MM:SS) seek 링크·URL 링크도 유지한다(`_on_summary_anchor_clicked`→`InlinePlayer.seek_to_ms` / 브라우저). URL은 escape/서식 적용 전에 분리해 보존한다. **`line_gap`(px) 인자로 줄마다 하단 여백을 준다** — 설명은 원문에 빈 줄 단락 구분이 있어 0(조밀)이지만, Gemini 요약은 개행이 촘촘해 `_SUMMARY_LINE_GAP`(=8)을 줘 단락·개행 간격을 벌려 읽기 편하게 한다(요약 렌더 3곳 모두 적용). **별도 "챕터" 섹션은 설명 속 타임라인과 중복되므로 제거하고 설명 하나로 병합**(기존 `_parse_chapters`·`_on_chapter_clicked` 삭제됨). `RelatedItem` dataclass + `item_selected` 시그널. **우측 `_RelatedList`는 두 구역**(위=연관 영상, 아래=`set_recommendations`로 채우는 "추천 영상")을 한 스크롤에 쌓으며, 구역마다 전용 컨테이너(`_rel_box`/`_rec_box`)를 둔다 — 예전처럼 한 레이아웃에 헤더·행·스트레치를 늘어놓고 인덱스로 지우면 구역이 둘이 되는 순간 삽입/삭제 위치가 어긋난다. **추천은 `_playlist`에 넣지 않는다**(자동 다음곡은 연관 영상 안에서만 이어진다). **연관영상 행(`_RelatedRow`)**은 제목을 최대 3줄까지 표시(9pt, `AlignTop`, `maximumHeight=lineSpacing*3`)하고 채널명·조회수·등록시기는 7pt로 1pt 줄여 title과 사이에 stretch를 둬 **행 아래쪽에 배치**(제목 가림 최소화). 요약 탭은 `gemini_summary`를 표시(`_summary_edit`)/편집(`_summary_editor`) **`QStackedWidget`(`_summary_stack`)** 2단으로 두고 **표시 영역 더블클릭→편집 모드**(`eventFilter`가 `_summary_edit.viewport()`의 `MouseButtonDblClick` 감지→`_enter_summary_edit`), **편집기 포커스 아웃→저장**(`_commit_summary_edit`이 변경 시 `_summary_raw` 갱신·재렌더 후 `gemini_summary_saved` 방출). ⟳ 버튼으로 `_GeminiSummaryWorker`(QThread) → `GeminiExtractor` 호출 → `gemini_summary_saved` 방출. 요약 원문은 `_summary_raw`에 보관(편집 대상). 제목행 `⟳`(상세 정보 갱신)는 `detail_refresh_requested(video_id)` 방출 → `LibraryPanel._on_detail_refresh_requested`가 `_vm.refresh_video_metadata(video_id)`로 **YouTube(yt-dlp)에서 메타데이터를 백그라운드 재수집**하고 `set_refresh_busy(True)`(⟳ 비활성). 완료 시 VM이 `video_metadata_refreshed(video_id, ok)` 방출 → `_on_video_metadata_refreshed`가 현재 그 영상 상세가 열려 있으면(`current_detail_id()` 일치) `_reload_detail_in_place`로 DB 최신 상세를 재로드(nav 히스토리 미변경). **과거에는 `get_video_detail`로 DB만 재조회해 저장된 오래된/부실(예: `extract_flat` 캡처) 메타데이터가 그대로여서 유튜브 웹과 달랐음** — 이제 실제 재수집으로 제목·설명·조회수·게시일·태그·썸네일을 웹 기준으로 갱신한다. **탭3 `_TAB_SONG`("노래")**는 `_SongTab` 위젯: 가수/앨범/제목/발매년도(`_EditableField` — 더블클릭 시 QLineEdit 인라인 편집, Enter/포커스아웃 저장→`field_edited`; 레이블·값 모두 세로 중앙 정렬, 값은 **PlainText 렌더**라 `'`·`&`·`<` 등이 `&#x27;`처럼 엔티티로 오표기되지 않음), 가사는 줄마다 `_LyricRow` 컨테이너로 표시(원문+한글 병행; 표시 영역 더블클릭→편집 모드 QPlainTextEdit, 포커스아웃 저장→`lyrics_edited`)하며 재생 중인 줄을 accent 틴트로 강조하고 자동 스크롤한다(사용자가 직접 스크롤하면 3초간 멈춘다 — `sliderPressed`/`actionTriggered`로 감지, `valueChanged`는 자동 스크롤 자신의 변화까지 잡아 영구 억제되므로 쓰지 않는다). `SongInfo.is_synced`가 아니면(시각 있는 줄이 없으면) 가사 검색 버튼 옆에 `⏱`(싱크 가사 찾기 — `FetchSongInfoCommand.synced_only`, 타이밍 없는 출처는 건너뛰고 전 출처 실패해도 기존 가사는 지우지 않음)가 대신 뜬다. **`is_synced`면 그 자리에 대신 가사 시작 시각 보정 입력 필드(`_offset_spin`, ±30초·0.25초 단위, `offset_changed(ms)` 발행)가 뜬다** — 영상 위 자막(💬)의 `[`/`]`·`,`/`.` 단축키·우클릭 메뉴와 값을 공유하며, `VideoDetailWidget`가 `offset_changed`를 `InlinePlayer.set_subtitle_offset_ms()`(공개 setter)에 그대로 연결해 기존 디바운스 저장 경로를 재사용한다(탭이 직접 저장하지 않음). 플레이어 쪽에서 바뀐 값은 `set_offset_ms()`로 탭에 되돌아와 표시만 갱신한다(`blockSignals`로 되돌림 방지). **번역 배치 전환 아이콘**(`_layout_btn` — "(더블클릭하여 편집)" 문구 오른쪽; 원문 아래↔원문 오른쪽 2열 토글, 비한국어 병행 가사일 때만 노출·세션 내 유지, **오른쪽 2열 배치는 행마다 교대 음영으로 경계 구분**), 출처 링크, **가사 검색 버튼(`_lyrics_refresh_btn` = `_SpinRefreshButton`) + 번역 버튼(`_translate_btn`, 가사 있을 때만 노출)** — 검색 버튼은 항상 **후보 목록 검색**을 요청한다(`_on_lyrics_search_clicked`→`candidates_requested`→`SongViewModel.search_lyrics_candidates`). 결과는 가사 영역 자리(`_lyrics_stack` index 2 = `_LyricsCandidateList`)에 |출처|가수|제목|가사 첫째 줄|싱크| 표로 뜨고, 고른 행만 `candidate_chosen`으로 반영한다. 번역 버튼은 현재 가사를 한글로 재번역(`translate_requested`→`translate_lyrics`, 조회와 분리된 독립 동작), "노래로 표시" 토글(`flag_toggled` — 켜면 **영상 제목 기준으로 가수·앨범·제목·발매년도만 채우고 가사는 조회하지 않음**), **가수·앨범 값 오른쪽 `»` 필터 아이콘**(`_EditableField` with_action — 값 있을 때만 노출, 클릭 시 `filter_requested(field,value)`→`song_filter_requested`→`LibraryPanel._on_song_filter_requested`가 `get_videos_by_song`으로 같은 가수/앨범 영상을 연관 목록 대신 나열하고 헤더를 "가수/앨범: XXX"로 교체). 스트리밍은 편집·조회 불가(안정적 id 없음)지만 **탭은 비활성화하지 않고** `_LockedNotice` 안내판(`_lyrics_stack` index 3 = `_STACK_LOCKED`, 요약은 `_summary_stack` index 2 = `_SUMMARY_LOCKED`)을 띄운다 — 아래 "라이브러리 밖 영상의 카테고리 지정" 항목 참고. 데이터는 위젯이 직접 조회하지 않고 `LibraryPanel`이 `SongViewModel`로 로드해 `set_song_info(dto)`/`set_song_busy(busy)`로 주입, 편집 신호는 `song_field_saved`/`song_lyrics_saved`/`song_refresh_requested`/`song_flag_toggled`로 재방출→`SongViewModel`이 저장. 가사 더블클릭 편집·편집기 포커스아웃은 요약과 동일하게 앱 레벨 `eventFilter`로 감지. **진입 시 재생 전 포스터**: `load`/`load_stream`에 `poster`(목록과 동일한 QPixmap, LibraryPanel이 `_load_thumb(thumbnail_path,…)`로 생성) + `autoplay` 인자 → `InlinePlayer.load(thumbnail_pixmap=…)`. **우측 목록은 재생목록**: `set_related(items, header=None)`이 payload 순서를 `_playlist`에 저장하고 현재 항목(`_current_key`)을 `_RelatedRow(is_current=…)`로 ▶+배경 강조. `InlinePlayer.playback_finished`(EndOfMedia) → `_on_playback_finished`가 다음 payload로 `play_next_requested` 방출 → `LibraryPanel._on_play_next`가 `_open_detail(autoplay=True)`로 자동재생(마지막이면 정지). 현재 영상도 목록에 포함(제외 조건 제거). **가사 자막**: 노래이고 `is_synced`면 `player.subtitle`(`LyricsOverlay`)에 `LyricsTrack.from_lines(...)`을 채우고, `InlinePlayer.current_line_changed`로 재생 중인 `_LyricRow`를 강조·스크롤한다. `InlinePlayer.subtitle_offset_changed`(`C`/`[`/`]`/`\` 단축키나 `💬` 우클릭 메뉴로 변경)는 **500ms 디바운스 후 조정 시점의 video_id를 캡처해 저장**한다(`SongViewModel.set_lyrics_offset`) — 디바운스 대기 중 다른 영상으로 넘어가도 원래 영상에 저장되도록 하는 레이스 수정이다.
│   │   ├── detail/                  # ⬆ video_detail_panel의 부품·동작 (분할 결과)
│   │   │   ├── widgets.py           # `_TagChip`·`_FlowLayout`·`_AutoHeight*`·`_EditableField`·`_LockedNotice` 등 소형 위젯
│   │   │   ├── related.py           # `RelatedItem`·`_RelatedRow`·`_RelatedList`(연관 영상 + 그 아래 추천 구역)
│   │   │   ├── song_tab.py          # `_SongTab`·`_LyricRow`·`_LyricsCandidateList`(가사 후보 표)
│   │   │   ├── text_format.py       # 설명·요약 렌더링 정규식(마크다운·타임스탬프·URL)과 요약 실패 안내 문구
│   │   │   ├── text_zoom.py         # 요약·가사 글자 배율 — clamp·pt 계산·설정 저장(`detail_text_scale`). 두 영역이 한 배율을 공유한다
│   │   │   ├── workers.py           # `_GeminiSummaryWorker`
│   │   │   └── mixins/              # info(제목·태그·설명·메모)·summary·song·files(다운로드/클립)·player
│   │   ├── album_panel.py           # 앨범 보기 부품 (진입은 툴바 보기 유형 💿 버튼) — `AlbumGrid`(자켓 카드 그리드, 폭에 맞춰 reflow)·`AlbumDetailPanel`(좌: 자켓·설명·▶앨범재생·빠진 곡 찾기 / 우: 수록곡 목록). 수록곡 행(`_TrackRow`)에 **출처 배지**(내 등록/자동 매핑/없음)를 그린다. **수록곡 헤더의 '✎ 수정' 토글(`_btn_edit`)을 켜야만 행마다 삭제(✕) 버튼이 보이고**, 그것도 자동 매핑(AUTO) 행에만 붙는다(`_TrackRow.set_edit_mode` — 내 라이브러리 영상 삭제는 훨씬 무거운 동작이라 여기서 다루지 않고 '없음'은 지울 게 없다). `set_detail`은 앨범이 바뀌면 수정 모드를 끈다(켜진 채 남으면 새 앨범에서 실수로 누른다). 자켓은 `_ThumbLoader`(prefix="album")를 재사용해 URL에서 받아 캐시하고, 없으면 대표 영상 썸네일 → ♪ 자리표시자 순으로 폴백
│   │   ├── settings_panel.py        # **섹션 배치만** 담당한다 — 520줄짜리 `_build_ui`를 섹션 빌더 10개로 쪼갰고 큰 섹션 위젯은 `settings/` 패키지에 있다(1,744→1,014줄). 전체 설정 패널 (다운로드 경로, 테마 등) + **가사 출처 관리**(`_LyricsSourcesSection`: `song_vm` 주입 시에만 표시) + **클라우드 동기화**(`_CloudSyncSection`: **폴더 방식이 기본**(안내 문구 + 폴더 경로 입력·찾아보기, OneDrive 환경변수 감지 시 `<OneDrive>/ovc-sync` 자동 채움) — 로그인·개발자설정 불필요. **"고급: 클라우드 API로 직접 연결(OAuth)" 체크박스**로 API provider(Google Drive/OneDrive) 드롭다운+Client ID/Secret을 펼침(`_advanced_check` 토글, 기본 숨김). 연결/해제/지금 동기화 버튼·상태 라벨. `sync_vm` 주입 시에만 표시) + **YouTube API 연동**(`yt_oauth` 주입 시에만 표시 — 위 클라우드 동기화의 "Client ID/Secret"과는 **별개 기능**이다. Client ID/Secret 입력란 없이 단일 버튼 `_yt_auth_btn`("Google 계정으로 연결"/"연결 중…"/"Google 계정 다시 연결") + `_yt_disconnect_btn`("연결 해제")만 노출한다. `YouTubeOAuthAdapter.has_client_config()`가 False면(번들 클라이언트 미포함) 버튼을 비활성화하고 "배포자에게 문의하세요" 안내를, 연결 성공 시 채널명 + "앱을 다시 시작하면…" 재시작 안내를 `_yt_status_lbl`에 표시한다. 인증 플로우는 `_AuthWorker`(QThread)가 무인자 `run_auth_flow()`를 호출한다 — Client ID/Secret 문자열을 UI가 갖고 있지 않다. 아래의 구독 피드용 브라우저 쿠키 섹션과는 시각적으로 분리된 별도 섹션이다) + **라이브러리 가져오기/내보내기**(`_ImportExportSection` — `transfer_vm` 주입 시에만 표시. 내보내기: `get_categories_fn`(=`library_vm.categories`)로 로컬 카테고리 체크트리(`CategorySelectDialog`) 노출 → `QFileDialog.getSaveFileName`으로 `.ovcpkg` 경로 선택 → `transfer_vm.export_library`. 가져오기: `QFileDialog.getOpenFileName` → `preview_import`로 패키지 안의 카테고리 체크트리 노출 → `detect_conflicts` → 값이 다른 영상이 있으면 `ImportConflictResolutionDialog`로 필드별 선택 → `import_library`. 각 단계는 이전 다이얼로그가 취소되면 그다음 단계로 넘어가지 않는다). **숨김 태그 관리 섹션은 맨 아래**(긴 목록이 다른 설정 접근을 방해하지 않도록 재배치). **업데이트 UI는 헤더('설정' 라벨) 우측 컴팩트 위젯**(`_build_update_header`: 자동확인 토글 + 상태 라벨 `_upd_status_lbl` + 준비 시 `_upd_install_btn`)로 이동 — 기존 하단 큰 섹션 제거. `set_update_ready(dto)`가 상태를 '준비됨'으로 바꾸고 설치 버튼 노출, `_on_install_update`→`install_update_requested`. 일반 섹션에 **"등록 시 요약·가사 자동 채우기"** 체크박스(`_auto_enrich_check` → `auto_enrich_on_add`) + 안내 문구(요약은 YouTube 쿠키 필요·일괄 임포트 제외)
│   │   ├── settings/                # ⬆ settings_panel의 부품 (분할 결과)
│   │   │   ├── helpers.py           # `_t`(현재 토큰)·`open_folder`(탐색기 열기)
│   │   │   ├── theme_cards.py       # 테마 프리셋 카드·미리보기
│   │   │   ├── hidden_tags.py       # 숨김 태그 관리(드래그로 표시/숨김 이동)
│   │   │   └── sections.py          # 가사 출처·클라우드 동기화·가져오기/내보내기 섹션(각자 뷰모델하고만 대화)
│   │   └── settings_dialog.py       # 간략 설정 다이얼로그 (레거시, 42줄)
│   ├── dialogs/
│   │   ├── youtube_auth_dialog.py   # `YouTubeAuthDialog` — Gemini 요약용 YouTube 쿠키 인증. "브라우저 계정"(기존 브라우저 프로필 선택)·"쿠키 파일"(직접 지정) 탭 + "새 계정으로 로그인…"(Playwright로 자체 브라우저 창을 띄워 로그인시키고 쿠키 직접 캡처 — 기존 브라우저 쿠키 DB 무관). 설정 화면 "브라우저 열어서 로그인 (권장)" 버튼(`SettingsPanel._on_open_auth_dialog`)으로 연결됨
│   │   ├── batch_download_dialog.py # 일괄 다운로드 URL 입력 다이얼로그
│   │   ├── quick_open_dialog.py     # 빠른 이동(Ctrl+K) — 카테고리·재생목록·영상을 한 입력창에서. 결과 구성은 순수 함수 `build_hits`(장소 먼저·접두 일치 우선·종류별 상한)라 GUI 없이 테스트한다
│   │   ├── library_cleanup_dialog.py # 라이브러리 정리 — 중복 영상·사라진 파일. **자동 삭제 없음**(확실한 중복만 첫 항목 남기고 기본 선택, '비슷함'은 선택 안 함)
│   │   └── library_transfer_dialogs.py  # 가져오기/내보내기 — `CategorySelectDialog`(체크트리, 부모 체크 시 하위도 함께 체크/해제 — 내보내기의 로컬 `CategoryDTO`·가져오기의 패키지 `ImportCategoryOptionDTO` 양쪽에서 재사용, 둘 다 id/name/parent_id/video_count 필드만 덕타이핑으로 씀) + `ImportConflictResolutionDialog`(좌: 값이 다른 영상 목록, 우: 선택한 영상의 필드별 `_FieldChoiceRow` — 기존값/가져올값을 "(비어있음)" 표시로 채워짐 여부까지 보이고 라디오로 선택. 기본 선택은 `ImportFieldDiffDTO.default_choice`. "전체 가져오기값 사용"/"전체 기존값 유지" 일괄 버튼)
│   ├── widgets/
│   │   ├── video_player.py          # **InlinePlayer 조립만** 담당하고 스트림·컨트롤·표시면은 `player/` 패키지에 있다(2,223→1,276줄). 인라인 비디오 플레이어 위젯 (QMediaPlayer 기반). **스트림 확보는 실패를 전제로 설계**한다 — `_STREAM_CLIENTS`(기본→android→ios→tv) 순회 + `_stream_playable` 사전 검증 + 재생 오류 시 1회 재조회. 자세한 배경은 아래 "스트리밍 재생 실패 → 브라우저 튕김" 항목 참조. **하이브리드 스트리밍 화질**: YouTube 고화질은 영상+오디오 분리(DASH)라 QMediaPlayer 단일 URL로는 360p가 한계 → `_StreamWorker`가 두 모드 운용. "자동(빠른 재생)"·360p·240p는 muxed URL 즉시 스트리밍(merge=False); 1080p/720p/480p는 `bestvideo[avc1]+bestaudio[mp4a]`를 번들 ffmpeg로 임시 mp4에 병합 후 로컬 재생(merge=True, `ovc_stream_*` 임시 디렉터리는 stop/load/품질전환 시 정리). WMF 호환 위해 avc1(H.264)+m4a 우선. 화질 변경 시 `_on_quality_changed`가 현재 위치 저장→`mediaStatusChanged`(LoadedMedia/BufferedMedia·seekable)에서 이어보기 seek(고정 지연 seek 폐기로 네트워크 스트림에서도 견고). **컨트롤바 배경**은 `_bar_style()`의 `#ctrlbar` 반투명 그라디언트(영상이 비쳐 보임). **재생·볼륨 슬라이더는 `_TrackSlider(QSlider)`로 트랙·핸들을 `paintEvent`에서 QPainter로 직접 그린다** — 영상(`QGraphicsVideoItem`) 위에 겹쳐진 컨트롤바에서는 `QSlider::groove`/`::add-page` 서브컨트롤이 스타일시트 색을 무시하고 검게 렌더되는 Qt 제약이 있어(불투명 지정·정지 프레임에서도 재현; 위젯 배경·`sub-page` 등 직접 채움만 정상), 스타일시트 대신 직접 페인팅으로 라이트 트랙을 보장한다. 따라서 슬라이더 색을 바꿀 땐 `_bar_style`의 QSS가 아니라 `_TrackSlider`(`_TRACK_BG`·`progress_fg`·`text_primary`)를 수정할 것. **전체화면(`_FullscreenWindow`)·화면 속 화면(`_PipWindow`)은 공유 `QMediaPlayer`의 `setVideoOutput` 대상만 자기 `_VideoView`로 바꿔 분리 재생**한다(하나의 player라 위치·볼륨·상태 유지). **`_VideoView`(QGraphicsView)는 `FocusPolicy.NoFocus`** — QGraphicsView가 기본적으로 포커스를 쥐고 방향키(↑/↓/←/→)를 스크롤용으로 소비해 전체화면·PiP 창의 `keyPressEvent`가 볼륨(↑/↓)·탐색(←/→) 단축키를 못 받던 문제를 막는다(상위 창이 모든 키 처리). **키보드 포커스는 InlinePlayer(`StrongFocus`)가 단독으로 받는다** — `_VideoView`는 `NoFocus`, 컨트롤바 버튼(`QToolButton`)은 `TabFocus`라 자신은 포커스를 갖지 않고, 플레이어 안 어디를 클릭하든 포커스가 `InlinePlayer`로 올라와 `keyPressEvent`가 단축키(Space/J/K/L/M/F/P·자막 `C`/`[`/`]`/`\`)를 처리한다. 이 위임이 깨지면 **단축키 전체가 조용히 죽으므로**(핸들러는 멀쩡하니 기존 테스트는 통과한다) `tests/gui/test_subtitle_player.py::TestShortcutReachability`가 실제 클릭+키 입력으로 도달성을 고정한다 — 포커스 정책을 바꿀 땐 이 테스트를 먼저 통과시킬 것. 두 창 모두 컨트롤바를 공개 속성 `bar`(`_ControlBar` 인스턴스)로 노출하며, **`bar` 신호는 외부(InlinePlayer)에서 반드시 배선**해야 버튼이 동작한다 — `_enter_fullscreen`/`_enter_pip`가 각각 `bar.play_toggled`~`quality_changed`를 인라인과 동일한 핸들러에 연결하고 초기 상태(재생시간·위치·재생여부·볼륨·음소거·화질)를 1회 반영하며, `_exit_fullscreen`/`_exit_pip`가 `durationChanged` 연결을 해제한다. 플레이어→분리창 바 동기화는 `_on_position`/`_on_playback_state`(위치·재생상태)와 `_change_volume`/`_toggle_mute`(볼륨·음소거)가 `_fs_win`/`_pip_win` 존재 시 팬아웃한다. PiP는 컨트롤바에 `_btn_pip`(⧉, `pip_toggled` 시그널, 단축키 `P`)로, 전체화면은 `_btn_fs`(⛶, `fullscreen_toggled` 시그널, 단축키 `F`)로 진입하며 `_enter_pip`/`_enter_fullscreen`은 서로 동시 분리를 허용하지 않아 진입 시 상대 창을 먼저 종료한다. PiP 활성 시 인라인은 `_show_pip_placeholder`로 "화면 속 화면으로 재생 중" 표시. `_PipWindow`는 프레임리스·항상 위, 영상 영역 드래그 이동(영상 `WA_TransparentForMouseEvents`)+`QSizeGrip` 리사이즈, 닫기/Esc/더블클릭/`_btn_pip`로 복귀. **분리 창 정리는 `stop()`/`load()`/`closeEvent`에서 출력 인라인 복귀 후 수행**(상세 이탈 시 `stop_player`→`stop` 경로로 자동 정리). **`load(...)`는 `thumbnail_pixmap` 포스터를 지원**(재생 전 index 0 `_thumb_label` 표시). **`playback_finished` 시그널**: `_on_media_status`에서 `EndOfMedia`(수동 stop과 구분되는 유일한 종료 지표)일 때 방출 → 상세화면 재생목록 자동 다음곡용. **화질 메뉴는 그 영상이 실제로 제공하는 해상도만 나열한다** — 다운로드 포맷이 `height<=N` 이라 최대치를 넘는 선택지는 같은 파일을 받아 무의미했다(최대 1080p인 영상에 4K가 뜨던 문제). ⬇ 클릭은 바로 메뉴를 열지 않고 `download_menu_requested`를 방출 → `InlinePlayer._on_download_menu_requested`가 `_FormatProbeWorker`(QThread, yt-dlp `extract_info`)로 높이 목록을 구한 뒤 `bar.set_available_heights()`+`bar.open_download_menu()`로 연다(조회 중 ⬇ 비활성, 결과는 `_HEIGHT_CACHE`에 URL 단위로 캐시, 실패하면 전체 목록으로 폴백해 다운로드를 막지 않는다). 재생 화질 메뉴도 같은 목록으로 걸러진다. 세로 영상은 높이가 1920처럼 잡히므로 '정확히 존재하는 값'이 아니라 **최대치 이하**로 판정한다(`tests/gui/test_quality_menu.py`). 일괄 다운로드 다이얼로그는 대상이 여러 개라 이 필터를 적용하지 않는다. **가사 자막**(`LyricsOverlay`)은 영상 위에 겹쳐 인라인·전체화면·PiP 3창 모두에서 재생되며, `bar`와 마찬가지로 `subtitle` 속성도 외부(상세화면)가 내용을 채워야 한다 — 단축키 `C`(자막 on/off)·`[`/`]`(오프셋 ∓250ms, `_OFFSET_STEP_MS`, `,`/`.`도 동일 동작의 별칭)·`\`(현재 위치를 그 줄에 맞춤)는 `subtitle_offset_changed`·`current_line_changed` 시그널로 상세화면에 통지된다. **`set_subtitle_offset_ms(ms)`는 절대값 지정용 공개 메서드**로, 노래 탭처럼 플레이어 밖(단축키·메뉴가 아닌 경로)에서 오프셋을 바꿀 때 이 메서드로 진입하면 내부 조정과 동일하게 바·오버레이 갱신 + `subtitle_offset_changed` 발행까지 그대로 이어진다.
│   │   ├── player/                  # ⬆ video_player의 부품 (분할 결과)
│   │   │   ├── constants.py         # `_STREAM_CLIENTS`·`_PROBE_*`(ffmpeg와 동일한 검증 요청)·화질 목록
│   │   │   ├── stream.py            # `_StreamWorker`·`_stream_playable`·`_FormatProbeWorker` — URL 확보와 사전 검증
│   │   │   ├── controls.py          # `_ControlBar`·`_TrackSlider`(영상 위에서는 QSS가 안 먹어 직접 그린다)
│   │   │   └── surfaces.py          # `_VideoArea`·`_VideoView`·`_PipWindow`·`_FullscreenWindow`. **`_VideoArea` 높이는 16:9를 지향하되 창 높이의 `_MAX_WINDOW_RATIO`(0.62)를 넘지 않는다** — 컨트롤바가 이 영역 바닥에 얹히므로 영역이 배정된 공간보다 커지면 바가 창 밖으로 밀려 보이지도 눌리지도 않는다(실측: 2200×900 창에서 바 하단이 창 아래로 335px). 넘칠 땐 영상이 좌우로 레터박스될 뿐이고 자동 숨김은 그대로다. 제한은 `heightForWidth`에 걸어 레이아웃 배정과 실제 배치가 어긋나지 않게 하고, **창 resize도 이벤트 필터로 지켜본다**(세로만 줄이면 폭이 그대로라 자기 resizeEvent가 오지 않아 제한값이 낡는다). 회귀 테스트 `tests/gui/test_player_geometry.py`는 창을 `setFixedSize`로 고정한다 — `resize`만 쓰면 Qt가 창을 키워 넘침이 재현되지 않는다
│   │   ├── mini_player_bar.py       # 지금 재생 중 미니바 — 창 하단(상태바 위) 띠. 썸네일·제목·▶⏸·⏭·위치 슬라이더·✕. **재생 주체를 옮기지 않는다** — 라이브러리 상세의 InlinePlayer 상태를 비추고 조작만 되돌려 보낸다(그래서 다른 페이지로 가도 계속 보인다). 클릭하면 보던 상세로 복귀
│   │   ├── subtitle_track.py        # 영상 자막 트랙 — `SubtitleCue`(시작·**끝**·텍스트)·`SubtitleTrack`(이분 탐색·오프셋). Qt 비의존. 가사(`LyricsTrack`)와 규칙이 다르다: **끝 시각이 있어** 대사가 없는 구간에는 아무것도 뜨지 않는다
│   │   ├── lyrics_overlay.py        # 가사 자막 — `LyricsTrack`(Qt 비의존 순수 로직: 이분 탐색 현재 줄 판정·오프셋 ±30초 clamp) + `LyricsOverlay(QWidget)`(배경 없이 QPainterPath 외곽선 텍스트, 글자 크기는 위젯 높이 비례라 전체화면에서 자동 확대). 폰트는 Pretendard→맑은 고딕→Noto Sans KR 순으로 설치된 것을 고름(`subtitle_font_family`). **`set_notice(text)`/`notice_text`는 조절 피드백 문구**를 위쪽 가운데에 그린다(자막은 아래라 안 겹침) — 전체화면·PiP에는 `InlinePlayer._status_lbl`이 안 보이므로 세 창이 다 가진 이 오버레이가 피드백을 책임진다. 자막이 꺼져 있거나 표시할 줄이 없어도 문구는 그린다. **자막 색(흰 글자/검은 외곽선)은 테마 토큰을 쓰지 않는 의도적 예외** — 앱 테마가 아니라 '어떤 영상 프레임 위에서도 읽히는가'가 기준
│   │   └── skeleton.py              # 로딩 중 화면 구조를 먼저 보여주는 공유 스켈레톤 프리미티브(v1.22.0 체감 성능 개선 Phase 1) — `ShimmerEffect(QWidget)`(블록 하나에 흐르는 좌→우 그래디언트, `SHIMMER_CYCLE_MS`=300ms 무한 반복)·`SkeletonRow(QWidget)`(높이·칸 개수·칸별 상대폭(`cell_ratios`) 커스터마이징 가능한 스켈레톤 한 행). **칸마다 위젯을 따로 만들지 않고 한 번의 `paintEvent`에서 전부 그린다**(카드/행마다 위젯을 만들지 않는 저사양 PC 메모리 규칙 — 목록에 이 행이 수십 개 늘어서도 위젯 수가 늘지 않는다). 색은 `tok()`(테마 토큰)에서만 파생하고(`bg_overlay`를 바탕으로 채널별 델타(`_HIGHLIGHT_DELTA`)만큼 밝힌 색이 반짝임 톤 — 근검정 톤에서도 `.lighter()` 곱셈 보정보다 확실히 밝아지도록 덧셈으로 계산), 색 하드코딩 금지 규칙을 지킨다. `set_loading(bool)`로 애니메이션을 시작/중단하며, **위젯이 숨겨지면(`hideEvent`) 로딩 중이어도 타이머를 자동으로 멈추고** 다시 보일 때만 재개한다(보이지 않는 곳에서 타이머가 도는 것 방지). 목록·앨범 등 여러 화면의 스켈레톤이 이 모듈 하나를 공유해 모양·색·애니메이션 규칙을 일원화하는 것이 목적이라, 실제 화면별 스켈레톤(목록·앨범 그리드/상세)은 이 프리미티브 위에 별도 파일로 얹힌다. 회귀 테스트: `tests/gui/test_skeleton.py`
│   ├── themes/
│   │   ├── manager.py               # ThemeManager 싱글턴 — 전역 QSS 교체, theme_changed 시그널
│   │   ├── tokens.py                # ThemeTokens dataclass + PRESETS(11종) — **기본 테마는 `mist`**(밝은 중간 톤): `bg_base #d9dee6` → `bg_surface #e7ebf1` → `bg_elevated #f8fafc`로 계층차를 12~18단위 확보한다. 기존 `slate`는 계층차가 3~7단위뿐이라 레이어 경계가 보이지 않았다. 어두운 4종(slate·zinc·warm·**forest**) + 밝은 7종(cloud·rose·sand·mist·**sage**·**lavender**·**graphite**). **모든 텍스트 토큰은 배경 대비 WCAG AA(4.5:1)를 만족**하도록 값이 정해져 있고 `tests/gui/test_theme_contrast.py`가 이를 강제한다 — 새 프리셋을 추가하거나 색을 바꾸면 이 테스트를 먼저 통과시킬 것. `is_light` 프로퍼티(배경 휘도 판정)는 의미 색 톤 선택에 쓴다
│   │   ├── colors.py                # 인라인 스타일시트용 색 헬퍼 — `tok()`(현재 토큰)·`sem('success'|'danger'|'warning')`(밝기별 톤). **위젯 `setStyleSheet`에 색을 하드코딩하지 말 것** — 밝은 테마에서 글자가 배경에 묻힌다
│   │   └── stylesheet.py            # build_qss(tokens) → QSS 문자열 생성
│   └── view_models/                 # UI 상태 — Application 레이어와 View 사이 브릿지
│       ├── library_vm.py            # LibraryViewModel — 영상 목록, 카테고리, 검색, 같은 가수/앨범 영상 조회(`get_videos_by_song` — `FindSongVideoIdsHandler`+`GetVideos(video_ids=)`). **등록 직후 자동 보강**: `_EnrichWorker`(QThread)로 `EnrichVideoHandler` 실행, `_pending_enrich` 큐로 **동시 1건** 직렬화(`_maybe_enrich`/`_drain_enrich`/`_release_enrich`), `enrich_started`/`enrich_finished` 시그널 방출. `_AddVideoWorker.finished_ok`이 `video_id`를 실어 보낸다. URL→ID 조회는 `get_video_id_by_url`
│       ├── download_vm.py           # DownloadViewModel — 다운로드 큐/이력 + 진행률
│       ├── feed_vm.py               # FeedViewModel — 전체 구독 피드(refresh) + 채널별 영상(load_channel) + 구독 채널 카드 정보(load_channel_infos) 로딩, shutdown() 워커 정리
│       ├── monitoring_vm.py         # MonitoringViewModel — 채널 구독 목록
│       ├── clip_vm.py               # ClipViewModel — 클립 목록 + 추출 작업
│       ├── playlist_vm.py           # PlaylistViewModel — 재생목록 관리
│       ├── recommend_vm.py          # RecommendViewModel — 추천 스트립 상태. `_RecommendWorker`(QThread) + 세대 카운터로 이전 조회 결과 폐기, 씨앗 캐시(`_last_key`)로 같은 목록 재조회 방지(`force=True`면 무시, 실패 시 캐시 비움), shutdown(). **FeedViewModel을 재사용하지 않는다** — FeedViewModel의 `_gen`은 키별 캐시가 있어도 전역 하나라, 추천 조회가 세대를 올리면 동시에 진행 중인 구독 피드/채널 조회 결과가 버려진다(추천은 목록이 바뀔 때마다 돌아 그 충돌이 상시 발생)
│       ├── album_vm.py              # AlbumViewModel — 앨범 목록/상세/빠진 곡 채우기를 QThread로. 세대 카운터로 늦게 온 결과 폐기, `cancel_fill()`로 앨범 이동 시 진행 중 검색 중단, shutdown(). `remove_track_link(disc_no, track_no)`는 **QThread 없이 즉시** 처리한다(DB 삭제 한 줄이라 네트워크가 없다) — 성공하면 그 슬롯을 '없음'으로 되돌린 DTO를 `track_removed`로 실어 화면 한 자리만 갱신한다(전체 재조회 없음)
│       ├── song_vm.py               # SongViewModel — 노래 탭 상태(load/refresh를 `_SongFetchWorker`(QThread) 백그라운드 조회, 필드·가사 편집, 노래 토글, 가사 출처 관리). **가사 후보 목록**: `search_lyrics_candidates`(`_CandidateSearchWorker` — `candidates_started`/`candidate_ready`/`candidates_finished` 방출, 새 검색 시 이전 워커 `cancel()`+신호 disconnect)·`apply_lyrics_candidate`(`_ApplyCandidateWorker` — 번역이 네트워크라 백그라운드). `translate_lyrics`(현재 가사 재번역, `_TranslateWorker`). **같은 영상 중복 조회 방지**(`_in_flight`), shutdown()
│       ├── sync_vm.py                # SyncViewModel — 클라우드 동기화 UI 상태(설정 패널). SyncService를 `_SyncWorker`(push/pull+미디어)·`_ConnectWorker`(OAuth) QThread로 감쌈. 연결 시 QTimer로 주기 자동 동기화(start_auto_sync=기동 후 1회+주기). 시그널: status_changed·busy_changed·sync_finished·connection_changed·error_occurred. shutdown()
│       └── transfer_vm.py            # LibraryTransferViewModel — 가져오기/내보내기 UI 상태(설정 패널). 네 핸들러(export/preview/conflicts/import)가 전부 `handle(cmd)->DTO` 한 메서드짜리라 워커 클래스 하나(`_CommandWorker`)를 공유. 시그널: export_finished·preview_ready·conflicts_ready·import_finished·busy_changed·error_occurred. shutdown()
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

> **어디를 열어야 하나 (2026-08 분할 이후)**
> 화면 *배치*를 바꾸려면 `*_panel.py`(조립부)를, *동작*을 바꾸려면 그 옆 패키지의
> `mixins/`를, *부품의 모양*을 바꾸려면 패키지의 위젯 모듈을 연다. 파일을 나눴을 뿐
> 런타임 클래스는 그대로라(mixin 합성) 상태 공유·시그널 배선 방식은 이전과 같다.
> 테스트에서 `monkeypatch`할 때는 **쓰는 쪽 모듈**을 패치해야 한다(재수출 이름을
> 바꿔도 소용없다 — 분할 과정에서 실제로 3건이 이 이유로 깨졌다).

## Key Design Decisions

- **노래 정보(song 컨텍스트)** — Video와 1:1인 `SongInfo`(가수·앨범·제목·발매년도·가사·is_song). **노래 판별**은 yt-dlp `categories`에 "Music" 포함 또는 `track`/`artist`/`album` 존재로 자동 감지하며, 상세 탭의 "노래로 표시" 토글로 수동 지정도 가능하다. **가사 조회는 관리형 출처 레지스트리(`lyrics_sources` 테이블)를 priority 순으로 순회하는 체인**(`FetchSongInfoHandler._run_chain`) — 기본 LRCLIB(무키·안정)→지니→벅스→Genius→멜론 순으로 부족한 항목(가사·가수·앨범·제목)을 이어서 채운다(**국내곡은 지니·벅스가 원가사를 안정적으로 반환**해 앞에 둔다 — Genius가 기여자/번역 헤더 쓰레기로 '조회 성공' 처리돼 국내 사이트가 시도조차 안 되던 문제 완화. Genius 파서는 `N ContributorsTranslations…Lyrics` 머리말·`…Embed` 꼬리말을 제거함. 멜론은 가사가 AJAX 지연 로드라 정적 스크래핑 불가 → 최하위·graceful None. 기존 설치본은 `_migrate_song_sources_reorder`로 1회 재정렬). **다중 아티스트 폴백**: yt-dlp `artist`는 협업/피처링을 콤마 등으로 이어 붙이는데(예: "NIKI, Phil Collins"), 제공자는 정확한 아티스트명으로 매칭하므로 이 전체 문자열로는 조회가 실패한다. `_run_chain`은 각 제공자에 **전체 아티스트 → 주(첫) 아티스트(`_primary_artist` — 콤마/`;`/`/`/`&`/`feat`/`ft`/`with`/`x`로 분리) 순으로 재시도**해 유명곡 가사를 놓치지 않는다(표시용 아티스트 값은 원본 전체를 보존). **가사 검색 기준값은 현재 노래 정보에 입력된 값(가수·제목·앨범 — 수동 편집 포함)을 최우선**으로 쓴다. **사용자가 항목을 한 번이라도 수정했으면(`manual_fields` 존재) 입력된 값만으로 검색하고, 빈 항목은 채우지 않는다**(영상 제목을 song_title 기본값으로 억지로 넣어 검색이 실패하던 문제 해결 — 예: 가수를 비우면 제목만으로 검색). **수정한 적이 없을 때만(자동 첫 조회) 영상 제목을 파싱**해 부족분을 보완한다. 따라서 제목·가수를 고친 뒤 ⟳를 누르면 그 값으로 다시 검색한다. 새 출처를 추가하면 자동으로 체인에 편입돼 정보를 보강한다(설정 화면에서 관리). **비한국어 가사는 `deep-translator`로 한글을 병행 표기**(원문+번역 `LyricsLine`); 한국어 가사(한글 비율≥0.3 감지)나 번역기 미설치 시 원문만. **등록·"노래로 표시" 토글·상세 최초 진입 시엔 영상 제목 기준으로 메타데이터(가수·앨범·제목·발매년도)만 채운다**(가사 네트워크 조회 생략 — `FetchSongInfoCommand.fetch_lyrics=False`; `SongViewModel.toggle_song`/`load(dto 없을 때)`). **가사는 '가사' 레이블 옆 가사 검색 버튼을 눌러야만 조회**한다(자동 조회 안 함). 검색 버튼은 아래 "가사 검색 후보 목록" 항목대로 **전 출처를 훑어 후보를 나열**하고 사용자가 고른 것만 반영한다. 옆의 **번역 버튼**은 현재 등록된 가사를 한글로 (재)번역해 저장한다(`TranslateSongLyricsCommand`/`TranslateSongLyricsHandler` — 조회와 분리된 독립 동작, `SongInfoAggregate.set_lyrics_translations`로 출처 유지·수동표시 안 함, 한국어면 no-op). **사용자가 더블클릭 편집한 필드는 `manual_fields`에 기록돼 갱신 시 덮어쓰지 않는다**(`SongInfoAggregate.apply_fetched`가 manual 필드를 건너뜀). 가사 제공자·번역기는 `domain/song/ports.py`의 Protocol(`ILyricsProvider`·`ITranslator`)에 의존하고 composition root가 구체 구현을 주입한다. Genius·국내 사이트 스크래퍼는 사이트 구조 변경에 취약하므로(그래서 켜고/끄기·순서 조정 가능) 실패는 격리돼 다음 출처로 이어지고 등록/재생에 영향을 주지 않는다. **같은 가수/앨범 필터**: 노래 탭 가수·앨범 값의 `»` 아이콘 → `ISongRepository.find_video_ids_by(artist=/album=)`(is_song=1 매칭)로 video_id를 구해 기존 `GetVideos(video_ids=)`로 조회, 상세화면 우측 목록을 그 결과로 교체(헤더 "가수/앨범: XXX"). **상세 우측 목록은 재생목록**으로 동작 — 현재 영상 포함·강조, `InlinePlayer.playback_finished`(EndOfMedia)에 다음 항목 자동재생(끝이면 정지). 진입 시 재생 전에는 목록과 동일한 썸네일을 포스터로 보여준다. **가수/앨범 필터 재생목록에서 마우스 뒤로가기**는 `LibraryPanel._playlist_ctx`(items·header·prev_related·history)를 두고 `_playlist_back`으로 재생 이력(history 스택)을 되짚어 이전 재생 항목을 열고(재생 중이면 이어재생), 이력이 소진되면 진입 직전 "연관 영상" 목록으로 복귀한다(재생목록 내 이동은 `push_nav=False`라 화면 히스토리를 오염시키지 않음).
- **가사 검색 후보 목록 (|출처|가수|제목|가사 첫째 줄|싱크|)** — 가사 검색 버튼(⟳)은
  이제 **활성 출처를 전부 훑어 후보를 나열**하고, 사용자가 고른 것만 반영한다.
  예전에는 체인(`FetchSongInfoHandler._run_chain`)이 첫 성공 출처를 곧바로 채택하고
  마음에 안 들면 '다음 출처'로 순환시켰는데, **어떤 가사인지는 적용된 뒤에야 볼 수 있었고**
  원하는 출처에 닿으려면 여러 번 눌러야 했다. 후보 검색은 별도 유스케이스
  (`SearchLyricsCandidatesHandler`)이며 **DB에 쓰지 않는다** — 채택은
  `ApplyLyricsCandidateHandler`가 맡아 "조회"와 "반영"을 분리한다(체인 검색은 등록 시
  자동 보강·싱크 가사 찾기 경로에서 그대로 쓰이므로 **삭제하지 않았다**).
  **출처당 후보는 여러 건이다.** 같은 제목의 다른 가수 곡이 흔해 1건만 받으면 엉뚱한
  곡이 걸리므로, 제공자에 `search()`(다건)를 추가하고 출처마다 최대
  `per_source_limit`건(기본 `DEFAULT_LYRICS_SEARCH_LIMIT`=10, **0이면 무제한**)을 모은다.
  무제한을 기본으로 두지 않는 이유는 스크래핑 출처(Genius·멜론·벅스·지니)가 곡마다
  상세 페이지를 한 번씩 긁어 요청 수 = 후보 수이기 때문이다. `search`가 없는 제공자는
  `fetch` 1건으로 폴백한다(`_search_one`이 `hasattr`로 판정 — 그래서 포트를
  `ILyricsSearchProvider`로 분리했다. `ILyricsProvider`에 넣으면 전 구현이 강제된다).
  **정렬은 출처가 주는 신호에 따라 다르다** — 조회수(Genius `stats.pageviews`)가 있으면
  내림차순, 없고 곡 길이만 있으면(LRCLIB) 영상 길이에 가까운 순, 둘 다 없으면
  **출처가 준 순서를 그대로 둔다**(국내 3사는 검색 결과 순서 자체가 그 사이트의 랭킹이라
  재정렬이 오히려 정보를 버린다). 핸들러의 `_rank_results`는 지표가 하나라도 있을 때만
  개입하는 **안정 정렬**이라, 제공자가 이미 정렬해 온 결과를 흐트러뜨리지 않는다.
  정렬 근거(조회수·길이)는 열을 늘리지 않고 행 툴팁(`_candidate_tooltip`)에 담는다.
  **결과는 전 출처가 끝나기를 기다리지 않고 도착하는 대로 표시한다** — 느린 출처 하나
  때문에 이미 확보한 후보를 못 보는 일이 없어야 하므로, 핸들러가 `on_start(출처)` →
  `on_result(출처, DTO)`(**출처당 여러 번**) → `on_source_done(출처, 건수)`를 부르고 GUI는
  '조회중…' 행을 먼저 깔아 둔 뒤 그 자리를 후보 N행으로 펼친다. **종료 통지가 따로 필요한
  이유**는 후보 0건인 출처는 `on_result`가 한 번도 안 불려 '조회중'과 구분이 안 되기
  때문이다. 표는 행 인덱스를 직접 만지지 않고 상태(`_order`/`_results`/`_pending`)에서
  **매번 다시 그린다**(`_rebuild`) — 출처마다 행 수가 달라 삽입 위치를 계산하면 어긋난다.
  대신 선택은 DTO 동일성으로 되찾아 유지한다(다른 출처 결과가 도착할 때마다 선택이
  풀리면 고르는 도중에 놓친다). `list_source_names()`가 반환하는 목록과 `handle()`이 실제로
  순회하는 목록은 **같은 조건**(활성 + 제공자 구현 존재)으로 추려야 한다 — 어긋나면 영영
  안 채워지는 '조회중…' 행이 남는다. 조회가 취소·중단돼도 `finish()`가 남은 행을
  '결과 없음'으로 정리한다.
  후보 DTO는 `lines`/`timings`를 **그대로 동봉**한다(고른 뒤 같은 출처를 다시 조회하지
  않기 위해 — 네트워크 절약 + 그새 다른 결과가 오는 사고 방지). 적용은 사용자가 명시적으로
  고른 것이므로 `force_lyrics=True`로 수동편집 가드를 넘어 교체하되, 가수·앨범 등
  메타데이터는 `apply_fetched` 규칙대로 수동 편집분을 보존한다. 검색 기준값 계산
  (`resolve_search_basis`)·다중 아티스트 폴백(`artist_search_candidates`)·번역 포함 줄 생성
  (`build_lyrics_lines`)은 체인 검색과 **같은 함수를 공유**한다(두 경로가 다른 결과를 내면
  "목록엔 있는데 자동 보강은 못 찾는" 혼란이 생긴다). UI는 가사 영역 스택의 index 2
  (`_LyricsCandidateList`)라 레이아웃이 흔들리지 않으며, 검색 중 다른 저장이
  `song_info_changed`를 쏘아도 목록을 닫지 않는다(`_SongTab.set_info`의 `_STACK_CANDIDATES`
  가드 — 닫히면 고르던 후보를 잃는다). 늦게 도착한 결과가 다른 영상의 목록에 섞이지 않도록
  VM은 새 검색 시 이전 워커를 `cancel()`+신호 disconnect하고, `VideoDetailWidget`은
  `video_id`가 현재 상세와 다르면 결과를 버린다. 회귀 테스트:
  `tests/unit/application/test_lyrics_candidates.py`(전 출처 순회·다건·상한·실패 격리·취소·적용 규칙),
  `tests/unit/infrastructure/test_lyrics_provider_search.py`(LRCLIB 제목만 재검색·중복 제거·Genius 상한·id 전수 추출),
  `tests/gui/test_lyrics_candidates_ui.py`(조회중 행·출처당 다행·선택 유지·VM→위젯 전 구간).
- **가사 자막 표시 · 싱크 조정** — 노래 영상 재생 중 가사를 영상 위 자막으로 표시한다.
  **타이밍의 유일한 출처는 LRCLIB의 `syncedLyrics`(LRC)** — 지니·벅스·Genius·멜론은
  시간 정보를 주지 않는다. 예전에는 syncedLyrics의 타임스탬프를 버리고 텍스트만 썼으나,
  이제 `infrastructure/song/lrc.py:parse_lrc`로 파싱해 `LyricsLine.start_ms`에 싣고
  `lyrics_json`에 `"s"` 키로 저장한다(값이 있을 때만 넣어 하위호환·프리필터 영향 최소화).
  **자막·싱크 UI는 `SongInfo.is_synced`(시각이 있는 줄이 1개 이상)일 때만 활성**하며,
  없으면 컨트롤바 `💬`가 비활성되고 노래 탭에 `⏱`(싱크 가사 찾기 —
  `FetchSongInfoCommand.synced_only`)가 뜬다. `synced_only` 조회는 타이밍 없는 출처를
  건너뛰고, **전 출처가 실패해도 기존 가사를 지우지 않는다.**
  보정은 **시작 오프셋 하나**(`SongInfo.lyrics_offset_ms`, ±30초 clamp)뿐이다 — 배속·구간
  늘림은 지원하지 않는다. `💬` 좌클릭 토글 / 우클릭 메뉴(±0.25초·"현재 위치를 이 줄에
  맞춤"·초기화), 단축키 `C`·`[`·`]`·`\`로 조작하고 500ms 디바운스로 DB에 저장한다
  (영상별 값이라 sync 캡처에 자동 편입 — 같은 영상은 다른 기기에서도 같은 어긋남을 갖는다).
  **`,`(빠르게)·`.`(늦게)는 `[`·`]`의 별칭**이다(`InlinePlayer.keyPressEvent`) — 자막 조정에
  익숙한 편집 프로그램 키 배치를 추가로 지원할 뿐 별개 동작은 아니다. **노래 탭에도
  같은 값을 직접 편집하는 입력 필드(`_SongTab._offset_spin`, ±30초·0.25초 단위)가
  있다** — ⏱(싱크 가사 찾기)와 상호 배타적으로 노출되며(시간 정보가 있어야 조정할
  대상이 있으므로), `InlinePlayer.set_subtitle_offset_ms()`(공개 setter, 내부적으로
  단축키가 쓰는 `_set_subtitle_offset`에 위임)를 호출해 **기존 저장 경로를 그대로
  재사용**한다 — 탭이 직접 DB에 쓰지 않고 플레이어의 `subtitle_offset_changed` 신호가
  다시 `VideoDetailWidget._on_subtitle_offset_changed`(디바운스 저장)로 흘러들어가는
  구조라, 플레이어 단축키·메뉴로 바뀐 값도 `_SongTab.set_offset_ms()`로 탭 표시에
  되돌아온다(양방향 동기화, `blockSignals`로 무한 루프 방지).
  **디바운스는 조정 시점의 video_id를 함께 캡처한다**(`_pending_offset: tuple[UUID, int]`)
  — 500ms 안에 다른 영상으로 전환해도 flush 시점 `self._detail`이 바뀐 값이 아니라
  원래 영상에 저장되도록 한다.
  렌더는 **`LyricsTrack`(순수 로직)과 `LyricsOverlay`(그리기)로 분리**해 경계값·오프셋
  로직을 QApplication 없이 테스트한다. 오버레이는 인라인·전체화면·PiP **3창 모두**에
  얹히며 기존 컨트롤바 팬아웃 패턴을 그대로 따른다 — **`bar`처럼 `subtitle`도 외부
  (InlinePlayer)가 내용을 채워야 한다.** 현재 줄 인덱스가 바뀔 때만 다시 그려 매 position
  틱 repaint를 피한다. 노래 탭은 재생에 맞춰 현재 줄을 accent 틴트로 강조하고 자동
  스크롤하되 **사용자가 직접 스크롤하면 3초간 멈춘다**(`valueChanged`가 아니라
  `sliderPressed`/`actionTriggered`를 듣는다 — `valueChanged`는 자동 스크롤 자신의 변화까지
  잡아 영구 억제된다). 가사를 손으로 편집하면 **줄 수가 같을 때만 기존 타이밍을 유지**한다
  (오탈자 수정으로 싱크가 날아가지 않게, 줄 구성이 바뀌면 신뢰할 수 없어 폐기).
  **자막 크기·위치는 사용자가 조절한다** — `Ctrl`+휠/방향키↑↓로 글자 크기(배율 0.5~3.0,
  스텝 0.1), `Ctrl+Shift`+휠/방향키↑↓로 세로 위치(`bottom_ratio` 0.0~0.6, 스텝 0.02).
  "위로 굴리면 값이 커진다"로 방향을 통일했고 `bottom_ratio`는 아래에서 띄우는 양이라
  값이 커지면 자막이 위로 올라간다. 두 값은 **영상별이 아니라 전역**이며(보기 설정이므로)
  `config.yaml`에 500ms 디바운스로 저장한다. **오버레이는 비디오 영역 전체를 덮는다** —
  예전엔 컨트롤바 위 28% 높이 띠라 글자를 키우면 잘렸고, 크기 비율(5.5%)이 그 띠에 적용돼
  실질 1.5%라 자막이 지나치게 작았다(지금은 영역 높이의 4.5%). 지오메트리는 인라인·PiP·
  전체화면(`_position_bar`/`resizeEvent`) **4곳**에 있으니 함께 고쳐야 한다.
  `keyPressEvent`는 원래 수정키를 보지 않았으므로 새 분기를 맨 앞에 두고 `Ctrl+Shift`를
  `Ctrl`보다 먼저 판정한다(맨 ↑↓ 볼륨과 충돌 방지). `_VideoView`(QGraphicsView)는 휠을
  삼키므로 `wheelEvent`에서 `ignore()`해야 하고, 이 도달성은
  `tests/gui/test_subtitle_player.py::TestSubtitleWheel`이 실제 휠 이벤트로 고정한다.
  다만 `ignore()`만으로는 부족하다 — `QAbstractScrollArea`는 viewport 이벤트를
  `viewportEvent()`로 dispatch해 부모 전파 경로를 타지 않으므로, `InlinePlayer.eventFilter`
  의 Wheel 분기가 **세 창의 viewport를 모두**(인라인 `_video_view`, 전체화면·PiP `_vw`)
  명시적으로 가로채 `wheelEvent`로 넘긴다. 한 곳이라도 빠지면 그 창에서만 조용히 죽는다.
  **저장된 값은 `_setup()` 끝에서 `_apply_subtitle_prefs()`로 오버레이에 밀어 넣는다** —
  생성자가 필드에 담기만 하면 화면은 기본 크기로 뜨고 첫 조작에서 값이 튄다.
  **조절 피드백은 `LyricsOverlay.set_notice()`로 3창 오버레이 모두에 그린다** — 인라인
  상태 라벨(`_status_lbl`)은 전체화면에서 가려지고 PiP는 아예 다른 창이라 안 보인다.
  임시 문구는 직전 안내("스트림 URL 가져오는 중…")를 보관했다가 만료 시 복원한다.
  **`💬` 우클릭 초기화 메뉴는 값이 기본값이 아니면 싱크 가사가 없어도 열린다**
  (`_ControlBar.set_subtitle_prefs_dirty` → `_refresh_cc_enabled`/`_build_subtitle_menu`).
  조절 단축키에는 가사 조건이 없어서, 없으면 비노래 영상에서 키운 전역 값을 되돌릴
  방법이 사라진다. 오프셋 관련 항목은 트랙이 있어야 의미가 있어 그때만 넣는다.
  저장값은 `round(v, 2)`로 자른다(0.1 누적이 `1.9700000000000002`로 박히던 문제).
  **테스트는 실사용 `data/config.yaml`을 절대 건드리면 안 된다** —
  `tests/gui/test_subtitle_player.py`의 autouse 픽스처가 `save_setting`을 무력화하고
  시작값을 기본값으로 고정한다(디바운스 타이머가 살아남아 실제 파일에 값을 누적하면
  다음 실행부터 다른 테스트가 깨진다).
- **추천 영상 스트립 (목록 아래 접이식)** — 지금 보고 있는 목록과 관련 있을 만한 영상을
  목록 아래 가로 띠로 나열하고, 좌측 카테고리 트리로 **드래그해 바로 담게** 한다.
  **관련 영상을 API로 받을 수 없다**: YouTube Data API v3의
  `search.list(relatedToVideoId=)`는 2023-08-07에 제거됐고 yt-dlp도 관련 영상을 주지 않는다.
  그래서 `domain/library/recommendation.py:derive_seed_queries`가 현재 목록의
  **제목 대표 키워드(문서빈도 기준)→최다 태그→최다 채널** 순으로 검색어를 최대 3개 만들고,
  `GetRecommendationsHandler`가 `IMediaSource.fetch_search_videos`(yt-dlp `ytsearchN:`)로
  후보를 모은다. **검색은 쿠키·API 키가 없어도 동작**하므로 미인증 사용자도 추천을 받는다
  (조회수·게시일은 YouTube API가 있으면 `get_videos_channels`로 보강). 검색어 파생을 도메인
  순수 함수로 뺀 이유는 추천 품질이 조용히 나빠지는 회귀를 테스트로 못박기 위함이다
  (`tests/unit/domain/test_recommendation.py`). **이미 라이브러리에 있는 영상은 결과에서
  제외**한다(목적이 '아직 없는 영상 담기'). 검색어별 실패는 격리해 나머지 검색어로 계속한다.
  반환형은 피드와 같은 `FeedVideoDTO`라 카드 렌더링(`_FeedCard`)을 공유한다.
  **검색창에 낱말이 입력돼 있으면 짐작을 그만두고 그 낱말의 YouTube 검색 결과로 스트립을
  채운다** — 사용자가 이미 무엇을 찾는지 말했으므로 목록에서 검색어를 뽑을 이유가 없고,
  뽑은 검색어를 섞으면 그 키워드와 무관한 후보가 함께 올라온다. 분기는 **검색어를 정하는
  한 곳**(`derive_seed_queries(search_text=…)`)에만 두고, `GetRecommendationsQuery.search_text`
  → `RecommendViewModel.load(search_text=…)`로 흘린다(두 경로가 갈라지면 "목록엔 검색어대로인데
  스트립은 딴 것"이 된다). GUI(`_refresh_recommendations`)는 검색 모드에서 **씨앗을 넘기지
  않는다** — 넘기면 목록이 바뀔 때마다(스트립에서 한 건 담기만 해도) 캐시 키가 달라져 같은
  검색을 다시 돌린다. 또 이때는 **로컬 결과가 0건이어도 조회한다**(검색 결과가 없을 때가
  오히려 'YouTube에는 뭐가 있나'를 가장 보고 싶은 순간이다 — 목록 기반 추천의
  "목록이 비어 있어 추천할 기준이 없습니다" 가드를 검색 모드에는 걸지 않는다).
  헤더 제목(`RecommendStrip.set_title`)이 `"<검색어>" YouTube 검색 결과`로 바뀌어 지금 뜬
  카드가 무엇인지 알려 주고, 검색어를 지우면 기본 제목·목록 기반 추천으로 돌아온다.
  회귀 테스트: `tests/gui/test_recommend_panel_wiring.py`(`TestSearchKeywordStrip`·
  `TestCollapsedStripSearchOverride`·`TestViewModelSearchText`),
  `tests/integration/test_recommendations.py`,
  `tests/unit/domain/test_recommendation.py`.
  **드롭 경로는 새로 만들지 않았다**: 카드 드래그가 `text/uri-list`+`text/plain`으로
  브라우저 URL 드래그와 동일한 MIME을 만들고, `_PlaylistTree`에 URL 드롭 처리를 추가해
  (`_url_drop_target` → `url_dropped(url, cat_id)` → `LibraryPanel._on_url_dropped` →
  `_vm.add_video(url, cat_id)`) 기존 등록 경로를 그대로 탄다. 대상 판정에 sentinel
  `_NO_URL_TARGET`을 쓰는 이유는 `cat_id=None`이 '미분류로 등록'이라는 **유효한 값**이라
  거부와 구분해야 하기 때문이다. 카테고리 노드와 **로컬 루트**만 대상으로 인정한다
  (YouTube 루트·채널·재생목록 노드는 거부). 부수 효과로 구독 피드 카드도 드래그 가능해졌다
  (`_FeedGrid`가 `draggable=True`로 카드를 만든다). 자동 갱신은 900ms 디바운스이고
  **접혀 있으면 조회하지 않는다** — 기본값은 펼침(`RECOMMEND_STRIP_EXPANDED`)이지만
  접어 두면 네트워크 조회가 완전히 멈춘다. **예외는 검색 결과가 0건일 때 하나뿐이다**
  (`_search_needs_recommendations`): 검색어는 있는데 로컬 결과가 없으면 화면에 아무것도
  남지 않아 헤더 바만 있는 접힌 스트립이 '결과 없음'과 구분되지 않는다 — 사용자가 이미
  무엇을 찾는지 말했으므로 `_apply_search_expand`가 스트립을 **임시로 펼쳐**(설정값은
  건드리지 않는다 — `set_expanded(notify=False)` + `_sync_recommend_sizes(save=False)`)
  그 낱말의 YouTube 결과를 채운다. 검색어를 지우거나 결과가 생기면 원래 접힘으로
  되돌리며 **그때 카드·헤더 제목도 함께 비운다** — 남겨 두면 나중에 사용자가 직접 펼쳤을
  때 `count() > 0`이라 재조회가 걸리지 않아, 지운 검색어의 결과가 '추천 영상'이라는 제목으로
  그대로 남는다. 사용자가 직접 토글하면(`_on_recommend_expanded`) 임시 펼침에서 손을 뗀다
  (직접 조작이 우선이다). 검색 0건 안내판(`_refresh_list_overlay`)도 "아래 '추천 영상' 띠에
  이 낱말의 YouTube 검색 결과를 채웁니다"로 스트립을 가리켜, 목록만 보고 있던 사용자가
  결과를 놓치지 않게 한다.
  **목록이 다 준비되기 전에는 스트립을 감춘다**(`LibraryPanel._recommend_ready`) — 조회 중인
  빈 띠가 미리 자리를 차지하지 않도록, 최종 결과(`items_changed`)가 와야 노출한다.
  **부분 결과(`partial_ready`)는 채워만 두고 노출하지 않는다.** 노출은 `_animate_recommend_in`이
  높이를 0→목표로 키워 아래에서 밀려 올라오듯 보이게 하는데, **`setSizes`만으로는 0에서 시작할
  수 없어**(스플리터가 자식의 `minimumSizeHint`를 최소로 삼는다) `maximumHeight`를 애니메이션한다
  — `qSmartMinSize`가 최소 크기를 `maximumSize`로 잘라 주기 때문에 최소 높이까지 함께 눌린다.
  끝나면 `_QWIDGET_MAX_H`로 되돌려 핸들 조절을 막지 않는다.
  **새 조회가 시작되면(카테고리 전환·검색·⟳) `_hide_recommend_strip`이 다시 아래로 접어
  감춘다** — 씨앗이 통째로 달라져 걸려 있던 카드는 새 목록과 무관한데, 그대로 두면 '이미
  준비된 추천'처럼 보인다. 접기 직전의 높이를 `_recommend_height`에 담아 두었다가 다시
  올라올 때 복원하고, 접히는 중에 결과가 도착하면 `_animate_recommend_in`이 **그 높이에서
  이어 올라간다**(0으로 튀지 않게). **결과가 없거나 실패해도, 추천 뷰모델이 없어도
  헤더 높이만큼은 띄운다** — 완전히 숨기면 ⟳(다시 받기)·접기 토글·안내 문구에 닿을 방법이
  사라진다. 같은 이유로 **접힌 상태로 시작하면 처음부터 헤더 바를 보여준다**(접혀 있으면 조회를
  안 하므로 노출 조건이 영영 오지 않는다).
  **상세화면 우측 '연관 영상' 목록 아래에도 같은 결과를 나열한다**(`_recommend_related_items()`
  → `VideoDetailWidget.set_recommendations`) — 상세를 열 때마다 따로 조회하지 않고 스트립의
  결과를 재사용한다(추천 뷰모델이 하나뿐이라 별도 조회는 스트립 목록까지 뒤엎는다). 추천은
  **재생목록(`_playlist`)에 넣지 않는다** — 자동 다음곡이 라이브러리 밖 영상으로 새면 안 된다.
  회귀 테스트: `tests/gui/test_recommend_strip.py`
  (접기·드래그 MIME·트리 드롭 대상·실제 드롭 이벤트), `tests/gui/test_recommend_panel_wiring.py`
  (디바운스·접힘 시 미조회·뷰별 숨김·**지연 노출·재조회 시 재감춤·등장/퇴장 애니메이션
  높이**·드롭 배선),
  `tests/gui/test_detail_recommendations.py`(상세 우측 두 구역 분리·재생목록 경계),
  `tests/integration/test_recommendations.py`.
- **라이브러리 밖 영상의 카테고리 지정 (요약·가사 잠금 해제)** — 상세화면 제목 행의 `📁`
  버튼(`VideoDetailWidget.category_assign_requested`)으로 **어떤 영상이든 카테고리에 담는다**.
  payload는 로컬이면 `video_id`(UUID), 스트리밍(추천·피드)이면 `FeedVideoDTO`이고,
  `LibraryPanel._on_detail_category_requested`가 전자는 `assign_category`(이동), 후자는
  `add_video(url, cat_id)`(등록)로 갈라 처리한다. 등록은 비동기라 **URL을
  `_pending_category_url`에 적어 두고** `video_add_finished`를 기다렸다가
  `_switch_to_local_detail`이 같은 영상의 로컬 상세로 갈아탄다(재생 위치·재생 여부 유지,
  `push_nav=False`라 화면 히스토리를 늘리지 않는다). 이미 라이브러리에 있는 URL을
  스트리밍으로 보고 있었다면 등록 없이 이동만 하고 전환한다.
  **요약·노래 탭은 더 이상 비활성화하지 않는다** — 두 기능은 영상별로 DB에 저장돼
  안정적인 로컬 `video_id`가 필요하지만, 탭을 비활성화하면 클릭조차 되지 않아 *왜* 못 쓰는지
  알릴 방법이 없었다. 이제 탭은 열리고 그 안에 `_LockedNotice`("카테고리에 담으면 …")와
  담기 버튼이 뜬다. 안내판은 `set_info(None)` 같은 갱신에도 유지된다(가사 후보 목록과
  같은 이유 — 되돌리면 설명이 사라진다). 카테고리 선택은 `LibraryPanel._pick_category()`가
  `_CategoryPickDialog`를 띄워 `(확인여부, cat_id)`를 돌려주며 추천 카드 우클릭 경로와 공유한다
  (`selected_id`는 **메서드**다 — 괄호를 빠뜨리면 바운드 메서드가 카테고리 id로 넘어가
  등록이 실패한다. 실제로 그 버그가 있었다). 회귀 테스트:
  `tests/gui/test_detail_category_assign.py`.
- **브라우저 URL → 카테고리 트리 드롭** — 드롭 판정은 **매 이벤트에서 MIME으로 다시 계산**한다
  (`_PlaylistTree._is_url_drag`). 예전엔 `dragEnterEvent`가 세운 `_ext_url_drag` 플래그에만
  의존해, 진입 이벤트를 놓치거나 중간에 `dragLeave`가 끼면 드롭이 **아무 반응 없이** 무시됐다.
  MIME 후보도 넓혔다: `text/uri-list`·`text/x-moz-url`에 더해 **`text/plain`과 Windows 네이티브
  포맷**(`application/x-qt-windows-mime;value="UniformResourceLocator(W)"`)까지 본다 —
  브라우저·사이트에 따라 dragEnter 시점에 uri-list가 없고 텍스트만 실려 오며, `…LocatorW`는
  **UTF-16LE**라 utf-8로 읽으면 첫 글자만 남는다. 트리는 접힌 채 로드되므로
  (`collapseAll`) 하위 카테고리에 떨구려면 드래그 중 펼침이 필요해
  `setAutoExpandDelay(600)`을 켰다(Qt 기본값은 -1=비활성). 거부된 드롭은 URL·대상·MIME 목록을
  `logger.debug`로 남긴다 — 화면에는 아무 일도 일어나지 않아 사후 진단이 불가능했다.
  회귀 테스트: `tests/gui/test_tree_url_drop.py`.
- **앨범 보기 (음악 카테고리 전용, 파생 그룹)** — 최상위 카테고리가
  `MUSIC_ROOT_CATEGORY_NAMES`(music·song·음악·노래·뮤직)일 때만 **보기 유형 버튼에 💿**가
  나타난다(`LibraryPanel._update_view_options`, ⊞/☰/⊟ 옆). 앨범은 **정렬이 아니라 보기
  방식**이다 — 같은 목록을 자켓 단위로 묶어 보는 것이라 리포지토리 정렬 컬럼으로는 표현할 수
  없다(처음엔 정렬 항목이었는데, 정렬로 두면 SQL 정렬로 새어 나갈 위험이 있고 의미도 맞지
  않아 옮겼다). 앨범 버튼도 `_view_group`의 일원이라 **앨범에서 빠져나올 때 `checkedId()`로
  되돌리면 다시 앨범**이 된다 — `_last_list_view`(마지막 아이콘/리스트/표 뷰)로 복귀한다.
  음악이 아닌 카테고리로 옮기면 버튼을 감추고 앨범 모드도 함께 푼다(버튼이 사라졌는데 화면만
  앨범 그리드로 남으면 빠져나갈 방법이 없다).
  **트리에서 카테고리를 고르면 음악 카테고리라도 앨범 보기에서 나온다**(`_on_cat_filter_changed`).
  트리 클릭은 "이 카테고리를 보겠다"는 뜻이지 "앨범 보기를 유지한 채 대상만 바꾸겠다"는 뜻이
  아니다 — 특히 앨범 상세를 보던 중이면 화면이 앨범에 머물러 갇힌 느낌이 든다. 나가는 것과
  잃는 것은 다르므로 직전 앨범 화면은 히스토리에 남아 뒤로가기로 돌아온다(진입은 💿 버튼).
  단 **복원 중(`_is_restoring`)에는 건드리지 않는다** — 그때는 스냅샷이 앨범 여부를 결정하며
  (`_restore_album_mode`), 여기서 나가 버리면 되살리려던 앨범 화면이 사라진다.
  **앨범은 저장되지 않는다**: `domain/song/album.py`가 노래 정보(가수·앨범)에서 묶음을 만들고,
  표기 차이는 정규화로 흡수하며 문자열 `"null"` 같은 자리표시자는 앨범명으로 보지 않는다
  (실제 DB에 있던 값). 목록 조회(`GetAlbumsHandler`)는 **네트워크를 쓰지 않는다** — 카테고리를
  옮길 때마다 외부 API를 때리지 않기 위해 캐시된 자켓만 붙인다. 자켓·설명·수록곡 전체는
  **앨범을 열 때** `GetAlbumDetailHandler`가 iTunes(무키)에서 받아 `album_cache`에 저장한다.
  **iTunes `lookup`에는 `country`를 붙이면 안 된다** — 실측 결과 수록곡이 통째로 빠지고 앨범
  한 건만 돌아와, 14곡짜리 앨범이 '내 곡 1개'로 조용히 잘못 보였다(`search`에는 붙여도 된다).
  **앨범 식별은 앨범명 텍스트 검색보다 곡 기준 조회를 먼저 시도한다**
  (`GetAlbumDetailHandler._resolve_metadata`) — 표기 차이·동명 앨범(재발매·베스트 앨범 등)
  때문에 `fetch_album(가수, 앨범명)`이 엉뚱한 앨범을 고르는 사고가 있었다. 대신
  `earliest_registered`(`domain/song/album.py`)로 **그 묶음에서 가장 먼저 등록한 곡**을
  앵커로 골라(생성 시각이 없으면 목록의 첫 항목으로 폴백) `find_album_of_track(가수,
  곡제목)`으로 정확히 그 곡을 iTunes에서 찾아 앨범을 확정한다 — 사용자가 직접 처음
  등록한 곡은 손대지 않은 원본 데이터라 가장 신뢰할 수 있다. `_anchor_in_tracks`가
  찾은 앨범이 실제로 그 곡을 담고 있는지 검증하는 안전판이다(잘못된 collectionId
  방어) — 검증에 실패하거나 앵커가 없을 때만 기존 앨범명 검색으로 되돌아간다.
  외부 조회가 실패하면 **내가 가진 곡만으로** 앨범을 구성한다(화면이 통째로 비지 않게).
  외부 수록곡과 내 영상은 `match_track_to_songs`로 붙이는데, 영상 제목에 붙은 꼬리표를 걷어낸
  뒤 완전일치→부분일치 순으로 보고 **3글자 미만 곡명은 부분일치를 허용하지 않는다**("Go"가
  아무 제목에나 걸린다). 외부 목록에 없는 내 곡은 뒤에 붙여 **화면에서 사라지지 않게** 한다.
  **수록곡의 신원은 (디스크, 트랙) 쌍이다** — 트랙 번호는 디스크 안에서만 유일해서,
  2장짜리 앨범(예: iTunes의 'Mercury - Acts 1 & 2' = disc1 1~14 + disc2 1~18)에서는
  번호만으로 다루면 **서로 다른 곡이 한 곡으로 뭉개진다**. 실제로 그 증상이 나왔다:
  `album_track_links`의 키가 `(album_key, track_no)`라 disc1·disc2의 같은 번호가 서로를
  덮어썼고, `AlbumDetailPanel.apply_filled_track`도 번호만 비교해 같은 번호 행 **둘 다**를
  같은 곡으로 갈아치웠다(화면에 같은 제목이 두 줄씩 떴다). 지금은 `AlbumTrackInfo`·
  `AlbumTrackDTO`·`AlbumTrackLink` 모두 `disc_no`를 갖고, 링크 키는
  `(album_key, disc_no, track_no)`이며 행 갱신도 `AlbumTrackDTO.slot`으로 찾는다.
  정렬은 `(disc_no, track_no)`, 표시는 2장 이상일 때만 `1-3`처럼 디스크를 붙인다.
  기존 캐시는 어느 디스크의 것인지 알 수 없어(=틀린 매핑이 섞여 있어)
  `migrate_album_disc_no`가 **버리고 다시 만든다** — 파생 캐시라 다시 조회하면 복구된다.
  **수록곡 헤더의 '＋ 현재 카테고리에 등록'**(`add_all_requested` → `AddAlbumTracksHandler`)은
  자동 매핑된(스트리밍) 곡을 현재 카테고리로 한꺼번에 담는다. 등록만 하면 새 영상이 앨범 값
  없이 들어와 '앨범 미상'으로 떨어지므로 — 담았는데 그 앨범에는 안 보인다 — **노래 정보
  (가수·앨범·곡 제목)를 함께 기록**한다. `AddVideoHandler`가 upsert라 중복 클릭·부분 실패 후
  재시도도 안전하고, 한 곡이 실패해도 나머지는 계속 담는다.
  라이브러리에 없는 곡은 앨범을 열 때 `FillAlbumTracksHandler`가 `"<가수> <곡> official audio"`로
  yt-dlp 검색해 붙이고(곡당 1회, 결과는 `album_track_links`에 저장돼 재검색하지 않음), 진행 상황을
  곡 단위 콜백으로 흘려 도착하는 대로 표시한다. 수록곡 배지는 **내 등록/자동 매핑/없음** 세 가지다.
  **검색 결과를 그대로 붙이지 않고 `domain/song/album.py:pick_official_audio`로 검증한다** —
  실제 신고: "자신의 음원이 아닌 경우"(동명이곡·커버·리액션·1시간 루프)가 수록곡에 붙었다.
  순수 함수라 네트워크 없이 판정한다: ① 후보 제목에 커버·리믹스·라이브 등
  위험 키워드가 있으면 배제(**대상 곡 제목 자체에 있는 표기는 예외** — 정식 발매곡이
  "Song (Remix)"면 후보도 당연히 그 표기를 담고 있어야 하므로) ② 정규화한 제목이 실제로
  그 곡을 가리키는지 확인(완전 일치 또는 3글자 이상 부분 포함) ③ **가수를 알면 후보
  제목이나 채널명에 그 가수가 보여야 한다** ④ iTunes가 준 곡 길이와
  크게 다르면(다른 버전·컴필레이션 추정) 배제.
  **①의 키워드 검사는 ASCII만 단어 경계(``)로 한다** — 부분문자열로 찾으면 "Amrit"의
  `mr`, "Alive"의 `live`가 걸려 정답 후보가 조용히 버려진다(실측). 한글은 띄어쓰기 없이
  붙는 일이 흔해("영상리액션") 경계를 쓰면 오히려 놓치므로 부분문자열 그대로 둔다.
  **②는 제목 변형(`_title_variants`)을 함께 본다** — iTunes 수록곡 제목에는 괄호 밖
  꼬리표가 붙어("Enemy (with JID) - from the series Arcane…") 전체 문자열로만 견주면
  실제 공식 영상조차 일치하지 않아 영영 '없음'으로 남는다(실측). 정규화는 제목 속
  하이픈을 지키려고 `" - "`를 자르지 않으므로, 여기서 `" - "` 앞부분을 변형으로 추가한다.
  **③은 원래 점수 가산 요소였을 뿐이라 아무 후보도 막지 못했다** — 실측 사고: Mr.Children의
  앨범 'HOME'을 채울 때 "Wake Me Up!"에 Avicii, "Piano Man"에 Billy Joel, "Houkiboshi"에
  규현의 곡이 붙었다(셋 다 제목만 같고 가수가 다르다). 검색어가 `"<가수> <곡> official
  audio"`라 정답 후보에는 가수가 제목이나 채널에 거의 항상 드러나므로, 근거가 하나도
  없는 후보는 남의 곡으로 본다. **가수명 대조(`_name_visible`)는 ASCII면 낱말 단위**다
  ("IU"가 "studious"에 걸리면 안 된다). 다만 **띄어쓰기를 지운 표기도 함께 본다** —
  YouTube 채널 핸들은 붙여쓰기가 흔해("ImagineDragons") 낱말 경계만 보면 정작 그 가수의
  공식 채널이 남의 채널로 판정된다(실측). 짧은 이름의 오탐을 막으려 붙여쓰기 대조는
  4글자 이상일 때만 허용하고, 한글·일본어는 조사가 붙는 표기가 흔해 부분문자열로 둔다.
  살아남은 후보 중에서는 **채널명에 가수가 있는지**(공식 채널 — 제목에만 가수를 적어 둔
  팬 편집본과 갈라 준다), YouTube가 자동 생성하는 `<가수> - Topic` 채널인지(공식 음원임을
  더 강하게 시사), 곡 길이가 얼마나 가까운지로 점수를 매겨 가장 그럴듯한 것을 고른다. 검색
  풀은 검증으로 걸러질 것을 감안해 `_SEARCH_POOL`(8)로 넉넉히 받는다(한 번의
  `ytsearchN:` 호출이라 늘려도 요청 수는 그대로다). **하나도 통과하지 못하면 그
  수록곡은 계속 'missing'으로 남는다** — 틀린 음원을 붙이느니 '없음'이 낫다(외부 수록곡
  제목이 로마자인데 실제 영상은 원어인 경우 — 일본곡의 "Houkiboshi" ↔ 「箒星」 — 처럼
  정답을 못 찾는 자리도 생기지만 그 자리는 비워 두는 것이 맞다).
  **검증 규칙을 고쳐도 이미 저장된 연결은 그대로 남는다** — 사용자 화면은 아무것도
  달라지지 않으므로 `migrate_album_links_reverify`가 1회 재판정한다. 저장된 행에 스트림
  제목·채널이 있고 앨범 키 앞부분이 정규화된 가수명이라(`album_key_artist`) **네트워크
  없이** `link_artist_matches`로 그 자리에서 판정할 수 있다. **전부 비우지 않고 틀린 것만
  지운다** — 실측 라이브러리에서 잘못된 매핑은 42건 중 3건뿐이었고, 나머지를 함께 버리면
  앨범을 열 때마다 곡마다 yt-dlp 검색이 다시 돈다. 사용자가 지운(`rejected`) 행은
  손대지 않는다(캐시가 아니라 판단이라, 지우면 그 자리가 자동 채우기 대상으로 되살아난다).
  **수정 모드로 잘못 붙은 자동 매핑을 지운다**: 앨범 상세 우측 상단 "✎ 수정" 토글을
  누르면(누르기 전엔 완전히 숨겨져 있다) **자동 매핑(AUTO) 행에만** 삭제(✕) 버튼이
  뜬다(`_TrackRow.set_edit_mode` — 내 라이브러리 영상은 훨씬 무거운 동작이라 대상이
  아니고, '없음'은 지울 게 없다). 클릭하면 `RemoveAlbumTrackLinkHandler`가
  그 (disc_no, track_no) 행을 **지우지 않고 `origin=rejected`로
  표시**한다(`IAlbumRepository.reject_track_link`, 스트림 정보는 비운다). **행을 지우면
  앨범을 다시 열 때 자동 채우기가 같은 영상을 도로 붙여 지우는 기능이 무력해진다**
  (실측 — `_on_album_detail_ready`가 `missing_count > 0`이면 매번 채우기를 돌린다).
  그래서 `FillAlbumTracksHandler`는 `retry_rejected=False`(앨범 열 때 도는 자동
  채우기)면 거부된 슬롯을 건너뛰고, 사용자가 **'빠진 곡 찾기'를 직접 누른 경우에만**
  `retry_rejected=True`로 다시 시도한다. DB 한 줄 갱신뿐이라 QThread 없이 즉시
  처리되며(`AlbumViewModel.remove_track_link`), 그 슬롯만 '없음'으로 되돌린 DTO를 실어
  화면 한 자리만 갱신한다(전체 재조회 없음). **VM이 들고 있는 `detail`도 함께 갈아
  끼운다** — 앨범 재생·수록곡 클릭이 `vm.detail`을 그대로 쓰므로, 안 고치면 방금 지운
  음원이 재생목록에 남아 그대로 재생된다. 다른 앨범으로 넘어가면 수정 모드는 자동으로 꺼진다
  (`AlbumDetailPanel.set_detail`) — 켜진 채로 남으면 새로 연 앨범에서 실수로 누를 수 있다.
  앨범 값이 빈 노래는 `ResolveUnknownAlbumsHandler`가 가수·제목으로 앨범을 추정해 `apply_fetched`로
  채우고(다음 조회부터 제 앨범으로 이동), 실패한 곡은 `album_lookup_state`에 남겨 **화면을 열
  때마다 같은 조회를 반복하지 않는다**. 재생은 새 경로를 만들지 않고 기존 재생목록 컨텍스트
  (`_playlist_ctx`)를 그대로 쓴다 — 로컬 곡은 video_id, 자동 매핑 곡은 FeedVideoDTO를 payload로
  실어 자동 다음곡·뒤로가기가 그대로 동작한다. 앨범 화면은 **하위 카테고리까지 포함**한다
  (`_album_category_ids` — 음악 라이브러리는 'Music > 가수 > 곡' 구조라 루트에서 보면 전부 빠진다).
  **앨범 화면도 화면 히스토리에 편입된다** — 스냅샷(`_capture_screen`)에 `album_mode`·
  `album_key`를 함께 실어, 앨범 그리드 진입(`_enter_album_mode`)·앨범 상세 진입
  (`_on_album_clicked`)·앨범 재생(`_start_album_playlist`) 세 지점에서 직전 화면을 쌓는다.
  복원은 `_restore_album_mode`가 모드를 맞춘 뒤 상세를 다시 여는 순서다(상세는 그리드 위에
  열리므로 순서가 뒤바뀌면 안 된다). 마우스 ‹/›가 앨범 화면에서도 먹도록 이벤트 필터를
  앨범 그리드·상세에도 설치한다(영상 상세는 자체 app 레벨 필터를 쓴다).
  회귀 테스트: `tests/unit/domain/test_album_grouping.py`(그루핑·정규화·매칭 규칙),
  `tests/unit/infrastructure/test_album_provider.py`(요청 파라미터·country 금지·실패 격리),
  `tests/integration/test_albums.py`(캐시·폴백·자동 채우기·앨범 추정),
  `tests/gui/test_album_view.py`(보기 버튼 노출 조건·배지·재생 배선·2장 앨범 행 갱신).
- **지금 재생 중 미니바** — 상세 화면을 떠나도 **재생 중이면** 멈추지 않고 창 하단
  띠(`MiniPlayerBar`)로 넘긴다. 멈춰 있었으면 예전처럼 정지한다 — 안 보이는 곳에서
  소리도 없이 자원만 붙들 이유가 없다. 핵심은 **플레이어를 옮기지 않는다**는 것이다:
  `VideoDetailWidget`은 `_nav_stack`에 살아 있는 위젯이라 화면을 목록(0)으로 바꿔도
  `QMediaPlayer`는 계속 재생한다. 그래서 복귀(`mini_open`)는 **다시 불러오는 게 아니라
  스택 인덱스만 1로 되돌리는 일**이고, 그 덕에 재생이 한 번도 끊기지 않는다(위치·화질·
  자막 상태까지 그대로). 여기에 재로드가 끼면 그 장점이 통째로 사라지므로
  `tests/gui/test_mini_player.py`가 "다시 불러오지 않는다"를 못박는다. 띠는 창 바닥
  (상태바 위)에 두어 다운로드·설정 페이지에서도 보이며, 위치·재생 여부는 신호가 아니라
  **0.5초 타이머로 훑는다**(`positionChanged`는 초당 수십 번 온다). 미니바로 듣는 중의
  자동 다음곡은 `stay_on_list=True`로 **화면을 뺏지 않고** 다음 곡만 갈아 끼우며, 이때
  연관 목록(재생목록)을 그대로 넘겨야 그다음 곡으로도 이어진다(`related=None`으로 열면
  지금 보고 있는 카테고리 목록으로 갈아타 버린다).
- **영상 자막 (언어 선택 · 자동 번역 · 두 줄 동시 표시)** — 영상에 딸린 YouTube 캡션을
  컨트롤바 `CC` 메뉴에서 고른다. **가사 자막(💬)과는 별개 기능**이다(가사는 노래 정보에서
  오고 자막은 그 영상의 캡션이다). 칸이 **둘**이라 원어와 모국어를 동시에 볼 수 있고,
  칸마다 '자동 번역' 대상을 따로 고른다. 렌더는 기존 `LyricsOverlay`를 그대로 쓰되
  `set_subtitle_texts(primary, secondary)`로 **한 번에** 세팅한다(따로 넣으면 짝이 어긋난
  화면이 한 프레임 스친다). 가사와 동시에 켜면 가사가 위, 자막이 아래에 놓인다.
  **번역은 우리가 문장을 번역하지 않고 YouTube의 번역 트랙을 받는다**(캡션 URL에
  `tlang=<코드>`). 자막 한 편을 `deep-translator`로 돌리면 수백 번 왕복이 생기고 문맥이
  끊겨 품질도 떨어진다 — 가사 번역(짧은 한 덩어리)과는 사정이 다르다. 번역본을 못 받으면
  **원본으로 한 번 더 시도**한다(번역이 없다고 자막 자체를 잃을 이유는 없다).
  **자동 자막 목록에서 번역본을 걸러 내는 것이 필수**다: 실측 결과 한 영상의
  `automatic_captions`에 312개(번역 가능한 모든 언어)가 들어 있었고, 그대로 나열하면
  원래 언어가 무엇인지도 알 수 없다 — URL에 `tlang=`이 있으면 번역본으로 보고 제외한다.
  원본 자동 자막의 키는 `en-en`·`de-de` 꼴이라 `en`으로 정규화해야 수동 자막 `en`과
  중복되지 않는다(실측으로 발견). 트랙 목록(yt-dlp)·파일 내려받기(HTTP)는 모두 QThread에서
  하고 영상별로 캐시하며, 늦게 도착한 결과는 그 사이 다른 트랙·영상으로 넘어갔으면 버린다.
  지난번에 고른 언어는 설정에 남아 **다음 영상에도 같은 언어가 있으면 이어서 켠다**
  (영상마다 다시 고르게 하면 '늘 쓰는 설정'이 매번 사라진다). 회귀 테스트:
  `tests/unit/infrastructure/test_subtitle_parsers.py`(자동 자막의 단어 타이밍 태그·반복 줄),
  `tests/unit/infrastructure/test_youtube_subtitles.py`(번역본 제외·키 정규화·번역 폴백),
  `tests/gui/test_video_subtitles.py`(두 칸 동시·빈 구간·늦은 결과 폐기).
- **추천 영상 미리 받기(무한 스크롤)** — 스트립이 오른쪽 끝에 **닿기 전**(카드 두 장쯤 앞)
  다음 묶음을 백그라운드로 받아 이어 붙인다. 끝까지 밀고 나서 받으면 빈 공백을 보며
  기다리게 된다. **씨앗을 새로 뽑지 않는다** — `derive_seed_queries`는 목록당 최대 3개
  (제목 키워드·최다 태그·최다 채널)뿐이라 더 뽑을 검색어가 없다. 대신 같은 검색어를
  **더 깊이**(`per_query`를 페이지마다 늘려) 파고 이미 보여 준 URL을 `exclude_urls`로
  걸러 새것만 남긴다. 결과가 하나도 없으면 그 씨앗은 바닥난 것으로 보고 더 요청하지
  않는다(스크롤할 때마다 같은 검색을 반복하면 조용히 네트워크만 축낸다). 추가분 워커는
  **본 조회와 분리**돼 있어 세대(`_gen`)를 올리지 않는다 — 올리면 진행 중인 첫 조회 결과가
  버려진다. 결과가 도착하면 `_more_worker` 자리를 **즉시** 비운다: 스레드가 끝나기를
  기다리면 그 사이 들어온 다음 요청이 '조회 중'으로 오인돼 조용히 버려진다(실제로 이
  경합이 테스트를 간헐 실패시켰다).
- **읽는 글(요약·가사) 글자 크기** — 요약과 가사는 읽으라고 있는 글인데 크기가 코드에
  박혀 있었다. `Ctrl` + `+`/`-`로 조절하고 `Ctrl+0` 또는 각 헤더의 **배율 버튼**(현재 %를
  표시하며 누르면 기본값)으로 되돌린다. 단일 키는 플레이어 몫이라 쓰지 않는다(입력 규칙).
  배율은 **두 영역이 공유**하고(글자 크기는 화면 설정이지 영역별 취향이 아니다) 전역
  설정(`detail_text_scale`)에 저장한다. 가사는 줄마다 스타일시트로 크기를 주므로 배율이
  바뀌면 다시 그리되 **현재 강조 줄은 유지**한다. 0.1 누적이 `1.97000…2`로 저장되지 않도록
  `clamp_scale`이 소수 둘째 자리에서 끊는다(자막 배율에서 겪은 문제).
- **재생 컨트롤 아이콘 크기** — 13px/24px(원래) → 26px/48px(2배, `gui/widgets/player/
  controls.py`) → **28px/38px**(상자를 20%가량 줄이되(48→38) 글자 대 상자 비율은 오히려
  키움(26/48=54% → 28/38=74%), 안쪽 여백도 `2px 6px` → `0px 1px`로 최소화)로 두 단계
  조정했다. 상자만 줄이고 글자 비율·여백을 그대로 두면 작아진 상자 안에 여백만 커 보여
  '꽉 찬' 느낌이 나지 않는다 — 그래서 상자를 줄이는 변경은 항상 비율 확대·여백 축소를
  함께 한다. **바 높이는 `_ICON_BOX + 48`**(여백+슬라이더 행 몫은 아이콘 상자 크기와
  무관하게 항상 48px)로 유도해, 상자 크기를 바꿀 때마다 높이 상수를 손으로 다시
  계산하지 않는다.
- **이어보기(재생 위치)** — `videos.last_position_ms`·`last_played_at`. **기기마다 보던
  지점이 다르므로 동기화 캡처 대상이 아니다**(view_count와 같은 취급). 판정은 도메인
  규칙(`VideoAggregate.update_playback_position`): 15초 미만은 기록하지 않고(잠깐 눌렀다 만 것),
  97% 이상이면 위치를 지우고 `watched`를 세운다(끝 직전으로 되돌아가면 오히려 불편하다).
  저장은 재생 중 5초마다 + 화면을 떠날 때 한 번 더이며, 아그리게이트 전체 저장 대신
  **가벼운 UPDATE 전용 경로**(`save_playback_position`)를 쓴다(반복 호출되므로).
  상세를 열면 저장된 지점으로 seek 하되 **자동 재생하지 않는다** — 목록에서 눌렀을 뿐인데
  소리가 나면 놀란다(재생목록 자동 전환만 `autoplay`). 카드 썸네일 바닥의 진행률 띠는
  `_paint_progress_bar`가 그리고, 정렬 '최근 재생순'·검색 `in_progress_only`가 짝을 이룬다.
  회귀 테스트: `tests/integration/test_resume_playback.py`, `tests/gui/test_resume_ui.py`.
- **라이브러리 정리(중복·사라진 파일)** — 중복 판정은 순수 규칙(`domain/library/duplicates.py`):
  **영상 ID로 먼저** 묶고(URL 정규화가 `youtu.be`·`watch?v=`만 합치고 **`/shorts/`는 그대로 두어**
  같은 영상이 두 행으로 들어온다), ID를 모르는 것만 제목+채널로 '비슷함'으로 묶는다.
  같은 것을 두 번 세지 않도록 ID로 묶인 것은 제목 묶기에서 제외한다. application 핸들러는
  **DTO로 바꾼 뒤 판정한다** — 아그리게이트는 값이 `.video.url`처럼 한 겹 안쪽이라 그대로
  넘기면 조용히 빈 결과가 된다(실제로 겪었다). 삭제는 자동으로 하지 않는다.
  회귀 테스트: `tests/integration/test_library_maintenance.py`, `tests/gui/test_library_cleanup_dialog.py`.
- **피드/채널 메타데이터 보강** — yt-dlp `extract_flat`은 구독 피드·채널 영상의 게시일·조회수를 주지 않으므로(영상 ID·길이만), `GetSubscriptionFeedHandler`·`GetChannelVideosHandler`가 YouTube Data API `videos.list`(`get_videos_channels`, part=snippet,statistics,contentDetails)로 `published_at`(ISO)·조회수·길이를 보강한다. 채널 카드의 "최근 영상" 시점은 채널 업로드 재생목록 첫 항목(`get_latest_upload_dates`, 채널당 1쿼터·스레드풀 병렬)으로 구한다. **`_yt_api`(OAuth) 미설정 시 graceful**: 시간 미표시 + 채널은 이름순 정렬.
- **번들 YouTube OAuth 로그인** — 사용자가 Client ID/Secret을 입력하던 방식을 배포자 소유 Desktop OAuth 클라이언트 1개를 빌드에 번들하는 방식으로 교체했다(소수 지인 배포 특성상 반복 입력이 번거롭고 실수하기 쉬움). **클라이언트 설정과 사용자 토큰은 서로 다른 자산**이다 — `infrastructure/youtube/oauth_client_config.py:find_youtube_oauth_config()`가 explicit path→`OVC_YOUTUBE_OAUTH_CONFIG` 환경변수→번들된 `config/OAuth2.json`(`get_resource_path`)→개발용 `data/OAuth2.json` 순으로 클라이언트 JSON 경로만 찾는다(값은 절대 반환·로그하지 않음, 형식이 틀린 후보는 조용히 건너뛰지 않고 `OAuthClientConfigError` 즉시 발생). **사용자 토큰은 keyring 우선**(`KeyringSecretStore("online-video-clipper.youtube-oauth", DATA_DIR/secrets/youtube_oauth.json)`, 키 `youtube.oauth.credentials.v1`) — 과거 SQLite `yt_oauth_tokens` 테이블(`yt_api_credentials`)에 있던 토큰은 최초 조회 시 1회 자동 마이그레이션되고, secret store 저장이 확인된 뒤에만 원본 SQLite 행을 삭제한다(확인 실패 시 인증 유실 방지를 위해 보존). `YouTubeOAuthAdapter(db, secret_store, client_config_path)`의 `run_auth_flow()`는 무인자로 Desktop/PKCE(`autogenerate_code_verifier=True`) + loopback(`host="127.0.0.1", port=0`) 플로우를 실행하고, 토큰 리프레시는 `verify=False` 세션 없이 정상 TLS 검증으로 수행한다(과거 코드는 `urllib3.disable_warnings`까지 썼던 위험한 패턴이었음). composition root(`main.py:_build_youtube_oauth(db)`)가 이 셋을 조립해 주입하며, 클라이언트 설정이 없어도 `has_client_config() == False`인 어댑터를 반환해 앱 시작을 막지 않는다(YouTube API 기능만 비활성). 설정 화면은 Client ID/Secret 입력란 없이 `Google 계정으로 연결` 단일 버튼만 노출한다(자세한 내용은 위 `settings_panel.py` 항목 참고). **인증은 재시작 후에만 전 핸들러에 적용**된다 — 이미 생성된 `_yt_api`/`YouTubeApiAdapter` 등을 실행 중 다시 묶는 라이브 리바인딩은 이번 범위에 포함하지 않는다. **YouTube 인증은 시작 시 lazy binding으로 미룬다(Phase 2 Step 1, 시작 시간 단축)** — `main.py`는 더 이상 시작 시점에 `yt_oauth.get_credentials()`를 호출하지 않고(keyring 접근 200~300ms 절감), 그 자리에 정의한 `_get_youtube_api()` 클로저(`nonlocal _yt_api`로 캐시)를 YouTube API가 필요한 모든 핸들러에 `yt_api_provider` 콜백으로 주입한다. 각 핸들러(`GetSubscriptionFeedHandler`·`GetChannelVideosHandler`·`GetSubscribedChannelInfosHandler`·`GetRecommendationsHandler`·`GetYouTubePlaylistsHandler`·`RenamePlaylistHandler`·`AddVideoToPlaylistHandler`·`RemoveVideoFromPlaylistHandler`·`ReorderPlaylistHandler`·`MoveVideoToPlaylistHandler`·`PushPlaylistToYouTubeHandler`·`ImportYouTubeSubscriptionsHandler`)는 각 파일의 `_resolve_yt_api(yt_api, yt_api_provider)` 헬퍼로 `handle()` 호출 시점에만 인증을 해석한다(`ImportYouTubePlaylistHandler`는 이미 `yt_oauth`+`yt_api_factory`로 같은 목적을 달성해 손대지 않았다). **해석 결과는 성공·실패 모두 캐시**되어 세션 중 반복 keyring 접근을 만들지 않으며, 이는 위에서 말한 "재시작 후에만 적용" 동작과 동일하다. `PushPlaylistToYouTubeHandler`는 `yt_adapter`가 필수였던 것을 옵션으로 바꾸고 미인증 시 `handle()`에서 `RuntimeError`를 던지도록 바꿔, `main.py`가 인증 유무로 핸들러 생성 자체를 조건분기(`if _yt_api else None`)하지 않아도 되게 했다(오류는 그대로 `PlaylistViewModel.push_to_youtube()`의 워커 `error_occurred`로 표출). PyInstaller 빌드는 `OVC_YOUTUBE_OAUTH_CONFIG`(미지정 시 `data/OAuth2.json`)가 가리키는 JSON을 `scripts/build_windows.ps1`/`scripts/build_linux.sh`가 값 노출 없이 검증한 뒤 `packaging/online_video_clipper.spec`이 `config/OAuth2.json` 한 개로 번들한다(환경변수 미설정·파일 없음이면 spec이 `SystemExit`).
- **라이브러리 가져오기/내보내기(카테고리 단위 zip 패키지)** — 모은 카테고리·영상·노래 가사/싱크 정보를 다른 사람에게 전달하거나 백업하는 용도. **내보내기**(`ExportLibraryHandler`)는 선택한 카테고리 id를 `list_categories()` 기준으로 하위까지 자동 확장(`_expand_with_descendants`)한 뒤, 그 집합에 속한 영상만 담는다 — **조상이 선택되지 않았으면 패키지 안에서 그 카테고리는 parent_id가 없는 루트로 취급**(가져오는 쪽이 상위 트리를 몰라도 되게). 패키지는 `manifest.json`+`data.json`(categories/videos, 영상마다 `song`(가사 포함) 중첩) + `thumbnails/`로 구성되고 실제 zip 입출력은 `infrastructure/transfer/portable_package.py`(`ILibraryPackageWriter`/`Reader` 포트 구현)가 전담해 application 레이어는 THUMBNAIL_DIR 절대경로를 모른다. **가져오기는 3단계**: `PreviewImportHandler`(패키지의 카테고리 목록+영상 수만 훑어 선택 UI 자료를 만든다, DB에 손대지 않음) → `DetectImportConflictsHandler`(선택된 카테고리의 영상 중 URL이 로컬에 이미 있는 것만 값이 다른 필드를 찾아 보고 — **값이 완전히 같으면 충돌로 보고하지 않는다**) → `ImportLibraryHandler`(실제 반영). **병합 키**: 영상=URL(`get_by_url`), 카테고리=(이름, 로컬로 매핑된 부모) — 패키지 카테고리 id는 그 패키지 안에서만 의미 있는 **문자열**(UUID로 강제 변환하지 않음)이라 부모가 선택 안 된 경우도 자연스럽게 표현된다. **충돌 필드의 기본 선택값**은 한쪽이 비어있고 다른 쪽이 채워져 있으면 채워진 쪽(빈 칸 채우기는 안전하다는 가정), 둘 다 채워져 있으면 기존값 유지(조용한 덮어쓰기 방지) — `ImportFieldDiffDTO.existing_filled`/`incoming_filled`로 GUI가 "(비어있음)" 표시까지 그대로 보여준다. **가사 시각(start_ms) 보존은 `apply_fetched`를 쓰고 `edit_lyrics`를 쓰지 않는다** — `edit_lyrics`는 수동 재입력용이라 줄 수가 바뀌면 시각을 버리는 게 의도된 동작이라(오탈자 수정 보호), 새 아그리게이트(줄 수 0→N)에 쓰면 항상 시각이 날아간다. **태그는 항상 합집합으로 자동 병합**(사용자에게 묻지 않음 — "둘 다 유지"가 항상 안전하므로). 카테고리가 비어있던(미분류) 영상은 가져온 카테고리로 자동 채워지고, 이미 분류돼 있으면 명시적으로 "가져오기"를 고르지 않는 한 유지된다. 설정 패널의 `_ImportExportSection`(`transfer_vm` 주입 시에만 노출)이 다이얼로그 순서(카테고리 선택 → 파일 선택 → 충돌 해결)만 조율하고, 실제 I/O·병합은 전부 `LibraryTransferViewModel`의 QThread 워커가 수행한다. **네 핸들러 모두 완료 시 `logger.info`로 카운트를 남긴다**(내보내기: 카테고리/영상 수+경로, 충돌감지: 새 영상/충돌/완전동일 수, 가져오기: 새 영상/병합/카테고리 수+경로) — 같은 라이브러리로 내보낸 뒤 그대로 다시 가져오면 전 영상이 완전히 동일해 충돌 화면 없이 조용히 병합되는데, 이게 정상 동작인지 오류인지 화면의 작은 상태 문구만으론 구분하기 어려워 실제 문의가 있었다. 로그가 없으면 사후 진단이 불가능하므로 필수로 남긴다.
- **GUI on main thread** — all network/download work runs in background `QThread`; results communicated via Qt signals.
- **yt-dlp progress hooks** → `DownloadProgress` value object → emitted as Qt signal to update progress bar.
- **Aggregates own state changes** — e.g., `VideoAggregate.mark_watched()` not `video.watched = True`.
- **Repositories are interfaces in `domain/`** — GUI and Application layers depend on abstractions; SQLite is an implementation detail.
- **Domain Events over direct calls** — when a download completes, `DownloadCompleted` event triggers library update and UI notification independently.
- **ffmpeg resolved via `get_ffmpeg_path()`** — checks `bin/` first (bundled), falls back to system PATH.
- **Ports over concrete infra in application** — application 레이어는 `EventBus`/`YtDlpAdapter`/`FfmpegAdapter`를 직접 import하지 않고 `domain/shared/ports.py`의 Protocol(`IEventBus`·`IMediaSource`·`IClipExtractor`)에 의존한다. 어댑터는 구조적 타이핑으로 이를 만족(상속 불필요)하며, 구체 인스턴스 주입은 composition root(`main.py`)가 담당한다. 작업별 진행률 훅이 필요한 다운로드처럼 인스턴스를 새로 만들어야 하는 경우는 **팩토리 콜백을 주입**한다(`make_downloader`, `yt_api_factory`).
- **자동 업데이트(백그라운드 다운로드 + 종료 시 설치)** — 시작 시 조용히 확인(`UpdateController.check_silently`, `AUTO_UPDATE_CHECK`+1시간 간격)해 새 버전이 있으면 **사용자 조작 없이 백그라운드로 다운로드**(`UpdateDownloadWorker`)한다. 완료되면 `gui/updater/pending.py:write_pending_update`가 `<tempdir>/ovc_pending_update.txt`(2줄: 인스톨러·exe) 마커를 기록하고(**앱 종료는 안 함**) `update_ready` 시그널을 방출 → `MainWindow`가 **설정 기어 버튼에 빨간 점 배지(`_NavButton.set_badge`)+"업데이트 준비 완료" 툴팁**을 표시하고 설정 헤더에 '지금 설치' 버튼을 노출한다. 실제 설치는 **앱을 닫을 때** `main.py` 종료 tail이 마커를 읽어 조용히 설치 후 재실행(설치는 실행 중 불가하므로). '지금 설치'는 `install_now`가 앱을 종료(마커가 이미 있으므로)해 즉시 설치를 유도한다. 마커 기록은 `UpdateDialog`(수동 경로)와 공유한다. **다운로드는 130MB가 넘어 API 조회용 타임아웃(10초)으로는 끊긴다** — 실제로 `Read timed out`으로 여러 번 실패했다. `download_asset`은 `_DL_TIMEOUT=(10,60)`을 쓰고, 끊기면 `Range`로 이어받아 `_DL_MAX_ATTEMPTS`(4)회까지 재시도한다(백오프 3초×시도). 이어받기 때문에 sha256은 스트리밍 중 누적하지 않고 완료된 `.part` 파일에서 한 번에 계산한다(`_sha256_of`). 본문이 content-length보다 짧게 끝나도 실패로 보고 재시도한다. **인터벌(1시간)은 성공했을 때만 소진한다**(`_mark_checked` — none_found·다운로드 완료·스누즈). 예전엔 확인을 시작하자마자 기록해, 다운로드가 실패하면 다음 1시간 동안 재확인이 막히고 앱을 다시 켜도 배지조차 안 떠 업데이트할 방법이 없었다. **다운로드 실패 시에도 설정 헤더에 설치 버튼을 노출한다** — `update_notification` → `MainWindow._on_update_notification` → `SettingsPanel.set_update_available(dto)`(상태 '업데이트 있음', 버튼 '설치하기' → `install_now`가 마커 없으면 `UpdateDialog` 수동 다운로드로 폴백). 예전엔 배지만 켜져 설정 화면에서 할 수 있는 게 없었다. 헤더의 **'확인' 버튼**(`check_update_requested`)으로 인터벌과 무관하게 즉시 재확인할 수 있다 — 이 시그널은 예전엔 선언만 되고 방출하는 곳이 없는 죽은 코드였다. 확인 중에는 `check_started`/`check_finished` → `set_update_busy`로 버튼을 잠근다.
- **스트리밍 재생 실패 → 브라우저 튕김 (해결)** — "카테고리·추천 영상을 재생하면 앱에서
  안 나오고 브라우저가 열린다"는 신고의 원인은 **두 가지**였다.
  ① **간헐적 403**: 기본(web) 클라이언트로 받은 googlevideo URL이 같은 영상인데도
  어떤 때는 200, 어떤 때는 403을 돌려준다(실측으로 재현 — PO token/SABR 전환기의
  서버측 거부로 보인다). 같은 순간 `android` 클라이언트로 받으면 정상이었다.
  ② **첫 실패에 곧바로 포기**: `_on_play_failed`가 원인과 무관하게
  `QDesktopServices.openUrl`로 브라우저를 열었고 **로그를 전혀 남기지 않아**,
  사용자 로그를 받아도 실패 흔적이 없었다.
  대응: `_StreamWorker._run_stream`이 `_STREAM_CLIENTS`(기본→android→ios→tv)를 돌며
  URL을 받고, **넘기기 전에 `_stream_playable`로 검증**해 거부되면 다음 클라이언트로 간다.
  **검증 요청은 실제 재생 주체(Qt Multimedia의 FFmpeg 백엔드)와 똑같아야 한다** — 이걸
  틀려서 한 번 헛돌았다: 처음엔 `Range: bytes=0-1`(제한 범위)로 확인했는데, 같은 URL이
  제한 범위에는 206을 주고 **ffmpeg가 파일을 열 때 보내는 `Range: bytes=0-`(열린 범위)
  에는 403**을 주는 경우가 있어 검증만 통과하고 재생은 실패했다. 그래서 `_PROBE_RANGE`는
  열린 범위이고 UA도 ffmpeg 기본값(`Lavf/...`)을 쓴다(yt-dlp 전용 헤더로 검증하면 같은
  이유로 위양성이 난다). 응답 본문은 읽지 않고 즉시 닫는다. 클라이언트
  교체 재시도는 `_is_youtube`일 때만 한다(다른 사이트엔 의미 없는 왕복).
  **검증이 전부 실패해도 URL을 하나라도 얻었으면 그대로 재생을 시도**한다 — 확인 요청이
  막히는 환경(프록시)에서 재생을 통째로 잃지 않기 위한 안전판이며, 최소한 예전 동작과
  같다. 고화질 병합 경로도 같은 클라이언트 목록을 돌고, 전부 실패하면 **낮은 화질
  스트리밍으로 폴백**한다(브라우저로 튕기는 것보다 낫다). 재생 중 QMediaPlayer 오류는
  `_MAX_STREAM_RETRIES`(1)회까지 새 URL로 조용히 재시도하되 **로컬 파일 재생 오류는
  재시도하지 않고**(같은 파일이라 무의미), 예산은 실제 재생이 시작될 때
  (`_on_playback_state`의 PlayingState) 회복한다 — 스트림을 받을 때마다 초기화하면
  오류→재시도가 무한 반복된다. `_pick_stream_url`은 **muxed(영상+오디오) 포맷만**
  고른다(예전 마지막 폴백은 `url`만 있으면 무엇이든 집어 영상 전용 포맷으로 무음·실패를
  만들었다). 실패 시 브라우저를 열지 않고 `InlinePlayer.show_playback_error`로 이유를
  영상 자리에 띄우며, 브라우저로 갈지는 상단 `🌐` 버튼으로 사용자가 고른다.
  회귀 테스트: `tests/gui/test_stream_fallback.py`.
- **다운로드 403 Forbidden + 조각난 `.part` 파일 (해결)** — 위 스트리밍 재생과 **원인은
  같지만 경로는 달랐다**: `YtDlpAdapter.download()`(`infrastructure/downloader/ytdlp_adapter.py`)는
  스트리밍 경로(`_StreamWorker`)의 클라이언트 폴백이 생기기 전에 작성됐고 그 뒤로도
  이식되지 않아, 기본(web) 클라이언트의 간헐적 403을 그대로 맞았다. yt-dlp가
  포맷(영상/오디오)별로 조각을 받다가 403으로 중단되면 `<제목>.f<itag>.<ext>.part`
  임시 파일이 병합·정리되지 않고 디스크에 남는다(실사용 데이터에서 재현: `f137.mp4.part`·
  `f399.mp4.part`). 대응: `download()`도 `_DOWNLOAD_CLIENTS`(기본→android→ios→tv, 스트리밍과
  동일한 순서)를 돌며 403일 때만 다음 클라이언트로 재시도하고(403이 아닌 오류는 클라이언트를
  바꿔도 소용없으므로 즉시 전파), 마지막 클라이언트도 실패하면 그대로 예외를 전파한다.
  **`.part` 정리는 성공 시에도 필요하다** — 첫 클라이언트가 403으로 조각을 남기고 두
  번째 클라이언트가 성공하는 흔한 경우, 정리를 "완전 실패했을 때만" 돌리면 그 조각은
  영원히 남는다. `_progress_hook`이 매 조각의 `tmpfilename`을 `_tmp_files_seen`에
  기록해 두고, 성공·완전실패 양쪽 경로 끝에서 `_cleanup_partial_files()`가 그 목록을
  지운다(이미 정상 병합·삭제된 파일은 `missing_ok=True`라 안전). 회귀 테스트:
  `tests/unit/infrastructure/test_ytdlp_download_retry.py`.
- **Gemini AI 요약 자동 메모 저장** — `DownloadSettings.capture_gemini=True`이면 다운로드 완료 후 `GeminiExtractor`(Playwright sync API)가 YouTube 페이지에서 요약 텍스트를 추출하고, `AddVideoHandler`를 통해 라이브러리 영상 `notes` 필드에 저장한다(`initial_notes` — 기존 메모가 비어있을 때만 덮어씀). 추출 실패는 완전히 격리돼 다운로드 결과에 영향을 주지 않는다. `infrastructure/browser/gemini_extractor.py`는 반드시 QThread에서만 호출한다. **패키징(PyInstaller) 빌드에는 Playwright의 Chromium 바이너리가 번들되지 않는다**(spec이 playwright 브라우저를 수집하지 않음 → `BrowserType.launch: Executable doesn't exist …chrome-headless-shell.exe`). 따라서 `_launch_browser()`는 시스템 설치 브라우저를 `channel="chrome"`→`"msedge"` 순으로 우선 실행하고, 둘 다 없을 때만 번들 Chromium으로 폴백한다(대상 사용자 대부분이 Chrome/Edge 보유 → 150MB 브라우저 번들 회피). 쿠키 소스(인증)와 실행 브라우저는 별개다. **"질문하기" 버튼 클릭은 채팅 패널을 여는 것일 뿐 자동 요약이 아니다** — 실제 요약을 얻으려면 패널 안의 "동영상을 요약해 줘" 추천 칩을 다시 클릭해야 한다(`_click_and_extract`). 응답은 스트리밍으로 채워지므로 고정 지연 대신 칩을 감싸는 컨테이너(칩에서 6단계 조상으로 추정)의 `innerText`가 `_STABLE_REQUIRED_COUNT`회 연속 동일할 때까지 폴링해 완료를 판단한다(`_wait_for_stable_text`). 실패 시 `LOG_DIR/gemini_debug.png`·`gemini_debug.html`에 진단 스냅샷을 남긴다. **Gemini가 자동화 브라우저를 감지해 "문제가 발생했습니다" 오류로 요청을 거부하는 사례를 확인**했다 — 헤드리스 Chromium에 `--disable-blink-features=AutomationControlled` 인자와 `navigator.webdriver` 오버라이드 init script로 완화하고, 오류 문구(`_ERROR_PHRASE`) 감지 시 칩을 최대 `_MAX_ERROR_RETRIES`회 재클릭한다. **`get_by_text`로 잡은 요소가 텍스트 span/div일 뿐 실제 클릭 핸들러가 걸린 button이 아니어서 클릭이 씹히는 사례를 확인** — 클릭 전 `xpath=ancestor-or-self::button[1]`로 진짜 버튼 조상을 우선 사용하고, 클릭 전/후 패널 텍스트가 동일하면(=클릭 미반영) 재시도 후에도 그대로면 실패로 처리한다(정적 인사말을 성공으로 오인하지 않도록). **인증은 쿠키 파일(Netscape 포맷)로만 이루어진다.** 확보 우선순위: 1) 설정 화면 "구독 피드 — 브라우저 쿠키" 섹션의 "또는 쿠키 파일"(`YT_AUTH_COOKIEFILE`), 2) `data/auth/youtube_cookies.txt` — `gui/dialogs/youtube_auth_dialog.py`의 `YouTubeAuthDialog`(Playwright로 **자체 브라우저 창**을 띄워 로그인시키고 `context.cookies()`로 직접 캡처해 `write_netscape_cookies`로 저장)가 이 파일을 만든다. **설정 화면 "구독 피드 — 브라우저 쿠키" 섹션 맨 위 "브라우저 열어서 로그인 (권장)" 버튼**(`SettingsPanel._on_open_auth_dialog`)으로 연결되어 있다 — 예전엔 이 다이얼로그가 구현은 돼 있었지만 앱 어디에서도 열리지 않는 미연결 코드였다("쿠키를 왜 찾아야 하냐, 브라우저를 띄워서 로그인시키면 안 되냐"는 사용자 질문으로 연결). **기존 브라우저의 쿠키 DB를 전혀 건드리지 않아**(자체 격리된 Playwright 컨텍스트에서 로그인) Chrome 잠금·App-Bound Encryption 문제와 완전히 무관하게 동작하는 것이 핵심 장점이다 — 아래 "브라우저/프로필" 자동 감지가 실패하는 환경에서도 이 방법은 별도의 문제다. `_find_system_chromium_exe()`가 시스템 설치된 Chrome/Edge/Brave 실행 파일을 직접 찾아 `executable_path`로 넘겨 실행하므로(playwright `channel=`이 아님) 패키징 빌드에도 번들 Chromium 없이 동작하며, 못 찾으면 `_open_system_browser()`가 기본 브라우저로 로그인 페이지만 열고(쿠키 자동 캡처는 안 됨) "브라우저 계정" 탭에서 프로필을 고르라고 안내한다. **Google이 자동화된 브라우저의 로그인을 차단하는 사례를 실제로 확인**했다("로그인할 수 없음 — 브라우저 또는 앱이 안전하지 않을 수 있습니다") — Playwright가 CDP로 제어하는 브라우저는 Google 로그인 시점에 자동화로 탐지되기 쉬우며, `gemini_extractor.py`와 동일하게 `--disable-blink-features=AutomationControlled` + `navigator.webdriver` 오버라이드를 추가했지만 **Google의 로그인 자동화 탐지는 페이지 열람 탐지보다 훨씬 엄격해 이 완화만으로 항상 우회되지는 않는다**(구조적 한계 — CDP 제어 자체가 탐지 신호가 될 수 있음). 따라서 **설정 화면에서 이 버튼은 더 이상 "권장"으로 표기하지 않고**, "쿠키 파일 등록 방법 보기"(사용자가 평소 쓰는 정상 브라우저에서 확장으로 직접 내보내는 방식 — 자동화 탐지 대상이 아님)를 실질적인 권장 경로로 안내한다. 3) 같은 설정 섹션의 "브라우저"/"프로필" 드롭다운(`YT_AUTH_BROWSER`/`YT_AUTH_PROFILE`)을 `GeminiExtractor._export_browser_cookies()`가 yt-dlp `cookiesfrombrowser`로 임시 내보내기(Firefox 등 대부분 브라우저에서 동작; 임시 파일은 Netscape 헤더로 미리 초기화해야 yt-dlp의 cookiejar 최초 로드가 실패하지 않음). **Chrome v127+ 예외**: Chrome은 쿠키를 App-Bound Encryption으로 암호화해 프로필 직접 실행·프로필 파일 복사·yt-dlp `cookiesfrombrowser` 세 가지 방식 모두 외부 프로세스가 복호화할 수 없음을 확인했다(DPAPI 오류) — Chrome 사용자는 방법 1(쿠키 파일 직접 등록)만 유효하다. **브라우저/프로필 쿠키 내보내기는 자동 감지로 폴백한다** — 사용자가 "매번 설정에서 브라우저/프로필을 다시 골라야 해서 불편하다"고 신고한 뒤 추가됨. `GeminiExtractor._export_browser_cookies()`는 이제 설정된 브라우저(있으면)를 먼저 시도하고, 실패하거나(브라우저 실행 중 DB 잠금·Chrome 암호화 실패 등) 아무것도 설정하지 않았으면 `_auto_detected_candidates()`가 `infrastructure/auth/youtube_auth.py:YouTubeAuthService.detect_profiles()`로 설치된 모든 브라우저의 로그인 프로필을 `_AUTO_DETECT_BROWSER_ORDER`(firefox→edge→chromium→chrome) 순으로 순회해 자동으로 시도한다. 자동 감지로 성공한 조합은 `save_setting`으로 즉시 저장돼 다음 시도부터 먼저 쓰인다(반복되는 실패-재탐색 축소). 이미 시도한 (브라우저, 프로필) 조합은 자동 감지 단계에서 중복 시도하지 않는다. **설정된 브라우저·자동 감지가 모두 실패해 쿠키를 전혀 못 찾으면 반드시 `out["reason"] = SUMMARY_REASON_NOT_SIGNED_IN`을 채운다** — 예전엔 이 경로가 사유를 채우지 않아 `extract_with_reason`이 기본값(`SUMMARY_REASON_ERROR`, "잠시 후 다시 시도하세요")으로 떨어졌다. 실제로는 로그인된 브라우저를 못 찾은 것인데 원인을 알 수 없는 오류로만 보여, 브라우저 프로필을 이미 선택했는데도 왜 계속 실패하는지 알 수 없게 만들었다(사용자 실제 신고로 발견). **쿠키 파일 후보 자동 스캔**: "쿠키 파일" 기능을 한 번도 써본 적이 없어 어디 두는지조차 모른다는 신고에 따라, `infrastructure/auth/youtube_auth.py:find_cookie_file_candidates()`가 `~/Downloads`·`~/Desktop`을 스캔해 Netscape 헤더 + `youtube.com` 도메인 항목을 포함한 `.txt` 파일(브라우저 확장이 내보낸 쿠키 파일 — 파일명이 제각각이라 **내용**으로 판별)을 최신 수정 순으로 찾는다. 설정 화면 "구독 피드 — 브라우저 쿠키" 섹션의 "감지된 쿠키 파일" 콤보(`SettingsPanel._reload_cookie_candidates`)가 이 목록을 보여주고, 선택하면 "또는 쿠키 파일" 경로란에 채워진다("다시 검색" 버튼으로 재스캔, 방금 확장으로 내보낸 경우 대응). 후보가 없으면 안내 문구만 표시되고 기존 "찾기…" 수동 선택은 그대로 남는다. **일반 사용자를 위한 폴더 바로가기·안내 다이얼로그**: "이건 컴퓨터 전문가용 앱이 아니다"(브라우저/프로필 자동 감지가 전혀 동작하지 않는 환경에서 경로를 직접 찾아야 하는 데 대한 불만)는 신고에 따라, `gui/panels/settings_panel.py:open_folder(path)`(`QDesktopServices.openUrl(QUrl.fromLocalFile(...))`)로 경로를 직접 입력할 필요 없이 버튼 클릭만으로 탐색기를 연다. "저장 경로" 섹션의 데이터베이스·다운로드·썸네일·로그 4개 행 각각에 "열기" 버튼을 추가했고, 쿠키 섹션에는 "쿠키 파일 등록 방법 보기"(`COOKIE_HELP_TEXT` — 확장 설치→로그인 확인→내보내기→"다시 검색" 4단계 평문 안내 + "다운로드 폴더 열기" 버튼이 있는 `QDialog`)와 "로그 폴더 열기" 버튼을 추가했다. 후자는 사용자가 `AppData` 경로를 몰라도 로그 폴더를 열어 `app.log`를 지원 요청 시 첨부할 수 있게 한다. **자동 감지가 왜 후보를 못 찾았는지도 로그에 남긴다**: 실제 사용자가 보내온 로그에서 "설정된 브라우저·자동 감지 모두 실패"만 보이고 firefox·edge·chromium·chrome 각각이 몇 개의 프로필을 찾았는지 전혀 알 수 없어 원인을 좁힐 수 없었던 사례가 있었다. `_auto_detected_candidates()`가 이제 브라우저별 프로필 개수를 `"자동 감지 브라우저별 프로필 개수: firefox=0, edge=1, ..."` 형식으로 INFO 로그에 남기고, `detect_profiles()` 호출 자체가 예상 밖의 예외를 던지는 경우도 호출부에서 한 번 더 잡아 로그로 남긴다(라이브러리 내부 예외 처리에만 의존하지 않음).
- **Gemini 요약 — Playwright 대기 함정과 영상별 기능 제공 여부** — `Locator.is_visible(timeout=...)`의 `timeout`은 **Playwright가 무시한다**(문서: "Deprecated: This option is ignored. `locator.is_visible()` does not wait for the element to become visible and returns immediately."). 과거 `_click_and_extract`가 이걸로 "질문하기" 버튼을 찾아 **0초 대기**했고, 액션 행이 아직 스켈레톤인 영상에서 0.2초 만에 미발견으로 포기했다. 지금은 `_find_ask_button`이 `wait_for(state="visible")`로 총 `_ASK_BUTTON_TIMEOUT_MS`(20초)를 한 번만 소비한다. **셀렉터마다 `>> visible=true`를 반드시 붙인다** — 실측 결과 지원 영상에서 `button[aria-label*='질문하기']`가 5개 매칭 중 첫 번째가 **숨은 요소**여서, 필터 없이 `or_`로 합치면 `.first`가 그 숨은 요소를 가리켜 정상 영상까지 실패하는 회귀가 난다(한 번 실제로 냈다). 로그인 판정 `_detect_login_state`도 같은 이유로 `wait_for`를 쓴다 — 예전엔 로그인이 됐는데도 "판별 불가"로 기록돼 실패 원인을 잘못 짚게 했다. **YouTube는 이 기능을 영상별로 선별 제공한다**: 조회수가 적거나 업로드가 최근인 영상은 DOM에 `질문하기`가 **아예 없어**(1920px에서도 0개, 오버플로 메뉴에도 없음) 어떤 대기·수정으로도 요약을 얻을 수 없다. 따라서 실패 로그는 '미로그인'과 '영상 미지원'을 구분해 남기고, UI 메시지도 쿠키 문제로 단정하지 않는다. **실패 사유는 영속된다**: `GeminiExtractor.extract_with_reason(url) -> (요약, 사유)`가 `SUMMARY_REASON_NO_BUTTON`·`NOT_SIGNED_IN`·`ERROR`를 돌려주고, `video_summary_status` 테이블(video_id, status, updated_at — `video_descriptions`처럼 분리해 `videos` 행을 늘리지 않는다)에 저장된다. `VideoDetailDTO.summary_status`로 실려 요약 탭 placeholder가 사유별로 달라진다(`video_detail_panel.summary_placeholder`, `no_button`이면 "질문하기 버튼이 없어 가져오는데 실패했습니다"). 요약을 성공적으로 가져오면 행을 삭제해 문구가 사라진다. 기록 경로는 등록 시 자동 보강(`EnrichVideoHandler`)과 상세 ⟳(`_GeminiSummaryWorker.done`이 사유를 실어 `summary_status_saved` → `UpdateVideoCommand.summary_status`) 두 곳이다. 기존 `extract()`는 `ISummarySource` 포트 계약이라 그대로 두었다(다운로드 완료 캡처가 쓴다). **상세 화면 상단의 한 줄 상태 라벨(`_summary_status_lbl`)도 사유별로 다른 문구를 쓴다**(`video_detail_panel.summary_failure_status_label`) — 과거엔 사유와 무관하게 항상 "설정에서 브라우저/프로필을 선택하거나 쿠키 파일을 등록하세요"를 보여줘, `no_button`(YouTube가 그 영상에 요약 기능을 제공하지 않는 것)처럼 설정을 고쳐도 소용없는 경우까지 설정 탓으로 안내해 사용자가 반복적으로 헛수고를 하게 만들었다.
- **영상 검색 (부분 일치)** — `SqliteVideoRepository._build_search_sql`이 **제목·태그·설명·메모·요약·노래(가수/앨범/제목/발매년도)·가사**를 부분 일치(`LIKE ... ESCAPE ''`)로 덮는다. 과거에는 `videos_fts`(FTS5)가 **제목·메모 두 열만** 덮었다. FTS5 대신 부분 일치를 쓰는 이유: ① 한글은 어미가 붙어 단어 단위 매칭이 자주 빗나간다 ② 어느 속성이 일치했는지 판정이 정확하다 ③ 규모가 작다(영상 수백 건). **가사는 절대 SQL `LIKE`로 다루지 않는다** — `lyrics_json`이 `[{"o":원문,"t":번역}]` 형태라 검색어 `o`·`t`가 JSON 키에 걸려 모든 노래를 오탐한다(회귀 테스트 `tests/integration/test_search_fields.py::TestLyricsJsonFalsePositive`로 고정). 일치 속성은 `match_fields_for(video_ids, text)`가 **현재 페이지 50건에만** 실행해 `MATCH_FIELD_KEYS` 순서로 반환하고, `VideoDTO.match_fields`로 실려 `VideoListModel.MatchFieldsRole`을 거쳐 그리드·리스트 델리게이트가 배지로 그린다(`_paint_match_badges`, 높이 `_MATCH_ROW_H`는 리플로우 방지를 위해 항상 확보). 한글 라벨(`MATCH_FIELD_LABELS`)은 GUI만 갖는다. `LIKE '%...%'`는 인덱스를 타지 않으므로 라이브러리가 수만 건이 되면 통합 FTS 테이블로 되돌리는 것이 맞다. `videos_fts`와 트리거는 `test_merge_applier.py`가 동기화 병합 후 발화를 검증하는 데 쓰므로 **제거하지 않았다**. **가사는 최상위 카테고리가 음악인 영상만 검색한다** — 루트 조상 카테고리 이름이
  `music`·`song`·`음악`·`노래`·`뮤직`(`MUSIC_ROOT_CATEGORY_NAMES`, trim+소문자 비교)일 때만 대상이며
  미분류는 제외한다. 게이트는 `_lyrics_match_ids`(검색 결과)와 `match_fields_for`(배지)
  **양쪽에 똑같이** 걸어야 한다 — 한쪽만 걸면 "가사로 검색됐는데 배지는 없는" 불일치가 난다.
  루트 해석은 재귀 CTE이고 `depth < 32` 가드가 필수다(`categories`에 순환을 막는 제약이
  `UNIQUE(name, parent_id)`뿐이라 데이터가 순환하면 앱이 멈춘다). 부수 효과로 매 검색마다
  전체 가사를 JSON 파싱하던 부담이 줄어든다.
- **검색 입력 응답성 (키 입력이 밀리던 문제)** — 검색창은 **키 입력마다 조회하지 않는다**. `LibraryPanel._on_search_text_changed`가 `_search_timer`(`_SEARCH_DEBOUNCE_MS`=300ms, 단발)만 재시작하고, 멎으면 `_apply_search_text`가 한 번 조회한다. Enter는 즉시, 지우기(빈 문자열)도 즉시 적용한다. 뷰모델 `set_search_text`는 **strip 결과가 같으면 재조회하지 않는다**(IME 조합·뒤 공백). 조회 자체는 예전부터 워커 스레드였지만, 그 뒤에 이어지는 **메인 스레드 작업**이 병목이었다: ① 표(상세) 뷰 `_refresh_table`이 결과가 바뀔 때마다 **행마다 `get_video_detail`**(영상당 여러 쿼리 + 다운로드 파일 `stat`)을 돌렸다 → `GetDownloadedFormatsHandler`(URL 묶음 단일 쿼리, `IDownloadRepository.find_completed_formats_by_urls`)로 대체하고, **표가 실제로 보일 때만** 채운다(숨겨져 있으면 `_table_dirty`로 표시했다가 `_switch_view`에서 지연 갱신). ② 결과가 바뀔 때마다 `_ThumbBgLoader`가 새로 떠 이전 목록의 썸네일 50장을 계속 디코딩했다 → 새 로더를 시작하기 전에 이전 로더를 `cancel()`한다. ③ 가사 후보 조회(`_lyrics_match_ids`)가 **매 검색마다 전체 가사를 JSON 파싱**했다 → `_lyrics_prefilter_safe(text)`일 때 `lyrics_json LIKE`로 후보를 먼저 좁히고(값이 그대로 저장돼 있어 안전 — `ensure_ascii=False`), `"`·`\`·제어문자·대소문자 있는 비ASCII가 섞이면 프리필터를 포기하고 전체 스캔으로 되돌아간다(이 폴백은 `tests/integration/test_search_fields.py::TestLyricsPrefilter`가 고정). `_lyrics_text`는 `lru_cache`로 재파싱을 피한다. 회귀 테스트: `tests/gui/test_search_debounce.py`, `tests/integration/test_downloaded_formats_bulk.py`.
- **목록·검색 로딩 스켈레톤 (v1.22.0 체감 성능 개선 Phase 1 Step 3)** — 카테고리 클릭은
  `loading_key_changed`(노드 키 기준)로 트리 스피너와 "불러오는 중" 안내가 떴지만,
  **검색 조회(`set_search_text`)는 노드 키가 없어 어떤 로딩 신호도 내지 않았다** —
  디바운스 300ms + 쿼리 시간 동안 화면이 낡은 목록을 든 채 아무 말도 하지 않는,
  체감 지연이 가장 큰 경로가 비어 있었다. `LibraryViewModel.loading_changed`
  (bool 시그널)를 추가해 `_run_list`/`_drain_list`가 **노드 키 유무와 무관하게**
  발행하고, 화면 표시는 텍스트 안내 대신 `gui/panels/library/skeleton_list.py`의
  `ListSkeleton`(카드/행 자리를 셰이머 블록으로 먼저 보여줌)으로 교체했다(텍스트와
  스켈레톤이 동시에 뜨면 안 되므로 `overlay.py`는 더 이상 '조회 중'을 그리지 않는다 —
  결과 0건 안내 3종만 남았다). **깊이 카운터(`_list_inflight`)로 겹치는 조회를 관리**한다
  — `_max_workers`(기본 4)로 여러 조회가 동시에 진행될 수 있어, 단순 bool 토글이면
  먼저 끝난 조회가 아직 진행 중인 다른 조회의 스켈레톤을 꺼버린다. 0→1에서만
  `loading_changed(True)`, 1→0에서만 `loading_changed(False)`를 낸다. 캐시 히트
  (`_video_cache` 적중)는 `_run_list`를 거치지 않고 즉시 반환하므로 스켈레톤이 뜨지
  않는다(깜빡임 방지). **트리 노드별 스피너(`loading_key_changed`)는 이 스켈레톤을
  더 이상 직접 켜고 끄지 않는다** — `sidebar.py`의 `_on_local_loading_key_changed`가
  예전엔 `_on_list_loading`을 함께 호출했는데, 겹치는 조회에서 먼저 끝난 노드가
  스켈레톤을 꺼버리는 사고(깊이 카운터를 우회)가 났다. 지금은 트리 스피너 전용으로만
  남았고, 스켈레톤은 오직 `_on_list_loading_any`(`vm.loading_changed` 슬롯)를 통해서만
  켜고 끈다. `ListSkeleton`은 폴더·피드·채널 카드 그리드에서는 뜨지 않는다(아이콘·
  리스트·표 뷰에서만 — 그 화면들은 영상 목록이 아니라 다른 스켈레톤이 필요하면 별도
  담당). 회귀 테스트: `tests/gui/test_library_vm_loading_signal.py`(신호 자체 —
  단일/검색/캐시 적중/겹치는 조회 깊이 안전), `tests/gui/test_list_skeleton.py`
  (`ListSkeleton` 위젯 — 표시/숨김·뷰별 배치·뷰포트 크기별 개수), `tests/gui/test_list_overlay.py`
  (패널 배선 — 스켈레톤과 텍스트 안내가 겹치지 않음, 노드 키 신호가 스켈레톤을 직접 못 끔).
- **단일 인스턴스 가드** — `gui/single_instance.py`의 `SingleInstanceGuard`(QLocalServer/QLocalSocket)가 앱 중복 실행을 막는다. `main.py`가 **DB를 열기 전에** `try_acquire()`를 호출해 두 프로세스가 같은 DB를 동시에 건드리지 않게 하고, 이미 실행 중이면 기존 창을 앞으로 부른 뒤 조용히 종료한다. 서버 이름은 사용자별(`ovc-single-instance-<username>`)이며 비정상 종료로 남은 소켓은 `removeServer()`로 회수한다. **업데이트 후 2개 실행의 근본 원인은 `packaging/installer.iss`의 `[Run]`에 `skipifsilent`가 없어 무인 설치에서도 Inno가 앱을 실행한 것**이었다(배치의 `start`와 중복). **재실행 주체는 배치 하나로 고정한다** — 배치는 구버전 앱이 만들고 인스톨러는 신버전이라, 양쪽을 모두 막으면 다음다음 업데이트에서 아무도 앱을 실행하지 않는다.
- **등록 시 요약·가사 자동 보강** — **단건 등록**(`LibraryViewModel.add_video`)이 끝나면 `EnrichVideoHandler`(application/library/commands.py)가 `song_info.is_song`을 읽어 한쪽만 채운다: 노래 영상이면 `FetchSongInfoCommand(fetch_lyrics=True)`로 **가사만**(가수·앨범·제목·발매년도는 등록 시 이미 채워졌고 체인은 빈 값만 채우므로 실질적으로 가사만 추가된다), 아니면 `ISummarySource.extract`(=`GeminiExtractor`)로 **요약**(`gemini_summary`)을 채운다. **가사를 못 찾아도 요약으로 폴백하지 않는다.** 이미 값이 있거나 추출기가 미주입이면 `kind="skipped"`로 건너뛴다. 설정 `AUTO_ENRICH_ON_ADD`(기본 ON)로 끌 수 있다. **재생목록·채널 일괄 임포트는 대상이 아니다** — 그 경로들은 `AddVideoHandler`를 직접 호출하고 ViewModel을 지나지 않으므로 자연히 제외되며, Gemini가 영상당 브라우저를 띄워 수십 초 걸리기 때문에 의도된 제외다. 보강은 `_EnrichWorker`(QThread)에서 **동시 1건**으로 직렬화한다(`_pending_enrich` 큐 — 브라우저 병렬 실행 방지). 진행·실패는 `MainWindow` 상태바에 표시하고(`enrich_started`/`enrich_finished`), 완료 시 그 영상 상세가 열려 있으면 `_reload_detail_in_place`로 재로드한다(상세 DTO+노래 정보를 함께 다시 읽어 요약 탭·노래 탭 모두 반영). `ISummarySource`는 `domain/shared/ports.py`의 Protocol이라 application 레이어가 infrastructure를 직접 import하지 않으며, 반환형은 실제 구현에 맞춰 `str | None`(실패 시 falsy)이다. 모든 실패는 `EnrichVideoResult(ok=False)`로 변환돼 등록 결과에 영향을 주지 않는다.
- **클라우드 동기화 캡처 (레코드 단위 oplog CRDT, 구현 중)** — 변경은 **리포지토리 경계에서 캡처**한다: `RecordingVideoRepository`가 `SqliteVideoRepository`를 상속해 `save`/`delete`만 오버라이드하고, super()로 라이브 DB에 반영한 뒤 `OplogRecorder`가 (이전 행 vs 새 값) diff로 **바뀐 필드만** op에 담아 로컬 세그먼트(`DATA_DIR/sync/pending/<install>/NNNNNN.ndjson`)에 append한다. 병합 레지스터 상태는 **로컬 전용** 테이블 `sync_identity`(자연키↔로컬 UUID + presence)·`sync_field_clock`(필드별 (lamport,install) 승자)·`sync_applied_ops`(멱등)에 materialize한다(동기화 대상 아님, `db/schema.sql`에 정의, 컴팩션 시 로그로 재생성 가능). `database.py`의 `MIGRATION_IDS` 상수가 "이 코드가 아는 스키마 능력"이며, 원격 op/스냅샷의 `schema_ids`가 이 집합을 벗어나면 `SnapshotStore`가 `SyncSchemaError`로 차단한다("앱 업데이트 필요"). 자격증명·install_id·lamport는 **DB 밖**(keyring, 부재 시 파일 폴백)에 둔다 — 시작 pull이 DB를 열기 전 접근해야 하기 때문. view_count 등 churn 필드·description(지연 로드)는 현재 캡처 제외. 캡처 엔티티는 **Video + video_tag 링크 + song_info**(Phase D-1)까지 확장됐다: 링크(조인 행)는 자체 필드가 없어 `record_link`/`record_unlink`가 presence-aware로 기록하고 양 끝점을 refs로 실어 보낸다(presence-only op은 merge writes가 비어 미반영되므로 refs 필수). **태그는 별도 op 없이** video_tag LINK op의 tag 이름 ref로부터 apply 측 `resolve_tag`가 lazy 생성한다(bare 태그 op이 sync_identity에 dangling UUID를 만들지 않도록). song_info는 Video와 1:1이라 nkey=영상 URL 키(가사 자막 오프셋 `lyrics_offset_ms`도 song_info 컬럼이라 함께 캡처된다 — 같은 영상 파일을 보는 기기라면 자막 어긋남도 같으므로 동기화 대상으로 삼는다). **category는 origin-identity(install+uuid)로 캡처**(Phase D-2a) — nkey가 rename에도 불변이라 rename이 필드 변경으로 올바르게 전파된다(이름경로 방식 폐기). video의 category 참조도 이름경로가 아니라 카테고리 origin nkey를 쓰며, apply 측 `resolve_category`는 origin nkey→로컬 UUID 해석(없으면 stub 생성해 배치 내 순서·FK 보장, 동명 카테고리 독립 생성 시 병합). clip·download는 origin-identity 단일 테이블(clip은 source_video ref). playlist·playlist_folder는 origin-identity, playlist_item·category_video_order·video_tag는 링크(멤버십만 동기화 — **수동 정렬 순서는 기기 로컬**, 적용 측이 append). **이제 전 엔티티 캡처/적용 완료(Phase D-2b)**. **캡처는 composition root(`main.py`)에 배선됨(Phase E) — 단 provider가 연결된 상태로 시작했을 때만** `SyncService.make_recording_repos`가 repo를 Recording*로 교체한다(미연결이면 무래핑 → 기존 앱 동작 무변경, oplog 미적재). 최초 연결 시 `SyncService`가 현재 DB를 스냅샷으로 push, 캡처는 다음 실행부터 활성. 시작 시 `pre_db_bootstrap()`(DB 열기 전)로 신규 기기는 스냅샷 부트스트랩, 기동 후 `sync_vm.start_auto_sync()`가 주기 push/pull+미디어 동기화.
- **미디어/썸네일 파일 동기화 (oplog와 별개 서브시스템, 구현 중)** — oplog는 **메타데이터만** 다루므로 실제 다운로드 파일·썸네일 바이트는 `infrastructure/sync/file_syncer.py`가 provider 위에서 별도로 왕복시킨다. **파일 identity의 진실원천 = sha256**(우리 `media/manifest.json`) — provider 네이티브 체크섬(Drive md5/OneDrive quickXorHash)은 교차 비교 불가라 안 쓴다. rel_path는 **DATA_DIR 기준 상대경로(POSIX)로 DB의 file_path 규약과 동일**해, 다운로드하면 `resolve_media_path`가 가리키는 위치에 바로 놓인다(DATA_DIR 밖 파일은 이식 불가라 스캔 제외 — Phase 0 규약과 일치). 재해시 회피: 이전 스캔 매니페스트를 캐시로 두고 size+mtime이 같으면 sha256 재사용. 계획은 순수 함수 `plan_file_sync`(로컬만→upload/원격만→download/sha다름→`prefer` 정책 "newer"(mtime 큰 쪽·동률 로컬)|"local"|"remote"), **삭제는 전파하지 않음**(어느 쪽에만 없는 건 미동기화로 봄). 다운로드는 `<name>.part`로 받은 뒤 `os.replace`로 원자 확정, 원격 매니페스트는 read-merge-write로 동시 추가 보존. `on_progress(MediaSyncProgress)`·`should_cancel` 콜백만 노출하고 **QThread 배선은 Phase 5(GUI)**가 감싼다. (원격 레이아웃: `media/manifest.json` + `media/files/<rel_path>`)
- **클라우드 provider 어댑터 (로컬 폴더 / Google Drive / OneDrive)** — `application/sync/ports.py`의 `ICloudSyncProvider` Protocol을 구조적으로 만족하는 세 백엔드. **`FolderProvider`(로컬 폴더=클라우드, 기본·권장)**: OneDrive/Drive 데스크톱 동기화 폴더를 가리키면 OS 클라이언트가 실제 왕복을 담당해 OAuth·API키가 필요 없다. `SyncState.folder_path`에 경로 영속, `provider_key="folder"`. 설정 UI에서 폴더 선택만으로 연결(`SyncService.connect_folder`). 이 provider로 **실 스택 end-to-end 테스트**(실 DB·캡처 repo·oplog·스냅샷 부트스트랩·실제 미디어 바이트)를 실계정 없이 수행한다(`tests/integration/test_folder_provider_e2e.py`, `tests/gui/test_sync_gui.py`). Google Drive/OneDrive API provider는 직접 연동을 원하는 사용자용. HTTP는 공용 `infrastructure/sync/rest_client.py`(requests + `verify=False` + 401 강제refresh 후 1회 재시도 — `youtube_api_adapter` 패턴 추출)로 하고, 토큰 획득/갱신은 provider별 콜백(`token_provider`/`force_refresh`)으로 주입한다. **Google Drive**는 파일 ID 모델이라 경로 기반 저장소(`oplog/...`, `media/...`)를 앱 루트 폴더 아래 폴더 트리로 **에뮬레이션**한다(경로→id 캐시로 중복 폴더 생성 방지), 인증은 `InstalledAppFlow`(scope `drive.file`), resumable 업로드 세션(청크 PUT, 308은 `allow_redirects=False`로 따라가지 않음). **OneDrive**는 Graph 경로 주소지정(`/me/drive/root:/<path>`)이라 훨씬 단순하며, msal `PublicClientApplication`+`SerializableTokenCache`(keyring 직렬화), 소형은 PUT `/content`·대형은 `createUploadSession`. 자격증명은 keyring(부재 시 파일)에 두고 `msal`은 지연 import라 미설치여도 모듈 import는 된다. **실계정 OAuth 왕복 검증은 로컬 전용(미완)** — 테스트는 in-memory fake HTTP로 401 재시도·경로/쿼리·URL 빌드·폴더트리·페이지네이션·텍스트/목록/삭제 왕복만 검증한다(`tests/integration/test_sync_providers.py`). provider **연결 UX**(설정 화면 OAuth 버튼)는 Phase 5.
- **컴팩션 + 스냅샷 부트스트랩 (구현 중)** — 오래된 op 로그를 무한히 재생하지 않도록 `CompactHandler`(application/sync/commands.py)가 현재 DB를 `snapshot_store.export_snapshot`(VACUUM INTO)으로 스냅샷 떠 provider에 `snapshot/library.db` + `snapshot/snapshot.json`(covered={install:seq}·schema_ids·db_sha256)로 발행한다. **covered = consumed ∪ {our_install: pushed_head}** — 스냅샷 DB가 반영한 각 install의 마지막 seq. 신규 기기는 시작 시 `infrastructure/sync/bootstrap.py:bootstrap_if_fresh`가 **DB를 열기 전(pre-DB)** 스냅샷을 받아 sha256 검증 후 `import_snapshot`(integrity+스키마 게이트+교체)하고 `consumed=covered`로 세팅한 뒤 이후 증분 pull한다. **부트스트랩은 로컬 DB가 없을 때만**(스냅샷 교체가 로컬 미병합 상태를 덮으므로) — 기존 기기가 뒤처지면 증분 pull로 따라잡는다. 세그먼트 **GC는 CompactHandler에서 기본 비활성**(`gc=False`): 스냅샷이 덮은 세그먼트를 지우면 뒤처진/휴면 install은 증분 pull로 회수 못 하고 스냅샷 부트스트랩에 의존하므로, 완전 안전 GC는 활성 install들의 consumed 워터마크 공유가 필요하다(열린 결정). 스냅샷 DB에는 sync_* 레지스터 테이블도 포함돼 새 기기가 일관된 필드 클럭·멱등 상태를 그대로 물려받는다.
- **미디어 경로 이식성 (머신 간 동기화 대비)** — `download_history.file_path`·`clips.file_path`·`clips.thumbnail_path`는 DB에 **DATA_DIR 기준 상대경로(POSIX 구분자)로 저장**하고, 런타임 엔티티에는 절대경로로 복원해 담는다. 변환은 **리포지토리 경계**에서만 일어난다 — `SqliteDownloadRepository`·`SqliteClipRepository`가 `save` 시 `config.settings.to_portable_path()`로 상대화, `_row_to_*` 로드 시 `resolve_media_path()`로 절대화한다(`delete_completed_duplicates`처럼 raw SQL로 경로를 읽는 지점도 resolve 적용). 따라서 application·gui·query 레이어는 예전과 동일하게 **절대경로**를 받으므로 수정할 필요가 없다. DATA_DIR 밖의 경로(사용자가 별도 위치 지정)는 이식 불가라 절대경로 그대로 보존한다. 기존 절대경로 DB는 `database.py`의 멱등 마이그레이션 `migrate_media_paths_relative`가 1회 정규화한다. (`videos.thumbnail_path`는 원래부터 `THUMBNAIL_DIR` 기준 상대경로라 이 규약 밖 — 읽는 쪽이 `Path(THUMBNAIL_DIR)/rel`로 결합.)
- **GUI→infra 예외 경계** — `gui/main_window.py`·`gui/dialogs/youtube_auth_dialog.py`는 `infrastructure.auth`를 직접 참조한다. `gui/panels/video_detail_panel.py`의 `_GeminiSummaryWorker`는 `infrastructure.browser.gemini_extractor.GeminiExtractor`를 지연 import한다. 로그인/Gemini 추출 플로우가 playwright 구동 등 **본질적으로 인프라**라 포트로 감싸도 런타임 의존이 사라지지 않으므로, composition-root 인접의 **수용된 경계**로 둔다(application 레이어는 이런 예외가 없어야 함).
- **Phase 2 성능 최적화 (YouTube OAuth 및 Database 지연 로딩)** — 시작 시간 단축 (200~300ms ↓):
  - **YouTube OAuth 지연 로딩**: `_build_youtube_oauth(db)` 람다를 `_get_youtube_api()` 클로저로 래핑해 시작 시점에 keyring 접근을 미루고, 각 핸들러(`GetSubscriptionFeedHandler` 등)에 `yt_api_provider` 콜백으로 주입. 최초 1회 호출 시점에만 `get_credentials()`를 평가해 keyring 접근(200~300ms)을 실제 API 필요 시점으로 뒤로 미룬다. 해석 결과(성공·실패 모두)는 캐시돼 세션 중 반복 keyring 접근을 만들지 않는다(재시작 후에만 갱신).
  - **Database 지연 로딩**: (구현 대기 — 유사 패턴 예상: schema validation·migration을 최소화하고 첫 쿼리 시점에 필요한 검사만 수행).
  - **누적 효과**: ~350~450ms 시작 시간 단축 예상 (메인 스레드 블로킹 제거).
- **버그 수정 기록** (v1.22.0 이후):
  - **스트리밍 재생 실패 → 브라우저 튕김 (403 Forbidden 폴백)**: `_StreamWorker`가 `_STREAM_CLIENTS` 체인(web→android→ios→tv)을 순회하고 `_stream_playable`로 **ffmpeg이 실제로 열 수 있는 URL**을 사전 검증. 거부되면 다음 클라이언트로 자동 전환. 검증 요청은 `Range: bytes=0-`(ffmpeg 기본)로 정확히 같게 하고 UA도 `Lavf/...`(ffmpeg 기본)으로 맞춰, 제한 범위와 열린 범위의 응답 차이(제한은 206·열린 범위는 403)를 감지한다. 모든 클라이언트가 실패해도 하나의 URL이라도 있으면 시도한다(환경 감지 불가에 대한 안전판).
  - **가사 번역 500 에러 및 일부 라인 누락**: `infrastructure/song/lyrics_providers.py`의 각 제공자 검색이 실패해도 나머지 결과는 계속 모은다(출처별 격리). 네트워크 타임아웃(connect 5s, read 8s)을 짧게 잡아 느린 출처를 빨리 건너뜨린다. 검색 결과 정렬은 조회수/길이 지표만 있을 때만 개입해 이미 랭킹된 검색 결과를 재정렬하지 않는다(국내 사이트 특성).
  - **`last_played_at` race condition**: 재생 위치 저장 시 **단조 증가 쿼리**(`UPDATE … SET last_played_at = MAX(last_played_at, ?), last_position_ms = ?, watched = ?`)로 지난 시간이 덮어쓰이지 않게 한다. 동시 저장이 일어나도 더 큰 타임스탐프만 유지된다.
  - **예외 로그 누락**: 네트워크 실패 경로(`infrastructure/browser/gemini_extractor.py`, `infrastructure/song/lyrics_providers.py`)에서 각 출처별 실패를 `logger.debug` 대신 **`logger.warning`("자동화 브라우저 감지", exc_info=True)** 등으로 명시적으로 기록해, 사후 진단이 가능하게 함. 격리된 예외(계속 다음 출처로 진행)는 `logger.debug`에 그치지만, 전체 경로가 폐기될 수 있는 판단에는 최소 `logger.info` 수준으로 의사결정 근거를 남긴다.

## 에러 처리 & 로깅 규칙 (mandatory)

- 진입점(`main.py`)에서 `utils.logging_config.setup_logging()`을 1회 호출한다(회전 파일 `LOG_DIR/app.log` + 콘솔).
- 모듈마다 `logger = logging.getLogger(__name__)`를 정의한다.
- **예외를 조용히 삼키지 말 것.** `except Exception: pass`/조용한 폴백이 필요하면(네트워크·API·DB 실패를 폴백 처리할 때) 반드시 `logger.exception("맥락")`으로 흔적을 남긴다. idempotent하게 무시해도 되는 경우만 `logger.debug(...)`.
- 예외를 UI로 표출하는 뷰모델 패턴(`error_occurred.emit(str(exc))`)은 이미 가시적이므로 그대로 둔다.
- **위젯이 띄우는 QThread는 절대 위젯에 매달지 않는다.** 부모로 주거나 위젯 속성 하나로만
  붙들면, 그 위젯이 지워질 때 실행 중인 스레드가 파괴돼 **Qt가 프로세스를 즉시 종료**한다
  (`QThread: Destroyed while thread '' is still running`). `quit()`+`deleteLater()`도 안전하지
  않다 — `quit()`은 이벤트 루프만 끝내므로 네트워크·yt-dlp를 도는 `run()`은 계속 실행된다.
  대신 `gui/workers.py`의 `track_thread`(생성 직후)와 `retire_thread`(정리 시)를 쓴다. 결과
  슬롯은 **QObject의 바운드 메서드**로 연결한다 — 수신 위젯이 사라지면 Qt가 연결을 자동으로
  끊지만, 위젯을 캡처한 람다는 그 보호를 받지 못해 죽은 위젯을 건드린다.
- **끝난 워커를 `deleteLater`로 지우지 않는다.** 아직 그 워커를 들고 있는 쪽(예: 플레이어의
  `self._worker`)이 나중에 접근하면 `RuntimeError: wrapped C/C++ object ... has been deleted`가
  난다(재생 중 뒤로가기에서 실제로 났다). `gui/workers.py`는 레지스트리에서 참조만 놓고,
  마지막 참조가 사라질 때 파이썬이 정리한다. `retire_thread`는 신호를 **이름으로** 받는다 —
  호출부에서 `worker.failed`를 꺼내는 순간 이미 정리된 객체면 거기서 터지기 때문이다.
- 백그라운드 워커를 만드는 뷰모델은 `shutdown()`을 제공하고 `MainWindow.closeEvent`에서 호출해 종료 시 워커를 정리한다. yt-dlp 다운로드처럼 협조적 취소 훅이 없으면 `terminate()` 후 `wait()`로 종료를 보장한다.
- **`track_thread` 없이 리스트 하나로만 QThread를 붙드는 것은 이 규칙을 지킨 게 아니다.** `MainWindow.closeEvent`의 `wait_all(3000)`은 `gui/workers.py`의 `_RUNNING` 레지스트리만 안다 — 자체 리스트(GC 방지용)에만 담아 둔 워커는 종료 시 기다려지지 않는다. `gui/panels/library/mixins/video_list.py:_start_thumb_preload`의 `_ThumbBgLoader`가 `_active_thumb_loaders`(취소용 리스트)에만 담겨 있어 이 구멍이 있었다(2026-08 메모리 최적화 점검에서 발견) — `track_thread(loader)`를 추가로 호출해 고쳤다. 자체 리스트로 다른 목적(취소·중복 방지)을 관리하더라도, **실행 중 QThread라면 반드시 `track_thread`도 함께 호출**한다. 회귀 테스트: `tests/gui/test_memory_cleanup.py::TestWorkerReferenceRelease`.

## 입력·움직임 규칙 (mandatory)

- **새 스크롤 영역을 만들면 `apply_smooth_scroll(area)`를 태운다**(패널 단위면
  `apply_smooth_scroll_tree(self)`). Qt 기본은 항목 단위 스크롤이라 카드 한 장씩 점프한다.
- **가로 전용 띠는 세로 스크롤바 정책을 `ScrollBarAlwaysOff`로 명시한다.** 내용 높이가
  뷰포트보다 몇 px만 커도 숨은 세로 막대에 근소한 범위가 생기는데, `_pick_bar`는 정책이
  꺼져 있으면 그 범위를 무시하고 가로로 고정한다 — 정책을 빼먹으면 휠을 굴릴 때마다
  화면이 위아래로 덜거덕거린다(실제 신고).
- **수정키가 붙은 휠은 절대 가로채지 않는다.** Ctrl+휠은 목록 뷰 전환, Ctrl(+Shift)+휠은
  자막 크기·위치 조절이 이미 쓴다 — 삼키면 그 기능이 **조용히** 죽는다.
- **단일 키(Space·J·K·L·화살표·C·M·F·P·[·]·\)는 플레이어 것이다.** 화면 단축키는
  Ctrl/Alt 조합·Esc·F5만 쓴다. 단축키 범위는 `WidgetWithChildrenShortcut`으로 좁혀
  다른 페이지를 볼 때 발동하지 않게 한다.
- **툴팁에 적은 단축키는 실제로 동작해야 한다** — 상세 뒤로가기 버튼이 "(Esc)"라고
  적어 두고 Esc를 처리하지 않던 적이 있다.
- **읽는 글의 크기는 사용자가 정한다.** 요약·가사 같은 '읽는 영역'에 글자 크기를 코드에
  박지 말고 `gui/panels/detail/text_zoom.py`의 배율을 곱한다(Ctrl +/- · Ctrl+0 · 배율 버튼).
- **마우스 ‹/›는 화면 단위가 아니라 창 단위로 받는다.** 위젯마다 이벤트 필터를 걸면 새 화면을
  추가할 때마다 조용히 죽는다 — 앱 전역 필터 + "같은 창인가" 판정으로 통일한다(모달 대화상자는 제외).
  대신 전역 필터에 붙는 다른 분기(Ctrl+휠 등)는 적용 범위를 명시적으로 좁힌다.
- **비동기로 도착한 그림은 `fade_in`으로 얹는다**(캐시 적중처럼 즉시 그려지는 경우는 그냥 둔다 —
  연출이 오히려 굼떠 보인다). 화면 전환은 `fade_switch`를 쓰되 **영상이 있는 화면은 즉시 전환**한다.
- **끝났다는 소식은 토스트로도 알린다**(`show_toast`) — 상태바는 시선이 가지 않아 놓치기 쉽다.
  진행 중 상태는 상태바가 계속 맡는다(계속 보여야 하므로).
- **상태를 말하지 않는 화면을 만들지 않는다.** 목록이 비면 왜 비었는지(검색·태그·빈
  카테고리)와 무엇을 하면 되는지를 안내판으로 알린다. 다만 **짧은 조회에서 로딩 표시가
  깜빡이면 더 산만하므로** 지연(250ms) 뒤에만 띄운다.

## 색상 규칙 (mandatory)

- **위젯 스타일시트에 색을 하드코딩하지 않는다.** `setStyleSheet`에 색이 필요하면
  `gui/themes/colors.py`의 `tok()`(테마 토큰)·`sem('success'|'danger'|'warning')`(의미 색)을 쓴다.
  하드코딩하면 테마를 바꿔도 그 색만 남아 밝은 테마에서 글자가 배경에 묻힌다(통계 화면이 그랬다).
- 예외는 **의미·브랜드 색**뿐이다: `_BADGE_EMPTY_BG`(영상 없음 경고), `_YT_BRAND_RED`(YouTube),
  `_PROGRESS_FG`(이어보기 진행률 띠 — 썸네일 위 고정 의미색), 영상 레터박스 검정,
  썸네일 위에 얹는 배지 배경·흰 글자, **자막 오버레이의 흰 글자·검은 외곽선**(영상
  프레임 위 가독성이 기준이라 앱 테마와 무관). 이유를 주석으로 남긴다.
- **`_TAG_PALETTE`(태그 식별용 32색)도 예외**다 — 테마 색이 아니라 태그를 서로
  구별하기 위한 고정 팔레트다. 단 칩 글자가 항상 흰색이므로 **전 32색이 흰 글자 대비
  4.5:1 이상**이어야 한다(`TestTagPaletteReadable`이 고정 — 실제로 2색이 미달이었다).
- 새 테마 프리셋을 추가하거나 토큰 색을 바꾸면 `tests/gui/test_theme_contrast.py`를 먼저 통과시킨다.
  이 파일은 텍스트 AA(4.5:1)뿐 아니라 **비텍스트 UI 요소의 3:1**(WCAG 1.4.11)도 지킨다:
  스크롤바 손잡이·포커스 링·칩 테두리. 텍스트 조합에는 **`bg_base` 위**도 포함된다 —
  이 조합이 빠져 있어 graphite의 `text_muted` 미달(4.18:1)이 통과한 채 방치됐다.
- **`bg_overlay`만으로 상태를 표현하지 않는다.** 배경 대비가 11개 테마에서 1.05~1.32:1뿐이라
  틴트만 걸면 반응이 없어 보인다(실측). 호버는 틴트 + **글자색 승급**(`text_secondary` →
  `text_primary`)을 함께 걸고, 호버보다 강한 상태(눌림·선택)는 accent 틴트를 쓴다.
  호버와 선택이 같은 색이면 지금 무엇이 켜져 있는지 알 수 없다.
- 토큰 사이의 중간값이 필요하면 **토큰을 새로 만들지 말고 파생**한다 —
  `stylesheet._rgba()`(QSS 틴트), `formatting._mix()`(델리게이트용 hex). 프리셋마다
  손으로 적으면 원본 토큰을 바꿀 때 같이 고치는 것을 잊는다.
- 카드·차트처럼 위젯 스타일시트나 QPainter로 직접 칠하는 화면은 전역 QSS 교체만으로 갱신되지 않는다 →
  `ThemeManager.theme_changed`에 다시 그리는 슬롯을 연결한다. **연결을 빼먹으면 그 화면만
  영구히 옛 색으로 남는다**(`player/controls.py`의 화질 배지가 그 상태다 — 미해결).
- **Qt가 지원하지 않는 QSS 선택자를 쓰지 않는다.** 조용히 무시돼 "고쳤는데 안 바뀐다"는
  함정이 된다. 대표적으로 placeholder 글자색은 QSS에 속성이 없고
  `QPalette.ColorRole.PlaceholderText`가 담당한다.
- **QWidget 서브클래스에 스타일시트 `background`를 주려면 `WA_StyledBackground`를 켜야
  한다.** 안 켜면 규칙이 조용히 무시된다 — `_ControlBar`의 `QWidget#ctrlbar
  { background: rgba(0,0,0,…) }`가 이 이유로 **한 번도 칠해지지 않았고**(실측: 바 영역
  픽셀이 뒤 배경색 그대로) 컨트롤바가 영상 위에 완전히 투명하게 떠 있었다. 스크림이
  없으면 어떤 글자색을 골라도 영상 밝기에 따라 묻힌다.
- **영상 위에 얹히는 UI는 테마 색을 쓰지 않는다.** 컨트롤바 배경은 테마와 무관하게 항상
  어두운 스크림인데 글자에 `tok.text_primary`를 쓰면 **밝은 테마 7종에서 어두운 글자가
  어두운 바에 얹힌다**(실측 1.10~1.90:1 — 재생·볼륨 버튼이 사실상 안 보였다).
  `controls.py`의 `_ON_VIDEO_*` 상수처럼 '어떤 영상 위에서도 읽히는가'를 기준으로 고정색을
  쓰고, 스크림 농도는 **순백 프레임 위에서도 흰 글자가 AA를 넘기는 값**(≥140/255)으로 잡는다.

---

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
- **YouTube OAuth 및 database 마이그레이션은 지연 로딩** — 시작 시 keyring 접근(200~300ms) 또는 스키마 검증을 미루고, 실제 API/DB 첫 사용 시점에만 평가한다.

### QThread Lifecycle Management (mandatory)

- **`gui/workers.py`의 `track_thread` + `retire_thread` 필수 사용** — QThread를 생성하면 즉시 `track_thread(worker, signal_name)`로 레지스트리에 등록(부모-자식 분리). 작업 완료 시 `retire_thread(worker_name, "signal_name")`으로 해제(신호를 **이름**으로 받음 — 객체 참조가 아님). 끝난 워커를 `deleteLater` 호출하지 말 것 — 아직 그 워커를 참조하는 코드가 나중에 접근하면 `RuntimeError: wrapped C/C++ object has been deleted`가 난다. 대신 마지막 참조가 떨어질 때 파이썬이 정리하도록 둔다. 위젯이 파괴될 때 실행 중 QThread가 있으면 Qt가 즉시 프로세스를 종료한다(exit 0xC0000409) — 이를 막는 유일한 방법이 `track_thread`/`retire_thread` 패턴이다. 결과 신호는 **QObject 바운드 메서드**로만 연결해야 Qt가 수신 위젯 파괴 시 자동으로 연결을 끊는다.

### Memory Profiling Results (v1.22.0 이후 검증)

- **썸네일 LRU 캐시 상한**: 100개/렌더 크기 종류(아이콘·리스트·상세) = 300개 QPixmap 최악 시 66MB (`QPixmapCache.setCacheLimit(30720)` 별도).
  - 아이콘 그리드(160×90) + 리스트(80×45) + 상세 뷰(배경용 큰 이미지)의 3 경로.
  - `library_panel.py`의 `_thumb_cache`에 대한 상한은 `library/thumbnails.py`의 `_ThumbnailCache` 데코레이터로 관리.
- **페이지네이션 구현 완료**: 모든 리포지토리 쿼리에 `LIMIT/OFFSET` 적용(기본 50), `.fetchall()` 사용 지점 0개, 커서 반복만 사용.
  - 검증: `tests/integration/test_downloaded_formats_bulk.py`(배치 조회), `tests/integration/test_search_fields.py`(검색 페이징).
- **Lazy Load 확인**:
  - `description`, `notes` 필드: `GetVideoByIdQuery` 상세 조회 시에만, 목록 쿼리에서 제외.
  - `song_info` 전체: 노래 탭 진입 시에만 `SongViewModel.load()` 호출.
  - 자막/영상 메타: 재생 시작 시점에만 `_on_playback_state`에서 조회.
- **기타 확인**:
  - `__slots__` 적용: `VideoUrl`, `Duration`, `Timestamp`, `ChannelInfo`, `DownloadProgress` 등 value objects (통계: ~30개 클래스).
  - Generator expressions: `_run_list`, `search_videos`, `get_related_videos` 경로 확인됨.
  - 백그라운드 QThread: 플레이리스트 임포트 50개 청크 단위, 다운로드 진행률 콜백 구현됨.

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
