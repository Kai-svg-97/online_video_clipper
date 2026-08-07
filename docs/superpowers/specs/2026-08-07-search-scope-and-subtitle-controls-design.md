# 가사 검색 범위 제한 · 자막 크기/위치 조절 설계

작성일: 2026-08-07
대상: 검색(`infrastructure/persistence/sqlite_video_repository.py`) ·
자막(`gui/widgets/lyrics_overlay.py`, `gui/widgets/video_player.py`, `config/settings.py`)

---

## 1. 목적 · 범위

독립적인 두 가지 개선을 하나의 계획으로 묶는다. 서로 코드가 겹치지 않으므로
구현 순서도 무관하다.

1. **가사 검색 범위 제한** — 최상위 카테고리가 음악인 영상에서만 가사를 검색한다.
2. **자막 크기 · 위치 조절** — 사용자가 자막 글자 크기와 세로 위치를 조절하고,
   그 값을 전역으로 기억한다. 현재 기본 자막이 지나치게 작은 계산식도 함께 바로잡는다.

### 하지 않는 것 (YAGNI)

- 무수정 휠(수정키 없는 휠) 동작 추가 — 기존 동작을 바꾸게 되므로 건드리지 않는다
- 자막 좌우 위치 · 색 · 배경 상자 · 폰트 종류 선택 — 요청 범위 밖
- 음악 카테고리 이름의 사용자 설정 UI — 상수로 충분하다
- 검색 범위 제한의 on/off 토글 — 요청은 "그렇게 동작하도록"이지 선택지가 아니다

---

## 2. 기능 1 — 가사 검색 범위 제한

### 2.1 판정 규칙

영상의 카테고리를 부모로 계속 거슬러 올라간 **최상위 조상 카테고리**의 이름이
`music` · `음악` · `노래` 중 하나(공백 제거 후 소문자 비교)일 때만 그 영상의 가사를
검색 대상에 넣는다.

- 중첩된 하위 카테고리(예: `Music > K-Pop > 2020s`)도 루트가 `Music`이므로 포함한다.
- **카테고리가 없는 영상(`category_id IS NULL`)은 제외한다** — 미분류·재생목록 전용 영상.
  카테고리가 삭제되면 스키마상 `ON DELETE SET NULL`로 `category_id`가 NULL이 되므로
  자동으로 제외 대상이 된다.

```python
# domain/library/repositories.py — MATCH_FIELD_KEYS 옆
# 가사 검색을 허용할 최상위 카테고리 이름. 검색 계약의 일부라 도메인에 둔다
# (테스트가 import 해서 규칙을 고정한다).
MUSIC_ROOT_CATEGORY_NAMES: frozenset[str] = frozenset({"music", "음악", "노래"})
```

### 2.2 적용 지점 — 반드시 두 곳 모두

가사를 읽는 코드는 두 군데이고, **한쪽만 고치면 결과와 배지가 어긋난다**
(가사로 검색됐는데 `가사` 배지는 안 뜨거나 그 반대).

| 위치 | 역할 | 변경 |
| --- | --- | --- |
| `_lyrics_match_ids(text)` | 어떤 영상이 가사로 걸리는지 | 음악 카테고리 게이트 추가 |
| `match_fields_for(ids, text)` | `가사` 배지를 띄울지 | 같은 게이트를 가사 조회에 추가 |

### 2.3 루트 카테고리 해석

재귀 CTE로 "루트가 음악인 카테고리 id 집합"을 구하는 헬퍼를 하나 만들고 두 곳에서 쓴다.

```python
def _music_category_ids(self, conn) -> list[str]:
    """최상위 조상 카테고리 이름이 음악인 카테고리 id 전체(중첩 포함)."""
```

```sql
WITH RECURSIVE tree(id, root_name, depth) AS (
    SELECT id, name, 0 FROM categories WHERE parent_id IS NULL
    UNION ALL
    SELECT c.id, t.root_name, t.depth + 1
      FROM categories c JOIN tree t ON c.parent_id = t.id
     WHERE t.depth < 32
)
SELECT id FROM tree WHERE lower(trim(root_name)) IN (?, ?, ?)
```

`depth < 32` 가드는 **선택이 아니라 필수**다. `categories`에 순환을 막는 제약은
`UNIQUE(name, parent_id)`뿐이라 데이터가 어쩌다 순환하면 재귀 CTE가 끝나지 않고
앱이 멈춘다. 32단계면 실제 카테고리 깊이를 한참 넘는다.

`IN (?, ?, ?)`의 바인딩은 `MUSIC_ROOT_CATEGORY_NAMES`를 정렬한 리스트로 만들어
플레이스홀더 개수를 상수에서 파생시킨다(이름을 추가해도 SQL이 안 깨지도록).

### 2.4 게이트 적용

```python
# _lyrics_match_ids — 기존 song_info 단독 조회에 videos 조인을 더한다
music_ids = self._music_category_ids(conn)
if not music_ids:
    return []                     # 음악 카테고리가 하나도 없으면 가사 검색 자체를 건너뛴다
ph = ",".join("?" * len(music_ids))
sql = (
    "SELECT s.video_id, s.lyrics_json FROM song_info s "
    "JOIN videos v ON v.id = s.video_id "
    f"WHERE s.lyrics_json <> '[]' AND v.category_id IN ({ph})"
)
```

`match_fields_for`의 가사 조회(`lyric_rows`)에도 같은 조인·조건을 건다.
기존 `_lyrics_prefilter_safe` 프리필터와 `_lyrics_text` 캐시는 그대로 유지한다.

### 2.5 부수 효과 — 검색 응답성 개선

지금은 검색어를 칠 때마다 가사 보유 곡 **전체**를 JSON 파싱한다. 이 게이트가 파싱
대상을 음악 카테고리로 좁히므로 CLAUDE.md "검색 입력 응답성" 항목의 부담이 함께 준다.
성능이 목적은 아니지만 퇴행이 아니라 개선 방향이라는 점을 기록해 둔다.

### 2.6 테스트 (`tests/integration/test_search_fields.py`)

1. `Music` 직속 노래가 가사로 검색된다
2. **중첩** 하위(`Music > K-Pop`) 노래도 검색된다
3. 같은 가사 문자열을 가진 **비음악 카테고리** 영상은 가사로 안 걸린다
4. **미분류**(`category_id IS NULL`) 노래는 안 걸린다
5. `음악` · `노래` 이름과 대소문자/공백 변형(` MUSIC `)도 인정된다
6. 검색 결과와 `가사` 배지가 일치한다(2.2의 불일치 방지)
7. 카테고리 부모가 순환해도 조회가 끝난다(깊이 가드)

---

## 3. 기능 2 — 자막 크기 · 위치 조절

### 3.1 구조 변경: 오버레이를 비디오 영역 전체로

현재 `_VideoArea._layout_children`은 자막 오버레이를 **컨트롤바 위 높이 28% 띠**로 배치하고
(`sub_h = max(60, int(h * 0.28))`), `LyricsOverlay`는 그 띠 안에서 글자를 하단 정렬한다.
이 구조는 두 가지를 막는다: 글자를 키우거나 위치를 올리면 띠 밖으로 잘리고,
글자 크기 기준이 "띠 높이"라 실제 플레이어 대비 비율이 왜곡된다.

→ **오버레이가 비디오 영역 전체(`0, 0, w, h`)를 덮게 한다.** 위치는 그리기 단계에서
아래 여백으로 계산하므로 잘림 문제가 사라지고, 글자 크기 기준이 플레이어 높이가 된다.

안전한 변경인 이유: 오버레이는 `WA_TransparentForMouseEvents`라 마우스를 통과시키고,
`_layout_children`이 자막을 `raise_()`한 **뒤에** 컨트롤바를 `raise_()`하므로 컨트롤바가
계속 자막 위에 온다.

### 3.2 두 설정값

| 값 | 의미 | 기본 | 범위 | 스텝 |
| --- | --- | --- | --- | --- |
| `subtitle_font_scale` | 글자 크기 배율 | 1.0 | 0.5 – 3.0 | 0.1 |
| `subtitle_bottom_ratio` | 아래에서 띄우는 높이(영역 높이 대비) | 0.10 | 0.0 – 0.6 | 0.02 |

둘 다 **비율**이다. px로 두면 같은 값이 PiP에서는 과하고 전체화면에서는 티가 안 난다.
범위 밖 값은 저장·적용 시 clamp한다(설정 파일을 손으로 고쳐 깨진 값이 들어와도 안전하게).

### 3.3 크기 계산식 정상화

```python
_BASE_FONT_RATIO = 0.045     # 영역 높이 대비 원문 글자 크기(일반 영상 자막 수준)

px = max(_MIN_FONT_PX, int(self.height() * _BASE_FONT_RATIO * self._font_scale))
```

기존 `_FONT_RATIO = 0.055`는 28% 높이 띠에 적용돼 실질 약 1.5%였다. 3.1로 기준이
영역 전체 높이가 되었으므로 비율을 0.045로 바꾸면 배율 1.0에서 이미 읽을 만하다.
번역 줄 비율(`_TRANSLATION_RATIO`)·외곽선 비율은 그대로 둔다.

### 3.4 위치 계산

```python
bottom = int(self.height() * self._bottom_ratio)
y = self.height() - bottom - total_h
y = max(0, y)                 # 글자가 커도 위로 잘려 나가지 않게
```

기본 `0.10`은 지금(컨트롤바에 딱 붙음)보다 살짝 띄운 값이다. 컨트롤바 높이만큼은
기본값이 자연히 비켜 준다.

### 3.5 조작

| 입력 | 동작 |
| --- | --- |
| `Ctrl` + 휠 위 / `Ctrl` + ↑ | 크기 **+0.1** (글자가 커짐) |
| `Ctrl` + 휠 아래 / `Ctrl` + ↓ | 크기 **−0.1** (글자가 작아짐) |
| `Ctrl+Shift` + 휠 위 / `Ctrl+Shift` + ↑ | 위치 **+0.02** (자막이 **위로** 올라감) |
| `Ctrl+Shift` + 휠 아래 / `Ctrl+Shift` + ↓ | 위치 **−0.02** (자막이 **아래로** 내려감) |

방향 규칙은 "위로 굴리면/위 키를 누르면 값이 커진다"로 통일한다. `subtitle_bottom_ratio`는
아래에서 띄우는 양이므로 값이 커지면 자막이 위로 올라간다 — 키 방향과 화면 움직임이 일치한다.
휠 방향은 `QWheelEvent.angleDelta().y()`의 부호로 판정한다(> 0 이면 위).

**함정 두 가지 — 구현 시 반드시 확인한다.**

1. `InlinePlayer.keyPressEvent`는 현재 **수정키를 전혀 보지 않는다.** 맨 `↑/↓`가 볼륨이므로
   `Ctrl+Shift` → `Ctrl` → 무수정 **순서로** 분기해야 한다(`Ctrl+Shift`도 Ctrl 비트가 켜져
   있어 순서를 뒤집으면 위치 조절이 크기 조절에 먹힌다).
2. `wheelEvent`가 현재 어디에도 없다. `_VideoView`(QGraphicsView)는 휠을 스크롤로
   **삼킬 수 있으므로**, 영상 위에서 굴린 휠이 `InlinePlayer`까지 오도록 `_VideoView.wheelEvent`가
   `event.ignore()`로 넘기게 한다. 이는 단축키 포커스 위임과 같은 종류의 함정이므로
   (핸들러는 멀쩡한데 이벤트가 도달하지 않아 조용히 죽는다) **도달성 테스트로 고정**한다.

### 3.6 3창 팬아웃

인라인 · 전체화면 · PiP가 각자 `LyricsOverlay` 인스턴스를 갖는다. 기존
`set_has_subtitle` 팬아웃과 같은 방식으로 세 오버레이 모두에 값을 밀어 넣고,
분리 창을 새로 열 때도 현재 값을 1회 반영한다(`bar` 초기 상태 반영과 동일한 패턴).

### 3.7 저장

`config/settings.py`에 `_load_float(key, default)`를 추가하고
`SUBTITLE_FONT_SCALE` · `SUBTITLE_BOTTOM_RATIO`를 노출한다. 저장은 기존
`save_setting(key, value)`를 쓴다.

휠은 이벤트가 연속으로 쏟아지므로 자막 오프셋과 **같은 500ms 디바운스** 후 1회만 기록한다.
디바운스 타이머는 `InlinePlayer`가 소유하고, 위젯이 사라질 때 남은 값을 flush 한다.

### 3.8 피드백 · 초기화

- 조절하는 동안 기존 `_status_lbl`에 `자막 크기 130%` / `자막 위치 24%`를 잠깐(약 1초) 띄운다.
  **없으면 안 된다**: 가사 줄이 표시되지 않는 구간에서 조절하면 화면에 아무 변화가 없어
  먹었는지 알 수 없다.
- 기존 `💬` 우클릭 메뉴에 `자막 크기·위치 초기화` 항목을 추가한다(둘을 기본값으로 되돌림).

### 3.9 테스트

**`tests/unit/gui/test_lyrics_track.py` 또는 신규 순수 로직 테스트**
1. 크기 배율이 글자 px에 선형 반영된다 · `_MIN_FONT_PX` 하한이 지켜진다
2. 위치 비율이 y 좌표에 반영되고 `y >= 0`으로 잘리지 않는다
3. 범위 밖 값이 clamp 된다(0.1 → 0.5, 9.9 → 3.0)

**`tests/gui/test_subtitle_player.py`**
4. `Ctrl`+↑ → 크기 변경, 맨 ↑ → **볼륨** 변경(회귀: 수정키 분기)
5. `Ctrl+Shift`+↑ → 위치 변경(크기는 안 변함 — 분기 순서 회귀)
6. **실제 휠 이벤트**가 영상 영역에서 `InlinePlayer`까지 도달한다(3.5 함정 2 고정)
7. 전체화면·PiP를 열면 현재 크기·위치가 반영된다

**`tests/gui/test_subtitle_wiring.py`**
8. 값 변경이 500ms 디바운스 후 1회 저장된다

---

## 4. 영향 · 문서

- `CLAUDE.md` — 검색 항목에 "가사는 최상위 카테고리가 음악인 영상만" 규칙,
  자막 항목에 크기·위치 조작과 오버레이가 영역 전체를 덮는다는 구조를 기록
- `planning/youtube_content_manager_prd.md` — 기능 요구사항 추가
- 색상 규칙: 자막 색은 기존대로 테마 토큰을 쓰지 않는 의도적 예외를 유지한다

## 5. 마이그레이션 · 호환

DB 스키마 변경이 없다. 설정 키 2개가 늘 뿐이고 없으면 기본값을 쓰므로 기존 설치본은
그대로 동작한다. 자막이 기본값에서 **커지고 살짝 올라오는** 변화가 눈에 띄는데,
이는 승인된 의도적 변경이다.
