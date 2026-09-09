<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-09 | Updated: 2026-09-09 -->

# bootstrap

## Purpose
조립 루트(composition root). 리포지토리·인프라 서비스·유스케이스 핸들러·뷰모델을
만들어 하나의 객체 그래프로 엮고, 프로세스 시작·종료 절차를 담당한다.

예전에는 이 전부가 `main()` 한 함수(609줄, 핸들러 생성 91번)에 있었고 기능을 추가할
때마다 그 함수를 고쳐야 했다(6개월간 39회 변경). 지금 `main.py`는 **순서만** 담고
(127줄), 조립은 컨텍스트별 파일로 갈라져 서로 부딪히지 않는다.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | `build_app_graph(db) -> AppGraph` — 그래프 전체 조립. `db`를 **인자로 받아** 테스트가 임시 DB로 만들어 볼 수 있다 |
| `context.py` | 조립 결과 컨텍스트(frozen dataclass) — `Repositories`·`Services`·컨텍스트별 `*Handlers`·`Handlers`·`AppGraph` |
| `runtime.py` | 시작·종료 **절차** — Qt 앱·스플래시·av 로그 억제·Qt 메시지 필터·대기 중 업데이트 설치 |
| `persistence.py` | 클라우드 스냅샷 부트스트랩(DB 열기 전)·DB 열기·리포지토리(동기화 연결 시 캡처 데코레이터로 교체) |
| `services.py` | 인프라 어댑터 + YouTube OAuth + API lazy provider |
| `view_models.py` | 뷰모델 배선 → `ViewModels` |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `handlers/` | 컨텍스트별 유스케이스 조립 — `song`·`library`·`download`·`clip`·`monitoring`·`playlist`·`album`·`transfer`·`updater` |

## For AI Agents

### Working In This Directory
- **새 핸들러·어댑터는 해당 컨텍스트 파일 하나만 고친다** (`handlers/<context>.py`).
  `main.py`는 대개 손대지 않는다.
- **조립 순서 의존은 함수 인자로 드러낸다.** `handlers/__init__.py`가 순서를 명시한다:
  `song → library → {download, playlist, album}`. 순서를 바꾸면 `NameError`가 아니라
  인자 누락으로 즉시 드러난다.
- **`main.py` 상단에서 이 패키지를 임포트하지 말 것.** 여기 모듈들은 인프라·GUI를
  모듈 수준에서 임포트하므로 무겁다 — `main()`이 **스플래시를 띄운 뒤에** 임포트해야
  시작 체감 성능이 유지된다(예전에도 같은 임포트를 함수 안에서 했다).
- **`ViewModels`는 여기 정의하지 않는다.** 뷰모델 묶음은 프레젠테이션 계층 개념이라
  `gui/view_models/bundle.py`가 소유하고 `context.py`가 재수출만 한다 — GUI가
  `bootstrap`을 의존하면 레이어 방향이 뒤집힌다.
- **YouTube 비밀 저장소는 전용 키를 쓴다.** `infrastructure.sync.build_secret_store()`는
  동기화 provider용이라 keyring 서비스명·파일 경로가 다르다 — 그걸 쓰면 기존 사용자의
  저장된 토큰을 못 찾아 로그아웃된 것처럼 보인다(`services.build_youtube_oauth` 주석).
- 컨텍스트는 `frozen=True, slots=True`다 — 없는 필드에 값을 넣으면 즉시 터진다(오타 방지).

### Testing Requirements
```bash
pytest tests/integration/test_composition_root.py   # 그래프 조립·배선 계약
```

여기서 지키는 계약: 그래프가 예외 없이 조립된다 / 모든 뷰모델·핸들러 필드가
채워진다(`None`으로 조용히 빠지지 않는다) / 조립은 **네트워크를 쓰지 않는다** /
YouTube 인증은 조립 시점에 해석되지 않고 첫 호출에서 한 번만 해석돼 캐시된다 /
`MainWindow`가 그 그래프로 만들어지고 `closeEvent`가 뷰모델을 빠짐없이 정리한다.
