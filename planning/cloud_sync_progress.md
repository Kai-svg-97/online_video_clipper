# 클라우드 동기화 — 진행 상황 & 로컬 이어가기 가이드

> 이 문서는 원격(웹) 세션에서 진행한 클라우드 동기화 기능의 상태와 **로컬에서 이어서 작업하기 위한** 핸드오프다.
> 설계 세부는 `planning/ddd_design.md`의 **Sync Context**, 파일 맵은 `CLAUDE.md`의 아키텍처 트리 및 "클라우드 동기화 캡처" Key Design Decision을 함께 볼 것.

## 이 기능이 하는 일 (확정된 방향)

여러 PC(집↔회사)에서 라이브러리·카테고리·태그·노래정보·메모·다운로드 이력 **+ 미디어 파일**을 OneDrive / Google Drive로 동기화한다.

- 병합 방식 = **레코드 단위 merge (oplog CRDT)**. 각 변경을 op 로그로 남겨 어느 기기의 추가·수정도 무손실 병합, 적용 순서와 무관하게 결정적 수렴.
- **진실원천 불변식**: 클라우드 마스터 DB는 로그로부터 재생성되는 **파생 스냅샷**일 뿐. 각 기기는 **자기 install-id 폴더의 로그에만 append**한다(파일 쓰기 경합 원천 제거).
- 자격증명·install_id·lamport는 **DB 밖(keyring)** — 시작 pull이 DB를 열기 전 접근해야 하므로.
- 미디어 파일은 manifest+diff, 백그라운드/수동(앱 종료를 막지 않음).

## 브랜치 / 커밋 상태

- 브랜치: `feat/cloud-sync-phase0-path-portability`
- 커밋(오래된→최신):
  - `d3c5c5a` Phase 0 — 미디어 경로 이식성
  - `26f84d0` Phase 1 — sync 도메인·포트
  - `25a235f` Phase 2 — 로컬 oplog·캡처·스냅샷 인프라
  - `19cae81` Phase 3 — merge_applier(op→라이브 DB)
  - `ee1d022` Phase 4 — sync 흐름 핸들러·원격 oplog·상태
  - `(이 문서 커밋)` — 진행 상황 정리

## 테스트 상태

- 비-GUI 테스트 **210개 통과**. 실행:
  ```bash
  pytest tests/unit tests/integration -q
  ```
- 원격 샌드박스엔 PyQt6가 없어 GUI 스모크(`tests/gui/`)는 미실행. 로컬에선 `pytest`로 전체 실행 가능.
- 관련 테스트 파일: `tests/unit/domain/test_sync.py`(순수 병합 로직 20 + 파일 동기화 계획 8), `tests/integration/test_sync_infra.py`(11), `tests/integration/test_merge_applier.py`(10), `tests/integration/test_sync_flow.py`(6), `tests/integration/test_file_syncer.py`(파일 동기화 엔진 12), `tests/integration/test_sync_providers.py`(provider 어댑터 14), `tests/integration/test_sync_compaction.py`(컴팩션·부트스트랩 6), `tests/integration/test_sync_entities.py`(엔티티 확장 D-1 6).

---

## 완료된 것 (Phase 0–4)

| Phase | 내용 | 핵심 파일 |
| --- | --- | --- |
| 0 | 미디어 경로 이식성(리포지토리 경계에서 절대↔상대 변환, 마이그레이션) | `config/settings.py`(`to_portable_path`/`resolve_media_path`), `database.py`(`migrate_media_paths_relative`), `sqlite_download_repository.py`, `sqlite_clip_repository.py` |
| 1 | 순수 도메인·포트 | `domain/sync/value_objects.py`(Op·OpKind·EntityKey·ClockEntry·SnapshotManifest), `domain/sync/services.py`(OpLogMerger·NaturalKey·topo_order·schema 게이트), `application/sync/ports.py` |
| 2 | 로컬 캡처·저장 인프라 | `infrastructure/sync/`: `keyring_secret_store`·`device`·`local_oplog_store`·`snapshot_store`·`recorder`·`recording_repository`(**Video만**) + `db/schema.sql`의 `sync_identity`/`sync_field_clock`/`sync_applied_ops` + `database.py`의 `MIGRATION_IDS` |
| 3 | 병합 적용 | `infrastructure/sync/merge_applier.py`(`MergeApplier` + `VideoApplyHandler` + 핸들러 registry, 직접 SQL로 FTS 트리거 정상 발화) |
| 4 | 흐름 오케스트레이션 | `application/sync/commands.py`(Push·Pull·SyncNow·Connect·Disconnect), `application/sync/queries.py`(GetSyncStatus), `infrastructure/sync/cloud_oplog_store.py`, `infrastructure/sync/sync_state.py` |

**동작 검증됨(핵심)**: 두 install(fake provider)에서 A가 영상 생성·편집→push, B가 pull→merge하면 B DB에 반영. 양방향 수렴, 순서 독립 수렴(순열 테스트), 필드 단위 LWW, tombstone(삭제/재add), 멱등 pull, 스키마 게이트 차단, FTS 일관성.

### 반드시 알아야 할 설계 규칙 / 불변식

- **자연키(nkey)**: video=정규화 URL(`normalize_video_url`), tag=name, category=이름경로, channel=channel_id, 링크=(부모nkey,자식nkey), 자연키 없는 것(로컬 재생목록·폴더·클립·다운로드)=`origin_key(install,uuid)`.
- **필드 단위 LWW**: `(lamport, install_id)` 큰 쪽 승. 서로 다른 필드 동시 편집은 모두 보존.
- **tombstone**: DELETE는 존재 레지스터에 부재 기록. 더 높은 lamport 재-add만 부활.
- **적용은 직접 SQL**(repo 아님) — RecordingRepository 미개입이라 원격 op를 다시 op로 기록하는 루프가 없고, FTS 트리거는 테이블에 걸려 있어 정상 발화, rowid는 로컬 재할당(op는 rowid를 실어나르지 않음).
- **스키마 게이트**: op/스냅샷의 `schema_ids`가 로컬 `MIGRATION_IDS` 부분집합이 아니면 `SyncSchemaError` 차단.
- **로그 제외 필드**(churn): `videos.view_count`, `description`(지연 로드), 순수 `updated_at`. — 현재 Video 캡처는 이들을 제외한 컬럼만.
- **캡처는 아직 composition root에 미배선** → 실행 중인 앱 동작 무변경. 켜지는 건 Phase 5.

---

## 남은 작업 (로컬에서 진행)

우선순위·의존순으로 정리. 각 항목은 착수 지점을 명시했다.

### A. ✅ 미디어/썸네일 파일 동기화 (구현 완료 — 엔진 레벨)
oplog는 **메타데이터만** 다룬다. "미디어 파일까지" 동기화는 별도 서브시스템으로 구현했다.
- ✅ `domain/sync/value_objects.py` `FileEntry(rel_path, size, mtime, sha256)` — 순수 값 객체(직렬화 포함).
- ✅ `domain/sync/services.py` `plan_file_sync`(순수) + `FileSyncAction`/`FileSyncItem` — 로컬만→upload/원격만→download/sha다름→`prefer` 정책("newer"|"local"|"remote"), **삭제 전파 안 함**, 결정적 정렬. 단위 테스트 8건.
- ✅ `infrastructure/sync/file_syncer.py`:
  - `scan_media_dirs` — `DOWNLOAD_DIR`·`THUMBNAIL_DIR` walk → rel_path(DATA_DIR 기준)·size+mtime 캐시로 sha256 재해시 회피. `.part`/DATA_DIR 밖 파일 제외.
  - `FileSyncer.sync(on_progress, should_cancel)` — 계획 실행. `media/manifest.json`(sha256 진실원천)+`media/files/<rel>` 레이아웃. 다운로드 `.part`→`os.replace` 원자 확정. 원격 매니페스트 read-merge-write(동시 추가 보존). `MediaSyncProgress`/`MediaSyncReport`.
  - 통합 테스트 12건(`tests/integration/test_file_syncer.py`) — 왕복·멱등·양방향 union·충돌 newer 승·진행률·취소·.part 잔여물 없음.
- 경로는 Phase 0 덕에 이미 `DATA_DIR` 기준 상대경로로 저장돼 있어 머신 독립.
- **남은 것(Phase 5로)**: QThread 래퍼(`_SyncWorker`)와 main.py 기동 후 백그라운드 트리거 배선. 엔진은 협조적 취소·진행률 콜백만 노출해 QThread가 그대로 감싸면 된다.

### B. ✅ provider 어댑터 (코드 완료 — 실계정 검증만 남음)
- ✅ `infrastructure/sync/rest_client.py`: 공용 `RestClient`(Bearer+verify=False+401 강제refresh 후 1회 재시도, `youtube_api_adapter` 패턴 추출). token_provider/force_refresh 콜백 주입, 세션 주입(테스트).
- ✅ `infrastructure/sync/gdrive_provider.py`: `GoogleDriveProvider`. `InstalledAppFlow`(scope `drive.file`), 토큰 keyring(`gdrive.token`). Drive ID모델을 앱루트 폴더트리(경로→id 캐시)로 에뮬레이션, resumable 업로드 세션(청크 PUT, 308 `allow_redirects=False`).
- ✅ `infrastructure/sync/onedrive_provider.py`: `OneDriveProvider`. msal `PublicClientApplication`+`SerializableTokenCache`(keyring), scope `Files.ReadWrite`+`offline_access`. Graph 경로주소지정(`/me/drive/root:/<path>`), 소형 PUT/대형 createUploadSession. msal 지연 import.
- ✅ 둘 다 `ICloudSyncProvider` Protocol을 구조적으로 만족. `connect_*`(대화형 인증)·`disconnect` 제공.
- ✅ 테스트 14건(`tests/integration/test_sync_providers.py`): 401 재시도·경로/쿼리/URL 빌드·폴더트리 에뮬레이션·페이지네이션·텍스트/목록/stat/삭제 왕복(in-memory fake HTTP). **OneDrive `_item_url` 이중 콜론 버그를 테스트가 잡음.**
- ✅ `requirements.txt`에 `msal>=1.28`·`keyring>=25.0` 추가.
- ⚠️ **남은 것 = 실계정 검증(로컬 전용)**: OAuth client_id/secret 발급 + 브라우저 로그인 후 텍스트/작은 파일 upload/download/list/delete 왕복 + resumable 중단→재개. msal 미설치 환경이라 OneDrive 코드는 로컬 import 검증도 필요. provider **연결 UX**(설정 OAuth 버튼)는 Phase 5(E).

### C. ✅ 컴팩션 + 스냅샷 부트스트랩 (구현 완료 — 배선만 Phase 5)
- ✅ `application/sync/commands.py` `CompactHandler`: 현재 DB를 `snapshot_store.export_snapshot`으로 스냅샷 → provider `snapshot/library.db` 업로드 + `snapshot/snapshot.json`(covered=consumed ∪ {our:pushed_head}·schema_ids·db_sha256) 발행 → (선택) 덮인 세그먼트 GC. **GC 기본 비활성(`gc=False`)** — 완전 안전 GC엔 install별 consumed 워터마크 공유 필요(열린 결정)라 명시적으로 켤 때만.
- ✅ `infrastructure/sync/bootstrap.py` `bootstrap_if_fresh`(pre-DB): **로컬 DB 미존재 시에만** 스냅샷 다운로드→sha256 검증→`import_snapshot`(integrity+게이트+교체)→`consumed=covered`. 기존 DB는 증분 pull에 맡김(스냅샷 교체가 로컬 미병합 상태를 덮으므로 신규만 안전).
- ✅ 테스트 6건(`tests/integration/test_sync_compaction.py`): 신규 부트스트랩·부트스트랩 후 증분 pull·기존DB면 skip·스냅샷 없으면 skip·sha 불일치 차단·GC 후 신규기기 부트스트랩+증분 회수.
- **남은 것(Phase 5)**: main.py에서 `db=Database()` 직전 `bootstrap_if_fresh` 호출, 컴팩션 트리거 시점(주기/로그크기)·GC 활성화 정책 결정.

### D. Phase 2b — 나머지 엔티티 캡처/적용
현재 Video만. 확장 대상: **Category·Tag·video_tag 링크·song_info·playlist·playlist_item·playlist_folder·download_history·clip·category_video_order**.
- 각 엔티티에 대해 (1) 캡처: 해당 Sqlite*Repository를 상속한 RecordingXxxRepository(mutating 메서드 오버라이드), (2) 적용: `merge_applier`의 핸들러 registry에 `XxxApplyHandler` 추가.
- ✅ **결정됨 — 카테고리(및 재생목록) 정체성 = origin-identity(install+uuid)**: rename을 필드 변경으로 올바르게 다루기 위해. video의 category 참조도 이름경로가 아니라 카테고리 origin nkey를 쓰도록 `recording_repository`의 category 참조 계산과 `merge_applier.resolve_category`를 함께 바꿔야 함 → **Phase D-2**에서 반영.

#### ✅ D-1 완료 (video_tag 링크 + song_info)
- `recorder.py` `record_link`/`record_unlink`(presence-aware) 추가 — 링크는 refs로 양 끝점 전달(presence-only op은 merge writes가 비어 미반영되므로 refs 필수).
- `recording_repository.py`: RecordingVideoRepository.save에 video_tag 링크 diff 캡처, `RecordingSongRepository` 신규(song_info, nkey=영상 URL).
- `merge_applier.py`: `SongApplyHandler`·`VideoTagApplyHandler` + `resolve_video`/`resolve_tag`(태그 lazy 생성). handler registry에 등록.
- **태그는 별도 op 없이** video_tag LINK op의 tag 이름 ref로 apply 측이 lazy 생성(bare 태그 op의 dangling identity 방지).
- 테스트 6건(`tests/integration/test_sync_entities.py`): 링크/언링크/재링크 수렴, song 수렴·필드 LWW 동시편집·삭제.

#### ✅ D-2a 완료 (category origin-identity 전환)
- `recorder.origin_nkey(entity, local_uuid)` — origin-identity nkey를 로컬 UUID로 조회(없으면 origin_key 생성).
- `recording_repository`: RecordingVideoRepository에 save_category/delete_category 캡처 추가. video의 category 참조를 이름경로 → 카테고리 origin nkey로 변경(`_category_ref`).
- `merge_applier`: `resolve_category` 재작성(origin nkey→로컬 UUID, 없으면 stub 생성 — placeholder 이름=nkey, 실제 op이 UPDATE로 채움 → 배치 내 부모/자식 순서 무관). `CategoryApplyHandler`(name 필드+parent ref, rename=필드변경, UNIQUE(name,parent) 충돌 시 동명 카테고리로 병합). handler registry 등록.
- 기존 테스트 2건(name-path 기반) 재작성 + 카테고리 수렴/rename 테스트 4건(merge_applier 2 + entities 2). sync 68건 통과.

#### ✅ D-2b-1 완료 (clip + download_history)
- `RecordingClipRepository`(origin-identity, source_video ref, file_path/thumbnail_path는 DB 상대경로 캡처)·`RecordingDownloadRepository`(origin-identity, video FK 없음).
- `ClipApplyHandler`(resolve_video로 source_video_id 해석)·`DownloadApplyHandler`. handler registry 등록.
- 테스트 4건: clip 수렴/삭제, download 수렴/상태갱신. 비-GUI 206개 통과.

#### ✅ D-2b-2 완료 (playlist·folder·playlist_item·category_video_order)
- `RecordingPlaylistFolderRepository`(origin-id)·`RecordingPlaylistRepository`(origin-id, folder ref + set_items/add_video/remove_video/update_folder에서 playlist_item 멤버십 링크 캡처)·`RecordingVideoRepository.set_category_video_order`(category_video_order 링크).
- 핸들러: PlaylistFolder·Playlist·PlaylistItem·CategoryVideoOrder ApplyHandler + resolve_playlist/resolve_folder. **item_count는 apply 측이 재계산, position(순서)은 append** — 멤버십만 동기화(수동 정렬 순서는 기기 로컬, 문서화된 제한).
- **버그 수정**: 링크 자연키를 `_LINK_SEP`(\x1e)로 조합 — 부모 nkey가 origin_key(내부 \x1f)일 때 split_link_key가 오파싱하던 문제. **배치 내 부모/자식 순서 무관**을 위해 부모 핸들러가 `_register_identity`로 sync_identity 즉시 등록(_persist_state는 모든 핸들러 이후라 늦음).
- 테스트 4건(playlist 멤버십/제거/삭제·category order). ENTITY_ORDER에서 playlist_folder를 playlist보다 앞으로. 비-GUI 210개 통과.
- **D(엔티티 확장) 전체 완료** — video·category·tag·song·clip·download·playlist·folder·playlist_item·category_video_order 캡처/적용.

### E. Phase 5 — GUI 배선 (기능이 앱에 켜지는 단계)
- `gui/view_models/sync_vm.py` — `gui/view_models/song_vm.py` 패턴 복제(`SyncViewModel(QObject)`, 시그널, `_SyncWorker(QThread)`, `shutdown()`).
- `gui/panels/settings_panel.py` — `_build_ui`의 `layout.addStretch()`(약 1001줄) 직전에 "클라우드 동기화" 섹션(기존 9px 헤더+행 패턴 재사용, YouTube OAuth 섹션 811-868을 연결/해제 UI 템플릿으로). `__init__`에 `sync_vm=None`.
- `gui/main_window.py` — 생성자 트레일링 `sync_vm=None` + `self._sync_vm`, `SettingsPanel(...)`에 전달, **`closeEvent` shutdown 튜플(707-719)에 `self._sync_vm` 추가**.
- `main.py` — ① `db=Database()`(233줄) **직전 `bootstrap_sync_pull()`**, ② repo 생성부(237-243)에서 **각 repo를 RecordingXxxRepository로 래핑**해 핸들러에 주입, ③ 431줄 인근 `sync_vm` 조립, 445줄 `MainWindow(...)`에 전달, ④ 기동 후 백그라운드 미디어 diff.
- **CLAUDE.md 규칙**: GUI 변경 후 `/verify` 필수(로컬 PyQt6 필요).

### F. ✅ 패키징 (완료)
- ✅ `requirements.txt`: `msal>=1.28`, `keyring>=25.0` 추가(Phase B).
- ✅ `packaging/online_video_clipper.spec` `hiddenimports`: `keyring`·`keyring.backends`·`msal`·`googleapiclient`·`google_auth_oauthlib` 추가.
- ✅ `planning/packaging_plan.md` 갱신(requirements + hiddenimports).

---

## 로컬에서 이어가는 법

1. 이 브랜치를 로컬에서 체크아웃(원격 push 완료 상태). `git switch feat/cloud-sync-phase0-path-portability`.
2. 의존성: `pip install -r requirements.txt`(로컬은 PyQt6 포함). 테스트: `pytest`.
3. 새 작업 착수 시 위 A–F 중 하나를 골라 진행. **권장 순서**: A(미디어 파일) 또는 B(provider) → C(컴팩션/부트스트랩) → D(엔티티 확장) → E(GUI) → F(패키징). GUI(E)와 실계정 검증(B)은 로컬에서만 가능.
4. 커밋 규칙(CLAUDE.md): 한국어 커밋, git 작업은 Haiku, 문서(CLAUDE.md/planning) 동반 갱신.

## 열린 결정 사항 요약
- [x] 카테고리/재생목록 **정체성 방식** → **origin-identity 확정**(D-2에서 반영).
- [ ] 미디어 파일 **삭제 전파** 정책(현재 계획은 전파 안 함/수동).
- [ ] 컴팩션 **트리거 시점**(주기 vs 로그 크기 임계) 및 dormant install GC 보수성.
- [ ] provider **연결 UX**(설정에서 OAuth 버튼 흐름) 세부.
