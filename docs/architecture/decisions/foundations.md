# 기반 — 레이어·스레드 원칙, 시작 성능, 데이터 안전, CI

> 레이어 규칙과 그 예외 경계, 메인 스레드 원칙, 시작 시간, DB 백업, 단일 인스턴스, CI가 드러낸 환경 의존 결함.
> 색인: [`../design-decisions.md`](../design-decisions.md).

## 항목별 기록

- **번들 YouTube OAuth 로그인** — 사용자가 Client ID/Secret을 입력하던 방식을 배포자 소유 Desktop OAuth 클라이언트 1개를 빌드에 번들하는 방식으로 교체했다(소수 지인 배포 특성상 반복 입력이 번거롭고 실수하기 쉬움). **클라이언트 설정과 사용자 토큰은 서로 다른 자산**이다 — `infrastructure/youtube/oauth_client_config.py:find_youtube_oauth_config()`가 explicit path→`OVC_YOUTUBE_OAUTH_CONFIG` 환경변수→번들된 `config/OAuth2.json`(`get_resource_path`)→개발용 `data/OAuth2.json` 순으로 클라이언트 JSON 경로만 찾는다(값은 절대 반환·로그하지 않음, 형식이 틀린 후보는 조용히 건너뛰지 않고 `OAuthClientConfigError` 즉시 발생). **사용자 토큰은 keyring 우선**(`KeyringSecretStore("online-video-clipper.youtube-oauth", DATA_DIR/secrets/youtube_oauth.json)`, 키 `youtube.oauth.credentials.v1`) — 과거 SQLite `yt_oauth_tokens` 테이블(`yt_api_credentials`)에 있던 토큰은 최초 조회 시 1회 자동 마이그레이션되고, secret store 저장이 확인된 뒤에만 원본 SQLite 행을 삭제한다(확인 실패 시 인증 유실 방지를 위해 보존). `YouTubeOAuthAdapter(db, secret_store, client_config_path)`의 `run_auth_flow()`는 무인자로 Desktop/PKCE(`autogenerate_code_verifier=True`) + loopback(`host="127.0.0.1", port=0`) 플로우를 실행하고, 토큰 리프레시는 `verify=False` 세션 없이 정상 TLS 검증으로 수행한다(과거 코드는 `urllib3.disable_warnings`까지 썼던 위험한 패턴이었음). composition root(`main.py:_build_youtube_oauth(db)`)가 이 셋을 조립해 주입하며, 클라이언트 설정이 없어도 `has_client_config() == False`인 어댑터를 반환해 앱 시작을 막지 않는다(YouTube API 기능만 비활성). 설정 화면은 Client ID/Secret 입력란 없이 `Google 계정으로 연결` 단일 버튼만 노출한다(자세한 내용은 위 `settings_panel.py` 항목 참고). **인증은 재시작 후에만 전 핸들러에 적용**된다 — 이미 생성된 `_yt_api`/`YouTubeApiAdapter` 등을 실행 중 다시 묶는 라이브 리바인딩은 이번 범위에 포함하지 않는다. **YouTube 인증은 시작 시 lazy binding으로 미룬다(Phase 2 Step 1, 시작 시간 단축)** — `main.py`는 더 이상 시작 시점에 `yt_oauth.get_credentials()`를 호출하지 않고(keyring 접근 200~300ms 절감), 그 자리에 정의한 `_get_youtube_api()` 클로저(`nonlocal _yt_api`로 캐시)를 YouTube API가 필요한 모든 핸들러에 `yt_api_provider` 콜백으로 주입한다. 각 핸들러(`GetSubscriptionFeedHandler`·`GetChannelVideosHandler`·`GetSubscribedChannelInfosHandler`·`GetRecommendationsHandler`·`GetYouTubePlaylistsHandler`·`RenamePlaylistHandler`·`AddVideoToPlaylistHandler`·`RemoveVideoFromPlaylistHandler`·`ReorderPlaylistHandler`·`MoveVideoToPlaylistHandler`·`PushPlaylistToYouTubeHandler`·`ImportYouTubeSubscriptionsHandler`)는 각 파일의 `_resolve_yt_api(yt_api, yt_api_provider)` 헬퍼로 `handle()` 호출 시점에만 인증을 해석한다(`ImportYouTubePlaylistHandler`는 이미 `yt_oauth`+`yt_api_factory`로 같은 목적을 달성해 손대지 않았다). **해석 결과는 성공·실패 모두 캐시**되어 세션 중 반복 keyring 접근을 만들지 않으며, 이는 위에서 말한 "재시작 후에만 적용" 동작과 동일하다. `PushPlaylistToYouTubeHandler`는 `yt_adapter`가 필수였던 것을 옵션으로 바꾸고 미인증 시 `handle()`에서 `RuntimeError`를 던지도록 바꿔, `main.py`가 인증 유무로 핸들러 생성 자체를 조건분기(`if _yt_api else None`)하지 않아도 되게 했다(오류는 그대로 `PlaylistViewModel.push_to_youtube()`의 워커 `error_occurred`로 표출). PyInstaller 빌드는 `OVC_YOUTUBE_OAUTH_CONFIG`(미지정 시 `data/OAuth2.json`)가 가리키는 JSON을 `scripts/build_windows.ps1`/`scripts/build_linux.sh`가 값 노출 없이 검증한 뒤 `packaging/online_video_clipper.spec`이 `config/OAuth2.json` 한 개로 번들한다(환경변수 미설정·파일 없음이면 spec이 `SystemExit`).
- **GUI on main thread** — all network/download work runs in background `QThread`; results communicated via Qt signals.
- **yt-dlp progress hooks** → `DownloadProgress` value object → emitted as Qt signal to update progress bar.
- **Aggregates own state changes** — e.g., `VideoAggregate.mark_watched()` not `video.watched = True`.
- **Repositories are interfaces in `domain/`** — GUI and Application layers depend on abstractions; SQLite is an implementation detail.
- **Domain Events over direct calls** — when a download completes, `DownloadCompleted` event triggers library update and UI notification independently.
- **ffmpeg resolved via `get_ffmpeg_path()`** — checks `bin/` first (bundled), falls back to system PATH.
- **Ports over concrete infra in application** — application 레이어는 `EventBus`/`YtDlpAdapter`/`FfmpegAdapter`를 직접 import하지 않고 `domain/shared/ports.py`의 Protocol(`IEventBus`·`IMediaSource`·`IClipExtractor`)에 의존한다. 어댑터는 구조적 타이핑으로 이를 만족(상속 불필요)하며, 구체 인스턴스 주입은 composition root(`main.py`)가 담당한다. 작업별 진행률 훅이 필요한 다운로드처럼 인스턴스를 새로 만들어야 하는 경우는 **팩토리 콜백을 주입**한다(`make_downloader`, `yt_api_factory`).
- **단일 인스턴스 가드** — `gui/single_instance.py`의 `SingleInstanceGuard`(QLocalServer/QLocalSocket)가 앱 중복 실행을 막는다. `main.py`가 **DB를 열기 전에** `try_acquire()`를 호출해 두 프로세스가 같은 DB를 동시에 건드리지 않게 하고, 이미 실행 중이면 기존 창을 앞으로 부른 뒤 조용히 종료한다. 서버 이름은 사용자별(`ovc-single-instance-<username>`)이며 비정상 종료로 남은 소켓은 `removeServer()`로 회수한다. **업데이트 후 2개 실행의 근본 원인은 `packaging/installer.iss`의 `[Run]`에 `skipifsilent`가 없어 무인 설치에서도 Inno가 앱을 실행한 것**이었다(배치의 `start`와 중복). **재실행 주체는 배치 하나로 고정한다** — 배치는 구버전 앱이 만들고 인스톨러는 신버전이라, 양쪽을 모두 막으면 다음다음 업데이트에서 아무도 앱을 실행하지 않는다.
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

## 스플래시는 창이 뜬 뒤에 닫는다 — 시작 체감 (2026-10, 성능 배치 1)

`QSplashScreen.show()`가 약 1초 걸렸다(같은 플래그의 `QLabel`은 약 50ms) → 프레임 없는
`QLabel`로 교체(`bootstrap.runtime.show_splash`). `finish`를 `window.show()` 전에 부르면
창이 그려지기 전에 스플래시가 사라져 약 1초 빈 화면이 났다 → `finish_splash`를 show **뒤**에
불러 창의 첫 Paint를 확인한 뒤 닫는다(안전 상한 `SPLASH_TIMEOUT_MS` 10초). 다만 **순서만 바꾸면
그동안 가려져 있던 `DownloadPanel`의 생성자 `refresh`(이력 50건, 약 0.4~0.6초)가 화면에
드러난다** — 그래서 같은 변경에서 첫 갱신을 첫 `showEvent`로 미뤘다(숨은 동안 신호는
dirty 표시만). 같은 이유로 `MonitoringVM.load` 중복 예약(라이브러리·모니터링 패널 각자)도
모니터링 패널 한 곳으로 합쳤다. 계약: `tests/unit/test_main_startup_order.py`,
`tests/gui/test_splash.py`, `tests/gui/test_download_panel_lazy_refresh.py`.

## DB 백업은 파일을 복사하는 일이 아니다 (v1.28)

라이브러리 DB는 WAL 모드로 열린다. `.db` 파일 하나만 복사하면 `-wal` 사이드카에 아직
본체로 넘어가지 않은 내용이 빠져 **어제까지의 DB**가 되고, 운이 나쁘면 손상된다.
클라우드 동기화 스냅샷과 같은 방법을 쓴다 — `PRAGMA wal_checkpoint(TRUNCATE)` 뒤
`VACUUM INTO`, 미지원 SQLite면 `conn.backup` 폴백.

두 가지를 더 지킨다:

* **임시 이름으로 만든 뒤 바꿔 단다.** 만들다 죽은 반쪽짜리가 '오늘치'로 남으면
  내일까지 다시 시도하지 않는다.
* **우리 이름(`library-YYYYMMDD.db`)의 파일만 세고 지운다.** 백업 폴더는 클라우드
  동기화의 충돌 백업도 쓰는 곳이라, 전체를 세면 남의 것을 지운다.

---

## 화면은 인프라를 임포트하지 않는다 — 포트 + 조립 루트 주입

레이어 규칙은 `gui → application → domain ← infrastructure`인데, `gui/`가 `infrastructure/`를
**22곳**에서 직접 임포트하고 있었다(쿠키 인증 서비스·쿠키 파일 도우미, 워치 폴더 스캐너,
Gemini 추출기·지원 언어, 재생 중계, 영상 자막 모듈, 뷰모델 넷의 `TYPE_CHECKING` 힌트).
대부분 함수 안의 지연 임포트라 눈에 띄지 않았고, 설정 화면은 `YouTubeAuthService()`를
**버튼을 누를 때마다 새로 만들었다** — 조립 루트가 만든 인스턴스가 이미 `MainWindow`에
들어와 있었는데도 아무도 쓰지 않았다.

### 어떻게 옮겼나

- **포트는 `domain/shared/ports.py`에 둔다**(기존 관례): `IYouTubeAuth`·`IStreamRelay`·
  `IVideoSubtitleSource` + `ISummarySource.extract_with_reason`. 쿠키 파일 상태 키
  (`COOKIE_*`)는 화면도 비교하므로 도메인으로 올리고 인프라가 재수출한다.
- **인프라에는 얇은 창구만 새로 만든다**(`infrastructure/streaming/gateway.py`·
  `infrastructure/subtitle/gateway.py`). 기존 모듈을 고치지 않고 모듈 함수에 잇기만 한다 —
  무거운 모듈은 **쓸 때 임포트**하고 중계 서버는 **첫 재생 때** 뜬다(예전과 같은 시점).
- **쿠키 도우미는 `YouTubeAuthService`의 메서드로 잇는다.** 화면이 서비스 하나만 받으면
  된다. 메서드가 호출할 때 모듈 전역을 찾으므로 모듈 함수를 바꿔 끼우는 기존 테스트가 그대로
  먹는다.
- **깊은 위젯 사슬은 묶음 하나로 내린다**(`gui/media_services.py:MediaServices`).
  `MainWindow → LibraryPanel/DownloadPanel → VideoDetailWidget → InlinePlayer →
  워커`로 낱개 인자 넷을 흘리면 한 단계를 잊는 순간 그 기능만 **조용히** 빠진다 —
  `ViewModels` 묶음과 같은 이유다. 조립 시험(`test_composition_root.py`)이 창을 실제로
  만들어 묶음이 플레이어까지 내려갔는지 본다.
- **주입이 없으면 그 기능만 빠진다**(다른 패널의 `vm=None` 관례와 같다): ⟳ 요약 버튼을
  숨기고, CC 목록을 조회하지 않고, 고화질은 실시간 remux 대신 병합 방식으로 받는다.
  앱에서는 조립 루트가 전부 채운다. 위젯 테스트는 최소 구성으로 만들 수 있다.

### 동작이 달라진 것 한 가지

⟳ 요약 워커가 매번 `GeminiExtractor()`를 새로 만들던 것을 **조립 루트의 공유 인스턴스**를
쓰게 했다. 추출기는 인스턴스 상태가 없고(호출마다 Playwright를 따로 띄운다) 자동 보강·다운로드
캡처가 이미 같은 인스턴스를 공유하므로 결과는 같다.

### `TYPE_CHECKING` 임포트도 막는다

`tests/unit/test_gui_does_not_import_infrastructure.py`가 `gui/**/*.py`를 AST로 훑어
**모든** 인프라 임포트(최상단·함수 안·`TYPE_CHECKING`)를 센다. 타입 힌트만을 위한
임포트를 허용하면 화면이 구체 형에 묶여 있다는 사실이 가려지고, "타입만"이 어느새 런타임
임포트로 번진다. 타입이 필요하면 포트를 쓴다. 허용 목록은 비어 있다.

---

## CI 첫 실행이 드러낸 것 — 개발 PC가 가리던 결함 셋

테스트 워크플로를 처음 돌리자 로컬에서 다 통과하던 시험 8건이 CI(windows-latest)에서
실패했다. 셋 다 "개발 PC 환경이 결함을 가리고 있었다"는 같은 모양이었다.

### keyring이 데이터 폴더 격리를 깨고 있었다 (앱 결함)

비밀 저장소(`KeyringSecretStore`)의 keyring 서비스 이름이 고정이었다
(`OnlineVideoClipper.sync`, `online-video-clipper.youtube-oauth`). keyring은 OS 사용자 하나에
하나라서 **데이터 폴더가 달라도 같은 비밀값**을 본다. 그래서:

- 동기화 시험의 "두 기기"가 install_id를 공유해 수렴하지 않았다(시험 5건).
- `OVC_DATA_DIR`로 격리한 실행(설명서 갈무리)이 사용자의 **실제** 동기화 자격증명·YouTube
  토큰을 읽을 수 있었다 — 격리 계약 위반.
- keyring이 있는 개발 PC에서 동기화 시험을 돌리면 **실제 install_id를 덮어쓸** 수 있었다.

개발 파이썬(3.14)에는 keyring이 없어 파일 폴백(`DATA_DIR/…/secrets.json`)이 폴더별로 갈라
주었고, 그래서 한 번도 드러나지 않았다. 고친 방식은 `scoped_service`다 — 기본 데이터 폴더는
이름 그대로(바꾸면 기존 사용자가 로그아웃된다), 다른 폴더만 경로 해시를 붙인다. 시험은
keyring 설치 여부와 무관하게 **이름**을 본다 — 다시 환경 탓에 가려지지 않게.

### 한글 코드페이지가 인코딩 결함을 가렸다 (시험 결함)

격리 시험이 자식 프로세스에 환경 변수를 세 개만 넘겨서 CI의 UTF-8 설정이 전달되지 않았고,
자식이 출력하는 `tmp_path`에는 한글 시험 이름이 들어 있다. 한국어 PC(cp949)는 한글을
찍을 수 있지만 CI 러너(cp1252)는 `UnicodeEncodeError`로 죽는다. 자식 환경에 UTF-8을 넘긴다.

### 큰 모니터가 창 크기 가정을 가렸다 (시험 결함)

플레이어 높이 제한 시험이 창을 2400×800으로 만들고 800 기준 값을 기대했다. CI 러너 화면은
작아서 창 관리자가 창을 749로 줄였다(464 = 749 × 0.62). 지키려는 것은 "창 높이의 비율로
제한한다"이므로 **실제** 창 높이로 기대값을 계산한다.

## 통계 화면은 보일 때 집계하고, 행은 묶음으로, 테마는 다시 칠하기만 (2026-10, 성능 배치 5)

`StatsPanel`은 숨은 화면인데 생성자가 집계하고(`_refresh`), 채널마다 행 위젯(약 10개)을
상한 없이 만들었고, **테마가 바뀔 때마다 `theme_changed`에 연결된 `_refresh`가 집계와 행
생성을 통째로 다시 했다.** 합성 5k(채널 400) 실측: 집계+행 만들기 2,337ms, 테마 전환 동기
처리 7,173ms(`theme_changed` 슬롯 합 1,824ms), 5k `MainWindow()` 약 5.2~5.6초. 집계
핸들러 자체는 44ms라 비싼 것은 **행 위젯 생성**이다 — 그래서 워커로 옮기지 않고 동기를
유지하되 생성량을 줄였다.

- 생성자는 집계하지 않는다. 첫 `showEvent`에서 1회, 재표시에는 안 한다(새로고침 버튼은 한다).
- 채널 행은 `CHANNEL_ROWS_MAX`(50)개만 만들고 "더 보기"(`statsMoreChannels`)를 누를 때마다
  **다음 묶음만** 덧붙인다. 다 보이면 버튼을 숨긴다.
- 테마 슬롯 `_on_theme_changed`는 조회도 재생성도 하지 않고 `_themed`에 모아 둔 재칠하기
  함수만 돈다. 숨은 동안은 dirty만 표시하고 다음 `showEvent`에서 현재 테마로 칠한다.
- 표시 중에 위젯을 채우므로 `_populate` 끝에서 `layout.activate()`로 지오메트리를 확정한다
  (안 하면 "더 보기" 버튼 높이가 0으로 남는다).

계약: `tests/gui/test_stats_panel_lazy.py`.
