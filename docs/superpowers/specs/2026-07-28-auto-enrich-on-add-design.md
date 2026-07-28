# 등록 시 요약·가사 자동 채우기 설계

작성일: 2026-07-28

## 배경

영상을 카테고리에 등록하면 지금은 노래 메타데이터(가수·앨범·제목·발매년도)만 기록되고,
요약(`gemini_summary`)과 가사는 사용자가 상세화면에서 직접 버튼을 눌러야 채워진다.

- `AddVideoHandler._register_song`이 `FetchSongInfoCommand(fetch_lyrics=False)`를 실행해
  노래 감지와 기본 메타데이터만 기록한다(가사 네트워크 조회는 의도적으로 생략).
- `gemini_summary`는 다운로드 완료 후 `capture_gemini` 옵션이 켜진 경우나
  상세화면 `⟳` 버튼을 누를 때만 채워진다.

## 목표

단건 등록 직후, 영상 성격에 따라 한쪽을 자동으로 채운다.

- 음원용이 아닌 영상 → 상세화면 **"요약" 탭**(`gemini_summary`)을 자동으로 채운다.
- 음원용 영상 → 상세화면 **"노래" 탭의 가사**를 자동으로 채운다.

## 범위 결정 (확정 사항)

| 항목 | 결정 |
| --- | --- |
| 적용 범위 | **단건 등록만**. 재생목록·채널 일괄 임포트는 제외 |
| 켜고 끄기 | 설정 패널에 토글 추가, 기본 ON |
| 진행·실패 표시 | `MainWindow` 상태바에 진행/실패 메시지 |
| 가사 조회 실패 시 | **폴백 없이 종료** (요약으로 넘어가지 않음) |
| 노래 영상의 보강 범위 | **가사만** 추가. 기본 정보는 등록 시점에 이미 채워짐 |

일괄 임포트를 제외하는 이유: Gemini 요약 추출은 Playwright로 실제 브라우저를 띄우고
YouTube 로그인 쿠키가 필요해 영상 1건당 수십 초가 걸린다. 수백 건 임포트에 그대로 걸면
임포트가 사실상 끝나지 않는다.

## 동작 정의

### 트리거

`LibraryViewModel.add_video` 성공 직후. 단건 등록 진입점 4곳
(`library_panel.py:5192`, `5286`, `6111`, `6115`)이 모두 이 메서드를 지나므로 배선 지점은 한 곳이다.
설정 `AUTO_ENRICH_ON_ADD`가 ON일 때만 실행한다.

### 분기 판정

등록 시 `AddVideoHandler._register_song`이 이미 `song_info.is_song`을 DB에 기록해 두므로,
보강 워커는 `song_repo`에서 `is_song`만 읽으면 되고 **yt-dlp를 다시 조회하지 않는다.**

- **`is_song=True`** → `FetchSongInfoCommand(video_id, fetch_lyrics=True)` 실행.
  `_run_chain`이 활성 가사 출처를 priority 순으로 순회해 가사를 확보하고, 비한국어면 한글 번역을 붙인다.
  메타데이터는 `artist = artist or result.artist` 형태로 **빈 값만** 채우고
  `apply_fetched`가 수동 편집 필드를 보존하므로, 등록 시 채워둔 가수·앨범·제목·발매년도는 그대로 남는다.
  즉 실질적으로 가사만 추가된다. 요약은 건드리지 않는다.
- **`is_song=False` 또는 노래 정보 행이 없음** → `ISummarySource.extract(url)`로 Gemini 요약을 추출해
  `UpdateVideoCommand(gemini_summary=…)`로 저장한다.
- **가사 조회 실패** → 폴백 없이 종료하고 상태바에 실패를 알린다.

`music_meta`가 비어 `_register_song`이 조기 반환한 경우(yt-dlp 조회 실패 등)에는 노래 정보 행이
없으므로 비노래로 취급해 요약을 시도한다.

### 건너뛰는 경우 (`kind="skipped"`)

- 요약이 이미 있는 영상 → Gemini 추출을 시도하지 않는다.
- 가사가 이미 있는 영상 → `FetchSongInfoHandler`가 `force=False`이므로 자체적으로 건너뛴다.
- `summary_source`가 주입되지 않은 경우 → 예외 없이 skipped.

등록이 기존 영상 upsert였을 때 중복 작업을 막기 위한 조건이다.

### 동시성

보강은 **한 번에 1건만** 실행하고 초과분은 큐에 쌓아 순차 처리한다.
Gemini 추출이 Playwright 브라우저를 띄우므로, URL을 연달아 등록했을 때 브라우저가
동시에 여러 개 뜨는 것을 막아야 한다.

### 일괄 임포트 제외 방식

`ImportYouTubePlaylistToCategoryHandler`·`ImportYouTubePlaylistHandler` 등은
`AddVideoHandler`를 직접 호출하고 ViewModel을 지나지 않으므로 **자동으로 제외된다.**
해당 코드는 수정하지 않는다 — 회귀 범위를 좁게 유지한다.

## 아키텍처

```
LibraryPanel(URL 등록) → LibraryViewModel.add_video
  → _AddVideoWorker(QThread): AddVideoHandler.handle        # 기존 — 노래 메타만 기록
      finished_ok(video_id)
  → [AUTO_ENRICH_ON_ADD] _EnrichWorker(QThread): EnrichVideoHandler.handle
      ├ is_song=True  → FetchSongInfoHandler(fetch_lyrics=True)   # 출처 체인 + 번역
      └ is_song=False → ISummarySource.extract → UpdateVideoHandler(gemini_summary)
      enrich_started / enrich_finished
        → MainWindow 상태바
        → LibraryPanel: 해당 상세가 열려 있으면 _reload_detail_in_place
```

등록은 지금처럼 즉시 끝나고 영상이 그리드에 바로 뜬다. 보강은 뒤따라 진행된다.

분기 정책은 application 레이어(`EnrichVideoHandler`)에 두고, 스레딩과 상태 표시만 GUI가 담당한다.

### 검토했으나 채택하지 않은 대안

- **`VideoAdded` 도메인 이벤트 구독**: CLAUDE.md의 "Domain Events over direct calls" 원칙에는 맞지만
  `VideoAdded`는 일괄 임포트에서도 동일하게 발생해 "단건만" 요구를 이벤트만으로 구분할 수 없다.
  결국 커맨드에 플래그를 다시 실어야 해 더 복잡해진다.
- **`AddVideoHandler` 안에서 인라인 보강**: 코드는 가장 적지만 Gemini 추출(수십 초)이 끝날 때까지
  등록 완료 시그널이 오지 않아 영상이 그리드에 수십 초간 나타나지 않는다.

## 컴포넌트

### `domain/shared/ports.py` — `ISummarySource` 추가

```python
class ISummarySource(Protocol):
    """YouTube Gemini AI 요약 추출 추상화 (infrastructure.browser.gemini_extractor.GeminiExtractor)."""

    def extract(self, url: str) -> str: ...
```

`StartDownloadHandler.gemini_extractor`는 현재 타입 힌트 없는 덕타이핑이므로 같은 포트로 힌트를 붙여
일관성을 맞춘다. `GeminiExtractor`는 이미 `extract(url) -> str`이라 구조적으로 만족하며
인프라 수정은 없다.

### `application/library/commands.py` — `EnrichVideoHandler` 신규

```python
@dataclass
class EnrichVideoCommand:
    video_id: UUID


@dataclass
class EnrichVideoResult:
    kind: str          # "song" | "summary" | "skipped"
    ok: bool
    detail: str = ""   # 상태바에 띄울 사유
```

`EnrichVideoHandler(video_repo, song_repo, update_video, song_fetch, summary_source=None)`.
`song_repo`에서 `is_song`을 읽어 분기하고 결과를 `EnrichVideoResult`로 반환한다.

`AddVideoHandler`가 이미 `song_fetch`를 주입받아 library/song 두 컨텍스트를 조율하는 선례가 있으므로
같은 파일·같은 패턴에 둔다. `ISongRepository`는 domain 인터페이스라 계층 의존 규칙을 위반하지 않는다.

### `gui/view_models/library_vm.py`

- `_AddVideoWorker.finished_ok`를 `pyqtSignal(object)`로 변경해 `video_id`를 전달
- `_EnrichWorker(QThread)` 추가 — `EnrichVideoHandler.handle` 실행, 결과를 시그널로 방출
- 신규 시그널: `enrich_started(str url, str kind)`, `enrich_finished(str url, str kind, bool ok, str detail)`
- `_enrich_workers` + `_pending_enrich: deque`로 동시 1건 제한
- `shutdown()`에 정리 추가. Gemini는 협조적 취소 훅이 없으므로 CLAUDE.md 규칙대로 `terminate()` 후 `wait()`

`kind`는 워커 시작 시점에 이미 판정돼 있어야 상태바에 "가사 조회 중"/"요약 생성 중"을 구분해 띄울 수 있다.
`is_song` 조회는 DB 한 번 읽기라 저렴하므로 `add_video` 완료 콜백(메인 스레드)에서 읽어
`enrich_started(url, kind)`의 라벨용으로만 쓴다. **실제로 무엇을 실행할지는 `EnrichVideoHandler`가
단독으로 판정한다**(권위 있는 판정은 한 곳에만 둔다). `enrich_finished`의 `kind`는 핸들러가 반환한
값이므로, 상태바 라벨과 최종 결과가 어긋날 경우 최종 결과 쪽을 따른다.

### `gui/main_window.py`

- `enrich_started` → `statusBar().showMessage("가사 조회 중: …" / "요약 생성 중: …", 0)` + `_add_progress.show()`
- `enrich_finished` → `_add_progress.hide()`, 성공 5초 / 실패 8초 표시
- 기존 `_on_add_finished`의 "등록 완료" 메시지 바로 뒤에 이어지도록 순서를 맞춘다

### `gui/panels/library_panel.py`

`enrich_finished` 수신 시 해당 영상 상세가 열려 있으면(`current_detail_id()` 일치)
`_reload_detail_in_place`로 재로드한다. 요약은 수십 초가 걸려 그 사이 사용자가 영상을 클릭해
상세를 열 수 있다. `_on_video_metadata_refreshed`의 기존 패턴을 그대로 재사용한다.

### `config/settings.py`

`AUTO_ENRICH_ON_ADD: bool = _load_bool("auto_enrich_on_add", True)` 추가 및
`save_setting`의 mapping에 `"auto_enrich_on_add": "AUTO_ENRICH_ON_ADD"` 등록.

### `gui/panels/settings_panel.py`

체크박스 "등록 시 요약·가사 자동 채우기" 추가. 설명 문구에 **Gemini 요약은 YouTube 로그인 쿠키가
필요하고 Chrome v127+ 사용자는 쿠키 파일을 직접 등록해야 한다**는 안내를 포함한다.

### `main.py`

`EnrichVideoHandler`를 조립하고(기존 `_gemini_extractor` 인스턴스 재사용) `library_vm`에 주입한다.

## 에러 처리

- `EnrichVideoHandler`는 모든 예외를 잡아 `EnrichVideoResult(ok=False, detail=…)`로 변환한다.
  등록 결과에는 영향을 주지 않는다.
- 예외는 `logger.exception`으로 흔적을 남긴다(CLAUDE.md 로깅 규칙).
- Gemini가 빈 문자열을 반환하는 정상적 실패(미로그인·쿠키 없음)는 `logger.warning`으로 남기고
  상태바에 "요약을 가져오지 못했습니다(YouTube 쿠키 확인)"를 표시한다.

## 테스트

`tests/integration/test_enrich_video.py` — 가짜 provider·summary_source로 검증:

- `is_song=True` → `fetch_lyrics=True`로 호출되고 `summary_source`는 호출되지 않음
- `is_song=False` → `extract` 호출 후 `gemini_summary`가 저장됨
- 가사 제공자 전부 실패 → 요약을 시도하지 않음(폴백 없음), `ok=False`
- 요약이 이미 있음 / `summary_source` 미주입 → `kind="skipped"`, 예외 없음
- 등록 시 채워둔 가수·앨범이 보강 후에도 유지됨

`tests/gui/` 스모크 — 설정 OFF면 `_EnrichWorker`가 생성되지 않음.

GUI 변경이므로 마지막에 `/verify`로 실앱을 실행해 확인한다(CLAUDE.md 규칙).

## 문서 갱신 (CLAUDE.md 필수 규칙)

- `CLAUDE.md` — Key Design Decisions에 "등록 시 요약·가사 자동 보강" 항목 추가,
  `gui/` 파일 맵의 `library_vm.py`·`main_window.py`·`settings_panel.py` 설명 갱신
- `planning/youtube_content_manager_prd.md` — 기능 요구사항 추가
