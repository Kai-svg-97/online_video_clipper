# 가사 자막 표시 · 싱크 조정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 노래 영상 재생 중 가사를 영상 위 자막으로 표시하고, 시작 오프셋 하나로 싱크를 보정한다.

**Architecture:** LRCLIB의 `syncedLyrics`(LRC)를 파싱해 `LyricsLine.start_ms`로 저장하고,
영상별 보정값 `SongInfo.lyrics_offset_ms`를 둔다. GUI는 Qt 비의존 순수 로직 `LyricsTrack`
(이분 탐색으로 현재 줄 판정)과 렌더 전용 `LyricsOverlay(QWidget)`로 분리해, 로직을
QApplication 없이 테스트한다. 오버레이는 인라인·전체화면·PiP 3창에 기존 컨트롤바
팬아웃 패턴 그대로 배선한다.

**Tech Stack:** Python 3.10+, PyQt6, SQLite(stdlib), pytest / pytest-qt, ruff

**설계 문서:** `docs/superpowers/specs/2026-08-01-lyrics-subtitle-sync-design.md`

## Global Constraints

- 모든 대화 응답·문서·코드 주석은 **한국어**. 코드 식별자·라이브러리명·SQL 키워드는 영어
- **DDD 레이어 의존 규칙 준수**: `gui → application → domain ← infrastructure`.
  `domain/`은 외부 의존 없음. `application/`은 infrastructure를 import하지 않는다
- **애그리게이트 루트를 통해서만 상태 변경** — 엔티티 필드 직접 대입 금지
- **위젯 스타일시트에 색을 하드코딩하지 않는다.** `gui/themes/colors.py`의 `tok()` / `sem()`을 쓴다.
  예외는 의미·브랜드 색뿐이며 이유를 주석으로 남긴다. 자막 오버레이의 흰 글자/검은 외곽선은
  **영상 위 가독성을 위한 고정색이므로 예외** — 주석으로 명시할 것
- **예외를 조용히 삼키지 않는다.** 폴백이 필요하면 `logger.exception(...)`(예상 가능한 경우
  `logger.debug/warning`)으로 흔적을 남긴다. 모듈마다 `logger = logging.getLogger(__name__)`
- **Value Object에는 `__slots__`** (`@dataclass(frozen=True, slots=True)`)
- 리포지토리 쿼리는 페이지네이션 유지 — 이 작업은 목록 쿼리를 건드리지 않는다
- 네트워크 호출은 **반드시 QThread**에서. 메인 스레드 블로킹 금지
- 테스트 실행: `pytest`, 린트: `ruff check .`, 포맷: `ruff format .`
- **GUI 파일을 수정하면 완료 전 `/verify`로 앱을 실제 실행해 확인한다** (Task 10)
- 커밋 메시지는 한국어, `feat:`/`fix:`/`chore:`/`docs:`/`test:` 접두 + 무엇을·왜

## 파일 구조

| 파일 | 책임 | 작업 |
|---|---|---|
| `infrastructure/song/lrc.py` | LRC 텍스트 → (시각, 가사) 파싱. 순수 함수 | 생성 (T1) |
| `domain/song/value_objects.py` | `LyricsLine.start_ms` | 수정 (T2) |
| `domain/song/entities.py` | `SongInfo.lyrics_offset_ms`, `is_synced` | 수정 (T2) |
| `domain/song/aggregates.py` | `set_lyrics_offset`, `edit_lyrics` 타이밍 보존 | 수정 (T2) |
| `db/schema.sql` | `lyrics_offset_ms` 컬럼 | 수정 (T2) |
| `infrastructure/persistence/database.py` | `migrate_lyrics_offset` | 수정 (T2) |
| `infrastructure/persistence/sqlite_song_repository.py` | `"s"` 키 직렬화, 오프셋 컬럼 | 수정 (T2) |
| `domain/song/ports.py` | `LyricsResult.timings` | 수정 (T3) |
| `infrastructure/song/lyrics_providers.py` | LRCLIB synced 우선 | 수정 (T3) |
| `application/song/commands.py` | `synced_only`, `SetLyricsOffset*` | 수정 (T4) |
| `application/song/dtos.py` · `queries.py` | DTO에 타이밍·오프셋 노출 | 수정 (T4) |
| `gui/widgets/lyrics_overlay.py` | `LyricsCue`·`LyricsTrack`(순수) + `LyricsOverlay`(렌더) | 생성 (T5) |
| `gui/widgets/video_player.py` | 오버레이 3창 배선, `💬` 버튼, 단축키 | 수정 (T6) |
| `gui/panels/video_detail_panel.py` | 노래 탭 행 컨테이너·하이라이트·`⏱`, 패널 배선 | 수정 (T7, T8) |
| `gui/view_models/song_vm.py` | `fetch_synced_lyrics`, `set_lyrics_offset` | 수정 (T8) |
| `gui/panels/library_panel.py` | VM ↔ 패널 신호 연결 | 수정 (T8) |

---

### Task 1: LRC 파서

**Files:**
- Create: `infrastructure/song/lrc.py`
- Test: `tests/unit/infrastructure/test_lrc_parse.py`

**Interfaces:**
- Consumes: 없음 (순수 함수, 첫 태스크)
- Produces: `parse_lrc(text: str) -> list[tuple[int | None, str]]`
  — 반환 항목은 `(시작ms 또는 None, 가사 텍스트)`. Task 3이 사용

- [ ] **Step 1: 테스트 디렉터리 확인**

`tests/unit/infrastructure/`가 이미 존재한다. `__init__.py`가 없으면 빈 파일로 만든다.

Run: `ls tests/unit/infrastructure/`

- [ ] **Step 2: 실패하는 테스트 작성**

Create `tests/unit/infrastructure/test_lrc_parse.py`:

```python
"""LRC(가사 타이밍) 파싱 검증.

LRCLIB의 syncedLyrics를 줄별 시각으로 바꾸는 순수 함수라 I/O 없이 테스트한다.
"""
from __future__ import annotations

from infrastructure.song.lrc import parse_lrc


class TestBasicTimestamps:
    def test_밀리초_포함(self):
        assert parse_lrc("[01:23.45]가사") == [(83450, "가사")]

    def test_밀리초_3자리(self):
        assert parse_lrc("[01:23.456]가사") == [(83456, "가사")]

    def test_밀리초_생략(self):
        assert parse_lrc("[01:23]가사") == [(83000, "가사")]

    def test_타임스탬프_뒤_공백_제거(self):
        assert parse_lrc("[00:05.00]   hello  ") == [(5000, "hello")]

    def test_여러_줄_시각_오름차순(self):
        text = "[00:10.00]둘\n[00:05.00]하나"
        assert parse_lrc(text) == [(5000, "하나"), (10000, "둘")]


class TestMultiTimestamp:
    def test_한_줄_다중_타임스탬프는_전개된다(self):
        text = "[00:10.00][01:10.00]후렴"
        assert parse_lrc(text) == [(10000, "후렴"), (70000, "후렴")]


class TestMetaTags:
    def test_메타태그는_버린다(self):
        text = "[ar:가수]\n[ti:제목]\n[al:앨범]\n[by:작성자]\n[length:03:20]\n[00:01.00]가사"
        assert parse_lrc(text) == [(1000, "가사")]

    def test_offset_태그는_모든_시각에_더한다(self):
        # LRC 표준: offset은 밀리초, 음수면 앞당김
        text = "[offset:-500]\n[00:10.00]가사"
        assert parse_lrc(text) == [(9500, "가사")]

    def test_offset으로_음수가_되면_0으로_보정(self):
        text = "[offset:-5000]\n[00:01.00]가사"
        assert parse_lrc(text) == [(0, "가사")]


class TestUntimedAndEdgeCases:
    def test_타임스탬프_없는_줄은_None으로_보존(self):
        text = "[00:01.00]첫줄\n주석 같은 줄"
        assert parse_lrc(text) == [(1000, "첫줄"), (None, "주석 같은 줄")]

    def test_타임스탬프_없는_줄은_직전_줄_뒤에_남는다(self):
        text = "[00:20.00]나중\n무시간\n[00:10.00]먼저"
        assert parse_lrc(text) == [(10000, "먼저"), (20000, "나중"), (None, "무시간")]

    def test_빈_입력(self):
        assert parse_lrc("") == []
        assert parse_lrc("   \n  \n") == []

    def test_깨진_대괄호는_텍스트로_취급(self):
        assert parse_lrc("[00:1x.00]가사") == [(None, "[00:1x.00]가사")]

    def test_내부_빈_줄은_보존된다(self):
        text = "[00:01.00]가사\n\n[00:02.00]다음"
        assert parse_lrc(text) == [(1000, "가사"), (None, ""), (2000, "다음")]

    def test_CRLF_처리(self):
        assert parse_lrc("[00:01.00]가사\r\n[00:02.00]둘") == [(1000, "가사"), (2000, "둘")]

    def test_빈_가사_줄도_시각을_갖는다(self):
        # 간주 구간 표기 — 텍스트가 비어도 시각은 유효하다
        assert parse_lrc("[00:30.00]") == [(30000, "")]
```

- [ ] **Step 3: 테스트 실패 확인**

Run: `pytest tests/unit/infrastructure/test_lrc_parse.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'infrastructure.song.lrc'`

- [ ] **Step 4: 구현**

Create `infrastructure/song/lrc.py`:

```python
"""LRC(가사 타이밍) 포맷 파서.

LRCLIB의 ``syncedLyrics``는 ``[mm:ss.xx]가사`` 형태의 LRC 텍스트다. 이 모듈은 그것을
``(시작ms, 가사)`` 목록으로 바꾸는 **순수 함수** 하나만 제공한다 — 네트워크·Qt 의존이
없어 단위 테스트가 쉽고, 제공자(lyrics_providers)와 파싱 규칙을 분리한다.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# [mm:ss] / [mm:ss.x] / [mm:ss.xx] / [mm:ss.xxx] — 줄 앞에 연속으로 여러 개 올 수 있다.
_TS_RE = re.compile(r"\[(\d{1,3}):([0-5]\d)(?:[.:](\d{1,3}))?\]")
# [ar:...] [ti:...] 같은 메타 태그 — 콜론 뒤 값이 있는 알파벳 키
_META_RE = re.compile(r"^\[([a-zA-Z_]+):(.*)\]$")


def _to_ms(minute: str, second: str, frac: str | None) -> int:
    ms = int(minute) * 60_000 + int(second) * 1_000
    if frac:
        # 1자리 = 100ms, 2자리 = 10ms, 3자리 = 1ms 단위
        ms += int(frac.ljust(3, "0"))
    return ms


def parse_lrc(text: str) -> list[tuple[int | None, str]]:
    """LRC 텍스트를 ``(시작ms | None, 가사)`` 목록으로 파싱한다.

    - 한 줄에 타임스탬프가 여러 개면 같은 가사를 각 시각으로 전개한다(반복 구간 표기).
    - ``[ar:]``·``[ti:]`` 등 메타 태그는 버리고, ``[offset:±ms]``는 모든 시각에 더한다
      (LRC 표준. 음수 결과는 0으로 보정).
    - 타임스탬프가 없는 줄은 ``(None, 줄)``로 보존한다 — 텍스트를 잃지 않기 위함이며,
      정렬 시 시각이 있는 줄 뒤로 밀린다.
    - 실패해도 예외를 던지지 않는다(파싱 가능한 것만 돌려준다).
    """
    if not text:
        return []

    offset_ms = 0
    timed: list[tuple[int, int, str]] = []   # (시각, 등장순서, 가사) — 동시각 안정 정렬용
    untimed: list[tuple[None, str]] = []
    order = 0

    for raw in text.replace("\r\n", "\n").split("\n"):
        line = raw.strip()

        meta = _META_RE.match(line)
        if meta and not _TS_RE.match(line):
            key, value = meta.group(1).lower(), meta.group(2).strip()
            if key == "offset":
                try:
                    offset_ms = int(value)
                except ValueError:
                    logger.debug("LRC offset 태그 파싱 실패 — 무시: %r", value)
            continue   # 그 외 메타 태그는 버린다

        stamps: list[int] = []
        pos = 0
        while (m := _TS_RE.match(line, pos)) is not None:
            stamps.append(_to_ms(m.group(1), m.group(2), m.group(3)))
            pos = m.end()

        content = line[pos:].strip()
        if stamps:
            for ms in stamps:
                timed.append((ms, order, content))
                order += 1
        else:
            untimed.append((None, content))

    result: list[tuple[int | None, str]] = [
        (max(0, ms + offset_ms), content)
        for ms, _, content in sorted(timed, key=lambda t: (t[0], t[1]))
    ]
    result.extend(untimed)
    return result
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest tests/unit/infrastructure/test_lrc_parse.py -v`
Expected: PASS (전 항목)

주의 — `test_내부_빈_줄은_보존된다`가 실패하면 빈 줄이 `untimed`로 들어가 맨 뒤로 밀린
것이다. 기대값은 `[(1000, "가사"), (None, ""), (2000, "다음")]`이 아니라 실제로는
`[(1000, "가사"), (2000, "다음"), (None, "")]`가 된다. **테스트 기대값을 실제 정렬 규칙에
맞춰 수정한다** (타임스탬프 없는 줄은 뒤로 모인다는 것이 문서화된 규칙이다):

```python
    def test_내부_빈_줄은_보존된다(self):
        text = "[00:01.00]가사\n\n[00:02.00]다음"
        assert parse_lrc(text) == [(1000, "가사"), (2000, "다음"), (None, "")]
```

같은 이유로 `test_타임스탬프_없는_줄은_직전_줄_뒤에_남는다`의 기대값도 이미 맨 뒤에
`(None, "무시간")`가 오도록 작성돼 있다. 테스트 이름이 오해를 부르므로
`test_타임스탬프_없는_줄은_맨_뒤로_모인다`로 바꾼다.

- [ ] **Step 6: 린트**

Run: `ruff check infrastructure/song/lrc.py tests/unit/infrastructure/test_lrc_parse.py`
Expected: `All checks passed!`

- [ ] **Step 7: 커밋**

```bash
git add infrastructure/song/lrc.py tests/unit/infrastructure/test_lrc_parse.py
git commit -m "feat: LRC 가사 타이밍 파서 추가

- [mm:ss.xx] 다중 타임스탬프 전개, [offset:] 반영, 메타 태그 제거
- 네트워크·Qt 의존 없는 순수 함수라 단위 테스트로 규칙을 고정"
```

---

### Task 2: 도메인에 타이밍·오프셋 싣기 + 영속

**Files:**
- Modify: `domain/song/value_objects.py`
- Modify: `domain/song/entities.py`
- Modify: `domain/song/aggregates.py`
- Modify: `db/schema.sql:232` (song_info 테이블)
- Modify: `infrastructure/persistence/database.py:18-29` (MIGRATION_IDS) + 새 메서드
- Modify: `infrastructure/persistence/sqlite_song_repository.py:21-40, 43-64, 80-110`
- Test: `tests/integration/test_song_synced_lyrics.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `LyricsLine(original: str, translation: str = "", start_ms: int | None = None)`
  - `SongInfo.lyrics_offset_ms: int` · `SongInfo.is_synced -> bool`
  - `SongInfoAggregate.set_lyrics_offset(ms: int) -> None` (±30000 clamp)
  - `song_info.lyrics_offset_ms` 컬럼, `lyrics_json` 항목의 `"s"` 키
  - Task 3·4·5·7이 이 타입들을 사용

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/integration/test_song_synced_lyrics.py`:

```python
"""싱크 가사(줄별 시각)·자막 오프셋의 저장/로드 왕복을 검증한다.

lyrics_json은 [{"o":원문,"t":번역,"s":시작ms}] 형태로 확장됐다. "s"가 없는 기존
데이터가 그대로 로드되어야 한다(하위호환) — 이 회귀가 나면 기존 사용자의 가사가
깨진다.
"""
from __future__ import annotations

import json
from uuid import uuid4

import pytest

from domain.library.aggregates import VideoAggregate
from domain.library.value_objects import VideoUrl
from domain.song.aggregates import SongInfoAggregate
from domain.song.value_objects import LyricsLine
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_song_repository import SqliteSongRepository
from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository


@pytest.fixture
def db(tmp_path):
    database = Database(path=tmp_path / "song.db")
    database.initialize()
    return database


@pytest.fixture
def repo(db):
    return SqliteSongRepository(db)


@pytest.fixture
def video_id(db):
    videos = SqliteVideoRepository(db)
    agg = VideoAggregate.create(VideoUrl("https://youtu.be/sync1"), "노래 영상")
    videos.save(agg)
    return agg.id


def _lines() -> list[LyricsLine]:
    return [
        LyricsLine(original="first line", translation="첫 줄", start_ms=1000),
        LyricsLine(original="second line", translation="둘째 줄", start_ms=5500),
        LyricsLine(original="untimed", translation="", start_ms=None),
    ]


class TestSyncedLyricsRoundTrip:
    def test_start_ms가_저장되고_로드된다(self, repo, video_id):
        agg = SongInfoAggregate.create(video_id, is_song=True)
        agg.apply_fetched(lyrics_lines=_lines(), mark_song=True)
        repo.save(agg)

        loaded = repo.get(video_id)
        assert loaded is not None
        assert [ln.start_ms for ln in loaded.info.lyrics_lines] == [1000, 5500, None]
        assert loaded.info.is_synced is True

    def test_타이밍_없는_가사는_is_synced_False(self, repo, video_id):
        agg = SongInfoAggregate.create(video_id, is_song=True)
        agg.apply_fetched(
            lyrics_lines=[LyricsLine(original="no timing")], mark_song=True
        )
        repo.save(agg)
        assert repo.get(video_id).info.is_synced is False


class TestBackwardCompatibility:
    def test_s_키_없는_기존_JSON도_로드된다(self, db, repo, video_id):
        """기존 설치본의 lyrics_json에는 "s" 키가 없다."""
        legacy = json.dumps(
            [{"o": "old line", "t": "옛 줄"}], ensure_ascii=False
        )
        with db.connection() as conn:
            conn.execute(
                "INSERT INTO song_info (video_id, is_song, lyrics_json, updated_at) "
                "VALUES (?, 1, ?, datetime('now'))",
                (str(video_id), legacy),
            )
        loaded = repo.get(video_id)
        assert loaded.info.lyrics_lines[0].original == "old line"
        assert loaded.info.lyrics_lines[0].start_ms is None
        assert loaded.info.is_synced is False

    def test_s_키가_비정수여도_None으로_취급(self, db, repo, video_id):
        broken = json.dumps([{"o": "line", "t": "", "s": "이상한값"}], ensure_ascii=False)
        with db.connection() as conn:
            conn.execute(
                "INSERT INTO song_info (video_id, is_song, lyrics_json, updated_at) "
                "VALUES (?, 1, ?, datetime('now'))",
                (str(video_id), broken),
            )
        assert repo.get(video_id).info.lyrics_lines[0].start_ms is None

    def test_타이밍_없는_줄은_s_키를_쓰지_않는다(self, db, repo, video_id):
        agg = SongInfoAggregate.create(video_id, is_song=True)
        agg.apply_fetched(lyrics_lines=[LyricsLine(original="a")], mark_song=True)
        repo.save(agg)
        with db.connection() as conn:
            raw = conn.execute(
                "SELECT lyrics_json FROM song_info WHERE video_id=?", (str(video_id),)
            ).fetchone()[0]
        assert "s" not in json.loads(raw)[0]


class TestLyricsOffset:
    def test_기본값은_0(self, repo, video_id):
        agg = SongInfoAggregate.create(video_id, is_song=True)
        repo.save(agg)
        assert repo.get(video_id).info.lyrics_offset_ms == 0

    def test_저장되고_로드된다(self, repo, video_id):
        agg = SongInfoAggregate.create(video_id, is_song=True)
        agg.set_lyrics_offset(1500)
        repo.save(agg)
        assert repo.get(video_id).info.lyrics_offset_ms == 1500

    def test_음수도_저장된다(self, repo, video_id):
        agg = SongInfoAggregate.create(video_id, is_song=True)
        agg.set_lyrics_offset(-750)
        repo.save(agg)
        assert repo.get(video_id).info.lyrics_offset_ms == -750

    def test_범위를_벗어나면_clamp된다(self, repo, video_id):
        agg = SongInfoAggregate.create(video_id, is_song=True)
        agg.set_lyrics_offset(999_999)
        assert agg.info.lyrics_offset_ms == 30_000
        agg.set_lyrics_offset(-999_999)
        assert agg.info.lyrics_offset_ms == -30_000

    def test_같은_값이면_이벤트를_내지_않는다(self, video_id):
        agg = SongInfoAggregate.create(video_id, is_song=True)
        agg.set_lyrics_offset(0)
        assert agg.pull_events() == []


class TestEditLyricsTimingPreservation:
    def test_줄_수가_같으면_타이밍을_유지한다(self, video_id):
        """오탈자 수정으로 싱크가 날아가면 안 된다."""
        agg = SongInfoAggregate.create(video_id, is_song=True)
        agg.apply_fetched(lyrics_lines=_lines(), mark_song=True)
        edited = [
            LyricsLine(original="FIRST LINE", translation="첫 줄"),
            LyricsLine(original="second line", translation="둘째 줄"),
            LyricsLine(original="untimed", translation=""),
        ]
        agg.edit_lyrics(edited)
        assert [ln.start_ms for ln in agg.info.lyrics_lines] == [1000, 5500, None]
        assert agg.info.lyrics_lines[0].original == "FIRST LINE"

    def test_줄_수가_다르면_타이밍을_폐기한다(self, video_id):
        agg = SongInfoAggregate.create(video_id, is_song=True)
        agg.apply_fetched(lyrics_lines=_lines(), mark_song=True)
        agg.edit_lyrics([LyricsLine(original="한 줄로 줄임")])
        assert agg.info.lyrics_lines[0].start_ms is None
        assert agg.info.is_synced is False


class TestTranslationPreservesTiming:
    def test_번역_교체_후에도_start_ms가_남는다(self, video_id):
        agg = SongInfoAggregate.create(video_id, is_song=True)
        agg.apply_fetched(lyrics_lines=_lines(), mark_song=True)
        translated = [
            LyricsLine(original=ln.original, translation="새 번역", start_ms=ln.start_ms)
            for ln in agg.info.lyrics_lines
        ]
        agg.set_lyrics_translations(translated)
        assert [ln.start_ms for ln in agg.info.lyrics_lines] == [1000, 5500, None]
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/integration/test_song_synced_lyrics.py -v`
Expected: FAIL — `TypeError: LyricsLine.__init__() got an unexpected keyword argument 'start_ms'`

- [ ] **Step 3: 값 객체 확장**

Modify `domain/song/value_objects.py` — `LyricsLine`을 아래로 교체:

```python
@dataclass(frozen=True, slots=True)
class LyricsLine:
    """가사 한 줄.

    ``original``은 원문, ``translation``은 한글 번역(한국어 노래이거나 번역이 없으면 "").
    비한국어 노래는 원문 1줄 + 한글 1줄을 병행 표기하기 위해 두 값을 함께 담는다.

    ``start_ms``는 이 줄이 시작하는 시각(ms). LRC(싱크) 가사를 제공하는 출처에서만
    채워지며, ``None``이면 시간 정보가 없다는 뜻이다(자막·싱크 기능 비활성 조건).
    """

    original: str
    translation: str = ""
    start_ms: int | None = None
```

- [ ] **Step 4: 엔티티 확장**

Modify `domain/song/entities.py` — `SongInfo`에 필드와 프로퍼티를 추가한다.
`updated_at` 필드 **앞**에 오프셋 필드를 넣는다(기본값 있는 필드끼리라 순서 자유):

```python
    lyrics_lines: list[LyricsLine] = field(default_factory=list)
    lyrics_language: str = ""          # "" 미상, "ko", "en" 등 (ISO 639-1)
    lyrics_offset_ms: int = 0          # 자막 싱크 보정(ms). 양수 = 자막을 늦게 띄움
    source: SongSourceRef | None = None
    manual_fields: frozenset[str] = frozenset()
    updated_at: datetime = field(default_factory=_now)

    @classmethod
    def create(cls, video_id: UUID, *, is_song: bool = False) -> "SongInfo":
        return cls(video_id=video_id, is_song=is_song)

    @property
    def is_synced(self) -> bool:
        """시간 정보가 있는 줄이 하나라도 있으면 True — 자막·싱크 활성 조건."""
        return any(ln.start_ms is not None for ln in self.lyrics_lines)
```

`MANUAL_FIELDS`는 **변경하지 않는다** — 오프셋은 수동 편집 보존 대상(가사 내용)이 아니라
재생 환경 보정값이다.

- [ ] **Step 5: 애그리게이트에 오프셋 변경·타이밍 보존 추가**

Modify `domain/song/aggregates.py`:

파일 상단 상수 추가 (import 아래):

```python
# 자막 싱크 보정 허용 범위(ms). 30초를 넘는 어긋남은 가사가 잘못 매칭된 것이므로 막는다.
# GUI(gui/widgets/lyrics_overlay.py)도 저장 전에 같은 상한으로 자르므로 **공개 상수**로 두고
# 그쪽에서 import한다 — 두 곳에 따로 적으면 값이 어긋나는 사고가 난다.
MAX_LYRICS_OFFSET_MS = 30_000
```

`set_lyrics_translations` **앞**에 메서드 추가:

```python
    def set_lyrics_offset(self, ms: int) -> None:
        """자막 싱크 보정값을 설정한다(양수 = 자막을 늦게 띄움).

        허용 범위를 벗어나면 clamp한다 — 30초를 넘는 어긋남은 보정이 아니라
        가사가 잘못 매칭된 것이라 사용자가 되돌리기 어려운 상태가 된다.
        """
        clamped = max(-MAX_LYRICS_OFFSET_MS, min(MAX_LYRICS_OFFSET_MS, int(ms)))
        if self._info.lyrics_offset_ms == clamped:
            return
        self._info.lyrics_offset_ms = clamped
        self._touch(("lyrics_offset",))
```

`edit_lyrics`를 아래로 교체 (타이밍 보존 규칙 추가):

```python
    def edit_lyrics(self, lines: list[LyricsLine], *, source_name: str = "직접 입력") -> None:
        """사용자의 가사 편집 — 수동 필드로 표시하고 출처를 사용자 입력으로 바꾼다.

        편집기는 평문 한 줄씩만 다루므로 들어오는 ``lines``에는 시각이 없다. 줄 수가
        그대로면 기존 시각을 그 순서대로 되살린다(오탈자 수정으로 싱크가 날아가지
        않게). 줄 구성이 바뀌었으면 시각을 신뢰할 수 없으므로 폐기한다.
        """
        merged = self._merge_timings(lines)
        if merged == self._info.lyrics_lines:
            return
        self._info.lyrics_lines = merged
        self._info.manual_fields = self._info.manual_fields | {"lyrics"}
        self._info.source = SongSourceRef(name=source_name, url="")
        self._touch(("lyrics",))

    def _merge_timings(self, lines: list[LyricsLine]) -> list[LyricsLine]:
        old = self._info.lyrics_lines
        if len(lines) != len(old):
            return [
                LyricsLine(original=ln.original, translation=ln.translation)
                for ln in lines
            ]
        return [
            LyricsLine(
                original=new.original,
                translation=new.translation,
                start_ms=new.start_ms if new.start_ms is not None else prev.start_ms,
            )
            for new, prev in zip(lines, old)
        ]
```

- [ ] **Step 6: 스키마 + 마이그레이션**

Modify `db/schema.sql` — `song_info` 테이블의 `lyrics_language` 줄 **다음**에 추가:

```sql
    lyrics_language TEXT NOT NULL DEFAULT '',      -- ISO 639-1 ("" 미상)
    lyrics_offset_ms INTEGER NOT NULL DEFAULT 0,   -- 자막 싱크 보정(ms). 양수 = 자막 지연
```

그리고 `lyrics_json` 주석을 갱신:

```sql
    lyrics_json     TEXT NOT NULL DEFAULT '[]',   -- [{"o": 원문, "t": 한글번역, "s": 시작ms}, ...]
```

Modify `infrastructure/persistence/database.py` — `MIGRATION_IDS` 끝에 추가:

```python
    "migrate_video_summary_status",
    "migrate_lyrics_offset",
)
```

`_migrate_video_summary_status` 메서드 **다음**에 추가:

```python
    def _migrate_lyrics_offset(self) -> None:
        """song_info에 lyrics_offset_ms 컬럼을 추가한다 (idempotent).

        기존 설치본은 schema.sql의 CREATE TABLE IF NOT EXISTS로는 컬럼이 늘지 않으므로
        ALTER TABLE로 보강한다.
        """
        with self.connection() as conn:
            try:
                conn.execute(
                    "ALTER TABLE song_info ADD COLUMN lyrics_offset_ms INTEGER NOT NULL DEFAULT 0"
                )
                logger.info("song_info.lyrics_offset_ms 컬럼 추가 완료")
            except Exception:
                logger.debug("song_info.lyrics_offset_ms 컬럼 이미 존재 — 건너뜀")
```

- [ ] **Step 7: 리포지토리 직렬화**

Modify `infrastructure/persistence/sqlite_song_repository.py`:

`_lyrics_to_json` / `_lyrics_from_json`을 교체:

```python
def _lyrics_to_json(lines: list[LyricsLine]) -> str:
    """가사를 JSON으로 직렬화한다.

    ``"s"``(시작ms)는 값이 있을 때만 넣는다 — 타이밍 없는 가사에 null을 잔뜩 남기지
    않고, 검색 프리필터(lyrics_json LIKE)의 오탐 여지도 줄인다.
    """
    out = []
    for ln in lines:
        item = {"o": ln.original, "t": ln.translation}
        if ln.start_ms is not None:
            item["s"] = int(ln.start_ms)
        out.append(item)
    return json.dumps(out, ensure_ascii=False)


def _lyrics_from_json(raw: str | None) -> list[LyricsLine]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        logger.debug("가사 JSON 파싱 실패 — 빈 목록 사용")
        return []
    out: list[LyricsLine] = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        raw_start = item.get("s")
        # "s"가 없거나(구 데이터) 정수가 아니면 시간 정보 없음으로 취급한다.
        start_ms = int(raw_start) if isinstance(raw_start, (int, float)) else None
        out.append(
            LyricsLine(
                original=item.get("o", ""),
                translation=item.get("t", ""),
                start_ms=start_ms,
            )
        )
    return out
```

`_row_to_aggregate`의 `SongInfo(...)` 생성에 오프셋을 추가한다 (`lyrics_language` 줄 다음):

```python
        lyrics_language=row["lyrics_language"] or "",
        lyrics_offset_ms=int(row["lyrics_offset_ms"] or 0),
```

`save`의 INSERT를 확장한다 — 컬럼 목록·VALUES 자리표시자·UPDATE SET 세 곳 모두:

```python
            conn.execute(
                """
                INSERT INTO song_info
                    (video_id, is_song, artist, album, song_title, release_year,
                     lyrics_json, lyrics_language, lyrics_offset_ms, source_name, source_url,
                     manual_fields, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(video_id) DO UPDATE SET
                    is_song=excluded.is_song,
                    artist=excluded.artist,
                    album=excluded.album,
                    song_title=excluded.song_title,
                    release_year=excluded.release_year,
                    lyrics_json=excluded.lyrics_json,
                    lyrics_language=excluded.lyrics_language,
                    lyrics_offset_ms=excluded.lyrics_offset_ms,
                    source_name=excluded.source_name,
                    source_url=excluded.source_url,
                    manual_fields=excluded.manual_fields,
                    updated_at=excluded.updated_at
                """,
```

그리고 바인딩 튜플에서 `lyrics_language` 뒤에 `info.lyrics_offset_ms`를 넣는다.
**바인딩 순서가 컬럼 순서와 정확히 맞는지 확인할 것** — `?` 개수는 13개다.

- [ ] **Step 8: 테스트 통과 확인**

Run: `pytest tests/integration/test_song_synced_lyrics.py -v`
Expected: PASS (전 항목)

- [ ] **Step 9: 기존 테스트 회귀 확인**

Run: `pytest tests/integration/test_search_fields.py tests/integration/test_sync_entities.py -v`
Expected: PASS — 가사 검색 프리필터와 sync 캡처가 `"s"` 키 추가에 영향받지 않아야 한다

Run: `pytest -q`
Expected: 전체 PASS

- [ ] **Step 10: 커밋**

```bash
git add domain/song/ db/schema.sql infrastructure/persistence/ tests/integration/test_song_synced_lyrics.py
git commit -m "feat: 가사 줄별 시각(start_ms)·자막 오프셋 도메인/영속 추가

- LyricsLine.start_ms, SongInfo.lyrics_offset_ms + is_synced
- SongInfoAggregate.set_lyrics_offset(±30초 clamp)
- edit_lyrics는 줄 수가 같으면 기존 타이밍 유지(오탈자 수정으로 싱크가 날아가지 않게)
- lyrics_json에 \"s\" 키(값 있을 때만) — 기존 데이터 하위호환
- song_info.lyrics_offset_ms 컬럼 + migrate_lyrics_offset"
```

---

### Task 3: LRCLIB 싱크 가사 채택

**Files:**
- Modify: `domain/song/ports.py:15-30` (`LyricsResult`)
- Modify: `infrastructure/song/lyrics_providers.py:31, 62-113` (`LrclibProvider`)
- Test: `tests/unit/infrastructure/test_lrclib_synced.py`

**Interfaces:**
- Consumes: `parse_lrc` (Task 1)
- Produces: `LyricsResult.timings: list[int | None]` — `lines`와 같은 길이이거나 빈 리스트.
  Task 4가 사용

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/unit/infrastructure/test_lrclib_synced.py`:

```python
"""LRCLIB 제공자가 syncedLyrics를 타이밍과 함께 채택하는지 검증한다.

과거에는 syncedLyrics의 타임스탬프를 버리고 텍스트만 썼다. 자막 기능은 이 타이밍이
있어야 하므로, synced가 있으면 그것을 우선 채택해야 한다. 네트워크 대신 세션을
가짜로 주입해 검증한다.
"""
from __future__ import annotations

from unittest.mock import patch

from infrastructure.song.lyrics_providers import LrclibProvider


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FakeSession:
    """/api/get 만 응답하는 최소 세션."""

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self._status = status_code
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        if url.endswith("/api/get"):
            return _FakeResponse(self._payload, self._status)
        return _FakeResponse([], 200)   # 검색은 빈 결과


def _fetch(payload):
    with patch(
        "infrastructure.song.lyrics_providers._session",
        return_value=_FakeSession(payload),
    ):
        return LrclibProvider().fetch("Artist", "Title", 200)


class TestSyncedPreferred:
    def test_synced가_있으면_타이밍을_함께_반환한다(self):
        result = _fetch(
            {
                "plainLyrics": "one\ntwo",
                "syncedLyrics": "[00:01.00]one\n[00:05.50]two",
                "artistName": "Artist",
                "albumName": "Album",
                "trackName": "Title",
            }
        )
        assert result is not None
        assert result.lines == ["one", "two"]
        assert result.timings == [1000, 5500]

    def test_synced_텍스트가_plain보다_우선한다(self):
        result = _fetch(
            {
                "plainLyrics": "플레인",
                "syncedLyrics": "[00:02.00]싱크",
            }
        )
        assert result.lines == ["싱크"]
        assert result.timings == [2000]


class TestPlainFallback:
    def test_synced가_없으면_plain을_쓰고_타이밍은_빈_리스트(self):
        result = _fetch({"plainLyrics": "only plain\nsecond"})
        assert result.lines == ["only plain", "second"]
        assert result.timings == []

    def test_synced가_빈_문자열이면_plain으로_폴백(self):
        result = _fetch({"plainLyrics": "plain", "syncedLyrics": ""})
        assert result.lines == ["plain"]
        assert result.timings == []

    def test_synced가_파싱_불가면_plain으로_폴백(self):
        # 타임스탬프가 하나도 없는 문자열 → 타이밍을 얻을 수 없다
        result = _fetch({"plainLyrics": "plain", "syncedLyrics": "타임스탬프 없음"})
        assert result.lines == ["plain"]
        assert result.timings == []

    def test_가사가_전혀_없으면_None(self):
        assert _fetch({"plainLyrics": "", "syncedLyrics": ""}) is None


class TestLengthInvariant:
    def test_timings_길이는_lines와_같다(self):
        result = _fetch({"syncedLyrics": "[00:01.00]a\n[00:02.00]b\n[00:03.00]c"})
        assert len(result.timings) == len(result.lines)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/unit/infrastructure/test_lrclib_synced.py -v`
Expected: FAIL — `AttributeError: 'LyricsResult' object has no attribute 'timings'`

- [ ] **Step 3: `LyricsResult`에 timings 추가**

Modify `domain/song/ports.py` — `LyricsResult`의 `lines` 다음에 필드를 추가하고 docstring 보강:

```python
@dataclass(frozen=True, slots=True)
class LyricsResult:
    """가사 제공자 조회 결과.

    ``lines``는 가사 원문 줄 목록(빈 리스트 = 가사 없음). ``timings``는 각 줄의 시작
    시각(ms)으로 ``lines``와 같은 길이이거나, 시간 정보가 없으면 빈 리스트다
    (LRC 싱크 가사를 주는 출처에서만 채워진다). 제공자가 함께 알려주는
    메타데이터(가수·앨범·제목·발매년도)는 부족분을 채우는 데 쓰인다.
    """

    lines: list[str] = field(default_factory=list)
    timings: list[int | None] = field(default_factory=list)
    language: str = ""          # ISO 639-1 (예: "en", "ko") — 미상이면 ""
    source_name: str = ""       # 표시 이름 (예: "LRCLIB")
    source_url: str = ""
    artist: str = ""
    album: str = ""
    title: str = ""
    release_year: str = ""
```

`timings`를 `lines` 바로 뒤에 넣으므로 **위치 인자로 `LyricsResult(...)`를 만드는 호출부가
있으면 깨진다.** 확인:

Run: `grep -rn "LyricsResult(" infrastructure/ application/ tests/`
모든 호출이 키워드 인자인지 확인하고, 위치 인자가 있으면 키워드로 바꾼다.

- [ ] **Step 4: `LrclibProvider` 구현 변경**

Modify `infrastructure/song/lyrics_providers.py`:

상단 import에 추가:

```python
from infrastructure.song.lrc import parse_lrc
```

`_LRC_TS_RE` 상수와 `_strip_lrc_timestamps` 함수를 **삭제**한다 (파싱은 `lrc.py`가 담당).

`LrclibProvider.fetch`의 반환 직전 블록(현재 99~113행)을 교체:

```python
        # 싱크 가사(syncedLyrics)가 있으면 우선 채택한다 — 텍스트 내용은 plainLyrics와
        # 같고 줄별 시각까지 얻을 수 있어, 자막·싱크 기능의 유일한 타이밍 출처다.
        lines: list[str] = []
        timings: list[int | None] = []
        synced = data.get("syncedLyrics") or ""
        if synced:
            parsed = parse_lrc(synced)
            if any(ms is not None for ms, _ in parsed):
                lines = [text for _, text in parsed]
                timings = [ms for ms, _ in parsed]
            else:
                logger.debug("LRCLIB syncedLyrics에 타임스탬프가 없음 — plain으로 폴백")
        if not lines:
            lines = _split_lines(data.get("plainLyrics") or "")
            timings = []
        if not lines:
            return None
        return LyricsResult(
            lines=lines,
            timings=timings,
            language="",
            source_name="LRCLIB",
            source_url="https://lrclib.net",
            artist=data.get("artistName") or "",
            album=data.get("albumName") or "",
            title=data.get("trackName") or "",
        )
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest tests/unit/infrastructure/test_lrclib_synced.py -v`
Expected: PASS

주의 — `test_synced_텍스트가_plain보다_우선한다`에서 `parse_lrc`가 앞뒤 빈 줄을
`(None, "")`로 남길 수 있다. `lines == ["싱크"]`가 아니라 뒤에 빈 항목이 붙으면,
`parse_lrc` 결과에서 **맨 뒤의 타임스탬프 없는 빈 줄만** 잘라낸다:

```python
            if any(ms is not None for ms, _ in parsed):
                # 맨 뒤에 몰린 '타임스탬프 없는 빈 줄'은 표시상 의미가 없어 잘라낸다.
                while parsed and parsed[-1][0] is None and not parsed[-1][1].strip():
                    parsed.pop()
                lines = [text for _, text in parsed]
                timings = [ms for ms, _ in parsed]
```

- [ ] **Step 6: 린트 + 전체 테스트**

Run: `ruff check infrastructure/ domain/ && pytest -q`
Expected: `All checks passed!` + 전체 PASS

- [ ] **Step 7: 커밋**

```bash
git add domain/song/ports.py infrastructure/song/lyrics_providers.py tests/unit/infrastructure/test_lrclib_synced.py
git commit -m "feat: LRCLIB 싱크 가사(syncedLyrics)를 타이밍과 함께 채택

- LyricsResult.timings 추가(lines와 같은 길이 또는 빈 리스트)
- 기존에는 타임스탬프를 버리고 텍스트만 썼으나, 자막 기능의 유일한 타이밍 출처라
  synced가 있으면 우선 채택하고 없을 때만 plainLyrics로 폴백
- 파싱 책임을 infrastructure/song/lrc.py로 분리(_strip_lrc_timestamps 제거)"
```

---

### Task 4: 애플리케이션 — 싱크 전용 조회 · 오프셋 커맨드 · DTO

**Files:**
- Modify: `application/song/commands.py:111-124` (커맨드), `204-377` (핸들러)
- Modify: `application/song/dtos.py`
- Modify: `application/song/queries.py:13-29` (`song_to_dto`)
- Test: `tests/unit/application/test_song_synced_fetch.py`

**Interfaces:**
- Consumes: `LyricsResult.timings` (T3), `SongInfoAggregate.set_lyrics_offset` (T2)
- Produces:
  - `FetchSongInfoCommand(..., synced_only: bool = False)`
  - `SetLyricsOffsetCommand(video_id: UUID, offset_ms: int)` · `SetLyricsOffsetHandler(song_repo, event_bus).handle(cmd) -> None`
  - `LyricsLineDTO(original, translation="", start_ms=None)`
  - `SongInfoDTO(..., lyrics_offset_ms: int = 0)` + `is_synced` 프로퍼티
  - Task 5·7·8이 사용

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/unit/application/test_song_synced_fetch.py`:

```python
"""싱크 전용 조회(synced_only)와 자막 오프셋 커맨드를 검증한다.

synced_only는 타이밍 없는 결과를 채택하지 않고 다음 출처로 넘어간다 — 실질적으로
LRCLIB만 통과하지만, 미래에 타이밍을 주는 출처가 생기면 자동 편입된다.
전 출처 실패 시 기존 가사를 지우지 않는 것이 핵심 계약이다.
"""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from application.song.commands import (
    FetchSongInfoCommand,
    FetchSongInfoHandler,
    SetLyricsOffsetCommand,
    SetLyricsOffsetHandler,
)
from domain.song.aggregates import SongInfoAggregate
from domain.song.entities import LyricsSource
from domain.song.ports import LyricsResult
from domain.song.value_objects import LyricsLine


class _Provider:
    def __init__(self, key, result):
        self.key = key
        self._result = result
        self.calls = 0

    def fetch(self, artist, title, duration_sec=None):
        self.calls += 1
        return self._result


@pytest.fixture
def video_id():
    return uuid4()


@pytest.fixture
def song_repo():
    repo = MagicMock()
    repo.list_lyrics_sources.return_value = [
        LyricsSource.create("플레인출처", "plain", priority=10),
        LyricsSource.create("싱크출처", "synced", priority=20),
    ]
    return repo


@pytest.fixture
def video_repo(video_id):
    repo = MagicMock()
    video = MagicMock()
    video.title = "Artist - Title"
    video.url = "https://youtu.be/x"
    video.channel = None
    video.duration = None
    agg = MagicMock()
    agg.video = video
    repo.get_by_id.return_value = agg
    return repo


def _handler(song_repo, video_repo, providers):
    return FetchSongInfoHandler(
        song_repo=song_repo,
        video_repo=video_repo,
        event_bus=MagicMock(),
        lyrics_providers=providers,
        translator=None,
        media_source=None,
    )


class TestSyncedOnlyFetch:
    def test_타이밍_없는_출처는_건너뛴다(self, song_repo, video_repo, video_id):
        song_repo.get.return_value = SongInfoAggregate.create(video_id, is_song=True)
        plain = _Provider("plain", LyricsResult(lines=["no timing"], timings=[]))
        synced = _Provider(
            "synced",
            LyricsResult(lines=["a", "b"], timings=[1000, 2000], source_url="u"),
        )
        handler = _handler(song_repo, video_repo, {"plain": plain, "synced": synced})

        agg = handler.handle(
            FetchSongInfoCommand(video_id=video_id, synced_only=True, force=True)
        )

        assert [ln.original for ln in agg.info.lyrics_lines] == ["a", "b"]
        assert [ln.start_ms for ln in agg.info.lyrics_lines] == [1000, 2000]
        assert agg.info.source.name == "싱크출처"

    def test_전_출처_실패면_기존_가사를_유지한다(self, song_repo, video_repo, video_id):
        existing = SongInfoAggregate.create(video_id, is_song=True)
        existing.apply_fetched(
            lyrics_lines=[LyricsLine(original="기존 가사")], mark_song=True
        )
        song_repo.get.return_value = existing
        plain = _Provider("plain", LyricsResult(lines=["x"], timings=[]))
        handler = _handler(song_repo, video_repo, {"plain": plain})

        agg = handler.handle(
            FetchSongInfoCommand(video_id=video_id, synced_only=True, force=True)
        )

        assert [ln.original for ln in agg.info.lyrics_lines] == ["기존 가사"]
        assert agg.info.is_synced is False

    def test_수동편집_가사도_싱크_가사로_교체된다(self, song_repo, video_repo, video_id):
        """사용자가 명시적으로 누른 버튼이므로 수동 편집 가드를 넘어선다."""
        existing = SongInfoAggregate.create(video_id, is_song=True)
        existing.edit_lyrics([LyricsLine(original="손으로 넣은 가사")])
        song_repo.get.return_value = existing
        synced = _Provider("synced", LyricsResult(lines=["새 가사"], timings=[500]))
        handler = _handler(song_repo, video_repo, {"synced": synced})

        agg = handler.handle(
            FetchSongInfoCommand(video_id=video_id, synced_only=True, force=True)
        )

        assert [ln.original for ln in agg.info.lyrics_lines] == ["새 가사"]
        assert agg.info.lyrics_lines[0].start_ms == 500


class TestNormalFetchUnaffected:
    def test_synced_only가_꺼져_있으면_타이밍_없는_가사도_채택(
        self, song_repo, video_repo, video_id
    ):
        song_repo.get.return_value = SongInfoAggregate.create(video_id, is_song=True)
        plain = _Provider("plain", LyricsResult(lines=["no timing"], timings=[]))
        handler = _handler(song_repo, video_repo, {"plain": plain})

        agg = handler.handle(
            FetchSongInfoCommand(video_id=video_id, force=True, fetch_lyrics=True)
        )

        assert [ln.original for ln in agg.info.lyrics_lines] == ["no timing"]

    def test_타이밍이_있으면_일반_조회에서도_보존된다(
        self, song_repo, video_repo, video_id
    ):
        song_repo.get.return_value = SongInfoAggregate.create(video_id, is_song=True)
        synced = _Provider("synced", LyricsResult(lines=["a"], timings=[700]))
        handler = _handler(song_repo, video_repo, {"synced": synced})

        agg = handler.handle(
            FetchSongInfoCommand(video_id=video_id, force=True, fetch_lyrics=True)
        )

        assert agg.info.lyrics_lines[0].start_ms == 700


class TestSetLyricsOffset:
    def test_오프셋을_저장한다(self, song_repo, video_id):
        agg = SongInfoAggregate.create(video_id, is_song=True)
        song_repo.get.return_value = agg
        bus = MagicMock()

        SetLyricsOffsetHandler(song_repo, bus).handle(
            SetLyricsOffsetCommand(video_id=video_id, offset_ms=1250)
        )

        assert agg.info.lyrics_offset_ms == 1250
        song_repo.save.assert_called_once_with(agg)

    def test_노래_정보가_없으면_새로_만든다(self, song_repo, video_id):
        song_repo.get.return_value = None
        SetLyricsOffsetHandler(song_repo, MagicMock()).handle(
            SetLyricsOffsetCommand(video_id=video_id, offset_ms=-500)
        )
        saved = song_repo.save.call_args[0][0]
        assert saved.info.lyrics_offset_ms == -500
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/unit/application/test_song_synced_fetch.py -v`
Expected: FAIL — `TypeError: FetchSongInfoCommand.__init__() got an unexpected keyword argument 'synced_only'`

- [ ] **Step 3: 커맨드 추가**

Modify `application/song/commands.py` — `FetchSongInfoCommand`에 필드 추가:

```python
@dataclass
class FetchSongInfoCommand:
    """노래 정보를 조회해 저장한다(등록 시 / 상세화면 ⟳ 갱신 시).

    prefetch: 등록 시 yt-dlp가 이미 조회한 info에서 뽑은 music 메타데이터 dict.
              (없으면 media_source로 재조회 — 갱신 버튼 경로)
    force:    True면 가사가 있어도 재조회한다.
    synced_only: True면 **시간 정보(LRC 타이밍)가 있는 가사만** 채택한다. 타이밍이 없는
              출처는 건너뛰고, 전 출처가 실패하면 기존 가사를 그대로 둔다(자막용 조회).
    """
    video_id: UUID
    prefetch: dict | None = None
    force: bool = False
    fetch_lyrics: bool = True   # False면 감지+메타데이터만(가사 네트워크 조회 생략)
    from_source_name: str | None = None  # 설정 시 이 출처 '다음'부터 검색(순환) — '다음 출처'
    synced_only: bool = False
```

`TranslateSongLyricsCommand` **앞**에 추가:

```python
@dataclass
class SetLyricsOffsetCommand:
    """자막 싱크 보정값을 저장한다(양수 = 자막을 늦게 띄움)."""
    video_id: UUID
    offset_ms: int
```

- [ ] **Step 4: `_run_chain` 반환형을 dataclass로 정리**

Modify `application/song/commands.py` — `FetchSongInfoHandler` **앞**에 내부 결과 타입을 추가:

```python
@dataclass
class _ChainOutcome:
    """출처 체인 순회 결과 — 반환 튜플이 길어져 이름을 붙였다(내부 전용)."""
    lyrics: list[str] = field(default_factory=list)
    timings: list[int | None] = field(default_factory=list)
    language: str = ""
    source: SongSourceRef | None = None
    artist: str = ""
    album: str = ""
    title: str = ""
    year: str = ""
```

- [ ] **Step 5: `handle`과 `_run_chain` 수정**

Modify `application/song/commands.py` — `FetchSongInfoHandler.handle`의 3~5단계(현재 253~281행)를 교체:

```python
        # 3) 출처 체인으로 가사·부족분 조회 (수동 편집 필드는 최종 apply에서 보존)
        outcome = _ChainOutcome(artist=artist, album=album, title=title, year=year)
        need_lyrics = cmd.fetch_lyrics and (cmd.force or not agg.info.lyrics_lines)
        if need_lyrics:
            outcome = self._run_chain(
                artist, title, album, year, duration,
                start_after_name=cmd.from_source_name,
                synced_only=cmd.synced_only,
            )

        # 4) 번역 (비한국어 가사에 한글 병행) — 줄별 시각을 함께 싣는다
        line_objs = self._build_lyrics_lines(
            outcome.lyrics, outcome.language, outcome.timings
        )

        # 5) 반영·저장
        agg.apply_fetched(
            artist=outcome.artist or None,
            album=outcome.album or None,
            song_title=outcome.title or None,
            release_year=outcome.year or None,
            lyrics_lines=line_objs or None,
            lyrics_language=outcome.language or None,
            source=outcome.source,
            mark_song=True,
            force_lyrics=bool(cmd.from_source_name) or cmd.synced_only,
        )
        self._songs.save(agg)
        self._bus.publish_all(agg.pull_events())
        return agg
```

`_run_chain` 시그니처·본문을 교체:

```python
    def _run_chain(
        self,
        artist: str,
        title: str,
        album: str,
        year: str,
        duration: int | None,
        start_after_name: str | None = None,
        synced_only: bool = False,
    ) -> _ChainOutcome:
        """활성 출처를 순서대로 시도해 가사와 부족한 메타데이터를 채운다.

        start_after_name이 주어지면(‘다음 출처’ 검색) 그 출처 **다음**부터 순회하도록 목록을
        회전한다. 끝에 도달하면 처음으로 순환한다(현재 출처는 맨 뒤로 밀려 마지막에만 재시도).

        synced_only면 시간 정보(timings)가 없는 결과는 가사로 채택하지 않고 다음 출처로
        넘어간다 — 자막용 '싱크 가사 찾기' 경로다.
        """
        out = _ChainOutcome(artist=artist, album=album, title=title, year=year)
        try:
            sources = [s for s in self._songs.list_lyrics_sources() if s.enabled]
        except Exception:
            logger.exception("가사 출처 목록 조회 실패")
            sources = []

        if start_after_name:
            idx = next((i for i, s in enumerate(sources) if s.name == start_after_name), -1)
            if idx >= 0:
                sources = sources[idx + 1:] + sources[: idx + 1]

        # 검색용 아티스트 후보: 전체 문자열 → 주(첫) 아티스트 순으로 시도한다.
        # 다중 아티스트 표기("NIKI, Phil Collins")로는 제공자 매칭이 실패하므로
        # 주 아티스트("NIKI")로 재시도해 유명곡 가사를 놓치지 않는다.
        artist_candidates = [out.artist]
        primary = _primary_artist(out.artist)
        if primary and primary != out.artist:
            artist_candidates.append(primary)

        for src in sources:
            provider = self._providers.get(src.provider_key)
            if provider is None:
                continue
            result: LyricsResult | None = None
            for cand_artist in artist_candidates:
                try:
                    result = provider.fetch(cand_artist, out.title, duration)
                except Exception:
                    logger.exception("가사 조회 실패: provider=%s", src.provider_key)
                    result = None
                if result is not None:
                    break
            if result is None:
                continue
            # 싱크 전용 조회는 타이밍이 없는 결과를 아예 채택하지 않는다(메타데이터 보강도 생략).
            if synced_only and not any(t is not None for t in result.timings):
                logger.debug("싱크 전용 조회 — 타이밍 없는 출처 건너뜀: %s", src.name)
                continue
            # 부족한 메타데이터 보강(빈 값만 채움)
            out.artist = out.artist or result.artist
            out.album = out.album or result.album
            out.title = out.title or result.title
            out.year = out.year or result.release_year
            # 가사는 처음 확보한 출처 것을 채택
            if not out.lyrics and result.lines:
                out.lyrics = list(result.lines)
                out.timings = list(result.timings)
                out.language = result.language or out.language
                # 출처명은 DB 출처 이름(src.name)을 저장 — '다음 출처' 검색 시 정확히 매칭·순환.
                out.source = SongSourceRef(name=src.name, url=result.source_url)
            # 가사 + 핵심 메타가 모두 채워졌으면 조기 종료
            if out.lyrics and out.artist and out.title and out.album:
                break
        return out
```

`_build_lyrics_lines`에 timings 인자를 추가:

```python
    def _build_lyrics_lines(
        self, lines: list[str], language: str, timings: list[int | None] | None = None
    ) -> list[LyricsLine]:
        if not lines:
            return []
        # 타이밍은 lines와 길이가 같을 때만 신뢰한다(길이가 어긋나면 잘못 짝지어진다).
        stamps: list[int | None] = list(timings or [])
        if len(stamps) != len(lines):
            stamps = [None] * len(lines)
        lang = (language or "").lower()
        # 언어 미상이면 번역기로 추정 시도
        if not lang and self._translator is not None:
            try:
                sample = next((ln for ln in lines if ln.strip()), "")
                lang = (self._translator.detect_language(sample) or "").lower()
            except Exception:
                logger.exception("가사 언어 감지 실패")
        # 한국어면 번역 없이 원문만
        if lang == "ko" or self._translator is None:
            return [
                LyricsLine(original=ln, translation="", start_ms=ms)
                for ln, ms in zip(lines, stamps)
            ]
        try:
            translations = self._translator.translate(lines, target="ko")
        except Exception:
            logger.exception("가사 번역 실패 — 원문만 표시")
            translations = lines
        if len(translations) != len(lines):
            translations = lines
        return [
            LyricsLine(original=o, translation=(t if t != o else ""), start_ms=ms)
            for o, t, ms in zip(lines, translations, stamps)
        ]
```

`TranslateSongLyricsHandler.handle`에서 새 `LyricsLine`을 만들 때 **시각을 보존**한다
(현재 414~417행):

```python
        new_lines = [
            LyricsLine(
                original=old.original,
                translation=(t if t != old.original else ""),
                start_ms=old.start_ms,
            )
            for old, t in zip(agg.info.lyrics_lines, translations)
        ]
```

`originals` 변수는 그대로 두되 위 zip은 `agg.info.lyrics_lines`를 직접 쓴다.

- [ ] **Step 6: 오프셋 핸들러 추가**

Modify `application/song/commands.py` — `SetSongFlagHandler` **앞**에 추가:

```python
class SetLyricsOffsetHandler:
    """자막 싱크 보정값을 저장한다. 노래 정보가 없으면 새로 만든다."""

    def __init__(self, song_repo: ISongRepository, event_bus: IEventBus) -> None:
        self._songs = song_repo
        self._bus = event_bus

    def handle(self, cmd: SetLyricsOffsetCommand) -> None:
        agg = self._songs.get(cmd.video_id) or SongInfoAggregate.create(
            cmd.video_id, is_song=True
        )
        agg.set_lyrics_offset(cmd.offset_ms)
        self._songs.save(agg)
        self._bus.publish_all(agg.pull_events())
```

- [ ] **Step 7: DTO 확장**

Modify `application/song/dtos.py`:

```python
@dataclass(frozen=True)
class LyricsLineDTO:
    original: str
    translation: str = ""
    start_ms: int | None = None


@dataclass(frozen=True)
class SongInfoDTO:
    video_id: UUID
    is_song: bool
    artist: str = ""
    album: str = ""
    song_title: str = ""
    release_year: str = ""
    lyrics_lines: tuple[LyricsLineDTO, ...] = ()
    lyrics_language: str = ""
    lyrics_offset_ms: int = 0
    source_name: str = ""
    source_url: str = ""

    @property
    def has_lyrics(self) -> bool:
        return bool(self.lyrics_lines)

    @property
    def is_bilingual(self) -> bool:
        """번역이 병행 표기된 가사인지(원문≠한국어)."""
        return any(line.translation for line in self.lyrics_lines)

    @property
    def is_synced(self) -> bool:
        """시간 정보가 있는 줄이 있는지 — 자막·싱크 UI 활성 조건."""
        return any(line.start_ms is not None for line in self.lyrics_lines)
```

Modify `application/song/queries.py` — `song_to_dto`:

```python
        lyrics_lines=tuple(
            LyricsLineDTO(
                original=ln.original, translation=ln.translation, start_ms=ln.start_ms
            )
            for ln in info.lyrics_lines
        ),
        lyrics_language=info.lyrics_language,
        lyrics_offset_ms=info.lyrics_offset_ms,
```

- [ ] **Step 8: 테스트 통과 확인**

Run: `pytest tests/unit/application/test_song_synced_fetch.py -v`
Expected: PASS

- [ ] **Step 9: 전체 회귀 + 린트**

Run: `pytest -q && ruff check application/ domain/ infrastructure/`
Expected: 전체 PASS + `All checks passed!`

- [ ] **Step 10: 커밋**

```bash
git add application/song/ tests/unit/application/test_song_synced_fetch.py
git commit -m "feat: 싱크 전용 가사 조회 + 자막 오프셋 커맨드

- FetchSongInfoCommand.synced_only — 타이밍 없는 출처는 건너뛰고, 전부 실패하면
  기존 가사를 그대로 둔다(자막용 '싱크 가사 찾기')
- SetLyricsOffsetCommand/Handler 추가
- _run_chain 반환을 _ChainOutcome dataclass로 정리(8-튜플 방지)
- 번역·조회 경로 모두 start_ms 보존, DTO에 start_ms·lyrics_offset_ms·is_synced 노출"
```

---

### Task 5: 자막 위젯 (순수 로직 + 렌더)

**Files:**
- Create: `gui/widgets/lyrics_overlay.py`
- Test: `tests/unit/gui/test_lyrics_track.py` (Qt 불필요)
- Test: `tests/gui/test_lyrics_overlay.py` (렌더 — qapp 필요)

**Interfaces:**
- Consumes: `SongInfoDTO.lyrics_lines`(`.original`/`.translation`/`.start_ms`) (T4)
- Produces:
  - `LyricsCue(start_ms: int, original: str, translation: str = "", line_index: int = -1)`
  - `LyricsTrack(cues: list[LyricsCue], offset_ms: int = 0)`
    · `from_lines(lines, offset_ms=0) -> LyricsTrack` (classmethod)
    · `is_empty: bool` · `offset_ms: int`(get/set, ±30000 clamp)
    · `index_at(pos_ms) -> int | None` · `cue_at(pos_ms) -> LyricsCue | None`
    · `start_of(index) -> int` · `__len__()`
  - `LyricsOverlay(QWidget)` · `set_cue(cue | None)` · `subtitle_font_family() -> str`
  - Task 6·7·8이 사용

- [ ] **Step 1: 순수 로직 테스트 작성**

Create `tests/unit/gui/test_lyrics_track.py`:

```python
"""LyricsTrack(현재 줄 판정)을 QApplication 없이 검증한다.

렌더(LyricsOverlay)와 분리한 이유가 이것 — 경계값·오프셋 로직은 Qt 없이 빠르게
돌릴 수 있어야 한다.
"""
from __future__ import annotations

from dataclasses import dataclass

from gui.widgets.lyrics_overlay import LyricsCue, LyricsTrack


@dataclass(frozen=True)
class _Line:
    """SongInfoDTO.lyrics_lines 항목을 흉내낸 최소 구조."""
    original: str
    translation: str = ""
    start_ms: int | None = None


def _track(offset_ms: int = 0) -> LyricsTrack:
    return LyricsTrack(
        [
            LyricsCue(start_ms=1000, original="one", line_index=0),
            LyricsCue(start_ms=5000, original="two", line_index=1),
            LyricsCue(start_ms=9000, original="three", line_index=2),
        ],
        offset_ms=offset_ms,
    )


class TestIndexAt:
    def test_첫_줄_시작_전에는_None(self):
        assert _track().index_at(0) is None
        assert _track().index_at(999) is None

    def test_정확히_시작_시각이면_그_줄(self):
        assert _track().index_at(1000) == 0
        assert _track().index_at(5000) == 1

    def test_줄_사이에서는_직전_줄이_유지된다(self):
        assert _track().index_at(4999) == 0
        assert _track().index_at(8999) == 1

    def test_마지막_줄은_끝까지_유지된다(self):
        assert _track().index_at(999_999) == 2

    def test_역방향_seek도_정확하다(self):
        track = _track()
        assert track.index_at(9000) == 2
        assert track.index_at(1500) == 0


class TestOffset:
    def test_양수_오프셋은_자막을_늦춘다(self):
        track = _track(offset_ms=2000)
        assert track.index_at(1000) is None      # 원래 첫 줄 시점 → 아직 안 뜸
        assert track.index_at(3000) == 0

    def test_음수_오프셋은_자막을_앞당긴다(self):
        track = _track(offset_ms=-500)
        assert track.index_at(500) == 0

    def test_오프셋_변경이_즉시_반영된다(self):
        track = _track()
        assert track.index_at(1000) == 0
        track.offset_ms = 3000
        assert track.index_at(1000) is None

    def test_오프셋은_범위로_clamp된다(self):
        track = _track()
        track.offset_ms = 999_999
        assert track.offset_ms == 30_000
        track.offset_ms = -999_999
        assert track.offset_ms == -30_000


class TestCueAndStartOf:
    def test_cue_at은_해당_줄을_준다(self):
        assert _track().cue_at(5001).original == "two"

    def test_cue_at은_시작_전에는_None(self):
        assert _track().cue_at(0) is None

    def test_start_of는_오프셋을_더한_절대_위치(self):
        track = _track(offset_ms=1500)
        assert track.start_of(1) == 6500

    def test_start_of는_음수가_되지_않는다(self):
        track = _track(offset_ms=-5000)
        assert track.start_of(0) == 0

    def test_범위_밖_index는_0(self):
        assert _track().start_of(99) == 0


class TestEmpty:
    def test_빈_트랙은_is_empty(self):
        track = LyricsTrack([])
        assert track.is_empty is True
        assert track.index_at(1000) is None
        assert len(track) == 0

    def test_큐가_있으면_is_empty_False(self):
        assert _track().is_empty is False


class TestFromLines:
    def test_시간_정보가_있는_줄만_큐가_된다(self):
        lines = [
            _Line("no timing"),
            _Line("timed", "번역", 2000),
            _Line("also timed", "", 4000),
        ]
        track = LyricsTrack.from_lines(lines)
        assert len(track) == 2
        assert track.cue_at(2000).original == "timed"
        assert track.cue_at(2000).translation == "번역"

    def test_line_index는_원본_목록_기준이다(self):
        """노래 탭 하이라이트가 원본 줄을 가리켜야 한다."""
        lines = [_Line("untimed"), _Line("first", start_ms=1000)]
        track = LyricsTrack.from_lines(lines)
        assert track.cue_at(1000).line_index == 1

    def test_시간_정보가_없으면_빈_트랙(self):
        assert LyricsTrack.from_lines([_Line("a"), _Line("b")]).is_empty is True

    def test_정렬되지_않은_입력도_정렬된다(self):
        lines = [_Line("late", start_ms=9000), _Line("early", start_ms=1000)]
        track = LyricsTrack.from_lines(lines)
        assert track.index_at(1000) == 0
        assert track.cue_at(1000).original == "early"

    def test_오프셋을_함께_받는다(self):
        track = LyricsTrack.from_lines([_Line("a", start_ms=1000)], offset_ms=500)
        assert track.offset_ms == 500
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/unit/gui/test_lyrics_track.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gui.widgets.lyrics_overlay'`

- [ ] **Step 3: 구현**

Create `gui/widgets/lyrics_overlay.py`:

```python
"""가사 자막 — 현재 줄 판정 로직(``LyricsTrack``)과 렌더 위젯(``LyricsOverlay``).

두 책임을 한 파일에 두되 **클래스로 분리**한다. ``LyricsTrack``은 Qt에 의존하지 않는
순수 로직이라 QApplication 없이 단위 테스트할 수 있고, ``LyricsOverlay``는 그리기만
담당한다. 영상 위에 얹히므로 배경 없이 외곽선 텍스트로 그린다.
"""

from __future__ import annotations

import bisect
import logging
from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

# 오프셋 상한은 도메인 상수를 그대로 쓴다 — GUI도 저장 전에 같은 값으로 자르는데,
# 두 곳에 따로 적으면 어긋난다(gui → domain 방향이라 레이어 규칙에 맞다).
from domain.song.aggregates import MAX_LYRICS_OFFSET_MS

logger = logging.getLogger(__name__)

# 자막 색은 테마 토큰을 쓰지 않는다 — 영상 프레임 위에 얹히므로 앱 테마가 아니라
# '어떤 영상 위에서도 읽히는가'가 기준이다(의미·가독성 고정색, CLAUDE.md 색상 규칙 예외).
_TEXT_COLOR = QColor("#ffffff")
_TRANSLATION_COLOR = QColor("#e0e0e0")
_OUTLINE_COLOR = QColor("#000000")

# 한글 가독성이 좋은 산세리프 후보 — 설치된 첫 항목을 쓴다.
_FONT_CANDIDATES = (
    "Pretendard",
    "Pretendard Variable",
    "Malgun Gothic",
    "맑은 고딕",
    "Noto Sans KR",
    "Apple SD Gothic Neo",
)

_font_family_cache: str | None = None


def subtitle_font_family() -> str:
    """설치된 자막용 폰트 계열 이름을 고른다(첫 호출 시 1회 조회 후 캐시)."""
    global _font_family_cache
    if _font_family_cache is not None:
        return _font_family_cache
    try:
        installed = set(QFontDatabase.families())
    except Exception:
        logger.debug("폰트 목록 조회 실패 — 시스템 기본 폰트 사용")
        installed = set()
    _font_family_cache = next(
        (name for name in _FONT_CANDIDATES if name in installed), QFont().family()
    )
    return _font_family_cache


@dataclass(frozen=True, slots=True)
class LyricsCue:
    """자막 한 장 — 시각이 있는 가사 한 줄.

    ``line_index``는 원본 가사 목록(노래 탭이 그리는 줄들)에서의 인덱스로, 재생 중인
    줄을 탭에서 하이라이트할 때 쓴다.
    """

    start_ms: int
    original: str
    translation: str = ""
    line_index: int = -1


class LyricsTrack:
    """시각이 있는 가사 줄 모음 + 싱크 오프셋. **Qt 비의존 순수 로직.**

    현재 줄은 다음 줄이 시작하기 직전까지 유효하고, 마지막 줄은 끝까지 유효하다.
    첫 줄 시작 전에는 표시할 자막이 없다(None).
    """

    def __init__(self, cues: list[LyricsCue], offset_ms: int = 0) -> None:
        self._cues = sorted(cues, key=lambda c: c.start_ms)
        self._starts = [c.start_ms for c in self._cues]
        self._offset_ms = 0
        self.offset_ms = offset_ms   # 세터로 clamp 적용

    @classmethod
    def from_lines(cls, lines, offset_ms: int = 0) -> "LyricsTrack":
        """``start_ms``가 있는 줄만 골라 트랙을 만든다.

        ``lines``는 ``original``/``translation``/``start_ms`` 속성을 갖는 객체 목록
        (``LyricsLineDTO``). 구조적으로만 의존해 DTO를 import하지 않는다.
        """
        cues = [
            LyricsCue(
                start_ms=int(line.start_ms),
                original=line.original,
                translation=line.translation,
                line_index=idx,
            )
            for idx, line in enumerate(lines or [])
            if getattr(line, "start_ms", None) is not None
        ]
        return cls(cues, offset_ms=offset_ms)

    def __len__(self) -> int:
        return len(self._cues)

    @property
    def is_empty(self) -> bool:
        return not self._cues

    @property
    def offset_ms(self) -> int:
        return self._offset_ms

    @offset_ms.setter
    def offset_ms(self, value: int) -> None:
        self._offset_ms = max(
            -MAX_LYRICS_OFFSET_MS, min(MAX_LYRICS_OFFSET_MS, int(value))
        )

    def index_at(self, pos_ms: int) -> int | None:
        """재생 위치에 해당하는 줄 인덱스. 표시할 줄이 없으면 None."""
        if not self._cues:
            return None
        target = pos_ms - self._offset_ms
        # bisect_right - 1 = target 이하인 마지막 시작점
        idx = bisect.bisect_right(self._starts, target) - 1
        return idx if idx >= 0 else None

    def cue_at(self, pos_ms: int) -> LyricsCue | None:
        idx = self.index_at(pos_ms)
        return self._cues[idx] if idx is not None else None

    def cue(self, index: int) -> LyricsCue | None:
        return self._cues[index] if 0 <= index < len(self._cues) else None

    def start_of(self, index: int) -> int:
        """``index`` 줄이 실제로 뜨는 재생 위치(오프셋 적용, 음수는 0)."""
        if not (0 <= index < len(self._cues)):
            return 0
        return max(0, self._cues[index].start_ms + self._offset_ms)


class LyricsOverlay(QWidget):
    """영상 위에 얹는 자막 렌더 위젯.

    배경을 칠하지 않고 외곽선 텍스트만 그려 화면을 가리지 않는다. 마우스 이벤트는
    통과시켜 아래의 영상·컨트롤바 조작을 방해하지 않는다. 글자 크기는 위젯 높이에
    비례해 전체화면에서 자동으로 커진다.
    """

    _MIN_FONT_PX = 13
    _FONT_RATIO = 0.055          # 위젯 높이 대비 원문 글자 크기
    _TRANSLATION_RATIO = 0.85    # 원문 대비 번역 글자 크기
    _OUTLINE_RATIO = 0.14        # 글자 크기 대비 외곽선 두께
    _LINE_GAP = 4                # 원문/번역 줄 간격(px)
    _SIDE_MARGIN = 24            # 좌우 여백(px)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._original = ""
        self._translation = ""
        self._visible_text = True

    # ── 상태 ──────────────────────────────────────────────────────
    def set_cue(self, cue: LyricsCue | None) -> None:
        """표시할 자막을 바꾼다. 내용이 같으면 다시 그리지 않는다."""
        original = cue.original if cue else ""
        translation = cue.translation if cue else ""
        if original == self._original and translation == self._translation:
            return
        self._original = original
        self._translation = translation
        self.update()

    def set_text_visible(self, on: bool) -> None:
        """자막 on/off. ``QWidget.setVisible``과 구분하기 위해 이름을 분리했다."""
        if self._visible_text == on:
            return
        self._visible_text = on
        self.update()

    @property
    def current_text(self) -> tuple[str, str]:
        """(원문, 번역) — 테스트가 렌더 결과 대신 상태를 확인할 때 쓴다."""
        return self._original, self._translation

    # ── 렌더 ──────────────────────────────────────────────────────
    def _fonts(self) -> tuple[QFont, QFont]:
        px = max(self._MIN_FONT_PX, int(self.height() * self._FONT_RATIO))
        family = subtitle_font_family()
        main = QFont(family, weight=QFont.Weight.Bold)
        main.setPixelSize(px)
        sub = QFont(family)
        sub.setPixelSize(max(self._MIN_FONT_PX - 2, int(px * self._TRANSLATION_RATIO)))
        return main, sub

    def _wrap(self, text: str, metrics: QFontMetrics, max_w: int) -> list[str]:
        """폭에 맞춰 공백 단위로 줄바꿈한다(한 단어가 넘치면 그대로 둔다)."""
        if not text:
            return []
        if metrics.horizontalAdvance(text) <= max_w:
            return [text]
        out: list[str] = []
        line = ""
        for word in text.split(" "):
            candidate = f"{line} {word}".strip()
            if line and metrics.horizontalAdvance(candidate) > max_w:
                out.append(line)
                line = word
            else:
                line = candidate
        if line:
            out.append(line)
        return out

    def _draw_line(self, painter: QPainter, text: str, font: QFont,
                   color: QColor, center_y: int) -> None:
        metrics = QFontMetrics(font)
        x = (self.width() - metrics.horizontalAdvance(text)) / 2
        path = QPainterPath()
        path.addText(x, center_y, font, text)
        pen = QPen(_OUTLINE_COLOR)
        pen.setWidthF(max(2.0, font.pixelSize() * self._OUTLINE_RATIO))
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)          # 외곽선 먼저
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPath(path)          # 그 위에 글자 채움

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 시그니처)
        if not self._visible_text or not (self._original or self._translation):
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        main_font, sub_font = self._fonts()
        max_w = max(50, self.width() - self._SIDE_MARGIN * 2)
        main_metrics, sub_metrics = QFontMetrics(main_font), QFontMetrics(sub_font)

        rows: list[tuple[str, QFont, QColor, int]] = [
            (line, main_font, _TEXT_COLOR, main_metrics.height())
            for line in self._wrap(self._original, main_metrics, max_w)
        ]
        rows += [
            (line, sub_font, _TRANSLATION_COLOR, sub_metrics.height())
            for line in self._wrap(self._translation, sub_metrics, max_w)
        ]
        if not rows:
            return

        total_h = sum(h for *_, h in rows) + self._LINE_GAP * (len(rows) - 1)
        # 아래에서부터 쌓아 올린다 — 자막은 하단 정렬이 자연스럽다.
        y = self.height() - total_h
        for text, font, color, height in rows:
            baseline = int(y + QFontMetrics(font).ascent())
            self._draw_line(painter, text, font, color, baseline)
            y += height + self._LINE_GAP
        painter.end()
```

- [ ] **Step 4: 순수 로직 테스트 통과 확인**

Run: `pytest tests/unit/gui/test_lyrics_track.py -v`
Expected: PASS

`tests/unit/gui/__init__.py`가 없으면 빈 파일로 만든다.

- [ ] **Step 5: 렌더 테스트 작성**

Create `tests/gui/test_lyrics_overlay.py`:

```python
"""자막 오버레이 위젯 렌더 상태 검증.

픽셀을 검사하는 대신 (a) 상태가 올바르게 반영되는지 (b) paintEvent가 예외 없이
도는지를 본다 — 폰트·안티에일리어싱은 환경마다 달라 픽셀 비교가 불안정하다.
"""
from __future__ import annotations

import pytest
from PyQt6.QtGui import QPixmap, QPainter

from gui.widgets.lyrics_overlay import LyricsCue, LyricsOverlay, subtitle_font_family


@pytest.fixture
def overlay(qapp_instance):
    w = LyricsOverlay()
    w.resize(640, 200)
    return w


def _paint(widget) -> None:
    """오프스크린 렌더 — paintEvent가 예외 없이 완주하는지 확인한다."""
    pm = QPixmap(widget.size())
    pm.fill()
    painter = QPainter(pm)
    widget.render(painter)
    painter.end()


class TestState:
    def test_초기에는_빈_텍스트(self, overlay):
        assert overlay.current_text == ("", "")

    def test_set_cue가_원문과_번역을_반영한다(self, overlay):
        overlay.set_cue(LyricsCue(start_ms=0, original="hello", translation="안녕"))
        assert overlay.current_text == ("hello", "안녕")

    def test_None이면_비운다(self, overlay):
        overlay.set_cue(LyricsCue(start_ms=0, original="hello"))
        overlay.set_cue(None)
        assert overlay.current_text == ("", "")


class TestRender:
    def test_원문만_있어도_그려진다(self, overlay):
        overlay.set_cue(LyricsCue(start_ms=0, original="only original"))
        _paint(overlay)

    def test_원문과_번역을_함께_그린다(self, overlay):
        overlay.set_cue(
            LyricsCue(start_ms=0, original="I don't wanna be alone", translation="혼자이고 싶지 않아")
        )
        _paint(overlay)

    def test_긴_줄도_예외_없이_그려진다(self, overlay):
        overlay.set_cue(LyricsCue(start_ms=0, original="word " * 60, translation="단어 " * 60))
        _paint(overlay)

    def test_자막_끄면_그리지_않는다(self, overlay):
        overlay.set_cue(LyricsCue(start_ms=0, original="hidden"))
        overlay.set_text_visible(False)
        _paint(overlay)   # 예외 없이 즉시 반환

    def test_아주_작은_높이에서도_최소_글자크기를_지킨다(self, overlay):
        overlay.resize(320, 40)
        overlay.set_cue(LyricsCue(start_ms=0, original="tiny"))
        _paint(overlay)


class TestFont:
    def test_폰트_계열_이름을_반환한다(self, qapp_instance):
        assert isinstance(subtitle_font_family(), str)
        assert subtitle_font_family() != ""

    def test_두_번_불러도_같은_값(self, qapp_instance):
        assert subtitle_font_family() == subtitle_font_family()


class TestMouseTransparency:
    def test_마우스_이벤트를_통과시킨다(self, overlay):
        from PyQt6.QtCore import Qt

        assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
```

- [ ] **Step 6: 렌더 테스트 통과 확인**

Run: `pytest tests/gui/test_lyrics_overlay.py -v`
Expected: PASS

- [ ] **Step 7: 린트 + 전체**

Run: `ruff check gui/widgets/lyrics_overlay.py tests/ && pytest -q`
Expected: `All checks passed!` + 전체 PASS

- [ ] **Step 8: 커밋**

```bash
git add gui/widgets/lyrics_overlay.py tests/unit/gui/test_lyrics_track.py tests/gui/test_lyrics_overlay.py
git commit -m "feat: 가사 자막 위젯 — LyricsTrack(순수 로직) + LyricsOverlay(렌더)

- LyricsTrack은 Qt 비의존이라 QApplication 없이 경계값·오프셋을 테스트한다
  (이분 탐색으로 현재 줄 판정, 오프셋 ±30초 clamp)
- LyricsOverlay는 배경 없이 외곽선 텍스트로 그려 어떤 영상 위에서도 읽히게 한다
  (글자 크기는 위젯 높이 비례 → 전체화면에서 자동 확대)
- 폰트는 Pretendard→맑은 고딕→Noto Sans KR 순으로 설치된 것을 고른다"
```

---

### Task 6: 플레이어 배선 — 오버레이 3창 · 💬 버튼 · 단축키

**Files:**
- Modify: `gui/widgets/video_player.py`
  - `_ControlBar` 신호·버튼 (316-411, 413-443)
  - `_VideoArea.set_overlay_subtitle` / `_layout_children` (541-580)
  - `_PipWindow.__init__` / `_layout_children` (653-699)
  - `_FullscreenWindow.__init__` / `_position_bar` (743-780)
  - `InlinePlayer._setup` (868-929), `keyPressEvent` (1147-1182),
    `_on_position` (1377-1383), `_enter_fullscreen` (1226-1268),
    `_exit_fullscreen` (1270-1284), `_enter_pip` (1294-1338), `load`/`stop`
- Test: `tests/gui/test_subtitle_player.py`

**Interfaces:**
- Consumes: `LyricsTrack`, `LyricsCue`, `LyricsOverlay` (T5)
- Produces (Task 8이 사용):
  - `InlinePlayer.set_lyrics(track: LyricsTrack | None) -> None`
  - `InlinePlayer.subtitle_offset_changed = pyqtSignal(int)`
  - `InlinePlayer.current_line_changed = pyqtSignal(int)` — 원본 줄 인덱스, 없으면 `-1`
  - `_ControlBar.set_has_subtitle(bool)` · `set_subtitle_on(bool)` · `set_subtitle_offset_ms(int)`

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/gui/test_subtitle_player.py`:

```python
"""플레이어 자막 배선 검증 — 💬 버튼 활성 조건, 현재 줄 갱신, 오프셋 조작.

실제 미디어 없이 InlinePlayer의 자막 상태 API만 두드린다(재생은 하지 않는다).
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent

from gui.widgets.lyrics_overlay import LyricsCue, LyricsTrack
from gui.widgets.video_player import InlinePlayer


@pytest.fixture
def player(qapp_instance):
    p = InlinePlayer()
    p.resize(800, 450)
    yield p
    p.stop()
    p.deleteLater()


def _track() -> LyricsTrack:
    return LyricsTrack(
        [
            LyricsCue(start_ms=1000, original="one", translation="하나", line_index=0),
            LyricsCue(start_ms=5000, original="two", translation="둘", line_index=1),
        ]
    )


def _key(player, key: int) -> None:
    player.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


class TestSubtitleButtonEnablement:
    def test_가사가_없으면_비활성(self, player):
        assert player._bar._btn_cc.isEnabled() is False

    def test_싱크_가사를_주면_활성(self, player):
        player.set_lyrics(_track())
        assert player._bar._btn_cc.isEnabled() is True

    def test_빈_트랙은_비활성(self, player):
        player.set_lyrics(LyricsTrack([]))
        assert player._bar._btn_cc.isEnabled() is False

    def test_None을_주면_다시_비활성(self, player):
        player.set_lyrics(_track())
        player.set_lyrics(None)
        assert player._bar._btn_cc.isEnabled() is False


class TestCurrentLine:
    def test_재생_위치에_맞는_줄이_오버레이에_뜬다(self, player):
        player.set_lyrics(_track())
        player._apply_subtitle_position(1200)
        assert player._subtitle.current_text == ("one", "하나")
        player._apply_subtitle_position(6000)
        assert player._subtitle.current_text == ("two", "둘")

    def test_첫_줄_이전에는_비어_있다(self, player):
        player.set_lyrics(_track())
        player._apply_subtitle_position(500)
        assert player._subtitle.current_text == ("", "")

    def test_current_line_changed가_원본_줄_인덱스를_알린다(self, player):
        seen: list[int] = []
        player.current_line_changed.connect(seen.append)
        player.set_lyrics(_track())
        player._apply_subtitle_position(1200)
        player._apply_subtitle_position(6000)
        assert seen[-2:] == [0, 1]

    def test_같은_줄이면_신호를_반복하지_않는다(self, player):
        seen: list[int] = []
        player.set_lyrics(_track())
        player.current_line_changed.connect(seen.append)
        player._apply_subtitle_position(1200)
        player._apply_subtitle_position(1300)
        assert seen == [0]


class TestSubtitleToggle:
    def test_C_키로_자막을_끄고_켠다(self, player):
        player.set_lyrics(_track())
        player._apply_subtitle_position(1200)
        _key(player, Qt.Key.Key_C)
        assert player._subtitle_on is False
        _key(player, Qt.Key.Key_C)
        assert player._subtitle_on is True

    def test_가사가_없으면_C_키가_무시된다(self, player):
        _key(player, Qt.Key.Key_C)
        assert player._subtitle_on is True


class TestOffsetShortcuts:
    def test_대괄호_키로_오프셋을_조정한다(self, player):
        player.set_lyrics(_track())
        _key(player, Qt.Key.Key_BracketRight)
        assert player._track.offset_ms == 250
        _key(player, Qt.Key.Key_BracketLeft)
        _key(player, Qt.Key.Key_BracketLeft)
        assert player._track.offset_ms == -250

    def test_오프셋_변경이_신호로_나간다(self, player):
        seen: list[int] = []
        player.set_lyrics(_track())
        player.subtitle_offset_changed.connect(seen.append)
        _key(player, Qt.Key.Key_BracketRight)
        assert seen == [250]

    def test_가사가_없으면_오프셋_키가_무시된다(self, player):
        seen: list[int] = []
        player.subtitle_offset_changed.connect(seen.append)
        _key(player, Qt.Key.Key_BracketRight)
        assert seen == []

    def test_오프셋_조정이_표시_줄에_반영된다(self, player):
        player.set_lyrics(_track())
        player._apply_subtitle_position(1200)
        assert player._subtitle.current_text[0] == "one"
        player._nudge_subtitle_offset(2000)   # 자막을 2초 늦춤
        assert player._subtitle.current_text == ("", "")


class TestSyncHere:
    def test_현재_위치를_현재_줄에_맞춘다(self, player):
        player.set_lyrics(_track())
        # 재생 위치 3000ms에서 "지금 이 줄"을 맞추면 현재 줄(1000ms)이 3000ms로 이동
        player._sync_subtitle_here(3000)
        assert player._track.offset_ms == 2000

    def test_표시할_줄이_없으면_아무것도_하지_않는다(self, player):
        player.set_lyrics(_track())
        player._sync_subtitle_here(200)
        assert player._track.offset_ms == 0


class TestLoadResetsSubtitle:
    def test_load하면_자막이_초기화된다(self, player):
        player.set_lyrics(_track())
        player.load("https://youtu.be/other", [])
        assert player._track is None
        assert player._bar._btn_cc.isEnabled() is False
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/gui/test_subtitle_player.py -v`
Expected: FAIL — `AttributeError: '_ControlBar' object has no attribute '_btn_cc'`

- [ ] **Step 3: `_ControlBar`에 💬 버튼 추가**

Modify `gui/widgets/video_player.py`:

`_ControlBar` 신호 목록(현재 317-327행)에 추가:

```python
    # 자막(가사) — 좌클릭 토글, 우클릭 메뉴에서 싱크 조정
    subtitle_toggled       = pyqtSignal(bool)
    subtitle_offset_nudged = pyqtSignal(int)   # ±ms
    subtitle_sync_here     = pyqtSignal()      # 현재 재생 위치를 현재 줄에 맞춤
    subtitle_offset_reset  = pyqtSignal()
```

`__init__`의 `self._heights = None` 다음에 상태 추가:

```python
        self._has_subtitle = False
        self._subtitle_on = True
        self._subtitle_offset_ms = 0
```

`_setup`에서 `self._btn_dl` 생성 **앞**에 버튼을 만들고, 배치는 `_btn_dl` **앞**에 넣는다:

```python
        self._btn_cc = btn("💬", "가사 자막  (C)", self._on_cc_clicked)
        self._btn_cc.setEnabled(False)
        self._btn_cc.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._btn_cc.customContextMenuRequested.connect(
            lambda _pos: self._show_subtitle_menu()
        )
```

배치 부분(현재 406-410행)을 교체:

```python
        row.addWidget(self._quality_lbl)
        row.addWidget(self._btn_quality)
        row.addWidget(self._btn_cc)
        row.addWidget(self._btn_dl)
        row.addWidget(self._btn_pip)
        row.addWidget(self._btn_fs)
```

`set_quality` 다음에 자막 상태 헬퍼를 추가:

```python
    # ── 자막(가사) ─────────────────────────────────────────────────
    def set_has_subtitle(self, has: bool) -> None:
        """싱크 가사 유무 — 없으면 버튼을 비활성하고 이유를 툴팁으로 알린다."""
        self._has_subtitle = has
        self._btn_cc.setEnabled(has)
        self._btn_cc.setToolTip(
            "가사 자막  (C)" if has else "시간 정보가 있는 가사가 없습니다"
        )
        self._update_cc_look()

    def set_subtitle_on(self, on: bool) -> None:
        self._subtitle_on = on
        self._update_cc_look()

    def set_subtitle_offset_ms(self, ms: int) -> None:
        self._subtitle_offset_ms = int(ms)

    def _update_cc_look(self) -> None:
        # 꺼진 상태는 흐리게 — 아이콘 하나로 on/off를 구분한다.
        self._btn_cc.setText("💬" if (self._subtitle_on and self._has_subtitle) else "🗨")

    def _on_cc_clicked(self) -> None:
        if not self._has_subtitle:
            return
        self._subtitle_on = not self._subtitle_on
        self._update_cc_look()
        self.subtitle_toggled.emit(self._subtitle_on)

    def _show_subtitle_menu(self) -> None:
        if not self._has_subtitle:
            return
        menu = QMenu(self)
        sec = self._subtitle_offset_ms / 1000.0
        menu.addAction(f"싱크: {sec:+.2f}초").setEnabled(False)
        menu.addSeparator()
        menu.addAction("−0.25초  ( [ )", lambda: self.subtitle_offset_nudged.emit(-250))
        menu.addAction("+0.25초  ( ] )", lambda: self.subtitle_offset_nudged.emit(250))
        menu.addAction("현재 위치를 이 줄에 맞춤  ( \\ )", self.subtitle_sync_here.emit)
        menu.addSeparator()
        menu.addAction("초기화", self.subtitle_offset_reset.emit)
        menu.exec(self._btn_cc.mapToGlobal(self._btn_cc.rect().bottomLeft()))
```

`QMenu`가 이미 import 돼 있는지 확인한다 (`_show_quality_menu`가 쓰므로 있을 것).

- [ ] **Step 4: `_VideoArea`에 자막 오버레이 자리 추가**

Modify `_VideoArea` — `_bar` 옆에 `_subtitle`을 두고 컨트롤바 위에 배치:

`__init__`에 추가:

```python
        self._subtitle: QWidget | None = None
```

`set_overlay_bar` 다음에 추가:

```python
    def set_overlay_subtitle(self, widget: QWidget) -> None:
        self._subtitle = widget
        widget.setParent(self)
        self._layout_children()
```

`_layout_children`을 교체:

```python
    def _layout_children(self) -> None:
        # self.height() 대신 heightForWidth 를 직접 계산:
        # resizeEvent 안에서 setFixedHeight() 직후에는 self.height()가 이전 값을 반환하므로
        # 컨트롤바 Y 좌표가 위젯 바깥으로 밀리는 버그가 발생함.
        h = self.heightForWidth(self.width())
        self._stack.setGeometry(0, 0, self.width(), h)
        if self._subtitle is not None:
            # 컨트롤바 바로 위. 컨트롤바가 숨어 있을 때도 같은 자리를 써서 자막이
            # 오르내리며 흔들리지 않게 한다.
            sub_h = max(60, int(h * 0.28))
            self._subtitle.setGeometry(0, h - self._BAR_H - sub_h, self.width(), sub_h)
            self._subtitle.raise_()
        if self._bar is not None:
            self._bar.setGeometry(0, h - self._BAR_H, self.width(), self._BAR_H)
            self._bar.raise_()
```

- [ ] **Step 5: `_PipWindow` / `_FullscreenWindow`에 오버레이 추가**

Modify `_PipWindow.__init__` — `self.bar = _ControlBar(self)` **앞**에 추가:

```python
        self.subtitle = LyricsOverlay(self)
```

`_layout_children`에 자막 배치를 추가 (`self.bar.setGeometry(...)` **앞**):

```python
        sub_h = max(48, int(self.height() * 0.28))
        self.subtitle.setGeometry(0, self.height() - bh - sub_h, self.width(), sub_h)
        self.subtitle.raise_()
        self.subtitle.show()
```

Modify `_FullscreenWindow` — 동일하게 `self.subtitle = LyricsOverlay(self)`를 만들고
`_position_bar`에서 컨트롤바 위에 배치한다 (`_position_bar` 안, 바 배치 앞):

```python
        sub_h = max(72, int(self.height() * 0.24))
        self.subtitle.setGeometry(0, self.height() - bh - sub_h, self.width(), sub_h)
        self.subtitle.raise_()
        self.subtitle.show()
```

파일 상단 import에 추가:

```python
from gui.widgets.lyrics_overlay import LyricsCue, LyricsOverlay, LyricsTrack
```

두 창의 docstring에 한 줄 덧붙인다: **`subtitle`도 `bar`와 마찬가지로 외부(InlinePlayer)가
내용을 채워야 한다.**

- [ ] **Step 6: `InlinePlayer` 상태·API 추가**

Modify `InlinePlayer`:

신호 목록에 추가:

```python
    subtitle_offset_changed = pyqtSignal(int)   # 사용자가 싱크를 바꿈 → 저장 요청
    current_line_changed    = pyqtSignal(int)   # 원본 가사 줄 인덱스(없으면 -1)
```

클래스 상수에 추가:

```python
    _OFFSET_STEP_MS = 250   # [ / ] 한 번에 움직이는 폭
```

`__init__`의 `self._temp_stream_path = ""` 다음에 추가:

```python
        self._track: LyricsTrack | None = None
        self._subtitle_on = True
        self._current_line_index = -1
```

`_setup`에서 `self._video_area.set_overlay_bar(self._bar)` **앞**에 오버레이를 만든다:

```python
        self._subtitle = LyricsOverlay()
        self._video_area = _VideoArea(self._visual_stack)
        self._video_area.set_overlay_subtitle(self._subtitle)
        self._video_area.set_overlay_bar(self._bar)
```

(기존 `self._video_area = _VideoArea(...)` 줄은 위로 합쳐 중복 생성하지 않게 한다.)

컨트롤바 신호 배선에 추가:

```python
        self._bar.subtitle_toggled.connect(self.set_subtitle_enabled)
        self._bar.subtitle_offset_nudged.connect(self._nudge_subtitle_offset)
        self._bar.subtitle_sync_here.connect(
            lambda: self._sync_subtitle_here(self._player.position())
        )
        self._bar.subtitle_offset_reset.connect(self._reset_subtitle_offset)
```

공개/내부 메서드를 `position_ms` 프로퍼티 근처에 추가:

```python
    # ── 가사 자막 ──────────────────────────────────────────────────
    def set_lyrics(self, track: LyricsTrack | None) -> None:
        """표시할 싱크 가사를 설정한다. None/빈 트랙이면 자막 UI를 비활성한다."""
        self._track = track if (track is not None and not track.is_empty) else None
        has = self._track is not None
        self._current_line_index = -1
        for bar in self._all_bars():
            bar.set_has_subtitle(has)
            bar.set_subtitle_on(self._subtitle_on)
            bar.set_subtitle_offset_ms(self._track.offset_ms if has else 0)
        for overlay in self._all_subtitles():
            overlay.set_cue(None)
            overlay.set_text_visible(self._subtitle_on)
        if has:
            self._apply_subtitle_position(self._player.position())

    def set_subtitle_enabled(self, on: bool) -> None:
        self._subtitle_on = bool(on)
        for bar in self._all_bars():
            bar.set_subtitle_on(self._subtitle_on)
        for overlay in self._all_subtitles():
            overlay.set_text_visible(self._subtitle_on)

    def subtitle_offset_ms(self) -> int:
        return self._track.offset_ms if self._track else 0

    def _all_bars(self) -> list:
        """인라인 + 분리 창의 컨트롤바 — 상태를 팬아웃할 대상."""
        bars = [self._bar]
        if self._fs_win:
            bars.append(self._fs_win.bar)
        if self._pip_win:
            bars.append(self._pip_win.bar)
        return bars

    def _all_subtitles(self) -> list:
        overlays = [self._subtitle]
        if self._fs_win:
            overlays.append(self._fs_win.subtitle)
        if self._pip_win:
            overlays.append(self._pip_win.subtitle)
        return overlays

    def _apply_subtitle_position(self, pos_ms: int) -> None:
        """재생 위치에 맞춰 자막을 갱신한다. **줄이 바뀔 때만** 다시 그린다."""
        if self._track is None:
            return
        idx = self._track.index_at(pos_ms)
        line_index = self._track.cue(idx).line_index if idx is not None else -1
        if line_index == self._current_line_index:
            return
        self._current_line_index = line_index
        cue = self._track.cue(idx) if idx is not None else None
        for overlay in self._all_subtitles():
            overlay.set_cue(cue)
        self.current_line_changed.emit(line_index)

    def _set_subtitle_offset(self, ms: int) -> None:
        if self._track is None:
            return
        self._track.offset_ms = ms
        for bar in self._all_bars():
            bar.set_subtitle_offset_ms(self._track.offset_ms)
        # 오프셋이 바뀌면 현재 줄 판정이 달라지므로 강제로 다시 계산한다.
        self._current_line_index = -2
        self._apply_subtitle_position(self._player.position())
        self.subtitle_offset_changed.emit(self._track.offset_ms)

    def _nudge_subtitle_offset(self, delta_ms: int) -> None:
        if self._track is None:
            return
        self._set_subtitle_offset(self._track.offset_ms + int(delta_ms))

    def _sync_subtitle_here(self, pos_ms: int) -> None:
        """현재 재생 위치가 '지금 표시 중인 줄'의 시작이 되도록 오프셋을 맞춘다."""
        if self._track is None:
            return
        idx = self._track.index_at(pos_ms)
        if idx is None:
            return
        cue = self._track.cue(idx)
        self._set_subtitle_offset(pos_ms - cue.start_ms)

    def _reset_subtitle_offset(self) -> None:
        self._set_subtitle_offset(0)
```

`_current_line_index = -2`는 "다음 계산을 반드시 반영하라"는 센티넬이다 — `-1`(자막 없음)과
구분해야 오프셋을 늘려 자막이 사라지는 전이도 반영된다. 이 의도를 주석으로 남긴다.

- [ ] **Step 7: 위치 팬아웃 · 단축키 · load/stop 정리**

`_on_position`에 한 줄 추가:

```python
    def _on_position(self, pos: int) -> None:
        dur = self._player.duration()
        self._bar.update_position(pos, dur)
        if self._fs_win:
            self._fs_win.bar.update_position(pos, dur)
        if self._pip_win:
            self._pip_win.bar.update_position(pos, dur)
        self._apply_subtitle_position(pos)
```

`keyPressEvent`의 `elif key == Qt.Key.Key_M:` **앞**에 추가:

```python
        elif key == Qt.Key.Key_C:
            if self._track is not None:
                self.set_subtitle_enabled(not self._subtitle_on)
        elif key == Qt.Key.Key_BracketLeft:
            self._nudge_subtitle_offset(-self._OFFSET_STEP_MS)
        elif key == Qt.Key.Key_BracketRight:
            self._nudge_subtitle_offset(self._OFFSET_STEP_MS)
        elif key == Qt.Key.Key_Backslash:
            self._sync_subtitle_here(self._player.position())
```

`load(...)` 본문 시작 부분에 자막 초기화를 추가 (기존 상태 리셋 코드 근처):

```python
        self.set_lyrics(None)   # 이전 영상의 자막이 남지 않게 초기화
```

`stop()`에도 같은 초기화를 넣되, **`load` 직후 `set_song_info`가 자막을 다시 넣으므로
순서에 유의**한다. `stop()`은 재생만 멈추는 경우도 있으니 자막 트랙은 유지하고
현재 줄만 지운다:

```python
        self._current_line_index = -1
        for overlay in self._all_subtitles():
            overlay.set_cue(None)
```

- [ ] **Step 8: 분리 창 진입/이탈 시 자막 상태 반영**

`_enter_fullscreen`의 `bar.set_available_heights(...)` 다음에 추가:

```python
        has = self._track is not None
        bar.set_has_subtitle(has)
        bar.set_subtitle_on(self._subtitle_on)
        bar.set_subtitle_offset_ms(self._track.offset_ms if has else 0)
        bar.subtitle_toggled.connect(self.set_subtitle_enabled)
        bar.subtitle_offset_nudged.connect(self._nudge_subtitle_offset)
        bar.subtitle_sync_here.connect(
            lambda: self._sync_subtitle_here(self._player.position())
        )
        bar.subtitle_offset_reset.connect(self._reset_subtitle_offset)
        self._fs_win.subtitle.set_text_visible(self._subtitle_on)
        # 현재 줄을 새 창에도 1회 반영
        self._current_line_index = -2
        self._apply_subtitle_position(self._player.position())
```

`_enter_pip`에도 **동일한 블록**을 추가한다 (`self._pip_win.subtitle`, `self._pip_win` 사용).
코드가 같아 보여도 대상 창이 다르므로 그대로 반복해 쓴다 — 기존 컨트롤바 배선도 같은
방식이다.

`_exit_fullscreen` / `_exit_pip`에서는 창을 닫으며 신호가 함께 사라지므로 추가 해제가
필요 없다(기존 `durationChanged`만 명시 해제하는 것과 동일). 다만 창을 닫은 뒤
인라인 오버레이가 현재 줄을 유지하도록 두 함수 끝(`self.setFocus()` 앞)에 추가:

```python
        self._current_line_index = -2
        self._apply_subtitle_position(self._player.position())
```

- [ ] **Step 9: 테스트 통과 확인**

Run: `pytest tests/gui/test_subtitle_player.py -v`
Expected: PASS

- [ ] **Step 10: 기존 플레이어 테스트 회귀**

Run: `pytest tests/gui/ -v`
Expected: PASS — 특히 `test_quality_menu.py`(컨트롤바 버튼 구성 변경 영향)와 `test_smoke.py`

- [ ] **Step 11: 린트 + 전체**

Run: `ruff check gui/ && pytest -q`
Expected: `All checks passed!` + 전체 PASS

- [ ] **Step 12: 커밋**

```bash
git add gui/widgets/video_player.py tests/gui/test_subtitle_player.py
git commit -m "feat: 영상 위 가사 자막 + 싱크 조작(컨트롤바 💬·단축키)

- 인라인·전체화면·PiP 3창 모두 LyricsOverlay를 얹고 기존 컨트롤바 팬아웃 패턴으로 배선
- 줄 인덱스가 바뀔 때만 다시 그려 매 position 틱 repaint를 피함
- 💬 좌클릭 토글 / 우클릭 메뉴(±0.25초·이 줄에 맞춤·초기화), 싱크 가사 없으면 비활성
- 단축키 C(on/off) [ ] (±0.25초) \\(이 줄에 맞춤) — 기존 단축키와 충돌 없음"
```

---

### Task 7: 노래 탭 — 줄 하이라이트 · 클릭 seek · ⏱ 버튼

**Files:**
- Modify: `gui/panels/video_detail_panel.py`
  - `_SongTab` 신호 (713-719), `_build_ui` 가사 헤더 (782-815)
  - `_render_lyrics` (895-946), `_lyric_label` (948-955), `set_info`(860-899 주변)
- Test: `tests/gui/test_song_tab_sync.py`

**Interfaces:**
- Consumes: `SongInfoDTO.is_synced` · `LyricsLineDTO.start_ms` (T4)
- Produces (Task 8이 사용):
  - `_SongTab.set_current_line(index: int | None) -> None`
  - `_SongTab.lyrics_seek_requested = pyqtSignal(int)` — 절대 ms(오프셋 미적용, 원본 시각)
  - `_SongTab.synced_requested = pyqtSignal()`

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/gui/test_song_tab_sync.py`:

```python
"""노래 탭의 싱크 UI 검증 — ⏱ 버튼 노출 조건, 현재 줄 하이라이트, 클릭 seek.

행 컨테이너(_LyricRow)로 통일했기 때문에 하이라이트·클릭 대상이 명확해졌다.
이 테스트가 그 구조를 고정한다.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from application.song.dtos import LyricsLineDTO, SongInfoDTO
from gui.panels.video_detail_panel import _LyricRow, _SongTab


@pytest.fixture
def tab(qapp_instance):
    w = _SongTab()
    w.resize(400, 600)
    return w


def _dto(lines) -> SongInfoDTO:
    return SongInfoDTO(
        video_id=uuid4(), is_song=True, artist="가수", song_title="제목",
        lyrics_lines=tuple(lines),
    )


def _synced_dto() -> SongInfoDTO:
    return _dto(
        [
            LyricsLineDTO(original="one", translation="하나", start_ms=1000),
            LyricsLineDTO(original="two", translation="둘", start_ms=5000),
        ]
    )


def _plain_dto() -> SongInfoDTO:
    return _dto([LyricsLineDTO(original="a"), LyricsLineDTO(original="b")])


def _rows(tab) -> list:
    layout = tab._lyrics_layout
    return [
        layout.itemAt(i).widget()
        for i in range(layout.count())
        if isinstance(layout.itemAt(i).widget(), _LyricRow)
    ]


class TestRowContainers:
    def test_줄마다_행_위젯이_생긴다(self, tab):
        tab.set_info(_plain_dto())
        assert len(_rows(tab)) == 2

    def test_번역_병행_모드에서도_행_수는_같다(self, tab):
        tab.set_info(_synced_dto())
        assert len(_rows(tab)) == 2

    def test_오른쪽_배치_전환_후에도_행_수가_같다(self, tab):
        tab.set_info(_synced_dto())
        tab._toggle_lyrics_layout()
        assert len(_rows(tab)) == 2


class TestSyncedButton:
    def test_싱크_가사가_없으면_노출된다(self, tab):
        tab.set_info(_plain_dto())
        assert tab._synced_btn.isVisible() is True

    def test_싱크_가사가_있으면_숨긴다(self, tab):
        tab.set_info(_synced_dto())
        assert tab._synced_btn.isVisible() is False

    def test_클릭하면_신호가_나간다(self, tab):
        seen = []
        tab.synced_requested.connect(lambda: seen.append(True))
        tab.set_info(_plain_dto())
        tab._synced_btn.click()
        assert seen == [True]

    def test_스트리밍은_비활성(self, tab):
        tab.set_editable(False)
        tab.set_info(_plain_dto())
        assert tab._synced_btn.isEnabled() is False


class TestHighlight:
    def test_현재_줄만_강조된다(self, tab):
        tab.set_info(_synced_dto())
        tab.set_current_line(1)
        rows = _rows(tab)
        assert rows[0].is_current is False
        assert rows[1].is_current is True

    def test_None이면_강조를_해제한다(self, tab):
        tab.set_info(_synced_dto())
        tab.set_current_line(0)
        tab.set_current_line(None)
        assert all(not r.is_current for r in _rows(tab))

    def test_범위_밖_인덱스는_무시된다(self, tab):
        tab.set_info(_synced_dto())
        tab.set_current_line(99)   # 예외 없이 아무것도 강조하지 않는다
        assert all(not r.is_current for r in _rows(tab))

    def test_가사_재렌더_후_강조가_초기화된다(self, tab):
        tab.set_info(_synced_dto())
        tab.set_current_line(0)
        tab.set_info(_synced_dto())
        assert all(not r.is_current for r in _rows(tab))


class TestClickSeek:
    def test_시간_정보가_있는_줄은_클릭하면_seek_신호(self, tab):
        seen: list[int] = []
        tab.lyrics_seek_requested.connect(seen.append)
        tab.set_info(_synced_dto())
        _rows(tab)[1].clicked.emit()
        assert seen == [5000]

    def test_시간_정보가_없는_줄은_클릭해도_신호가_없다(self, tab):
        seen: list[int] = []
        tab.lyrics_seek_requested.connect(seen.append)
        tab.set_info(_plain_dto())
        _rows(tab)[0].clicked.emit()
        assert seen == []


class TestAutoScrollSuppression:
    def test_사용자_스크롤_중에는_자동_스크롤을_멈춘다(self, tab):
        tab.set_info(_synced_dto())
        tab._on_user_scroll()
        assert tab._autoscroll_suppressed() is True

    def test_기본값은_자동_스크롤_허용(self, tab):
        assert tab._autoscroll_suppressed() is False
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/gui/test_song_tab_sync.py -v`
Expected: FAIL — `ImportError: cannot import name '_LyricRow'`

- [ ] **Step 3: `_LyricRow` 추가**

Modify `gui/panels/video_detail_panel.py` — `_SongTab` 클래스 **앞**에 추가:

```python
class _LyricRow(QWidget):
    """가사 한 줄 컨테이너 — 하이라이트·클릭 대상.

    예전에는 원문/번역 라벨을 레이아웃에 낱개로 넣어 '줄'이라는 단위가 없었다.
    재생 위치를 따라 강조하고 클릭으로 seek 하려면 줄마다 위젯이 필요하다.
    """

    clicked = pyqtSignal()

    def __init__(self, line_index: int, seekable: bool, shaded: bool,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.line_index = line_index
        self.is_current = False
        self._seekable = seekable
        self._shaded = shaded
        if seekable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style()

    def set_current(self, on: bool) -> None:
        if self.is_current == on:
            return
        self.is_current = on
        self._apply_style()

    def _apply_style(self) -> None:
        tok = _t()
        if self.is_current:
            # 트리 선택 표현과 같은 어법 — accent 14% 틴트. 색은 테마 토큰에서 파생한다.
            color = QColor(tok.accent)
            bg = f"rgba({color.red()},{color.green()},{color.blue()},0.14)"
        elif self._shaded:
            bg = "rgba(127,127,127,0.09)"
        else:
            bg = "transparent"
        self.setStyleSheet(f"background:{bg}; border-radius:4px;")

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt 시그니처)
        if self._seekable and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
```

`QColor` import가 없으면 `from PyQt6.QtGui import QColor`를 추가한다.

- [ ] **Step 4: `_SongTab` 신호·⏱ 버튼 추가**

신호 목록에 추가:

```python
    synced_requested = pyqtSignal()          # 싱크(시간 정보) 가사 찾기
    lyrics_seek_requested = pyqtSignal(int)  # 가사 줄 클릭 → 그 줄 시작 ms
```

`__init__` 상태에 추가:

```python
        self._rows: list[_LyricRow] = []
        self._current_row: _LyricRow | None = None
        self._scroll_hold_until = 0.0   # 사용자 스크롤 후 자동 스크롤을 멈추는 시각(monotonic)
```

`_build_ui`의 `self._translate_btn` 추가 **다음**에 ⏱ 버튼을 넣는다:

```python
        # 싱크 가사 찾기 — 시간 정보가 없는 가사일 때만 노출(자막 기능의 전제).
        self._synced_btn = QPushButton("⏱")
        self._synced_btn.setFixedSize(26, 24)
        self._synced_btn.setToolTip("싱크(시간 정보) 가사 찾기 — 자막 표시에 필요합니다")
        self._synced_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._synced_btn.clicked.connect(self.synced_requested.emit)
        self._synced_btn.setVisible(False)
        lyr_header.addWidget(self._synced_btn)
```

`_lyrics_scroll` 생성 다음에 사용자 스크롤 감지를 배선한다:

```python
        self._lyrics_scroll.verticalScrollBar().sliderPressed.connect(self._on_user_scroll)
        self._lyrics_scroll.verticalScrollBar().actionTriggered.connect(
            lambda _a: self._on_user_scroll()
        )
```

`sliderMoved`/`valueChanged`가 아니라 `sliderPressed`·`actionTriggered`를 쓰는 이유를
주석으로 남긴다 — **`valueChanged`는 자동 스크롤 자신이 일으키는 변화까지 잡아
영구히 억제되기 때문**이다.

- [ ] **Step 5: `set_info`에서 ⏱ 노출 제어**

`set_info` 안, `self._translate_btn.setVisible(...)` 근처에 추가:

```python
        has_lyrics = bool(dto and dto.lyrics_lines)
        is_synced = bool(dto and dto.is_synced)
        # 싱크 가사가 이미 있으면 찾을 이유가 없다.
        self._synced_btn.setVisible(has_lyrics and not is_synced and self._editable)
        self._synced_btn.setEnabled(self._editable)
```

`set_editable`(현재 839행 근처)에도 추가:

```python
        self._synced_btn.setEnabled(editable)
```

- [ ] **Step 6: `_render_lyrics`를 행 컨테이너로 통일**

`_render_lyrics`를 교체 (빈 상태 처리는 유지):

```python
    def _render_lyrics(self, dto: SongInfoDTO | None) -> None:
        _clear_layout(self._lyrics_layout)
        self._rows = []
        self._current_row = None
        bilingual = bool(dto and dto.is_bilingual)
        # 번역 배치 전환 아이콘은 병행(번역 있는) 가사일 때만 노출
        self._layout_btn.setVisible(bilingual)
        if not dto or not dto.lyrics_lines:
            msg = (
                "가사 정보가 없습니다.\n'가사' 옆 ⟳ 버튼으로 조회하거나 더블클릭하여 직접 입력하세요."
                if (dto and dto.is_song)
                else "'노래로 표시'하면 영상 제목으로 정보를 채웁니다."
            )
            empty = QLabel(msg)
            empty.setStyleSheet(f"color:{_t().text_secondary}; padding:12px;")
            empty.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            self._lyrics_layout.addWidget(empty)
            self._lyrics_layout.addStretch()
            return
        tok = _t()
        side = self._side_by_side and bilingual
        content_idx = 0   # 오른쪽 배치 시 행 교대 음영용(빈 줄 제외)
        for idx, line in enumerate(dto.lyrics_lines):
            if not line.original.strip() and not line.translation.strip():
                spacer = QLabel(" ")
                spacer.setFixedHeight(8)
                self._lyrics_layout.addWidget(spacer)
                continue
            # 오른쪽 배치일 때만 교대 음영을 준다(원문 아래 배치는 두 줄이 한 덩어리라
            # 음영을 주면 오히려 경계가 헷갈린다).
            row = _LyricRow(
                line_index=idx,
                seekable=line.start_ms is not None,
                shaded=side and content_idx % 2 == 0,
            )
            if line.start_ms is not None:
                row.clicked.connect(
                    lambda ms=int(line.start_ms): self.lyrics_seek_requested.emit(ms)
                )
            if side:
                rl = QHBoxLayout(row)
                rl.setContentsMargins(6, 3, 6, 3)
                rl.setSpacing(12)
                orig = self._lyric_label(line.original or " ", tok.text_primary, 10)
                orig.setAlignment(Qt.AlignmentFlag.AlignTop)
                trans = self._lyric_label(line.translation or "", tok.text_secondary, 9)
                trans.setAlignment(Qt.AlignmentFlag.AlignTop)
                rl.addWidget(orig, 1)
                rl.addWidget(trans, 1)
            else:
                rl = QVBoxLayout(row)
                rl.setContentsMargins(6, 1, 6, 1)
                rl.setSpacing(0)
                rl.addWidget(self._lyric_label(line.original or " ", tok.text_primary, 10))
                if line.translation:
                    rl.addWidget(
                        self._lyric_label(line.translation, tok.text_secondary, 9)
                    )
            self._lyrics_layout.addWidget(row)
            self._rows.append(row)
            content_idx += 1
        self._lyrics_layout.addStretch()
```

- [ ] **Step 7: 하이라이트 · 자동 스크롤**

`_toggle_lyrics_layout` **앞**에 추가:

```python
    # ── 재생 연동 (현재 줄 강조·자동 스크롤) ──────────────────────
    _SCROLL_HOLD_SEC = 3.0   # 사용자가 직접 스크롤한 뒤 자동 스크롤을 멈추는 시간

    def _on_user_scroll(self) -> None:
        """사용자가 가사를 직접 훑는 중에는 화면을 끌고 가지 않는다."""
        self._scroll_hold_until = time.monotonic() + self._SCROLL_HOLD_SEC

    def _autoscroll_suppressed(self) -> bool:
        return time.monotonic() < self._scroll_hold_until

    def set_current_line(self, index: int | None) -> None:
        """재생 중인 가사 줄을 강조하고(필요하면) 보이도록 스크롤한다.

        ``index``는 ``SongInfoDTO.lyrics_lines`` 기준 인덱스다(빈 줄 때문에 화면 행
        순서와 다를 수 있어 ``_LyricRow.line_index``로 찾는다).
        """
        target = None
        if index is not None:
            target = next((r for r in self._rows if r.line_index == index), None)
        if target is self._current_row:
            return
        if self._current_row is not None:
            self._current_row.set_current(False)
        self._current_row = target
        if target is None:
            return
        target.set_current(True)
        if not self._autoscroll_suppressed():
            self._lyrics_scroll.ensureWidgetVisible(target, 0, target.height() * 2)
```

파일 상단 import에 `import time`을 추가한다.

- [ ] **Step 8: 테스트 통과 확인**

Run: `pytest tests/gui/test_song_tab_sync.py -v`
Expected: PASS

`test_싱크_가사가_없으면_노출된다`가 실패하면 `isVisible()`이 부모 표시 여부에 좌우된 것이다.
탭이 화면에 없으면 `isVisible()`은 항상 False다 — 테스트를 `isVisibleTo(tab)`로 바꾼다:

```python
        assert tab._synced_btn.isVisibleTo(tab) is True
```

세 개의 가시성 단언 모두 `isVisibleTo(tab)`로 통일한다.

- [ ] **Step 9: 회귀 + 린트**

Run: `pytest tests/gui/ -q && ruff check gui/`
Expected: 전체 PASS + `All checks passed!`

- [ ] **Step 10: 커밋**

```bash
git add gui/panels/video_detail_panel.py tests/gui/test_song_tab_sync.py
git commit -m "feat: 노래 탭 현재 줄 하이라이트·클릭 seek·싱크 가사 찾기(⏱)

- 가사를 줄마다 _LyricRow 컨테이너로 통일(예전엔 라벨을 낱개로 넣어 '줄' 단위가 없었다)
- 재생 위치에 맞춰 accent 틴트로 강조 + 자동 스크롤, 사용자가 직접 스크롤하면 3초 억제
- 시간 정보가 있는 줄만 클릭 seek 가능(커서로 구분)
- 싱크 가사가 없을 때만 ⏱ 버튼 노출"
```

---

### Task 8: 뷰모델 · 패널 배선

**Files:**
- Modify: `gui/view_models/song_vm.py` (신호·메서드 추가, 생성자 인자 추가)
- Modify: `gui/panels/video_detail_panel.py` (신호 추가, `set_song_info`, 배선)
- Modify: `gui/panels/library_panel.py:4260-4275` (VM ↔ 패널 연결)
- Modify: `main.py` (composition root — `SetLyricsOffsetHandler` 주입)
- Test: `tests/gui/test_subtitle_wiring.py`

**Interfaces:**
- Consumes: `SetLyricsOffsetHandler`·`FetchSongInfoCommand.synced_only` (T4),
  `LyricsTrack` (T5), `InlinePlayer.set_lyrics`/`subtitle_offset_changed`/
  `current_line_changed` (T6), `_SongTab.set_current_line`/`lyrics_seek_requested`/
  `synced_requested` (T7)
- Produces:
  - `SongViewModel.fetch_synced_lyrics(video_id: UUID) -> None`
  - `SongViewModel.set_lyrics_offset(video_id: UUID, offset_ms: int) -> None`
  - `VideoDetailWidget.song_synced_requested = pyqtSignal(object)`
  - `VideoDetailWidget.song_offset_saved = pyqtSignal(object, int)`

- [ ] **Step 1: 실패하는 테스트 작성**

Create `tests/gui/test_subtitle_wiring.py`:

```python
"""뷰모델·패널 배선 검증 — 싱크 가사 조회 요청, 오프셋 디바운스 저장.

DB·네트워크 없이 핸들러를 목으로 대체해 '무엇이 호출되는가'만 본다.
"""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from application.song.dtos import LyricsLineDTO, SongInfoDTO
from gui.view_models.song_vm import SongViewModel


def _vm(qapp_instance, **overrides) -> SongViewModel:
    kwargs = dict(
        get_song_info=MagicMock(**{"handle.return_value": None}),
        fetch_song=MagicMock(),
        set_flag=MagicMock(),
        update_field=MagicMock(),
        update_lyrics=MagicMock(),
        translate_lyrics=MagicMock(),
        set_lyrics_offset=MagicMock(),
        list_sources=MagicMock(**{"handle.return_value": []}),
        add_source=MagicMock(),
        update_source=MagicMock(),
        delete_source=MagicMock(),
        reorder_sources=MagicMock(),
    )
    kwargs.update(overrides)
    return SongViewModel(**kwargs)


class TestFetchSyncedLyrics:
    def test_synced_only_커맨드로_조회한다(self, qapp_instance):
        vm = _vm(qapp_instance)
        video_id = uuid4()
        vm.fetch_synced_lyrics(video_id)
        # 워커가 끝날 때까지 기다린다(짧은 목 호출)
        for worker in list(vm._workers):
            worker.wait(3000)
        cmd = vm._fetch.handle.call_args[0][0]
        assert cmd.synced_only is True
        assert cmd.force is True
        assert cmd.fetch_lyrics is True
        assert cmd.video_id == video_id

    def test_같은_영상_중복_조회를_막는다(self, qapp_instance):
        vm = _vm(qapp_instance)
        video_id = uuid4()
        vm._in_flight.add(video_id)
        vm.fetch_synced_lyrics(video_id)
        assert vm._fetch.handle.called is False


class TestSetLyricsOffset:
    def test_핸들러에_오프셋을_넘긴다(self, qapp_instance):
        handler = MagicMock()
        vm = _vm(qapp_instance, set_lyrics_offset=handler)
        video_id = uuid4()
        vm.set_lyrics_offset(video_id, 1500)
        cmd = handler.handle.call_args[0][0]
        assert cmd.video_id == video_id
        assert cmd.offset_ms == 1500

    def test_핸들러_예외는_error_occurred로_보고된다(self, qapp_instance):
        handler = MagicMock()
        handler.handle.side_effect = RuntimeError("실패")
        vm = _vm(qapp_instance, set_lyrics_offset=handler)
        seen: list[str] = []
        vm.error_occurred.connect(seen.append)
        vm.set_lyrics_offset(uuid4(), 100)
        assert seen and "실패" in seen[0]

    def test_핸들러가_없으면_조용히_넘어간다(self, qapp_instance):
        vm = _vm(qapp_instance, set_lyrics_offset=None)
        vm.set_lyrics_offset(uuid4(), 100)   # 예외가 나면 안 된다


class TestDetailWidgetTrack:
    def test_싱크_가사를_주면_플레이어에_트랙이_실린다(self, qapp_instance):
        from gui.panels.video_detail_panel import VideoDetailWidget

        widget = VideoDetailWidget()
        dto = SongInfoDTO(
            video_id=uuid4(), is_song=True,
            lyrics_lines=(
                LyricsLineDTO(original="a", translation="가", start_ms=1000),
                LyricsLineDTO(original="b", start_ms=3000),
            ),
            lyrics_offset_ms=750,
        )
        widget.set_song_info(dto)
        assert widget._player._track is not None
        assert widget._player._track.offset_ms == 750
        assert len(widget._player._track) == 2
        widget.deleteLater()

    def test_시간_정보가_없으면_트랙이_없다(self, qapp_instance):
        from gui.panels.video_detail_panel import VideoDetailWidget

        widget = VideoDetailWidget()
        dto = SongInfoDTO(
            video_id=uuid4(), is_song=True,
            lyrics_lines=(LyricsLineDTO(original="a"),),
        )
        widget.set_song_info(dto)
        assert widget._player._track is None
        widget.deleteLater()

    def test_None_dto도_안전하다(self, qapp_instance):
        from gui.panels.video_detail_panel import VideoDetailWidget

        widget = VideoDetailWidget()
        widget.set_song_info(None)
        assert widget._player._track is None
        widget.deleteLater()
```

`VideoDetailWidget`는 `gui/panels/video_detail_panel.py:997`에 정의돼 있다(`_SongTab`을
품는 상위 위젯). 신호·핸들러는 이 클래스에 추가한다.

- [ ] **Step 2: 테스트 실패 확인**

Run: `pytest tests/gui/test_subtitle_wiring.py -v`
Expected: FAIL — `TypeError: SongViewModel.__init__() got an unexpected keyword argument 'set_lyrics_offset'`

- [ ] **Step 3: `SongViewModel` 확장**

Modify `gui/view_models/song_vm.py`:

import에 추가:

```python
from application.song.commands import (
    ...
    SetLyricsOffsetCommand,
    SetLyricsOffsetHandler,
    ...
)
```

생성자 인자에 추가 (`translate_lyrics` 다음, 기본값 `None`으로 두어 기존 호출부가 깨지지 않게):

```python
        translate_lyrics: TranslateSongLyricsHandler,
        set_lyrics_offset: SetLyricsOffsetHandler | None = None,
```

본문에 `self._set_offset = set_lyrics_offset` 추가.

`translate_lyrics` 메서드 다음에 추가:

```python
    def fetch_synced_lyrics(self, video_id: UUID) -> None:
        """'싱크 가사 찾기' — 시간 정보가 있는 가사만 채택해 교체한다.

        전 출처가 실패하면 기존 가사는 그대로 남는다(핸들러 계약).
        """
        self._current = video_id
        self._start_fetch(
            FetchSongInfoCommand(
                video_id=video_id, force=True, fetch_lyrics=True, synced_only=True
            )
        )

    def set_lyrics_offset(self, video_id: UUID, offset_ms: int) -> None:
        """자막 싱크 보정값을 저장한다(짧은 DB 쓰기라 워커 없이 동기 실행)."""
        if self._set_offset is None:
            logger.debug("오프셋 핸들러 미주입 — 저장 생략")
            return
        try:
            self._set_offset.handle(
                SetLyricsOffsetCommand(video_id=video_id, offset_ms=int(offset_ms))
            )
        except Exception as exc:
            logger.exception("자막 오프셋 저장 실패: %s", video_id)
            self.error_occurred.emit(str(exc))
```

오프셋 저장 후 `song_info_changed`를 **방출하지 않는다** — 방출하면 `set_song_info`가
트랙을 새로 만들어 사용자가 조정 중인 값이 되돌아가는 왕복이 생긴다. 이 이유를 주석으로 남긴다.

- [ ] **Step 4: `VideoDetailWidget` 신호·배선**

Modify `gui/panels/video_detail_panel.py`:

import에 추가:

```python
from gui.widgets.lyrics_overlay import LyricsTrack
```

신호 목록(1018-1024행 근처)에 추가:

```python
    song_synced_requested       = pyqtSignal(object)        # video_id — 싱크 가사 찾기
    song_offset_saved           = pyqtSignal(object, int)   # (video_id, offset_ms)
```

`__init__`에 디바운스 타이머 추가:

```python
        # 단축키 연타마다 DB에 쓰지 않도록 오프셋 저장을 묶는다.
        self._offset_timer = QTimer(self)
        self._offset_timer.setSingleShot(True)
        self._offset_timer.setInterval(500)
        self._offset_timer.timeout.connect(self._flush_offset)
        self._pending_offset: int | None = None
```

`_song_tab` 신호 배선(1246행 근처)에 추가:

```python
        self._song_tab.synced_requested.connect(self._on_song_synced)
        self._song_tab.lyrics_seek_requested.connect(self._on_lyrics_seek)
```

플레이어 배선(1100행 근처)에 추가:

```python
        self._player.current_line_changed.connect(self._on_current_line_changed)
        self._player.subtitle_offset_changed.connect(self._on_subtitle_offset_changed)
```

`set_song_info`를 교체:

```python
    def set_song_info(self, dto) -> None:
        """SongViewModel이 로드/갱신한 노래 정보를 노래 탭과 플레이어 자막에 반영한다."""
        self._song_tab.set_info(dto)
        # 스트리밍은 안정적 video_id가 없어 편집·자막 대상이 아니다.
        if dto is None or self._streaming or not dto.is_synced:
            self._player.set_lyrics(None)
            return
        self._player.set_lyrics(
            LyricsTrack.from_lines(dto.lyrics_lines, offset_ms=dto.lyrics_offset_ms)
        )
```

핸들러들을 `_on_song_flag_toggled` 근처에 추가:

```python
    def _on_song_synced(self) -> None:
        if self._detail is not None and not self._streaming:
            self.song_synced_requested.emit(self._detail.id)

    def _on_lyrics_seek(self, start_ms: int) -> None:
        """가사 줄 클릭 → 그 줄이 실제로 뜨는 위치로 이동(오프셋 반영)."""
        self._player.seek_to_ms(max(0, start_ms + self._player.subtitle_offset_ms()))

    def _on_current_line_changed(self, line_index: int) -> None:
        self._song_tab.set_current_line(line_index if line_index >= 0 else None)

    def _on_subtitle_offset_changed(self, offset_ms: int) -> None:
        self._pending_offset = offset_ms
        self._offset_timer.start()

    def _flush_offset(self) -> None:
        if self._pending_offset is None or self._detail is None or self._streaming:
            self._pending_offset = None
            return
        self.song_offset_saved.emit(self._detail.id, self._pending_offset)
        self._pending_offset = None
```

- [ ] **Step 5: `LibraryPanel` 연결**

Modify `gui/panels/library_panel.py` — 4275행 근처(`song_flag_toggled` 연결 다음)에 추가:

```python
            self._detail_widget.song_synced_requested.connect(
                self._song_vm.fetch_synced_lyrics
            )
            self._detail_widget.song_offset_saved.connect(self._song_vm.set_lyrics_offset)
```

- [ ] **Step 6: composition root 주입**

Modify `main.py` — `SongViewModel(...)`은 **472행**에서 만들어진다. `translate_lyrics=...`
(478행) 다음 줄에 추가:

```python
        set_lyrics_offset=SetLyricsOffsetHandler(song_repo, event_bus),
```

`SetLyricsOffsetHandler`를 `application.song.commands` import 목록에 추가한다.
`song_repo`·`event_bus`는 그 자리에서 이미 쓰이는 변수명이다(475행 `SetSongFlagHandler(song_repo, event_bus)` 참조).

- [ ] **Step 7: 테스트 통과 확인**

Run: `pytest tests/gui/test_subtitle_wiring.py -v`
Expected: PASS

- [ ] **Step 8: 전체 회귀 + 린트**

Run: `pytest -q && ruff check .`
Expected: 전체 PASS + `All checks passed!`

- [ ] **Step 9: 커밋**

```bash
git add gui/view_models/song_vm.py gui/panels/ main.py tests/gui/test_subtitle_wiring.py
git commit -m "feat: 자막 싱크 뷰모델·패널 배선

- SongViewModel.fetch_synced_lyrics(synced_only) / set_lyrics_offset
- 상세 패널이 SongInfoDTO → LyricsTrack을 만들어 플레이어에 주입
- 플레이어 current_line_changed → 노래 탭 하이라이트, 탭 줄 클릭 → 플레이어 seek
- 오프셋 저장은 500ms 디바운스(단축키 연타마다 DB에 쓰지 않게)"
```

---

### Task 9: 문서 갱신

**Files:**
- Modify: `CLAUDE.md`
- Modify: `planning/youtube_content_manager_prd.md`
- Modify: `planning/ddd_design.md`

**Interfaces:**
- Consumes: 앞선 전 태스크의 결과
- Produces: 없음 (문서)

- [ ] **Step 1: CLAUDE.md 아키텍처 트리 갱신**

`gui/widgets/` 항목에 추가:

```
│   │   └── lyrics_overlay.py        # 가사 자막 — `LyricsTrack`(Qt 비의존 순수 로직: 이분 탐색 현재 줄 판정·오프셋 ±30초 clamp) + `LyricsOverlay(QWidget)`(배경 없이 QPainterPath 외곽선 텍스트, 글자 크기는 위젯 높이 비례라 전체화면에서 자동 확대). 폰트는 Pretendard→맑은 고딕→Noto Sans KR 순으로 설치된 것을 고름(`subtitle_font_family`). **자막 색(흰 글자/검은 외곽선)은 테마 토큰을 쓰지 않는 의도적 예외** — 앱 테마가 아니라 '어떤 영상 프레임 위에서도 읽히는가'가 기준
```

`domain/song/` 항목에 `value_objects.py`·`entities.py` 설명을 갱신하고,
`infrastructure/song/` 항목에 추가:

```
│   │   └── lrc.py                   # LRC(가사 타이밍) 파서 — `parse_lrc(text) -> [(시작ms|None, 가사)]`. 다중 타임스탬프 전개·`[offset:]` 반영·메타 태그 제거. 순수 함수라 단위 테스트로 규칙을 고정
```

`video_player.py`·`video_detail_panel.py` 설명에 자막 관련 문장을 덧붙인다.

- [ ] **Step 2: Key Design Decisions에 항목 추가**

`- **노래 정보(song 컨텍스트)**` 항목 **다음**에 새 항목을 넣는다:

```markdown
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
  렌더는 **`LyricsTrack`(순수 로직)과 `LyricsOverlay`(그리기)로 분리**해 경계값·오프셋
  로직을 QApplication 없이 테스트한다. 오버레이는 인라인·전체화면·PiP **3창 모두**에
  얹히며 기존 컨트롤바 팬아웃 패턴을 그대로 따른다 — **`bar`처럼 `subtitle`도 외부
  (InlinePlayer)가 내용을 채워야 한다.** 현재 줄 인덱스가 바뀔 때만 다시 그려 매 position
  틱 repaint를 피한다. 노래 탭은 재생에 맞춰 현재 줄을 accent 틴트로 강조하고 자동
  스크롤하되 **사용자가 직접 스크롤하면 3초간 멈춘다**(`valueChanged`가 아니라
  `sliderPressed`/`actionTriggered`를 듣는다 — `valueChanged`는 자동 스크롤 자신의 변화까지
  잡아 영구 억제된다). 가사를 손으로 편집하면 **줄 수가 같을 때만 기존 타이밍을 유지**한다
  (오탈자 수정으로 싱크가 날아가지 않게, 줄 구성이 바뀌면 신뢰할 수 없어 폐기).
```

- [ ] **Step 3: 색상 규칙 예외 문서화**

`## 색상 규칙 (mandatory)`의 예외 문단에 자막을 추가:

```markdown
- 예외는 **의미·브랜드 색**뿐이다: `_BADGE_EMPTY_BG`(영상 없음 경고), `_YT_BRAND_RED`(YouTube),
  영상 레터박스 검정, **자막 오버레이의 흰 글자·검은 외곽선**(영상 프레임 위 가독성이
  기준이라 앱 테마와 무관). 이유를 주석으로 남긴다.
```

- [ ] **Step 4: PRD 갱신**

`planning/youtube_content_manager_prd.md`에 요구사항 항목을 추가한다 (기존 노래/가사
섹션 근처):

```markdown
### 가사 자막

- 노래 영상 재생 중 가사를 영상 위 자막으로 표시한다(원문 + 한글 번역 병행).
- **시간 정보가 있는 가사에 한해서만** 자막·싱크 기능이 활성화된다. 시간 정보는
  LRCLIB의 싱크 가사에서만 얻을 수 있으며, 없을 경우 '싱크 가사 찾기'로 재탐색한다.
- 가사와 영상의 어긋남은 **시작 오프셋 하나**로 보정한다(±30초). 배속·구간별 보정은
  범위 밖이다.
- 자막은 어떤 영상 배경에서도 읽히도록 외곽선 텍스트로 그리고, 전체화면에서 글자가
  커진다. 번역은 원문보다 한 단계 작게 표시한다.
- 노래 탭의 가사 목록은 재생에 맞춰 현재 줄을 강조하고, 줄을 클릭하면 그 시점으로 이동한다.
```

- [ ] **Step 5: DDD 설계 문서 갱신**

`planning/ddd_design.md`의 song 컨텍스트 절에 반영:

```markdown
- `LyricsLine`(VO): `original`, `translation`, **`start_ms: int | None`** — 줄 시작 시각.
  `None`이면 시간 정보 없음.
- `SongInfo`(Entity): **`lyrics_offset_ms: int`** — 영상별 자막 싱크 보정값(±30초).
  `is_synced` 프로퍼티는 시각이 있는 줄이 1개 이상인지 알려주며 자막 기능의 활성 조건이다.
- `SongInfoAggregate.set_lyrics_offset(ms)` — 오프셋 변경(clamp 포함)은 애그리게이트를 통해서만.
  `edit_lyrics`는 줄 수가 같을 때 기존 타이밍을 유지한다.
```

- [ ] **Step 6: 커밋**

```bash
git add CLAUDE.md planning/
git commit -m "docs: 가사 자막·싱크 기능 문서화

- CLAUDE.md: gui/infrastructure 파일 맵에 lyrics_overlay.py·lrc.py 추가,
  Key Design Decisions에 '가사 자막 표시·싱크 조정' 항목, 색상 규칙 예외 명시
- PRD: 가사 자막 요구사항(시간 정보 있는 가사 한정·시작 오프셋만·시인성)
- ddd_design: LyricsLine.start_ms, SongInfo.lyrics_offset_ms, set_lyrics_offset"
```

---

### Task 10: 실행 검증

**Files:** 없음 (검증만)

**Interfaces:**
- Consumes: Task 1~9 전부
- Produces: 없음

- [ ] **Step 1: 전체 테스트 + 린트**

Run: `pytest -q && ruff check . && ruff format --check .`
Expected: 전체 PASS

`ruff format --check`가 실패하면 `ruff format .`으로 정리 후 재실행한다.

- [ ] **Step 2: 마이그레이션 회귀 확인 (기존 DB)**

기존 DB에 새 컬럼이 붙는지 실제로 확인한다:

```bash
python -c "
from pathlib import Path
import sqlite3, tempfile
from infrastructure.persistence.database import Database
d = Path(tempfile.mkdtemp()) / 'old.db'
# 구 스키마로 song_info를 만든 뒤 initialize()가 컬럼을 보강하는지 본다
conn = sqlite3.connect(d)
conn.execute('CREATE TABLE song_info (video_id TEXT PRIMARY KEY, is_song INTEGER NOT NULL DEFAULT 0, artist TEXT NOT NULL DEFAULT \'\', album TEXT NOT NULL DEFAULT \'\', song_title TEXT NOT NULL DEFAULT \'\', release_year TEXT NOT NULL DEFAULT \'\', lyrics_json TEXT NOT NULL DEFAULT \'[]\', lyrics_language TEXT NOT NULL DEFAULT \'\', source_name TEXT NOT NULL DEFAULT \'\', source_url TEXT NOT NULL DEFAULT \'\', manual_fields TEXT NOT NULL DEFAULT \'[]\', updated_at TEXT NOT NULL)')
conn.commit(); conn.close()
Database(path=d).initialize()
conn = sqlite3.connect(d)
cols = [r[1] for r in conn.execute('PRAGMA table_info(song_info)')]
print('lyrics_offset_ms' in cols, cols)
"
```

Expected: `True [...]` — 컬럼 목록에 `lyrics_offset_ms`가 있어야 한다

- [ ] **Step 3: `/verify` 실행**

GUI를 실제로 띄워 확인한다. CLAUDE.md의 GUI 변경 규칙에 따른 필수 단계다.

`/verify` 스킬을 호출하고 아래를 확인한다:

1. 앱이 오류 없이 실행되고 라이브러리 화면이 뜬다
2. 노래로 표시된 영상 상세를 열면 노래 탭이 정상 표시된다
3. 가사가 있고 시간 정보가 없으면 컨트롤바 `💬`가 **비활성**이고 노래 탭에 `⏱`가 보인다
4. `⏱`로 싱크 가사를 찾으면(LRCLIB에 있는 곡) `💬`가 활성되고 재생 시 자막이 뜬다
5. `[` / `]`로 자막이 앞뒤로 밀리고, 노래 탭 현재 줄 강조가 따라 움직인다
6. 전체화면(`F`)·PiP(`P`)에서도 자막이 보이고 글자가 화면 크기에 맞게 커진다
7. 노래 탭 가사 줄을 클릭하면 그 시점으로 이동한다
8. 앱을 껐다 켜도 조정한 오프셋이 유지된다

- [ ] **Step 4: 실패 항목 수정**

`/verify`에서 문제가 나오면 해당 Task로 돌아가 고치고, 회귀 테스트를 추가한 뒤 다시 검증한다.
**검증 없이 완료를 보고하지 않는다.**

- [ ] **Step 5: 최종 커밋 (수정이 있었다면)**

```bash
git add -A
git commit -m "fix: /verify에서 발견한 자막 동작 문제 수정"
```

---

## Self-Review

**1. 스펙 커버리지**

| 스펙 요구사항 | 담당 Task |
|---|---|
| LRC 파싱 (`parse_lrc`, 다중 타임스탬프·메타·offset) | T1 |
| `LyricsLine.start_ms` | T2 |
| `SongInfo.lyrics_offset_ms` · `is_synced` | T2 |
| `set_lyrics_offset` (±30초 clamp) | T2 |
| `edit_lyrics` 타이밍 보존 규칙 | T2 |
| `lyrics_json` `"s"` 키 + 하위호환 | T2 |
| `song_info.lyrics_offset_ms` 컬럼 + 마이그레이션 | T2, T10 검증 |
| sync 캡처 자동 편입 | T2 (필드 diff 캡처라 코드 변경 불필요, T2 Step 9에서 회귀 확인) |
| `LyricsResult.timings` | T3 |
| LRCLIB synced 우선 채택 | T3 |
| `synced_only` 조회 | T4 |
| `SetLyricsOffsetCommand/Handler` | T4 |
| DTO 확장 (`start_ms`·`lyrics_offset_ms`·`is_synced`) | T4 |
| `LyricsTrack` (이분 탐색·오프셋) | T5 |
| `LyricsOverlay` (외곽선·높이 비례 폰트·폰트 후보) | T5 |
| `_VideoArea.set_overlay_subtitle` | T6 |
| 전체화면·PiP 오버레이 | T6 |
| `💬` 버튼 + 활성 조건 | T6 |
| 단축키 `C` `[` `]` `\` | T6 |
| 노래 탭 행 컨테이너 통일 | T7 |
| 현재 줄 하이라이트 · 자동 스크롤 억제 | T7 |
| 줄 클릭 seek | T7 |
| `⏱` 싱크 가사 찾기 버튼 | T7 |
| `SongViewModel` 메서드 2종 | T8 |
| 패널 배선 · 500ms 디바운스 | T8 |
| composition root 주입 | T8 |
| 오류 처리 (파싱 실패·조회 실패·저장 실패·폰트 부재) | T1·T3·T4·T5·T8 각 구현에 포함 |
| 테스트 (unit/integration/gui) | 각 Task Step 1 |
| 문서 갱신 | T9 |
| `/verify` | T10 |

누락 없음.

**2. 플레이스홀더 스캔**

"TBD"·"적절히 처리"·"비슷하게" 없음. 모든 코드 스텝에 실제 코드 블록이 있다.
계획 작성 중 불확실했던 두 지점(`VideoDetailWidget` 클래스명, `main.py`의 `SongViewModel`
생성 위치·변수명)은 실제 코드로 확인해 행 번호까지 확정했다 —
`video_detail_panel.py:997`, `main.py:472`(`song_repo`·`event_bus`).

**3. 타입 일관성**

- `parse_lrc -> list[tuple[int | None, str]]` — T1 정의, T3 사용 ✓
- `LyricsResult.timings: list[int | None]` — T3 정의, T4 사용 ✓
- `LyricsLine(original, translation, start_ms)` — T2 정의, T3·T4·T7 사용 ✓
- `LyricsCue(start_ms, original, translation, line_index)` — T5 정의, T6 사용 ✓
- `LyricsTrack.from_lines(lines, offset_ms)` — T5 정의, T8 사용 ✓
- `InlinePlayer.set_lyrics/subtitle_offset_ms()/current_line_changed/subtitle_offset_changed`
  — T6 정의, T8 사용 ✓
- `_SongTab.set_current_line/lyrics_seek_requested/synced_requested` — T7 정의, T8 사용 ✓
- `_ControlBar.set_has_subtitle/set_subtitle_on/set_subtitle_offset_ms` — T6 정의, T6 내부 사용 ✓
- `SongViewModel.fetch_synced_lyrics/set_lyrics_offset` — T8 정의, T8 배선 ✓

**실행 전 조율(사용자 결정)**

1. 오프셋 상한은 처음에 domain·gui 양쪽에 상수를 따로 두려 했으나, 값이 어긋나는 사고를
   막기 위해 **domain의 공개 상수 `MAX_LYRICS_OFFSET_MS` 하나로 통일**하고 gui가 import한다
   (T2에서 정의, T5에서 import). `gui → domain`이라 레이어 규칙에 맞다.
2. T6 Step 8의 전체화면·PiP 자막 배선 블록은 **의도적으로 복사**한다 — 바로 옆 컨트롤바
   배선이 이미 같은 방식이라 주변 코드와 어법을 맞추는 쪽을 택했다. 리뷰에서 중복으로
   지적되면 이 결정을 근거로 유지한다.
