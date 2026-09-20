# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

이 파일은 **지켜야 할 규칙**과 **어디를 볼지에 대한 색인**만 담는다. 파일별 책임과
설계 근거는 아래 문서로 분리돼 있다 — 매 세션 컨텍스트에 실리는 파일이라, 코드보다
빨리 낡는 서술을 여기 두면 부담만 커지고 정확도는 떨어진다(분리 전 1,106줄 / 208KB).

## 문서 지도

| 무엇을 찾나 | 어디 |
| --- | --- |
| 파일별 책임, 레이어 구조, `gui/` 파일 맵 | [`docs/architecture/file-map.md`](docs/architecture/file-map.md) |
| 왜 이렇게 만들었나, 실제로 밟은 함정 | [`docs/architecture/design-decisions.md`](docs/architecture/design-decisions.md) |
| 메모리 프로파일링 실측값 | [`docs/architecture/memory-profiling.md`](docs/architecture/memory-profiling.md) |
| 사용자용 상세 설명서(F1이 여는 문서) | [`docs/manual.md`](docs/manual.md) |
| 기능 요구사항 | `planning/youtube_content_manager_prd.md` |
| DDD 설계(컨텍스트·아그리게이트) | `planning/ddd_design.md` |
| 빌드·패키징 계획·체크리스트 | `planning/packaging_plan.md` |
| 플랫폼별 빌드 실행 가이드 | `docs/packaging-windows.md` · `-linux.md` · `-macos.md` |
| 과거 기능의 설계·구현 계획 원문 | `docs/superpowers/specs/` · `docs/superpowers/plans/` |

> **세션 시작 시**: `gui/` 코드를 만지기 전에 `docs/architecture/file-map.md`를 1차
> 참조한다. 거기 없는 파일만 탐색 에이전트를 쓴다.

---
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

의존 방향은 한 줄로 요약된다 — **`gui → application → domain ← infrastructure`**.
`domain/`은 외부 의존이 없고, `application/`은 `domain/shared/ports.py`의 Protocol에만
의존하며(구체 인프라를 직접 import하지 않는다), 구체 구현 주입은 조립 루트
(`bootstrap/`)가 담당한다.

```text
main.py              진입점 — 조립 목록이 아니라 순서만 있다(127줄)
bootstrap/           조립 루트 — 리포지토리·서비스·핸들러·뷰모델을 만든다
domain/              순수 도메인 — library · download · clip · monitoring · song · sync
application/         유스케이스(command/query) + DTO
infrastructure/      SQLite · yt-dlp · ffmpeg · playwright · YouTube API · 클라우드 동기화
gui/                 PyQt6 (MVVM) — panels · widgets · view_models · themes
tests/               unit(순수) · integration(SQLite·외부) · gui(pytest-qt)
```

**파일별 책임은 [`docs/architecture/file-map.md`](docs/architecture/file-map.md)에 있다.**

### 조립 루트 (`bootstrap/`)

기능을 추가할 때 조립을 고칠 곳은 **컨텍스트별 파일 하나**다:

| 파일 | 책임 |
| --- | --- |
| `bootstrap/__init__.py` | `build_app_graph(db)` — 그래프 전체 조립 |
| `bootstrap/context.py` | 조립 결과 컨텍스트(frozen dataclass) |
| `bootstrap/runtime.py` | 시작·종료 절차(Qt 앱·스플래시·중복 실행 가드·업데이트 설치) |
| `bootstrap/persistence.py` | DB 열기 + 리포지토리(동기화 연결 시 캡처 데코레이터로 교체) |
| `bootstrap/services.py` | 인프라 어댑터 + YouTube API lazy provider |
| `bootstrap/handlers/*.py` | 컨텍스트별 유스케이스 조립 |
| `bootstrap/view_models.py` | 뷰모델 배선 |

규칙 3가지:

1. **`main.py` 상단에서 `bootstrap`을 임포트하지 않는다.** 스플래시를 띄운 **뒤에**
   임포트해야 시작 체감 성능이 유지된다(인프라·GUI를 끌어오는 무거운 임포트다).
2. **조립 순서 제약은 함수 경계로 표현한다.** 클라우드 스냅샷 부트스트랩은 DB 열기
   전, 중복 실행 가드는 DB 열기 전, 업데이트 설치는 앱 종료 후다.
3. **핸들러 사이 의존은 함수 인자로 드러낸다.** `song → library → {download,
   playlist, album}` 순서가 `bootstrap/handlers/__init__.py`에 명시돼 있다.

조립은 `tests/integration/test_composition_root.py`가 검증한다 — 그래프가 성립하는지,
모든 뷰모델·핸들러가 채워졌는지, 조립 중 네트워크를 쓰지 않는지, YouTube 인증이
지연 해석되는지.

---
## 에러 처리 & 로깅 규칙 (mandatory)

- 진입점(`main.py`)에서 `utils.logging_config.setup_logging()`을 1회 호출한다(회전 파일 `LOG_DIR/app.log` + 콘솔).
- 모듈마다 `logger = logging.getLogger(__name__)`를 정의한다.
- **예외를 조용히 삼키지 말 것.** `except Exception: pass`/조용한 폴백이 필요하면(네트워크·API·DB 실패를 폴백 처리할 때) 반드시 `logger.exception("맥락")`으로 흔적을 남긴다. idempotent하게 무시해도 되는 경우만 `logger.debug(...)`.
- 예외를 UI로 표출하는 뷰모델 패턴(`error_occurred.emit(str(exc))`)은 이미 가시적이므로 그대로 둔다.
- **자기보다 오래 사는 신호원에는 위젯을 캡처한 람다를 연결하지 않는다.** 수신자가
  QObject의 **바운드 메서드**면 그 객체가 파괴될 때 Qt가 연결을 끊어 주지만, 람다는
  그 보호를 받지 못해 죽은 위젯을 건드리고 `RuntimeError: wrapped C/C++ object ...
  has been deleted`로 터진다. `ThemeManager.instance()`처럼 **싱글턴**이 가장 위험하다
  (앱 수명 내내 살아 있다). 신호가 인자를 넘겨서 람다를 쓰고 싶다면, 그 인자를 받아
  버리는 바운드 메서드를 두고 그것을 연결한다. `tests/gui/test_theme_signal_lifetime.py`
  가 `gui/` 전역을 AST로 훑어 **새 위반을 막고**, `tests/gui/test_panel_teardown.py`가
  런타임(패널 파괴 후 테마 변경)을 지킨다.
- **실행 중인 애니메이션을 위젯의 자식으로 두지 않는다.** `QVariantAnimation(self)`처럼
  부모를 주고 `start()`하면, 그 위젯이 파괴될 때 C++ 소멸자가 **실행 중인 자식
  애니메이션까지 지우며 프로세스가 죽는다**(access violation). QThread와 같은 함정이라
  해결도 같다 — `gui/anim.py`의 `track_animation(anim)`으로 부모를 떼고 멈출 때까지
  레지스트리가 붙든다. 대가로 애니메이션이 대상 위젯보다 오래 살 수 있으므로 **콜백은
  `RuntimeError`를 가드한다**(잡을 수 있는 예외가 access violation보다 낫다).
  `destroyed`에서 `stop()`이나 `disconnect()`를 부르는 것은 **소용없다**(그 시점엔 이미
  늦다 — 실측).
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
- **델리게이트 `paint()` 안에서 예외를 내지 않는다.** 그 안에서 난 파이썬 예외는
  PyQt가 **프로세스 종료**로 처리한다(Windows에서 0xC0000409) — 로그도, 예외 메시지도
  남지 않고 앱이 그냥 사라진다. 특히 **DTO에 필드를 늘릴 때 화면이 읽는 속성을 함께
  늘렸는지** 확인한다: `DownloadProgressDTO`에 `is_indeterminate`가 빠져 있어
  다운로드 카드가 하나라도 보이면 앱이 죽던 적이 있다(도메인 값 객체에만 있었다).
  회귀 테스트는 **실제로 그려 보는 것**이어야 한다(`tests/gui/test_download_card_paint.py`) —
  값 검사만으로는 이 경로를 밟지 않는다.
- **`nativeEvent`에서 `super().nativeEvent(...)`를 부르지 않는다.** PyQt 6.11에서 그
  호출은 **액세스 위반으로 프로세스를 죽인다**(0xC000041D — 창이 만들어지는 바로 그
  순간, 화면에 아무것도 뜨지 않고 로그도 없다). `return False, 0`이 의미가 같다 —
  Qt 기본 구현도 "처리하지 않았다"만 반환한다. `tests/gui/test_frameless_guard.py`가
  `gui/` 전역을 AST로 훑어 되돌아가는 것을 막는다.
- **네이티브 메시지 핸들러는 예외를 밖으로 내지 않는다.** `nativeEvent`는 메시지 루프
  안이라 델리게이트 `paint()`와 같은 부류의 조용한 사망 경로다. 전부 감싸고, 한 번이라도
  터지면 훅을 꺼서 네이티브 동작으로 떨어진다(`gui/frameless/__init__.py:safe_dispatch`).
  위험한 산술은 순수 함수(`gui/frameless/geometry.py`)로 빼 검증 가능하게 둔다.
- **캡션(타이틀바) 영역의 비대화형 자식에는 `WA_TransparentForMouseEvents`를 켠다.**
  안 켜면 `childAt()` 히트테스트가 그 위젯을 돌려주어 `HTCLIENT`이 되고, **그 자리에서
  창을 끌 수 없다**(제목 글자 위에서 드래그가 안 되는 형태로 나타난다).
- **`setWindowFlags`는 창 생성 시 한 번만 호출한다.** HWND가 재생성되므로 나중에
  건드리면 `gui/frameless/`가 걸어 둔 창 스타일 패치가 조용히 날아가고 Aero Snap만 죽는다.
- **`showNormal()`은 최소화뿐 아니라 최대화까지 해제한다.** 트레이·중복 실행에서 창을
  되부를 때는 `gui/window_state.py:restore_from_tray()`를 쓴다(최소화 비트만 지운다).
- 백그라운드 워커를 만드는 뷰모델은 `shutdown()`을 제공하고 `MainWindow.closeEvent`에서 호출해 종료 시 워커를 정리한다. yt-dlp 다운로드처럼 협조적 취소 훅이 없으면 `terminate()` 후 `wait()`로 종료를 보장한다.
- **`track_thread` 없이 리스트 하나로만 QThread를 붙드는 것은 이 규칙을 지킨 게 아니다.** `MainWindow.closeEvent`의 `wait_all(3000)`은 `gui/workers.py`의 `_RUNNING` 레지스트리만 안다 — 자체 리스트(GC 방지용)에만 담아 둔 워커는 종료 시 기다려지지 않는다. `gui/panels/library/mixins/video_list.py:_start_thumb_preload`의 `_ThumbBgLoader`가 `_active_thumb_loaders`(취소용 리스트)에만 담겨 있어 이 구멍이 있었다(2026-08 메모리 최적화 점검에서 발견) — `track_thread(loader)`를 추가로 호출해 고쳤다. 자체 리스트로 다른 목적(취소·중복 방지)을 관리하더라도, **실행 중 QThread라면 반드시 `track_thread`도 함께 호출**한다. 회귀 테스트: `tests/gui/test_memory_cleanup.py::TestWorkerReferenceRelease`.

## 재생 스트림 규칙 (mandatory)

- **재생 위치를 `self._player.position()`으로 직접 읽지 않는다 — `position_ms`를 쓴다.**
  실시간 remux 스트림은 seek 할 때마다 ffmpeg를 그 지점에서 새로 띄우므로 재생기가
  **매번 0부터 다시 센다**. 영상 기준 위치는 `재생기 위치 + _stream_offset_ms`이고,
  아직 반영되지 않은 seek이 있으면 그 목표가 답이다. 직접 읽으면 자막 싱크·이어보기·
  SponsorBlock이 전부 엉뚱한 지점을 가리킨다.
- **`setPosition`을 직접 부르지 않는다 — `_seek_to`를 거친다.** remux 스트림은 재생기가
  seek을 못 한다(`isSeekable()`이 False다). `_seek_to`가 소스 종류를 판정해 일반 소스는
  재생기에게 맡기고, remux는 `?ss=` 로 새 연결을 연다. 새 seek 경로를 만들면서 이 함수를
  건너뛰면 그 경로만 조용히 죽는다.
- **길이는 `_effective_duration()`으로 묻는다.** 파이프로 흘리는 fragmented mp4에는 길이
  정보가 없어 `QMediaPlayer.duration()`이 0/-1이다. 진행 막대를 재생기 신호에 직접
  연결하면 막대가 멎는다 — 전체화면·PiP 바를 `durationChanged`에 직접 잇던 것이 이
  경우였고, 지금은 `_publish_duration`이 한 곳에서 팬아웃한다.
- **끊긴 스트림을 '끝까지 봤다'로 취급하지 않는다.** 상위가 조각을 거부하면 **중간에서도**
  `EndOfMedia`가 온다. 그대로 믿으면 재생목록이 멋대로 다음 곡으로 넘어간다 — 끝 근처가
  아니면 이어 받거나 방식을 바꾼다(`_fall_back_to_merge`).
- **중계(`infrastructure/streaming/`)에서 403을 만나면 두 갈래로 나눈다.** 아직 성공한 적
  없는 크기면 조각을 줄이고, **통하던 크기가 거부되면 쉬었다 같은 크기로 재시도**한다.
  둘을 섞으면 일시적 거부에서 조각이 계속 작아지고 요청이 잦아져 더 나빠진다(실측:
  seek 첫 바이트 1초대 → 22초).
- **`Content-Length`를 약속한 뒤 조용히 돌아가지 않는다.** 재생기가 남은 바이트를 영원히
  기다린다(실측: 요청이 타임아웃까지 멈춤). 못 채우면 연결을 끊어 즉시 알린다.

## 도움말 문서 규칙 (mandatory)

- **설명서 원본은 `docs/manual.md` 하나다.** 고쳤으면 `python scripts/build_manual.py`로
  `docs/manual/index.html`을 다시 만든다 — F1과 설정 → 도움말이 여는 것이 그 HTML이고,
  빌드가 그 파일을 번들한다(`packaging/online_video_clipper.spec`).
- **화면이 바뀌면 `python scripts/capture_screenshots.py`로 갈무리를 다시 만든다.** 손으로
  찍지 않는다 — 사용자의 실제 라이브러리가 찍힐 수 있고 조용히 낡는다.
- **사용자 자료를 읽는 새 저장소를 만들면 `OVC_DATA_DIR`를 보게 한다.** 이 환경 변수는
  "사용자의 실제 설정을 절대 읽으면 안 되는 실행"을 위한 단일 스위치다(갈무리 스크립트가
  쓴다). DB·`config.yaml`·즐겨찾기가 이미 따른다. **`config.settings.DATA_DIR` 밖에 파일을
  두는 코드가 특히 위험하다** — `application/library/favorites.py`가 OS 사용자 데이터
  경로를 쓰는 바람에 격리를 빠져나가, v1.32.0 갈무리에 사용자의 즐겨찾기가 찍혀 공개
  저장소와 설치본에 들어갔다. 계약은 `tests/unit/test_capture_isolation.py`가 강제한다.
- **갈무리 스크립트 위쪽에 앱 모듈을 임포트하지 않는다.** 경로 상수는 모듈을 불러올 때
  정해지므로, 환경 변수를 세우기 전에 한 줄이라도 앱을 불러오면 격리가 **조용히** 깨진다.
- **설명서에 새 마크다운 문법을 쓰기 전에 렌더러가 그것을 아는지 확인한다.** 모르는 문법은
  오류 없이 **글자 그대로** 나온다(`| 키 | 동작 |`이 표가 아니라 문장으로 보이는 식).
  `tests/unit/test_build_manual.py`가 실제 설명서를 렌더해 남은 마크다운이 없는지 지킨다.

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
  영구히 옛 색으로 남는다** — `player/controls.py`의 화질 배지·화질 버튼이 그랬고,
  `_on_theme_changed`가 둘의 스타일시트를 다시 씌우도록 고쳤다(해결됨).
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
- Load `description` and `notes` fields **only** when the detail panel is opened (`GetVideoDetailHandler`), not in list queries.
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

- **뷰모델은 `gui/view_models/base.py`의 `WorkerOwnerMixin`을 섞는다.** 워커를 만들고
  `self._start_worker(worker)` 한 줄로 시작하면 전역 레지스트리 등록·완료 시 해제·
  종료 시 대기가 자동으로 지켜진다. 뷰모델 자신의 자료구조(취소·중복 판정용 리스트나
  dict)는 그대로 둬도 된다 — 믹스인은 `_tracked_workers`라는 자기 이름만 쓴다.
  종료 규칙이 특별한 경우(다운로드는 협조적 취소가 없어 `terminate`)는 `shutdown()`을
  오버라이드하고 **끝에 `super().shutdown()`을 잇는다**.
  `MainWindow.closeEvent`는 `shutdown_all(self)`로 정리 대상을 **발견**한다 — 목록을
  손으로 나열하지 말 것(그 방식이 실제로 뷰모델 셋을 빠뜨려 종료 시 프로세스가
  죽는 경로를 만들었다). 계약은 `tests/gui/test_vm_worker_contract.py`가 강제한다.
- **위젯이 직접 워커를 띄울 때는 `gui/workers.py`의 `track_thread` + `retire_thread`를 쓴다** — QThread를 생성하면 즉시 `track_thread(worker, signal_name)`로 레지스트리에 등록(부모-자식 분리). 작업 완료 시 `retire_thread(worker_name, "signal_name")`으로 해제(신호를 **이름**으로 받음 — 객체 참조가 아님). 끝난 워커를 `deleteLater` 호출하지 말 것 — 아직 그 워커를 참조하는 코드가 나중에 접근하면 `RuntimeError: wrapped C/C++ object has been deleted`가 난다. 대신 마지막 참조가 떨어질 때 파이썬이 정리하도록 둔다. 위젯이 파괴될 때 실행 중 QThread가 있으면 Qt가 즉시 프로세스를 종료한다(exit 0xC0000409) — 이를 막는 유일한 방법이 `track_thread`/`retire_thread` 패턴이다. 결과 신호는 **QObject 바운드 메서드**로만 연결해야 Qt가 수신 위젯 파괴 시 자동으로 연결을 끊는다.


> 실측 프로파일링 값은 [`docs/architecture/memory-profiling.md`](docs/architecture/memory-profiling.md)에 있다.

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
| Build / packaging change | `planning/packaging_plan.md` |
| 화면·사용법 변경 | `docs/manual.md` 수정 후 `python scripts/build_manual.py` |
| 레이어 구조 변경 · 파일 추가/삭제/이름 변경 | `docs/architecture/file-map.md` **즉시** 수정 |
| 설계 근거, 실제로 밟은 함정, 버그 수정 배경 | `docs/architecture/design-decisions.md` |
| 조립(`bootstrap/`) 규약 변경 | This file (`CLAUDE.md`)의 "조립 루트" 항목 |

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

- 세션 시작 시 [`docs/architecture/file-map.md`](docs/architecture/file-map.md)를 1차 참조한다 — 파일 맵에 없는 경우에만 탐색 에이전트를 호출한다.
- `gui/` 내 어느 파일을 수정해야 하는지 모를 때는 파일 맵에서 책임 설명을 먼저 확인한다.
- **어디를 열어야 하나**: 화면 *배치*는 `*_panel.py`(조립부), *동작*은 그 옆 패키지의 `mixins/`, *부품의 모양*은 패키지의 위젯 모듈. 파일을 나눴을 뿐 런타임 클래스는 그대로다(mixin 합성).
- 테스트에서 `monkeypatch`할 때는 **쓰는 쪽 모듈**을 패치한다(재수출 이름을 바꿔도 소용없다 — 분할 과정에서 실제로 3건이 이 이유로 깨졌다).

---

## 언어 정책

- 모든 대화 응답, 문서(CLAUDE.md, planning/), 코드 주석은 **한국어**로 작성한다.
- 예외(영어 유지): 코드 식별자(함수명·클래스명·변수명), 라이브러리·프레임워크 명칭, SQL 키워드, 셸 명령어 등 기술적으로 영어가 필수인 요소.

---

## Platform Support Notes

- Target OS: Windows (primary), macOS/Linux (secondary)
- Requires Python 3.10+
- ffmpeg binary must be on PATH or bundled in `bin/`
