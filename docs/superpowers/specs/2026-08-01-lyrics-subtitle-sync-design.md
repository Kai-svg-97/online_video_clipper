# 가사 자막 표시 · 싱크 조정 설계

작성일: 2026-08-01
대상 컨텍스트: `song`(가사 타이밍) · GUI(`gui/widgets/video_player.py`, `gui/panels/video_detail_panel.py`)

---

## 1. 목적 · 범위

노래 영상 재생 중 **가사를 영상 위 자막으로 표시**하고, LRC 타이밍과 영상 시작 시점의
어긋남을 **시작 오프셋 하나로 보정**한다. 번역이 있으면 원문 아래에 함께 표시한다.

### 하는 것

- LRCLIB의 `syncedLyrics`(LRC)를 파싱해 줄마다 시각(`start_ms`)을 확보·저장
- 시간 정보가 있는 가사에 한해 자막 표시 및 싱크 조정 활성화
- 영상 위 자막 오버레이(인라인 · 전체화면 · PiP 3곳 모두)
- 컨트롤바 `💬` 버튼 + 단축키로 오프셋 조정, 영상별로 DB 영속
- 노래 탭 가사 목록에서 현재 줄 하이라이트 · 자동 스크롤 · 줄 클릭 시 seek
- 싱크 가사 전용 조회 버튼(`⏱`) — 비싱크 가사만 있을 때 LRCLIB에서 싱크 버전만 재탐색

### 하지 않는 것 (YAGNI)

- 줄별 타이밍 수동 편집기 — 오프셋 보정으로 충분하다고 판단
- 배속·구간 늘림(scale) 보정 — 요청은 "시작 부분만 동기화"
- LRCLIB 외 제공자의 타이밍 확보 — 지니·벅스·Genius·멜론은 시간 정보 자체가 없다
- 단어 단위(karaoke) 싱크

---

## 2. 도메인 · 데이터 모델

### 2.1 값 객체 · 엔티티

```python
# domain/song/value_objects.py
@dataclass(frozen=True, slots=True)
class LyricsLine:
    original: str
    translation: str = ""
    start_ms: int | None = None   # None = 시간 정보 없음
```

```python
# domain/song/entities.py — SongInfo
lyrics_offset_ms: int = 0         # 영상별 싱크 보정(양수 = 자막을 늦춤)

@property
def is_synced(self) -> bool:
    """시간 정보가 있는 줄이 하나라도 있으면 True — 자막·싱크 활성 조건."""
    return any(ln.start_ms is not None for ln in self.lyrics_lines)
```

`lyrics_offset_ms`는 `MANUAL_FIELDS`에 넣지 **않는다** — 수동 편집 보존 대상(가사 내용)이
아니라 재생 환경 보정값이라 성격이 다르다.

### 2.2 애그리게이트

`SongInfoAggregate.set_lyrics_offset(ms: int) -> None`
- 값이 같으면 no-op, 다르면 `_touch(("lyrics_offset",))`
- 범위 clamp: `-30_000 ≤ ms ≤ 30_000` (30초를 넘는 어긋남은 잘못된 가사 매칭이다)

`edit_lyrics`(사용자 수동 편집) 시 타이밍 처리 — **줄 수가 같으면 기존 `start_ms`를 유지**,
다르면 전부 `None`으로 폐기한다. 오탈자 수정으로 싱크가 날아가지 않으면서, 줄 구성이
바뀌면 잘못된 타이밍을 유지하지 않는다.

`set_lyrics_translations`는 번역만 갈아끼우므로 호출부가 `start_ms`를 보존해 넘긴다
(애그리게이트는 받은 리스트를 그대로 저장 — 현재 동작 유지).

### 2.3 영속

`db/schema.sql`:

```sql
lyrics_json     TEXT NOT NULL DEFAULT '[]',   -- [{"o": 원문, "t": 한글번역, "s": 시작ms}, ...]
lyrics_offset_ms INTEGER NOT NULL DEFAULT 0,  -- 자막 싱크 보정(ms)
```

- `sqlite_song_repository._lyrics_to_json`: `start_ms`가 `None`이 아닐 때만 `"s"` 키를 넣는다
  (없는 줄에 `null`을 쓰지 않아 JSON 크기·프리필터 영향 최소화)
- `_lyrics_from_json`: `"s"` 없으면 `None`. **기존 데이터 하위호환**
- `database.py`: `add_lyrics_offset_ms` 마이그레이션 추가 후 `MIGRATION_IDS`에 등록
  (동기화 스키마 게이트가 이 상수를 능력 집합으로 쓰므로 반드시 함께 갱신)

### 2.4 동기화(sync) 영향

`RecordingSongRepository`가 song_info 변경을 필드 diff로 캡처하므로 `lyrics_offset_ms`는
자동으로 캡처 대상에 들어간다. **의도된 동작**: 같은 영상을 다른 기기에서 볼 때도 보정값이
따라간다(영상 파일이 같으므로 어긋남도 같다).

---

## 3. LRC 파싱 · 조회

### 3.1 신규 모듈 `infrastructure/song/lrc.py`

순수 함수 하나. 네트워크·Qt 의존 없음 → unit 테스트 대상.

```python
def parse_lrc(text: str) -> list[tuple[int | None, str]]:
    """LRC 텍스트를 (시작ms, 가사) 목록으로 파싱한다."""
```

처리 규칙:

| 입력 | 처리 |
|---|---|
| `[01:23.45] 가사` | `(83450, "가사")` |
| `[01:23] 가사` | `(83000, "가사")` — 밀리초 생략 허용 |
| `[00:10][01:10] 후렴` | 두 줄로 전개 (반복 구간 표기) |
| `[ar:...]` `[ti:...]` `[al:...]` `[by:...]` `[length:...]` | 메타 태그 — 버린다 |
| `[offset:-500]` | 전역 오프셋 — 모든 시각에 더한다(LRC 표준) |
| 타임스탬프 없는 줄 | `(None, 줄)` — 텍스트는 보존 |
| 빈 줄 | 보존(단락 구분) |

출력은 **시각 오름차순 정렬**한다(반복 구간 전개 후 순서가 뒤섞이므로). 타임스탬프 없는
줄은 직전 타임스탬프 줄 바로 뒤에 남긴다.

### 3.2 `LyricsResult` 확장

```python
# domain/song/ports.py
timings: list[int | None] = field(default_factory=list)  # lines와 같은 길이 또는 빈 리스트
```

빈 리스트 = 타이밍 없음. 기존 4개 제공자는 수정 불필요.

### 3.3 `LrclibProvider` 변경

현재는 `plainLyrics`를 우선 쓰고 없을 때만 `syncedLyrics`의 타임스탬프를 **제거**해서 쓴다.
이를 뒤집어 **`syncedLyrics`가 있으면 그것을 파싱해 lines + timings를 함께 채운다**
(텍스트 내용은 동일하고 타이밍만 추가 확보). `syncedLyrics`가 없으면 지금과 같이 `plainLyrics`.

`_strip_lrc_timestamps`는 더 이상 필요 없으므로 제거하고 `parse_lrc`로 대체한다.

### 3.4 싱크 전용 조회

`FetchSongInfoCommand`에 `synced_only: bool = False` 추가.

`FetchSongInfoHandler._run_chain`에서 `synced_only`가 켜져 있으면:
- 각 제공자 결과에 `timings`가 비어 있으면 **채택하지 않고 다음 출처로** 넘어간다
- 메타데이터(가수·앨범 등) 보강도 하지 않는다 — 목적이 타이밍 확보뿐이므로
- 전 출처 실패 시 `ok=False`로 보고하고 **기존 가사는 그대로 둔다**
- `force_lyrics=True`로 동작(수동 편집 가드 우회 — 사용자가 명시적으로 누른 버튼)

실질적으로 LRCLIB만 통과하지만, 미래에 타이밍을 주는 출처가 추가되면 자동 편입된다.

### 3.5 신규 커맨드

```python
# application/song/commands.py
@dataclass(frozen=True)
class SetLyricsOffsetCommand:
    video_id: UUID
    offset_ms: int

class SetLyricsOffsetHandler:  # aggregate.set_lyrics_offset → repo.save
```

### 3.6 DTO

```python
# application/song/dtos.py
class LyricsLineDTO:  start_ms: int | None = None
class SongInfoDTO:
    lyrics_offset_ms: int = 0
    @property
    def is_synced(self) -> bool: ...
```

---

## 4. GUI

### 4.1 신규 `gui/widgets/lyrics_overlay.py`

두 클래스로 분리한다 — 로직과 렌더를 갈라야 로직을 Qt 없이 테스트할 수 있다.

#### `LyricsTrack` (Qt 비의존 순수 로직)

```python
class LyricsTrack:
    def __init__(self, lines: list[LyricsCue], offset_ms: int = 0)
    @property
    def is_empty(self) -> bool          # 싱크 줄이 하나도 없으면 True
    offset_ms: int                      # 읽기/쓰기
    def index_at(self, pos_ms: int) -> int | None
    def cue_at(self, pos_ms: int) -> LyricsCue | None
    def start_of(self, index: int) -> int   # 줄 클릭 seek용(오프셋 적용된 절대 위치)
```

- 생성 시 `start_ms`가 있는 줄만 골라 오름차순 정렬해 보관
- `index_at`은 **이분 탐색**(`bisect`) — 매 position 틱마다 선형 스캔하지 않는다
- 현재 줄은 다음 줄 시작 직전까지 유효, 마지막 줄은 끝까지
- 첫 줄 시작 전이면 `None`(자막 없음)
- 판정 위치 = `pos_ms - offset_ms` (양수 오프셋 = 자막이 늦게 뜸)

#### `LyricsOverlay(QWidget)`

- `setAttribute(WA_TransparentForMouseEvents)` — 클릭이 영상/컨트롤바로 통과
- 배경 없음. `paintEvent`에서 `QPainterPath.addText` → 검정 `QPen`(둥근 join/cap) stroke →
  흰색 fill. 승인된 스타일
- 원문: 굵게, 크기 `max(13, height * 0.055)` — **위젯 높이 비례**라 전체화면에서 자동 확대
- 번역: 원문의 0.85배, `#e0e0e0`
- 여러 줄 wrap 지원(`QFontMetrics.boundingRect`로 폭 계산 후 수동 줄바꿈)
- 폰트 선택 `_pick_font()`: `QFontDatabase.families()`에 존재하는 첫 후보
  `Pretendard` → `Pretendard Variable` → `맑은 고딕(Malgun Gothic)` → `Noto Sans KR` →
  시스템 기본. 모듈 로드 시 1회 계산해 캐시
- `set_text(original, translation)` — 값이 같으면 `update()`를 호출하지 않는다

### 4.2 `_VideoArea` 배치

`set_overlay_bar`와 대칭으로 `set_overlay_subtitle(widget)` 추가.
`_layout_children`에서 컨트롤바 **바로 위** 영역에 배치한다:

```
y = h - _BAR_H - subtitle_height,  높이 = h * 0.28 (자막 2줄 + 여유)
```

컨트롤바가 숨어 있을 때도 같은 위치를 쓴다(자막이 오르내리며 흔들리지 않게).

### 4.3 `InlinePlayer` 배선

기존 컨트롤바 팬아웃 패턴을 그대로 따른다.

공개 API:

```python
def set_lyrics(self, track: LyricsTrack | None) -> None
def set_subtitle_enabled(self, on: bool) -> None
def lyrics_offset_ms(self) -> int
subtitle_offset_changed = pyqtSignal(int)   # 사용자가 오프셋을 바꿈 → 저장 요청
```

- `_on_position`에서 `track.index_at()` 호출 → **인덱스가 바뀔 때만** 오버레이 갱신
- 오버레이는 인라인 · `_FullscreenWindow` · `_PipWindow` 각각 자체 인스턴스를 갖고,
  `_on_position`이 존재하는 창에 팬아웃(볼륨·위치 팬아웃과 동일 패턴)
- `_enter_fullscreen`/`_enter_pip`에서 현재 자막 상태(on/off, 현재 줄)를 1회 반영
- `stop()`/`load()` 시 자막 초기화

### 4.4 컨트롤바 `💬` 버튼

`_ControlBar`에 `_btn_cc` 추가(⚙ 왼쪽). 신호:

```python
subtitle_toggled = pyqtSignal(bool)
subtitle_offset_nudged = pyqtSignal(int)   # ±250ms
subtitle_sync_here = pyqtSignal()          # 현재 재생 위치를 현재 줄 시작으로
subtitle_offset_reset = pyqtSignal()
```

- 좌클릭: 자막 on/off 토글
- 우클릭(또는 길게 누름 대신 **드롭다운 화살표 없이 우클릭**): 메뉴
  - `싱크  −0.25초  /  +0.25초` (현재 오프셋을 제목에 표기: `싱크 +0.50초`)
  - `현재 위치를 이 줄에 맞춤` — 재생 중이고 현재 줄이 있을 때만 활성
  - `초기화`
- **싱크 가사가 없으면 버튼 비활성**, 툴팁 `"시간 정보가 있는 가사가 없습니다"`
- `set_has_subtitle(bool)`로 활성/비활성 제어

버튼 아이콘·색은 하드코딩하지 않고 기존 `_bar_style()` / 테마 토큰 규약을 따른다.

### 4.5 단축키

`InlinePlayer.keyPressEvent`(전체화면·PiP는 `key_handler`로 위임 — 기존 구조 그대로):

| 키 | 동작 |
|---|---|
| `[` | 오프셋 −0.25초 |
| `]` | 오프셋 +0.25초 |
| `\` | 현재 재생 위치를 현재 줄 시작으로 맞춤 |
| `C` | 자막 on/off |

싱크 가사가 없으면 무시한다. 기존 단축키(`Space`/`K`/`J`/`L`/방향키/`M`/`P`/`F`/`Esc`/`0~9`)와
충돌하지 않음을 확인했다.

### 4.6 노래 탭 (`_SongTab`)

**선행 정리**: 현재 `_render_lyrics`는 비-side 모드에서 원문/번역 라벨을 레이아웃에
개별 추가한다(줄 단위 컨테이너 없음). 하이라이트·클릭·스크롤 대상이 필요하므로
**두 모드 모두 줄마다 `_LyricRow(QWidget)` 컨테이너로 통일**한다. side 모드의 교대 음영은
행 컨테이너 스타일로 그대로 유지된다.

추가 API·신호:

```python
def set_current_line(self, index: int | None) -> None   # 하이라이트 + ensureWidgetVisible
lyrics_seek_requested = pyqtSignal(int)                 # 줄 클릭 → 그 줄 시작 ms
synced_requested = pyqtSignal()                         # ⏱ 버튼
```

- 하이라이트: 행 배경을 accent 14% 틴트 + 원문 굵게(트리 선택 표현과 동일한 어법).
  색은 전부 테마 토큰에서 파생 — 하드코딩 금지
- 자동 스크롤: `ensureWidgetVisible(row, yMargin=행높이*2)`.
  **사용자가 직접 스크롤 중이면 3초간 자동 스크롤을 멈춘다**(스크롤바 `sliderPressed`/
  `valueChanged` 감지) — 가사를 훑어보는데 화면이 끌려가는 것을 막는다
- 줄 클릭: `start_ms`가 있는 행만 커서를 `PointingHandCursor`로 바꾸고 클릭 가능
- `⏱` 버튼: 가사 헤더의 🔍(검색) · 번역 버튼 옆. 툴팁 `"싱크(시간 정보) 가사 찾기"`.
  이미 싱크 가사가 있으면 숨긴다

### 4.7 `VideoDetailPanel` · `LibraryPanel` 연결

- `set_song_info(dto)`에서 `dto.is_synced`면 `LyricsTrack`을 조립해
  `InlinePlayer.set_lyrics(track)`, 아니면 `set_lyrics(None)`
- `InlinePlayer.subtitle_offset_changed` → `VideoDetailPanel.song_offset_saved(video_id, ms)`
  → `LibraryPanel` → `SongViewModel.set_lyrics_offset(...)`.
  **500ms 디바운스**(`QTimer`) — 단축키 연타마다 DB에 쓰지 않는다
- `InlinePlayer` 현재 줄 인덱스 변경 → `_SongTab.set_current_line(index)`
- `_SongTab.lyrics_seek_requested` → `InlinePlayer.seek_to_ms`
- `_SongTab.synced_requested` → `SongViewModel.fetch_synced_lyrics(video_id)`
- 스트리밍 상세(`load_stream`)는 안정적 video_id가 없어 노래 탭이 이미 비활성 →
  자막도 비활성(`set_lyrics(None)`)

### 4.8 `SongViewModel`

```python
def fetch_synced_lyrics(self, video_id: UUID) -> None   # _SongFetchWorker, synced_only=True
def set_lyrics_offset(self, video_id: UUID, offset_ms: int) -> None
```

- `fetch_synced_lyrics`는 기존 `_in_flight` 중복 가드를 공유한다
- 실패 시 `error_occurred`로 `"싱크(시간 정보) 가사를 찾지 못했습니다"` 전달
- 오프셋 저장은 짧은 DB 쓰기라 워커 없이 직접 호출(디바운스는 GUI 쪽에서)

---

## 5. 오류 처리

| 상황 | 동작 |
|---|---|
| LRC 파싱 실패/부분 실패 | 파싱 가능한 줄만 타이밍 부여, 나머지는 `start_ms=None`. 예외 전파 없음 |
| `syncedLyrics` 필드가 깨진 JSON/빈 문자열 | `plainLyrics` 경로로 폴백(기존 동작) |
| 싱크 전용 조회 실패 | 기존 가사 유지 + 상태 메시지. 라이브러리 상태 변화 없음 |
| 오프셋 저장 실패 | `error_occurred` (기존 뷰모델 패턴). 화면상 오프셋은 유지 |
| 폰트 후보가 하나도 없음 | `QFont()` 기본값 사용 — 렌더는 계속된다 |
| `lyrics_json`에 `"s"`가 문자열 등 비정수 | `None`으로 취급(방어적 파싱) |

로깅은 CLAUDE.md 규약대로 — 조용한 폴백 지점마다 `logger.debug` 이상을 남긴다.

---

## 6. 테스트

### unit (`tests/unit/`)

- `test_lrc_parse.py` — 밀리초 유무, 다중 타임스탬프 전개, 메타 태그 제거,
  `[offset:]` 반영, 타임스탬프 없는 줄 보존, 빈 입력, 깨진 대괄호
- `test_lyrics_track.py` — `index_at` 경계값(첫 줄 직전/정확히 시작/마지막 줄 이후),
  오프셋 ±적용, 역방향 seek, 싱크 줄이 0개일 때 `is_empty`

### integration (`tests/integration/`)

- `test_song_synced_lyrics.py`
  - `start_ms` 저장 → 로드 왕복
  - `"s"` 키가 없는 **기존 JSON 하위호환**
  - `lyrics_offset_ms` 영속 + clamp
  - `edit_lyrics` 시 줄 수 동일 → 타이밍 유지 / 줄 수 변경 → 타이밍 폐기
  - `set_lyrics_translations` 후 `start_ms` 보존
- `test_search_fields.py` **회귀 확인** — `"s"` 키 추가 후에도 가사 검색·프리필터 정상

### gui (`tests/gui/`)

- `test_lyrics_overlay.py`
  - 싱크 가사 없음 → `💬` 비활성
  - 싱크 가사 있음 → 활성, position 변경 시 오버레이 텍스트가 해당 줄로 바뀜
  - 번역 있으면 2줄, 없으면 1줄
  - 오프셋 변경이 표시 줄에 반영됨
  - 전체화면 진입 시 오버레이가 따라감

GUI 변경이므로 CLAUDE.md 규약대로 완료 전 `/verify`로 앱을 실제 실행해 확인한다.

---

## 7. 문서 갱신 (CLAUDE.md 규약)

- `CLAUDE.md`
  - `gui/` 파일 맵에 `gui/widgets/lyrics_overlay.py` 추가
  - `video_player.py` · `video_detail_panel.py` 항목에 자막·싱크 설명 추가
  - `domain/song/`, `infrastructure/song/lrc.py` 항목 추가
  - Key Design Decisions에 "가사 자막·싱크" 항목 추가
- `planning/youtube_content_manager_prd.md` — 자막 기능 요구사항 추가
- `planning/ddd_design.md` — `LyricsLine.start_ms`, `SongInfo.lyrics_offset_ms` 반영
