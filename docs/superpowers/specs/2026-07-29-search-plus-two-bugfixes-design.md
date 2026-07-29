# 검색 확장 + 로컬 루트 선택 표시 + 중복 실행 수정 설계

작성일: 2026-07-29

세 항목을 한 스펙으로 묶는다. 서로 독립적이지만 모두 작고, 같은 릴리즈로 나갈 예정이다.

---

## 1. 버그 — "로컬" 루트를 선택해도 트리 선택이 유지된다

### 현상

좌측 트리 최상단 "로컬" 헤더를 클릭하면 영상 목록은 로컬 전체로 바뀌지만, 직전에 선택했던
카테고리 노드의 선택 표시가 그대로 남아 어느 것이 활성인지 헷갈린다.

### 원인

`gui/panels/library_panel.py:3015`가 목록 갱신만 요청하고 선택 상태는 건드리지 않는다.

```python
local_hdr.clicked.connect(lambda: self.category_selected.emit(None))
```

"로컬"은 트리 항목이 아니라 `_PlaylistPanel`의 `QPushButton`(`local_hdr`)이므로, 트리의 선택
모델과 연결된 지점이 아예 없다.

### 수정

`_PlaylistPanel`에 `set_local_root_active(active: bool)`을 추가하고 세 지점에서 호출한다.

| 시점 | 동작 |
| --- | --- |
| "로컬" 헤더 클릭 | 두 트리 `clearSelection()` + 헤더 활성 + `category_selected.emit(None)` |
| 트리 노드 선택(어느 트리든) | 헤더 비활성 |
| 뒤로/앞으로 복원(`select_snapshot`) | 스냅샷이 로컬 루트면 활성, 아니면 비활성 |

트리 선택 해제는 `blockSignals(True)`로 감싼다 — `select_snapshot`(`:3159~3174`)이 이미 쓰는
패턴이며, 해제가 `currentItemChanged`를 통해 핸들러를 재실행하는 이중 실행을 막는다.

활성 표시는 `local_hdr.setCheckable(True)` + `setChecked()`로 하고, 기존 토큰 기반
`hdr_style`에 규칙 하나를 더한다.

```
QPushButton#playlist_section_header_local:checked {
    color: {tok.accent};
    background: {tok.bg_overlay};
    border-radius: 4px;
}
```

`local_hdr`은 현재 지역 변수이므로 `self._local_hdr`로 보관한다.

---

## 2. 버그 — 업데이트 후 앱이 2개 실행된다

### 원인 (확정)

앱을 띄우는 경로가 **두 개** 있고 둘 다 실행된다.

1. `packaging/installer.iss`의 `[Run]` 항목:
   ```
   Filename: "{app}\YouTubeContentManager.exe"; Flags: postinstall nowait
   ```
   `skipifsilent` 플래그가 없어 무인 설치(`/VERYSILENT`)에서도 Inno가 앱을 실행한다.
2. `main.py` 종료 tail이 만든 배치의 `start "" "<exe>"` (`:524`).

`installer.iss`의 주석은 "앱 재실행은 배치가 담당하므로 Inno의 자동 재시작은 끈다"고 적고
`RestartApplications=no`를 설정했지만, 그것은 재시작 관리자용이고 `[Run] postinstall`은
별개 경로여서 남아 있었다.

### 수정 (a) — 인스톨러 플래그

```
Filename: "{app}\YouTubeContentManager.exe"; Description: "Launch YouTube Content Manager"; Flags: postinstall nowait skipifsilent
```

**배치의 `start` 줄은 그대로 둔다.** 이유가 타이밍에 있다 — 배치는 **구버전 앱**이 만들고
인스톨러는 **신버전**이다. 양쪽을 모두 고치면 다음다음 업데이트에서 아무도 앱을 실행하지
않는다. 실행 주체를 배치 하나로 고정하는 것이 이 구조에서 올바른 선택이다.

| 업데이트 | 배치(구버전 출처) | 인스톨러(신버전) | 결과 |
| --- | --- | --- | --- |
| 1.9.0 → 다음 | `start` 있음 | `skipifsilent` 적용 | 1개 ✅ |
| 그 다음 | `start` 있음 | `skipifsilent` 적용 | 1개 ✅ |

### 수정 (b) — 단일 인스턴스 가드

인스톨러 경로와 무관하게 중복을 막는 안전망을 둔다. 사용자가 아이콘을 두 번 눌러 직접
띄우는 경우도 함께 해결된다.

`gui/single_instance.py`(신규)에 `SingleInstanceGuard`를 둔다.

- `try_acquire() -> bool`: `QLocalSocket`으로 기존 인스턴스에 연결을 시도한다. 연결되면
  한 바이트를 보내고 `False`(이미 실행 중)를 반환한다. 실패하면 `removeServer()` 후
  `QLocalServer.listen()`으로 소유권을 얻고 `True`를 반환한다.
- `set_activate_callback(fn)`: 새 연결이 오면 호출된다. `MainWindow`가 자신을
  `showNormal()`·`raise_()`·`activateWindow()`하도록 연결한다.
- 서버 이름은 `ovc-single-instance-{username}` — 다중 사용자 환경에서 서로 막지 않게 한다.
- `removeServer()`를 먼저 부르는 이유: 비정상 종료로 남은 소켓 파일이 있으면 `listen()`이
  실패해 정상 기동이 막힌다.

`main.py`는 `QApplication` 생성 직후 가드를 시도하고, 이미 실행 중이면 `return 0`으로
조용히 끝낸다. **`pre_db_bootstrap()`이나 DB 열기보다 먼저** 해야 두 프로세스가 같은 DB를
동시에 건드리지 않는다.

---

## 3. 신기능 — 검색 확장 및 일치 속성 표시

### 요구사항 (확정)

검색어를 넣으면 다음에서 찾고, 각 결과 카드 하단에 어느 속성이 일치했는지 표시한다.

| 표시 라벨 | 대상 데이터 |
| --- | --- |
| 제목 | `videos.title` |
| 태그 | `tags.name` (via `video_tags`) |
| 설명 | `video_descriptions.description` |
| 메모 | `videos.notes` |
| 요약 | `videos.gemini_summary` |
| 노래 | `song_info.artist` · `album` · `song_title` · `release_year` |
| 가사 | `song_info.lyrics_json`의 원문·번역 텍스트 |

- **매칭은 부분 일치**(포함). "가정부"로 "가정부라고"를 찾는다.
- 검색어는 **입력 문자열 전체를 하나의 부분 문자열로** 취급한다(공백 분리 AND 아님).
  나중에 확장하기 쉬운 형태로 둔다.
- 검색어가 없으면 배지를 표시하지 않는다.

### 현재 상태

`videos_fts`(FTS5)는 `title`·`notes` **두 열만** 덮는다. `description`은 목록 쿼리를 가볍게
유지하려고 별도 테이블 `video_descriptions`로 분리돼 있어 인덱스 대상이 아니다.

### 왜 FTS 확장이 아니라 부분 일치인가

- **한글 적합성**: FTS5 기본 토크나이저는 어미가 붙은 한글에서 단어 단위 매칭이 자주
  빗나간다. 부분 일치가 사용자 기대에 맞다.
- **일치 속성 판정이 정확**: 어느 열이 맞았는지 곧바로 알 수 있다. FTS5로 열을 알아내려면
  열별 개별 MATCH나 보조 함수가 필요하다.
- **규모**: 실측 영상 197건, 태그 연결 1,169건, 가사 총 45KB. 스캔 비용이 무의미하다.

### 반드시 지켜야 할 것 — 가사는 SQL `LIKE` 금지

`lyrics_json`은 `[{"o": 원문, "t": 번역}, ...]` 형태의 JSON 문자열이다. 여기에 `LIKE`를 쓰면
검색어가 **JSON 키에 걸려 오탐**한다. 실측 확인:

| 검색어 | `lyrics_json LIKE '%검색어%'` |
| --- | --- |
| `heart` | 1 (정상) |
| `o` | 1 — **모든 노래가 매칭** (키 `"o"`) |
| `t` | 1 — **모든 노래가 매칭** (키 `"t"`) |

따라서 가사는 `is_song=1` 행의 JSON을 파싱해 원문·번역 텍스트만 이어붙여 비교한다.
현재 34건이라 비용은 무시할 수 있다.

### 대소문자

SQLite `LIKE`는 ASCII 대소문자를 이미 무시한다(`'ABC' LIKE '%bc%'` → 1). 한글은 무관하므로
`LOWER()`를 씌우지 않는다 — 씌우면 인덱스 활용 여지만 더 없어진다.

### 구현

**리포지토리** — `SqliteVideoRepository._build_search_sql`(`:425~439`)의 FTS 분기를 부분 일치
서브쿼리로 교체한다. 이 메서드가 텍스트 검색의 유일한 진입점이라 변경이 한곳에 모인다.

```sql
(videos.id IN (
     SELECT id FROM videos WHERE title LIKE ? ESCAPE '\'
     UNION SELECT id FROM videos WHERE notes LIKE ? ESCAPE '\'
     UNION SELECT id FROM videos WHERE gemini_summary LIKE ? ESCAPE '\'
     UNION SELECT video_id FROM video_descriptions WHERE description LIKE ? ESCAPE '\'
     UNION SELECT vt.video_id FROM video_tags vt JOIN tags t ON t.id = vt.tag_id
            WHERE t.name LIKE ? ESCAPE '\'
     UNION SELECT video_id FROM song_info
            WHERE artist LIKE ? ESCAPE '\' OR album LIKE ? ESCAPE '\'
               OR song_title LIKE ? ESCAPE '\' OR release_year LIKE ? ESCAPE '\'
 )
 OR videos.id IN (<가사 일치 id 플레이스홀더>))
```

`%`·`_`·`\`는 `ESCAPE '\'`와 함께 이스케이프한다(파이썬 문자열에서 백슬래시를 정확히
전달하도록 주의).

가사 일치 id는 파이썬에서 JSON을 파싱해 미리 구한 뒤 별도 `IN` 절로 OR 결합한다 —
SQL 안에서 `lyrics_json`을 다시 훑지 않는다. 일치가 없으면 그 절을 아예 붙이지 않는다
(`IN ()`은 SQLite 문법 오류다).

**일치 필드 판정** — 새 메서드 `match_fields_for(video_ids, text) -> dict[UUID, tuple[str, ...]]`.
현재 페이지의 50건에만 실행해 비용을 억제한다. 반환 키는 표시 라벨이 아니라 안정적인 식별자
(`"title"`·`"tags"`·`"description"`·`"notes"`·`"summary"`·`"song"`·`"lyrics"`)로 두고,
한글 라벨 매핑은 GUI가 갖는다 — 도메인에 표시 문자열을 넣지 않는다.

**DTO** — `VideoDTO`에 `match_fields: tuple[str, ...] = ()`를 더한다. frozen dataclass이고
기본값이 있어 기존 생성 코드는 영향받지 않는다.

**GUI** — 카드 델리게이트 두 곳에 배지를 그린다.

- `_IconDelegate`(그리드, `:603`) — `setItemDelegate`는 `:3934`
- `_ListDelegate`(리스트, `:742`) — `setItemDelegate`는 `:3943`

`VideoListModel`에 `MatchFieldsRole`을 추가해 델리게이트가 읽는다. 색은 기존
`chip_colors()`를 재사용해 테마를 따르게 한다.

### 성능 한계 (문서화)

`LIKE '%...%'`는 인덱스를 타지 않는 전체 스캔이다. 현재 규모(197건)에서는 즉시 응답하지만,
라이브러리가 수만 건으로 커지면 체감이 생긴다. 그 시점에는 모든 대상 필드를 덮는 통합 FTS
테이블로 되돌리는 것이 맞다. 이 판단 근거를 남겨 나중에 성급히 되돌리지 않게 한다.

### 기존 FTS 처리

`videos_fts`와 동기화 트리거는 **남긴다**. 검색에서 쓰지 않게 되지만
`tests/integration/test_merge_applier.py:173~181`이 "동기화 병합 후에도 FTS 트리거가
발화한다"를 검증하는 데 사용하므로, 제거하면 그 회귀 방어가 사라진다. 스키마 변경은 동기화
스키마 게이트(`MIGRATION_IDS`)와도 얽혀 위험 대비 이득이 없다. CLAUDE.md에 "검색은
부분 일치로 대체됐고 `videos_fts`는 동기화 트리거 검증용으로 유지"를 기록한다.

---

## 검증

- **버그1**: 카테고리 선택 → "로컬" 클릭 시 트리 선택이 지워지고 헤더가 활성 표시되는지,
  뒤로가기로 복원했을 때도 일치하는지
- **버그2**: 단일 인스턴스 가드 단위 테스트(두 번째 획득 시도가 `False`)와,
  `installer.iss`에 `skipifsilent`가 있는지 확인하는 테스트
- **신기능**: 필드별 매칭 테스트(제목·태그·설명·메모·요약·노래·가사 각각),
  **가사 오탐 회귀 테스트**(검색어 `"o"`·`"t"`가 노래를 매칭하지 않아야 함),
  `%`·`_` 이스케이프 테스트, 검색어 없을 때 `match_fields`가 비는지
- GUI 변경이므로 `/verify`로 실앱 확인

## 문서 갱신 (CLAUDE.md 필수 규칙)

- `CLAUDE.md` — 검색 방식 전환과 이유, 가사 JSON 오탐 주의, 단일 인스턴스 가드,
  `gui/` 파일 맵에 `single_instance.py` 추가
- `db/AGENTS.md`·`infrastructure/persistence/AGENTS.md` — "검색은 FTS5 사용"이라는 현재 서술이
  사실과 달라지므로 수정
- `planning/youtube_content_manager_prd.md` — 검색 기능 요구사항 추가
