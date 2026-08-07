# 가사 검색 범위 제한 · 자막 크기/위치 조절 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 가사 검색을 최상위 카테고리가 음악인 영상으로 제한하고, 자막 글자 크기·세로 위치를 `Ctrl`/`Ctrl+Shift` + 휠·방향키로 조절해 전역 저장한다.

**Architecture:** 검색은 `SqliteVideoRepository`에 재귀 CTE 기반 "음악 루트 카테고리 id 집합" 헬퍼를 추가해 가사를 읽는 두 지점에 동일한 게이트를 건다. 자막은 오버레이 위젯을 비디오 영역 전체로 확대해 잘림을 없앤 뒤, 크기 배율과 하단 여백 비율 두 값을 `LyricsOverlay`가 갖고 `InlinePlayer`가 3창(인라인·전체화면·PiP)에 팬아웃하며 `config.yaml`에 디바운스 저장한다.

**Tech Stack:** Python 3.10+, PyQt6, SQLite(재귀 CTE), pytest / pytest-qt, PyYAML

## Global Constraints

- 설계 문서: `docs/superpowers/specs/2026-08-07-search-scope-and-subtitle-controls-design.md`
- 모든 주석·문서는 **한국어**로 작성한다(코드 식별자는 영어).
- 색상 하드코딩 금지 — 단, **자막 색(흰 글자·검은 외곽선)은 기존의 의도적 예외를 유지**한다.
- 예외를 조용히 삼키지 않는다. 폴백이 필요하면 `logger.exception`/`logger.debug`로 흔적을 남긴다.
- `ruff format .`을 저장소 전체에 실행하지 않는다(143개 파일이 미포맷 상태). 린트는 "이 변경이 새 위반을 추가했는가"로만 판단하고 `python -m ruff check <변경파일>`로 확인한다. `ruff`는 PATH에 없으므로 `python -m ruff`로 호출한다.
- `pytest`에 `--timeout` 옵션이 없다(플러그인 미설치).
- 자막 조절 방향 규칙: **위로 굴리거나 위 키를 누르면 값이 커진다.** `subtitle_bottom_ratio`는 아래에서 띄우는 양이므로 값이 커지면 자막이 위로 올라간다.
- 값 범위: `subtitle_font_scale` 0.5–3.0(스텝 0.1, 기본 1.0), `subtitle_bottom_ratio` 0.0–0.6(스텝 0.02, 기본 0.10).
- 커밋은 작업 단위로. 푸시는 하지 않는다.

---

### Task 1: 가사 검색을 음악 카테고리로 제한

**Files:**
- Modify: `domain/library/repositories.py` (14행 `MATCH_FIELD_KEYS` 아래)
- Modify: `infrastructure/persistence/sqlite_video_repository.py` (`_lyrics_match_ids` 504행, `match_fields_for` 526행)
- Test: `tests/integration/test_search_fields.py`

**Interfaces:**
- Consumes: 없음(첫 작업)
- Produces: `MUSIC_ROOT_CATEGORY_NAMES: frozenset[str]`,
  `SqliteVideoRepository._music_category_ids(conn) -> list[str]`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/integration/test_search_fields.py` 맨 아래에 추가한다. 파일 상단 import에
`Category`를 더한다(`from domain.library.entities import Category`).

```python
class TestLyricsSearchScope:
    """가사 검색은 최상위 카테고리가 음악인 영상에서만 동작한다."""

    def _song(self, repo, songs, url, title, lyric, category_id=None):
        agg = VideoAggregate.create(VideoUrl(url), title)
        if category_id is not None:
            agg.assign_category(category_id)
        repo.save(agg)
        s = SongInfoAggregate.create(agg.id)
        s.set_flag(True)
        s.edit_lyrics([LyricsLine(original=lyric)])
        songs.save(s)
        return agg

    def test_music_루트_직속은_가사로_검색된다(self, repo, songs):
        music = Category.create("Music")
        repo.save_category(music)
        a = self._song(repo, songs, "https://youtu.be/s1", "곡1", "청춘의 노랫말", music.id)
        assert _ids(repo.search(SearchQuery(text="노랫말"))) == {a.id}

    def test_중첩_하위도_검색된다(self, repo, songs):
        music = Category.create("Music")
        repo.save_category(music)
        kpop = Category.create("K-Pop", parent_id=music.id)
        repo.save_category(kpop)
        a = self._song(repo, songs, "https://youtu.be/s2", "곡2", "청춘의 노랫말", kpop.id)
        assert _ids(repo.search(SearchQuery(text="노랫말"))) == {a.id}

    def test_비음악_카테고리는_가사로_안_걸린다(self, repo, songs):
        movies = Category.create("Movies")
        repo.save_category(movies)
        self._song(repo, songs, "https://youtu.be/s3", "곡3", "청춘의 노랫말", movies.id)
        assert _ids(repo.search(SearchQuery(text="노랫말"))) == set()

    def test_미분류는_가사로_안_걸린다(self, repo, songs):
        self._song(repo, songs, "https://youtu.be/s4", "곡4", "청춘의 노랫말", None)
        assert _ids(repo.search(SearchQuery(text="노랫말"))) == set()

    def test_한글이름과_대소문자_공백_변형도_인정된다(self, repo, songs):
        for i, name in enumerate((" MUSIC ", "음악", "노래")):
            c = Category.create(name)
            repo.save_category(c)
            self._song(repo, songs, f"https://youtu.be/v{i}", f"곡{i}", "청춘의 노랫말", c.id)
        assert len(repo.search(SearchQuery(text="노랫말"))) == 3

    def test_배지와_검색결과가_일치한다(self, repo, songs):
        music = Category.create("Music")
        repo.save_category(music)
        movies = Category.create("Movies")
        repo.save_category(movies)
        a = self._song(repo, songs, "https://youtu.be/m1", "곡A", "청춘의 노랫말", music.id)
        b = self._song(repo, songs, "https://youtu.be/m2", "곡B", "청춘의 노랫말", movies.id)
        fields = repo.match_fields_for([a.id, b.id], "노랫말")
        assert "lyrics" in fields.get(a.id, ())
        assert "lyrics" not in fields.get(b.id, ())

    def test_카테고리_부모가_순환해도_멈추지_않는다(self, repo, songs, db):
        # 앱 UI로는 못 만들지만 데이터가 깨지면 재귀 CTE 가 무한 루프에 빠진다.
        a = Category.create("A")
        b = Category.create("B")
        repo.save_category(a)
        repo.save_category(b)
        with db.connection() as conn:
            conn.execute("UPDATE categories SET parent_id=? WHERE id=?", (str(b.id), str(a.id)))
            conn.execute("UPDATE categories SET parent_id=? WHERE id=?", (str(a.id), str(b.id)))
        self._song(repo, songs, "https://youtu.be/c1", "곡C", "청춘의 노랫말", a.id)
        assert _ids(repo.search(SearchQuery(text="노랫말"))) == set()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/integration/test_search_fields.py::TestLyricsSearchScope -v`
Expected: FAIL — 비음악/미분류 케이스가 지금은 가사로 걸리므로 `AssertionError`

- [ ] **Step 3: 상수 추가**

`domain/library/repositories.py`, `MATCH_FIELD_KEYS` 정의 바로 아래:

```python
# 가사 검색을 허용할 최상위(루트) 카테고리 이름 — trim + 소문자로 비교한다.
# 검색 계약의 일부라 도메인에 둔다(테스트가 import 해 규칙을 고정).
MUSIC_ROOT_CATEGORY_NAMES: frozenset[str] = frozenset({"music", "음악", "노래"})
```

- [ ] **Step 4: 루트 카테고리 헬퍼 추가**

`infrastructure/persistence/sqlite_video_repository.py` — import 에
`MUSIC_ROOT_CATEGORY_NAMES`를 더하고(11행 기존 import 라인 확장),
`_lyrics_match_ids` 바로 위에 추가한다:

```python
    def _music_category_ids(self, conn) -> list[str]:
        """최상위 조상 카테고리 이름이 음악인 카테고리 id 전체(중첩 포함).

        depth 가드는 선택이 아니라 필수다 — categories 에 순환을 막는 제약이
        UNIQUE(name, parent_id) 뿐이라, 데이터가 순환하면 재귀 CTE 가 끝나지 않고
        앱이 멈춘다. 32단계면 실제 카테고리 깊이를 한참 넘는다.
        """
        names = sorted(MUSIC_ROOT_CATEGORY_NAMES)
        ph = ",".join("?" * len(names))
        sql = f"""
            WITH RECURSIVE tree(id, root_name, depth) AS (
                SELECT id, name, 0 FROM categories WHERE parent_id IS NULL
                UNION ALL
                SELECT c.id, t.root_name, t.depth + 1
                  FROM categories c JOIN tree t ON c.parent_id = t.id
                 WHERE t.depth < 32
            )
            SELECT id FROM tree WHERE lower(trim(root_name)) IN ({ph})
        """
        return [r[0] for r in conn.execute(sql, names).fetchall()]
```

- [ ] **Step 5: `_lyrics_match_ids`에 게이트 적용**

기존 메서드 본문을 통째로 아래로 교체한다(연결을 먼저 열고 그 안에서 헬퍼를 쓴다):

```python
    def _lyrics_match_ids(self, text: str) -> list[str]:
        """가사(원문·번역)에 검색어가 든 video_id 목록을 반환한다.

        최상위 카테고리가 음악인 영상만 대상으로 한다. lyrics_json 에 SQL LIKE 를
        쓰면 검색어 'o'·'t' 가 JSON 키에 걸려 모든 노래를 오탐하므로 파싱해서
        값만 비교한다.
        """
        needle = text.lower()
        with self._db.connection() as conn:
            music_ids = self._music_category_ids(conn)
            if not music_ids:
                return []
            cat_ph = ",".join("?" * len(music_ids))
            sql = (
                "SELECT s.video_id, s.lyrics_json FROM song_info s "
                "JOIN videos v ON v.id = s.video_id "
                f"WHERE s.lyrics_json <> '[]' AND v.category_id IN ({cat_ph})"
            )
            params: list = list(music_ids)
            if _lyrics_prefilter_safe(text):
                # 후보를 SQL 로 먼저 좁힌다 — 전체 가사를 매 검색마다 JSON 파싱하면
                # 검색어를 한 글자 칠 때마다 라이브러리 전체를 파싱하게 된다.
                sql += " AND s.lyrics_json LIKE ? ESCAPE '\\'"
                params.append(_like_pattern(text))
            rows = conn.execute(sql, params).fetchall()
        return [
            r["video_id"]
            for r in rows
            if needle in _lyrics_text(r["lyrics_json"]).lower()
        ]
```

- [ ] **Step 6: `match_fields_for`의 가사 조회에도 같은 게이트 적용**

`match_fields_for` 안의 `lyric_rows = conn.execute(...)` 블록을 교체한다.
**두 곳을 함께 고쳐야 한다** — 한쪽만 고치면 "가사로 검색됐는데 `가사` 배지는
안 뜨는" 불일치가 난다.

```python
            # 가사는 파싱해서 비교한다(JSON 키 오탐 방지). 음악 카테고리만 대상.
            needle = text.lower()
            music_ids = self._music_category_ids(conn)
            if music_ids:
                cat_ph = ",".join("?" * len(music_ids))
                lyric_rows = conn.execute(
                    "SELECT s.video_id, s.lyrics_json FROM song_info s "
                    "JOIN videos v ON v.id = s.video_id "
                    f"WHERE s.video_id IN ({ph}) AND v.category_id IN ({cat_ph})",
                    [*ids, *music_ids],
                ).fetchall()
            else:
                lyric_rows = []
```

- [ ] **Step 7: 테스트 통과 확인**

Run: `python -m pytest tests/integration/test_search_fields.py -v`
Expected: 전체 PASS(기존 케이스 포함)

- [ ] **Step 8: 전체 회귀 + 린트**

Run: `python -m pytest -q`
Expected: 전부 PASS

Run: `python -m ruff check domain/library/repositories.py infrastructure/persistence/sqlite_video_repository.py tests/integration/test_search_fields.py --output-format=concise`
Expected: `All checks passed!`

- [ ] **Step 9: 커밋**

```bash
git add domain/library/repositories.py infrastructure/persistence/sqlite_video_repository.py tests/integration/test_search_fields.py
git commit -m "feat: 가사 검색을 최상위 카테고리가 음악인 영상으로 제한

- MUSIC_ROOT_CATEGORY_NAMES(music/음악/노래) 기준으로 루트 조상 카테고리를
  재귀 CTE 로 해석, 미분류는 제외
- _lyrics_match_ids 와 match_fields_for 양쪽에 같은 게이트 — 한쪽만 걸면
  검색 결과와 '가사' 배지가 어긋난다
- categories 에 순환 방지 제약이 없어 재귀에 depth<32 가드 필수
- 부수 효과: 매 검색마다 전체 가사를 JSON 파싱하던 부담이 준다"
```

---

### Task 2: 자막 표시 설정값 2개 추가

**Files:**
- Modify: `config/settings.py` (`_load_bool` 115행 아래, `save_setting` mapping 162행)
- Test: `tests/unit/test_settings_subtitle_prefs.py` (신규)

**Interfaces:**
- Consumes: 없음
- Produces: `config.settings.SUBTITLE_FONT_SCALE: float`,
  `config.settings.SUBTITLE_BOTTOM_RATIO: float`,
  `_load_float(key: str, default: float) -> float`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/test_settings_subtitle_prefs.py` 신규 생성:

```python
"""자막 표시 설정(크기 배율·하단 여백 비율)의 로드·저장 왕복 검증."""
from __future__ import annotations

import importlib


def test_기본값(monkeypatch, tmp_path):
    import config.settings as s
    importlib.reload(s)
    assert s.SUBTITLE_FONT_SCALE == 1.0
    assert s.SUBTITLE_BOTTOM_RATIO == 0.10


def test_저장하면_모듈변수가_즉시_갱신된다(tmp_path, monkeypatch):
    import config.settings as s
    monkeypatch.setattr(s, "DATA_DIR", tmp_path)
    monkeypatch.setattr(s, "_CONFIG_FILE", tmp_path / "config.yaml")
    s._load_config.cache_clear()
    s.save_setting("subtitle_font_scale", 1.6)
    s.save_setting("subtitle_bottom_ratio", 0.24)
    assert s.SUBTITLE_FONT_SCALE == 1.6
    assert s.SUBTITLE_BOTTOM_RATIO == 0.24


def test_잘못된_값은_기본값으로_떨어진다(monkeypatch):
    import config.settings as s
    monkeypatch.setattr(s, "_load_config", lambda: {"subtitle_font_scale": "삼"})
    assert s._load_float("subtitle_font_scale", 1.0) == 1.0
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/unit/test_settings_subtitle_prefs.py -v`
Expected: FAIL — `AttributeError: module 'config.settings' has no attribute 'SUBTITLE_FONT_SCALE'`

- [ ] **Step 3: `_load_float` 추가**

`config/settings.py`의 `_load_bool` 정의 바로 아래:

```python
def _load_float(key: str, default: float) -> float:
    try:
        return float(_load_config().get(key, default))
    except (TypeError, ValueError):
        return default
```

- [ ] **Step 4: 설정값 노출**

`AUTO_ENRICH_ON_ADD` 정의 아래에 추가:

```python
# 자막 표시 설정 — 전역(영상과 무관한 보기 설정). 비율이라 인라인·전체화면·PiP
# 어디서나 같은 비중으로 보인다. 값 범위 clamp 는 LyricsOverlay 가 담당한다.
SUBTITLE_FONT_SCALE: float = _load_float("subtitle_font_scale", 1.0)
SUBTITLE_BOTTOM_RATIO: float = _load_float("subtitle_bottom_ratio", 0.10)
```

- [ ] **Step 5: `save_setting` mapping 에 등록**

`save_setting` 안 `mapping` 딕셔너리에 두 줄 추가(`"auto_enrich_on_add"` 아래):

```python
        "subtitle_font_scale": "SUBTITLE_FONT_SCALE",
        "subtitle_bottom_ratio": "SUBTITLE_BOTTOM_RATIO",
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `python -m pytest tests/unit/test_settings_subtitle_prefs.py -v`
Expected: PASS

- [ ] **Step 7: 커밋**

```bash
git add config/settings.py tests/unit/test_settings_subtitle_prefs.py
git commit -m "feat: 자막 크기 배율·하단 여백 비율 설정 추가

- _load_float 헬퍼 + SUBTITLE_FONT_SCALE(1.0)·SUBTITLE_BOTTOM_RATIO(0.10)
- save_setting mapping 에 등록해 저장 즉시 모듈 변수 반영"
```

---

### Task 3: 자막 오버레이를 비디오 영역 전체로 + 기본 크기 정상화

**Files:**
- Modify: `gui/widgets/lyrics_overlay.py` (153–158행 상수, `_fonts` 193행, `paintEvent` 263행)
- Modify: `gui/widgets/video_player.py` (`_VideoArea._layout_children` 647–652,
  `_PipWindow._layout_children` 767–770, `_FullscreenWindow._position_bar` 854–857,
  `_FullscreenWindow.resizeEvent` 866–869)
- Test: `tests/unit/gui/test_lyrics_overlay_layout.py` (신규)

**Interfaces:**
- Consumes: 없음
- Produces: `LyricsOverlay._BASE_FONT_RATIO = 0.045`,
  `LyricsOverlay._font_scale: float`, `LyricsOverlay._bottom_ratio: float`
  (Task 4가 공개 setter 를 붙인다)

**배경:** 지금 오버레이는 "컨트롤바 위 높이 28% 띠"라 글자를 키우거나 위치를 올리면
띠 밖으로 잘리고, 글자 크기 기준이 띠 높이라 실질 비율이 약 1.5%로 왜곡돼 있다.
영역 전체를 덮게 바꾸면 두 문제가 동시에 사라진다. 마우스는 이미
`WA_TransparentForMouseEvents`로 통과하고, 레이아웃이 자막을 `raise_()` 한 **뒤에**
컨트롤바를 `raise_()` 하므로 컨트롤바가 계속 위에 온다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/gui/test_lyrics_overlay_layout.py` 신규 생성:

```python
"""자막 오버레이의 글자 크기·세로 위치 계산 검증(QApplication 필요, 재생 없음)."""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication

from gui.widgets.lyrics_overlay import LyricsCue, LyricsOverlay


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def overlay(app):
    w = LyricsOverlay()
    w.resize(1600, 900)
    w.set_cue(LyricsCue(start_ms=0, original="hello", translation="안녕", line_index=0))
    yield w
    w.deleteLater()


def test_글자크기가_영역높이의_약_4_5퍼센트(overlay):
    main, _sub = overlay._fonts()
    assert main.pixelSize() == int(900 * 0.045)


def test_최소_크기_하한이_지켜진다(overlay):
    overlay.resize(200, 60)          # 60 * 0.045 = 2.7px
    main, _sub = overlay._fonts()
    assert main.pixelSize() == LyricsOverlay._MIN_FONT_PX


def test_기본_하단여백은_높이의_10퍼센트(overlay):
    assert overlay._bottom_ratio == pytest.approx(0.10)
    assert overlay._bottom_px() == int(900 * 0.10)
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/unit/gui/test_lyrics_overlay_layout.py -v`
Expected: FAIL — `AttributeError: 'LyricsOverlay' object has no attribute '_bottom_ratio'`

- [ ] **Step 3: 상수·상태 교체**

`gui/widgets/lyrics_overlay.py` 153–158행의 상수 블록을 교체한다
(`_FONT_RATIO`를 `_BASE_FONT_RATIO`로 바꾸고 값도 조정):

```python
    _MIN_FONT_PX = 13
    # 영역(비디오 전체) 높이 대비 원문 글자 크기. 예전 0.055 는 높이 28% 띠에
    # 적용돼 실질 1.5% 였다 — 오버레이가 영역 전체를 덮게 되면서 기준이 바뀌었다.
    _BASE_FONT_RATIO = 0.045
    _TRANSLATION_RATIO = 0.85    # 원문 대비 번역 글자 크기
    _OUTLINE_RATIO = 0.14        # 글자 크기 대비 외곽선 두께
    _LINE_GAP = 4                # 원문/번역 줄 간격(px)
    _SIDE_MARGIN = 24            # 좌우 여백(px)
```

`__init__` 의 `self._visible_text = True` 아래에 상태 두 개를 더한다:

```python
        # 사용자 조절값(Task 4에서 setter 로 노출). 비율이라 창 크기와 무관하게 일정.
        self._font_scale: float = 1.0
        self._bottom_ratio: float = 0.10
```

- [ ] **Step 4: 계산식 반영**

`_fonts` 의 첫 줄을 교체한다:

```python
        px = max(
            self._MIN_FONT_PX,
            int(self.height() * self._BASE_FONT_RATIO * self._font_scale),
        )
```

`_fonts` 바로 위에 하단 여백 헬퍼를 추가한다:

```python
    def _bottom_px(self) -> int:
        """아래에서 띄울 픽셀 수 — 비율이라 창 크기가 변해도 비중이 같다."""
        return int(self.height() * self._bottom_ratio)
```

`paintEvent` 의 y 계산부(기존 `y = self.height() - total_h`)를 교체한다:

```python
        # 아래에서부터 쌓아 올린다 — 자막은 하단 정렬이 자연스럽다.
        y = self.height() - self._bottom_px() - total_h
        y = max(0, y)   # 글자가 커도 위로 잘려 나가지 않게
```

- [ ] **Step 5: 오버레이 지오메트리를 영역 전체로 (4곳)**

`gui/widgets/video_player.py` — **네 곳 모두** 고친다. 빠뜨리면 그 창에서만 잘린다.

`_VideoArea._layout_children` 안:

```python
        if self._subtitle is not None:
            # 영역 전체를 덮는다 — 글자를 키우거나 위치를 올려도 잘리지 않는다.
            # 컨트롤바를 나중에 raise_() 하므로 바가 계속 자막 위에 온다.
            self._subtitle.setGeometry(0, 0, self.width(), h)
            self._subtitle.raise_()
```

`_PipWindow._layout_children` 안:

```python
        self.subtitle.setGeometry(0, 0, self.width(), self.height())
        self.subtitle.raise_()
        self.subtitle.show()
```

`_FullscreenWindow._position_bar` 와 `_FullscreenWindow.resizeEvent` 안 (같은 3줄):

```python
        self.subtitle.setGeometry(0, 0, self.width(), self.height())
        self.subtitle.raise_()
```

(`_position_bar` 쪽에는 기존대로 `self.subtitle.show()` 를 유지한다. 각 메서드에서
더 이상 쓰지 않게 된 `sub_h` 지역 변수는 삭제한다.)

- [ ] **Step 6: 테스트 통과 확인**

Run: `python -m pytest tests/unit/gui/test_lyrics_overlay_layout.py -v`
Expected: PASS

- [ ] **Step 7: 자막 관련 기존 테스트 회귀 확인**

Run: `python -m pytest tests/gui/test_lyrics_overlay.py tests/gui/test_subtitle_player.py tests/gui/test_subtitle_wiring.py -q`
Expected: 전부 PASS. (확인함: 이 세 파일에 자막 지오메트리를 단언하는 테스트는 없으므로
수정할 것이 없어야 한다. 실패한다면 그건 이 변경이 깨뜨린 것이니 고쳐야 한다.)

- [ ] **Step 8: 커밋**

```bash
git add gui/widgets/lyrics_overlay.py gui/widgets/video_player.py tests/unit/gui/test_lyrics_overlay_layout.py
git commit -m "fix: 자막 오버레이를 비디오 영역 전체로 넓히고 기본 글자 크기 정상화

- 예전엔 컨트롤바 위 28% 높이 띠라 글자를 키우면 잘렸고, 크기 비율 5.5%가
  그 띠에 적용돼 실질 1.5%였다(그래서 자막이 지나치게 작았다)
- 오버레이가 영역 전체를 덮게 하고 비율을 영역 높이 기준 4.5%로 교정
- 하단 여백을 비율(_bottom_ratio, 기본 0.10)로 분리 — Task 4가 조절 API를 붙인다
- 인라인·PiP·전체화면(_position_bar/resizeEvent) 4곳 지오메트리 모두 변경"
```

---

### Task 4: 크기·위치 조절 API (clamp 포함)

**Files:**
- Modify: `gui/widgets/lyrics_overlay.py`
- Test: `tests/unit/gui/test_lyrics_overlay_layout.py`

**Interfaces:**
- Consumes: `LyricsOverlay._font_scale`, `LyricsOverlay._bottom_ratio` (Task 3)
- Produces: `LyricsOverlay.set_font_scale(scale: float) -> None`,
  `LyricsOverlay.set_bottom_ratio(ratio: float) -> None`,
  `LyricsOverlay.font_scale -> float`, `LyricsOverlay.bottom_ratio -> float`,
  클래스 상수 `FONT_SCALE_MIN/MAX`, `BOTTOM_RATIO_MIN/MAX`,
  `FONT_SCALE_DEFAULT`, `BOTTOM_RATIO_DEFAULT`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/unit/gui/test_lyrics_overlay_layout.py` 아래에 추가:

```python
class TestAdjust:
    def test_배율이_글자크기에_선형_반영된다(self, overlay):
        overlay.set_font_scale(2.0)
        main, _ = overlay._fonts()
        assert main.pixelSize() == int(900 * 0.045 * 2.0)

    def test_배율_범위가_clamp_된다(self, overlay):
        overlay.set_font_scale(9.9)
        assert overlay.font_scale == LyricsOverlay.FONT_SCALE_MAX
        overlay.set_font_scale(0.01)
        assert overlay.font_scale == LyricsOverlay.FONT_SCALE_MIN

    def test_위치_범위가_clamp_된다(self, overlay):
        overlay.set_bottom_ratio(5.0)
        assert overlay.bottom_ratio == LyricsOverlay.BOTTOM_RATIO_MAX
        overlay.set_bottom_ratio(-1.0)
        assert overlay.bottom_ratio == LyricsOverlay.BOTTOM_RATIO_MIN

    def test_위치값이_커지면_자막이_위로_올라간다(self, overlay):
        overlay.set_bottom_ratio(0.0)
        low = overlay._bottom_px()
        overlay.set_bottom_ratio(0.30)
        assert overlay._bottom_px() > low
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/unit/gui/test_lyrics_overlay_layout.py::TestAdjust -v`
Expected: FAIL — `AttributeError: 'LyricsOverlay' object has no attribute 'set_font_scale'`

- [ ] **Step 3: 상수·setter·property 추가**

상수 블록(`_SIDE_MARGIN` 아래)에 공개 상수를 더한다. **공개(밑줄 없음)로 두는 이유는
`InlinePlayer`와 테스트가 범위를 참조하기 때문이다** — 두 곳에 따로 적으면 어긋난다.

```python
    # 사용자 조절 범위 — InlinePlayer 와 테스트가 참조하므로 공개 상수로 둔다.
    FONT_SCALE_DEFAULT = 1.0
    FONT_SCALE_MIN, FONT_SCALE_MAX = 0.5, 3.0
    BOTTOM_RATIO_DEFAULT = 0.10
    BOTTOM_RATIO_MIN, BOTTOM_RATIO_MAX = 0.0, 0.6
```

`set_text_visible` 아래에 setter 와 property 를 추가한다:

```python
    def set_font_scale(self, scale: float) -> None:
        """글자 크기 배율. 범위 밖 값은 잘라낸다(설정 파일이 깨져도 안전하게)."""
        v = min(self.FONT_SCALE_MAX, max(self.FONT_SCALE_MIN, float(scale)))
        if v == self._font_scale:
            return
        self._font_scale = v
        self.update()

    def set_bottom_ratio(self, ratio: float) -> None:
        """아래에서 띄우는 비율. 값이 커지면 자막이 위로 올라간다."""
        v = min(self.BOTTOM_RATIO_MAX, max(self.BOTTOM_RATIO_MIN, float(ratio)))
        if v == self._bottom_ratio:
            return
        self._bottom_ratio = v
        self.update()

    @property
    def font_scale(self) -> float:
        return self._font_scale

    @property
    def bottom_ratio(self) -> float:
        return self._bottom_ratio
```

`__init__` 의 초기값을 새 상수로 바꾼다:

```python
        self._font_scale: float = self.FONT_SCALE_DEFAULT
        self._bottom_ratio: float = self.BOTTOM_RATIO_DEFAULT
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/unit/gui/test_lyrics_overlay_layout.py -v`
Expected: 전부 PASS

- [ ] **Step 5: 린트 + 커밋**

Run: `python -m ruff check gui/widgets/lyrics_overlay.py tests/unit/gui/test_lyrics_overlay_layout.py --output-format=concise`
Expected: `All checks passed!`

```bash
git add gui/widgets/lyrics_overlay.py tests/unit/gui/test_lyrics_overlay_layout.py
git commit -m "feat: 자막 크기 배율·하단 여백 비율 조절 API

- set_font_scale/set_bottom_ratio + 범위 clamp(0.5~3.0 / 0.0~0.6)
- 범위 상수는 InlinePlayer 와 공유해야 하므로 공개 상수로 노출"
```

---

### Task 5: 방향키(Ctrl / Ctrl+Shift) 조작 + 3창 팬아웃 + 상태 표시

**Files:**
- Modify: `gui/widgets/video_player.py` (`InlinePlayer` 상수 912행 부근, `keyPressEvent` 1350행,
  `_all_subtitles` 1179행 아래, `_status_lbl` 1000행)
- Test: `tests/gui/test_subtitle_player.py`

**Interfaces:**
- Consumes: `LyricsOverlay.set_font_scale/set_bottom_ratio/font_scale/bottom_ratio`,
  `LyricsOverlay.FONT_SCALE_*`, `LyricsOverlay.BOTTOM_RATIO_*` (Task 4);
  `config.settings.SUBTITLE_FONT_SCALE/SUBTITLE_BOTTOM_RATIO` (Task 2)
- Produces: `InlinePlayer._nudge_subtitle_scale(delta: float) -> None`,
  `InlinePlayer._nudge_subtitle_bottom(delta: float) -> None`,
  `InlinePlayer._apply_subtitle_prefs() -> None`,
  `InlinePlayer._show_transient(text: str, ms: int = 1000) -> None`,
  `InlinePlayer._subtitle_font_scale: float`, `InlinePlayer._subtitle_bottom_ratio: float`,
  상수 `_FONT_SCALE_STEP = 0.1`, `_BOTTOM_RATIO_STEP = 0.02`

**함정:** `keyPressEvent` 는 현재 **수정키를 전혀 보지 않는다.** 맨 `↑/↓` 가 볼륨이므로
새 분기를 **메서드 맨 앞**에 두고 `Ctrl+Shift` → `Ctrl` 순서로 판정해야 한다
(`Ctrl+Shift` 도 Ctrl 비트가 켜져 있어 순서를 뒤집으면 위치 조절이 크기 조절에 먹힌다).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/gui/test_subtitle_player.py` 아래에 추가한다. 파일 상단 import 에
`from PyQt6.QtGui import QKeyEvent` 는 이미 있고, `QApplication`·`QTest` 도
`TestShortcutReachability` 에서 이미 import 되어 있다.

```python
def _key_mod(player, key: int, mods) -> None:
    player.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, mods))


class TestSubtitleScaleAndPosition:
    def test_ctrl_위아래가_크기를_바꾼다(self, player):
        player.set_lyrics(_track())
        before = player._subtitle.font_scale
        _key_mod(player, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
        assert player._subtitle.font_scale == pytest.approx(before + 0.1)
        _key_mod(player, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
        assert player._subtitle.font_scale == pytest.approx(before)

    def test_맨_위아래는_여전히_볼륨이다(self, player):
        """회귀: 수정키 분기를 넣다가 볼륨 단축키를 깨뜨리기 쉽다."""
        player.set_lyrics(_track())
        before_scale = player._subtitle.font_scale
        vol_before = player._audio.volume()
        _key_mod(player, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
        assert player._subtitle.font_scale == before_scale
        assert player._audio.volume() != pytest.approx(vol_before)

    def test_ctrl_shift_위아래가_위치를_바꾼다(self, player):
        """회귀: Ctrl+Shift 도 Ctrl 비트가 켜져 있어 분기 순서가 틀리면 크기가 바뀐다."""
        player.set_lyrics(_track())
        scale_before = player._subtitle.font_scale
        pos_before = player._subtitle.bottom_ratio
        mods = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        _key_mod(player, Qt.Key.Key_Up, mods)
        assert player._subtitle.bottom_ratio == pytest.approx(pos_before + 0.02)
        assert player._subtitle.font_scale == scale_before

    def test_분리창에도_현재값이_반영된다(self, player):
        player.set_lyrics(_track())
        _key_mod(player, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
        player._enter_fullscreen()
        assert player._fs_win.subtitle.font_scale == pytest.approx(
            player._subtitle.font_scale
        )
        player._exit_fullscreen()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/gui/test_subtitle_player.py::TestSubtitleScaleAndPosition -v`
Expected: FAIL — `Ctrl+↑` 가 지금은 볼륨을 올리므로 `font_scale` 이 그대로

- [ ] **Step 3: 상수·상태 추가**

`InlinePlayer` 의 `_OFFSET_STEP_MS = 250` 아래에 추가:

```python
    _FONT_SCALE_STEP = 0.1      # Ctrl + 휠/방향키 한 번에 움직이는 배율
    _BOTTOM_RATIO_STEP = 0.02   # Ctrl+Shift + 휠/방향키 한 번에 움직이는 위치 비율
```

`__init__` 의 `self._subtitle_on = True` 아래에 현재값을 설정에서 읽어 보관한다:

```python
        # 자막 표시 설정은 전역이라 생성 시 설정값을 읽어 시작한다.
        self._subtitle_font_scale: float = settings.SUBTITLE_FONT_SCALE
        self._subtitle_bottom_ratio: float = settings.SUBTITLE_BOTTOM_RATIO
```

**`config.settings` 는 이 모듈에 import 되어 있지 않다(확인함).** 파일 상단 import 블록에
아래 한 줄을 추가한다:

```python
from config import settings
```

새 시그널은 만들지 않는다. 저장은 Task 7이 `_queue_subtitle_prefs_save()` 로 직접 처리하므로
값 변경을 알리는 시그널은 구독자가 없는 죽은 코드가 된다.

- [ ] **Step 4: 팬아웃·조절 메서드 추가**

`_all_subtitles` 메서드 바로 아래에 추가:

```python
    def _apply_subtitle_prefs(self) -> None:
        """현재 크기·위치를 3창 오버레이 전부에 반영한다."""
        for overlay in self._all_subtitles():
            overlay.set_font_scale(self._subtitle_font_scale)
            overlay.set_bottom_ratio(self._subtitle_bottom_ratio)

    def _nudge_subtitle_scale(self, delta: float) -> None:
        ov = self._subtitle
        ov.set_font_scale(self._subtitle_font_scale + delta)
        self._subtitle_font_scale = ov.font_scale       # clamp 된 실제 값을 되받는다
        self._apply_subtitle_prefs()
        self._show_transient(f"자막 크기 {round(self._subtitle_font_scale * 100)}%")

    def _nudge_subtitle_bottom(self, delta: float) -> None:
        ov = self._subtitle
        ov.set_bottom_ratio(self._subtitle_bottom_ratio + delta)
        self._subtitle_bottom_ratio = ov.bottom_ratio
        self._apply_subtitle_prefs()
        self._show_transient(f"자막 위치 {round(self._subtitle_bottom_ratio * 100)}%")
```

(Task 7이 이 두 메서드 끝에 `self._queue_subtitle_prefs_save()` 를 덧붙인다.)

- [ ] **Step 5: 일시 표시 헬퍼 추가**

`_status_lbl` 은 스트림 로딩 안내에도 쓰이므로 **내가 띄운 문구일 때만 지운다.**
`__init__` 에서 `self._status_lbl` 을 만든 직후에 타이머를 준비한다:

```python
        self._transient_timer = QTimer(self)
        self._transient_timer.setSingleShot(True)
        self._transient_timer.timeout.connect(self._clear_transient)
        self._transient_text = ""
```

`_nudge_subtitle_scale` 위에 헬퍼를 추가한다:

```python
    def _show_transient(self, text: str, ms: int = 1000) -> None:
        """조절 중 현재 값을 잠깐 보여준다.

        가사 줄이 안 나오는 구간에서 조절하면 화면에 아무 변화가 없어 먹었는지
        알 수 없다. 그래서 값 표시는 있으나 마나 한 장식이 아니라 필수다.
        """
        self._transient_text = text
        self._status_lbl.setText(text)
        self._status_lbl.show()
        self._transient_timer.start(ms)

    def _clear_transient(self) -> None:
        # 그 사이 스트림 안내 문구로 바뀌었다면 건드리지 않는다.
        if self._status_lbl.text() == self._transient_text:
            self._status_lbl.hide()
        self._transient_text = ""
```

- [ ] **Step 6: `keyPressEvent` 맨 앞에 수정키 분기 추가**

`keyPressEvent` 의 `key = event.key()` 바로 다음 줄에 삽입한다. **기존 분기보다
앞이어야 하고, Ctrl+Shift 를 Ctrl 보다 먼저 봐야 한다.**

```python
        mods = event.modifiers()
        if (
            mods & Qt.KeyboardModifier.ControlModifier
            and key in (Qt.Key.Key_Up, Qt.Key.Key_Down)
        ):
            sign = 1 if key == Qt.Key.Key_Up else -1
            # Ctrl+Shift 도 Ctrl 비트가 켜져 있으므로 Shift 를 먼저 판정한다.
            if mods & Qt.KeyboardModifier.ShiftModifier:
                self._nudge_subtitle_bottom(sign * self._BOTTOM_RATIO_STEP)
            else:
                self._nudge_subtitle_scale(sign * self._FONT_SCALE_STEP)
            return
```

- [ ] **Step 7: 분리 창 진입 시 현재값 반영**

`_enter_fullscreen` 과 `_enter_pip` 에서 `bar.set_has_subtitle(has)` 를 호출하는 줄
(각각 1475행·1556행 부근) **바로 아래**에 한 줄씩 추가한다:

```python
        self._apply_subtitle_prefs()
```

- [ ] **Step 8: 테스트 통과 확인**

Run: `python -m pytest tests/gui/test_subtitle_player.py -v`
Expected: 전부 PASS

- [ ] **Step 9: 커밋**

```bash
git add gui/widgets/video_player.py tests/gui/test_subtitle_player.py
git commit -m "feat: Ctrl/Ctrl+Shift + 방향키로 자막 크기·위치 조절

- keyPressEvent 맨 앞에 수정키 분기 추가. 기존 코드는 수정키를 전혀 보지 않아
  맨 ↑/↓(볼륨)와 충돌하므로 Ctrl+Shift → Ctrl → 무수정 순으로 판정한다
- 조절값을 인라인·전체화면·PiP 3창에 팬아웃(_apply_subtitle_prefs)
- 조절 중 '자막 크기 130%' 를 상태 라벨에 잠깐 표시 — 가사 줄이 없는 구간에서는
  화면 변화가 없어 이게 없으면 먹었는지 알 수 없다"
```

---

### Task 6: 휠 조작 (도달성 포함)

**Files:**
- Modify: `gui/widgets/video_player.py` (`_VideoView` 663행, `_PipWindow` 712행,
  `_FullscreenWindow` 812행, `InlinePlayer`)
- Test: `tests/gui/test_subtitle_player.py`

**Interfaces:**
- Consumes: `InlinePlayer._nudge_subtitle_scale/_nudge_subtitle_bottom` (Task 5)
- Produces: `InlinePlayer.wheelEvent`, `_VideoView.wheelEvent`,
  `_PipWindow`/`_FullscreenWindow` 생성자의 `wheel_handler` 인자

**함정:** `_VideoView`(QGraphicsView)는 휠을 스크롤로 **삼킬 수 있다.** 핸들러가 멀쩡해도
이벤트가 도달하지 않아 조용히 죽는 종류의 버그라(단축키 포커스 위임과 같은 함정),
**실제 휠 이벤트를 보내는 도달성 테스트로 고정한다.**

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/gui/test_subtitle_player.py` 의 `TestSubtitleScaleAndPosition` 아래에 추가.
파일 상단에 `from PyQt6.QtGui import QWheelEvent` 와 `from PyQt6.QtCore import QPointF` 를 더한다.

```python
def _wheel(widget, up: bool, mods) -> None:
    """실제 QWheelEvent 를 위젯에 보낸다(핸들러 직접 호출이 아니다)."""
    ev = QWheelEvent(
        QPointF(10, 10), widget.mapToGlobal(QPoint(10, 10)),
        QPoint(0, 0), QPoint(0, 120 if up else -120),
        Qt.MouseButton.NoButton, mods, Qt.ScrollPhase.NoScrollPhase, False,
    )
    QApplication.sendEvent(widget, ev)


class TestSubtitleWheel:
    def test_ctrl_휠이_크기를_바꾼다(self, player):
        player.set_lyrics(_track())
        before = player._subtitle.font_scale
        _wheel(player, True, Qt.KeyboardModifier.ControlModifier)
        assert player._subtitle.font_scale == pytest.approx(before + 0.1)

    def test_ctrl_shift_휠이_위치를_바꾼다(self, player):
        player.set_lyrics(_track())
        before = player._subtitle.bottom_ratio
        mods = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        _wheel(player, True, mods)
        assert player._subtitle.bottom_ratio == pytest.approx(before + 0.02)

    def test_영상_위에서_굴린_휠이_플레이어까지_도달한다(self, player):
        """회귀: QGraphicsView 가 휠을 삼키면 핸들러가 멀쩡해도 조용히 죽는다."""
        player.resize(800, 450)
        player.show()
        QTest.qWaitForWindowExposed(player)
        player.set_lyrics(_track())
        before = player._subtitle.font_scale
        _wheel(player._video_view.viewport(), True, Qt.KeyboardModifier.ControlModifier)
        assert player._subtitle.font_scale == pytest.approx(before + 0.1)
        player.hide()
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/gui/test_subtitle_player.py::TestSubtitleWheel -v`
Expected: FAIL — `wheelEvent` 가 없어 배율이 그대로

- [ ] **Step 3: `InlinePlayer.wheelEvent` 추가**

`keyPressEvent` 바로 아래에 추가한다:

```python
    def wheelEvent(self, event) -> None:
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            # angleDelta().y() > 0 이면 위로 굴린 것 — 값이 커진다.
            sign = 1 if event.angleDelta().y() > 0 else -1
            if mods & Qt.KeyboardModifier.ShiftModifier:
                self._nudge_subtitle_bottom(sign * self._BOTTOM_RATIO_STEP)
            else:
                self._nudge_subtitle_scale(sign * self._FONT_SCALE_STEP)
            event.accept()
            return
        # 수정키 없는 휠은 건드리지 않는다(기존 동작 유지).
        super().wheelEvent(event)
```

- [ ] **Step 4: `_VideoView` 가 휠을 넘기게 한다**

`_VideoView` 의 `video_item` property 아래에 추가:

```python
    def wheelEvent(self, event) -> None:
        # QGraphicsView 는 휠을 스크롤로 소비한다. 스크롤바를 꺼 둔 뷰라 쓸모가 없고,
        # 삼키면 상위 플레이어의 자막 크기·위치 단축키가 조용히 죽는다.
        event.ignore()
```

- [ ] **Step 5: 분리 창에서 휠 전달**

`_PipWindow.__init__` 과 `_FullscreenWindow.__init__` 시그니처에
`wheel_handler=None` 인자를 더하고 `self._wheel_handler = wheel_handler` 를 보관한다.
두 클래스 각각에 메서드를 추가한다(`keyPressEvent` 옆):

```python
    def wheelEvent(self, event) -> None:
        # 자막 크기·위치 조절이 분리 창에서도 동작하도록 InlinePlayer 로 넘긴다.
        if self._wheel_handler:
            self._wheel_handler(event)
        else:
            super().wheelEvent(event)
```

`_enter_fullscreen` / `_enter_pip` 에서 창을 만들 때 `key_handler=self.keyPressEvent`
옆에 `wheel_handler=self.wheelEvent` 를 넘긴다.

- [ ] **Step 6: 테스트 통과 확인**

Run: `python -m pytest tests/gui/test_subtitle_player.py -v`
Expected: 전부 PASS

- [ ] **Step 7: 커밋**

```bash
git add gui/widgets/video_player.py tests/gui/test_subtitle_player.py
git commit -m "feat: Ctrl/Ctrl+Shift + 휠로 자막 크기·위치 조절

- _VideoView(QGraphicsView)가 휠을 스크롤로 삼켜 상위 플레이어까지 오지 않으므로
  ignore() 로 넘긴다. 핸들러가 멀쩡해도 조용히 죽는 종류라 실제 휠 이벤트를
  보내는 도달성 테스트로 고정했다
- 전체화면·PiP 는 wheel_handler 로 InlinePlayer 에 전달(key_handler 와 같은 패턴)
- 수정키 없는 휠은 건드리지 않아 기존 동작 유지"
```

---

### Task 7: 디바운스 저장 + 초기화 메뉴

**Files:**
- Modify: `gui/widgets/video_player.py` (`_ControlBar._show_subtitle_menu` 489행, `InlinePlayer`)
- Test: `tests/gui/test_subtitle_player.py`
  (**`test_subtitle_wiring.py` 가 아니다** — 그 파일은 `SongViewModel` 을 목으로 검증하는
  파일이라 `player` 픽스처도 `_track()` 헬퍼도 없다. 둘 다 `test_subtitle_player.py` 에 있다.)

**Interfaces:**
- Consumes: `InlinePlayer._nudge_subtitle_scale/_nudge_subtitle_bottom`,
  `InlinePlayer._apply_subtitle_prefs` (Task 5), `config.settings.save_setting` (Task 2),
  `LyricsOverlay.FONT_SCALE_DEFAULT/BOTTOM_RATIO_DEFAULT` (Task 4)
- Produces: `_ControlBar.subtitle_prefs_reset = pyqtSignal()`,
  `InlinePlayer._reset_subtitle_prefs() -> None`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/gui/test_subtitle_player.py` 아래에 추가(같은 파일의 `player` 픽스처·`_track()` 재사용):

```python
class TestSubtitlePrefsPersistence:
    def test_연속_조절이_한_번만_저장된다(self, player, monkeypatch):
        """휠은 이벤트가 쏟아지므로 500ms 디바운스 후 1회만 기록한다."""
        from PyQt6.QtTest import QTest
        import config.settings as settings

        saved: list[tuple] = []
        monkeypatch.setattr(settings, "save_setting", lambda k, v: saved.append((k, v)))

        player.set_lyrics(_track())
        for _ in range(5):
            player._nudge_subtitle_scale(0.1)
        assert saved == []                 # 아직 디바운스 중
        QTest.qWait(700)
        keys = [k for k, _ in saved]
        assert keys.count("subtitle_font_scale") == 1

    def test_초기화가_기본값으로_되돌린다(self, player):
        player.set_lyrics(_track())
        player._nudge_subtitle_scale(0.5)
        player._nudge_subtitle_bottom(0.1)
        player._reset_subtitle_prefs()
        assert player._subtitle.font_scale == LyricsOverlay.FONT_SCALE_DEFAULT
        assert player._subtitle.bottom_ratio == LyricsOverlay.BOTTOM_RATIO_DEFAULT
```

파일 상단 import 에 `LyricsOverlay` 를 더한다(기존 줄이
`from gui.widgets.lyrics_overlay import LyricsCue, LyricsTrack` 이므로 `LyricsOverlay` 를 추가):

```python
from gui.widgets.lyrics_overlay import LyricsCue, LyricsOverlay, LyricsTrack
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/gui/test_subtitle_player.py::TestSubtitlePrefsPersistence -v`
Expected: FAIL — `AttributeError: '_reset_subtitle_prefs'`

- [ ] **Step 3: 디바운스 타이머 추가**

`InlinePlayer.__init__` 의 `_transient_timer` 아래에 추가:

```python
        # 휠은 이벤트가 연속으로 쏟아지므로 자막 오프셋과 같은 500ms 디바운스로
        # 마지막 값만 한 번 기록한다.
        self._prefs_save_timer = QTimer(self)
        self._prefs_save_timer.setSingleShot(True)
        self._prefs_save_timer.setInterval(500)
        self._prefs_save_timer.timeout.connect(self._flush_subtitle_prefs)
```

- [ ] **Step 4: 저장 메서드 추가**

`_nudge_subtitle_bottom` 아래에 추가:

```python
    def _queue_subtitle_prefs_save(self) -> None:
        self._prefs_save_timer.start()

    def _flush_subtitle_prefs(self) -> None:
        try:
            settings.save_setting("subtitle_font_scale", self._subtitle_font_scale)
            settings.save_setting("subtitle_bottom_ratio", self._subtitle_bottom_ratio)
        except OSError:
            logger.exception("자막 표시 설정 저장 실패")

    def _reset_subtitle_prefs(self) -> None:
        self._subtitle_font_scale = LyricsOverlay.FONT_SCALE_DEFAULT
        self._subtitle_bottom_ratio = LyricsOverlay.BOTTOM_RATIO_DEFAULT
        self._apply_subtitle_prefs()
        self._show_transient("자막 크기·위치 초기화")
        self._queue_subtitle_prefs_save()
```

`_nudge_subtitle_scale` 과 `_nudge_subtitle_bottom` 의 마지막 줄
(`self._show_transient(...)`) 다음에 각각 `self._queue_subtitle_prefs_save()` 를 더한다.

- [ ] **Step 5: 위젯 종료 시 남은 값 flush**

`InlinePlayer.closeEvent`(1052행 — 807행 `_PipWindow`·887행 `_FullscreenWindow` 의 것과
혼동하지 말 것) 안, 분리 창 정리 코드 앞에 추가한다:

```python
        if self._prefs_save_timer.isActive():
            self._prefs_save_timer.stop()
            self._flush_subtitle_prefs()
```

- [ ] **Step 6: 초기화 메뉴 항목 추가**

`_ControlBar` 시그널 선언부에 추가:

```python
    subtitle_prefs_reset = pyqtSignal()
```

`_show_subtitle_menu` 의 마지막 `menu.addAction("초기화", ...)` 아래에 한 줄 더한다:

```python
        menu.addAction("자막 크기·위치 초기화", self.subtitle_prefs_reset.emit)
```

`InlinePlayer` 의 컨트롤바 배선부(`self._bar.subtitle_offset_nudged.connect(...)` 근처)와
`_enter_fullscreen`/`_enter_pip` 의 `bar.subtitle_offset_nudged.connect(...)` 옆에
각각 추가한다(3곳):

```python
        self._bar.subtitle_prefs_reset.connect(self._reset_subtitle_prefs)
```

```python
        bar.subtitle_prefs_reset.connect(self._reset_subtitle_prefs)
```

- [ ] **Step 7: 테스트 통과 확인 + 전체 회귀**

Run: `python -m pytest tests/gui/ -q`
Expected: 전부 PASS

Run: `python -m pytest -q`
Expected: 전부 PASS

- [ ] **Step 8: 린트 + 커밋**

Run: `python -m ruff check gui/widgets/video_player.py tests/gui/test_subtitle_player.py --output-format=concise`
Expected: `All checks passed!`

```bash
git add gui/widgets/video_player.py tests/gui/test_subtitle_player.py
git commit -m "feat: 자막 크기·위치 500ms 디바운스 저장 + 초기화 메뉴

- 휠은 이벤트가 쏟아지므로 마지막 값만 1회 config.yaml 에 기록
- 위젯이 닫힐 때 대기 중인 값을 flush
- 💬 우클릭 메뉴에 '자막 크기·위치 초기화' 추가(인라인·전체화면·PiP 3곳 배선)"
```

---

### Task 8: 문서 갱신

**Files:**
- Modify: `CLAUDE.md`
- Modify: `planning/youtube_content_manager_prd.md`

**Interfaces:**
- Consumes: Task 1~7 전부
- Produces: 없음

- [ ] **Step 1: `CLAUDE.md` — 검색 규칙 기록**

"**영상 검색 (부분 일치)**" 항목 끝에 문장을 추가한다:

```
**가사는 최상위 카테고리가 음악인 영상만 검색한다** — 루트 조상 카테고리 이름이
`music`·`음악`·`노래`(`MUSIC_ROOT_CATEGORY_NAMES`, trim+소문자 비교)일 때만 대상이며
미분류는 제외한다. 게이트는 `_lyrics_match_ids`(검색 결과)와 `match_fields_for`(배지)
**양쪽에 똑같이** 걸어야 한다 — 한쪽만 걸면 "가사로 검색됐는데 배지는 없는" 불일치가 난다.
루트 해석은 재귀 CTE이고 `depth < 32` 가드가 필수다(`categories`에 순환을 막는 제약이
`UNIQUE(name, parent_id)`뿐이라 데이터가 순환하면 앱이 멈춘다). 부수 효과로 매 검색마다
전체 가사를 JSON 파싱하던 부담이 줄어든다.
```

- [ ] **Step 2: `CLAUDE.md` — 자막 조작·구조 기록**

"**가사 자막 표시 · 싱크 조정**" 항목 끝에 추가한다:

```
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
```

- [ ] **Step 3: PRD 기능 요구사항 추가**

`planning/youtube_content_manager_prd.md` 의 검색·자막 관련 절에 두 항목을 추가한다:

```
- 가사 검색은 최상위 카테고리가 음악(Music/음악/노래)인 영상으로 한정한다.
- 자막 글자 크기와 세로 위치를 Ctrl(+Shift) + 휠·방향키로 조절하고 전역 설정으로 유지한다.
```

- [ ] **Step 4: 최종 전체 검증**

Run: `python -m pytest -q`
Expected: 전부 PASS

- [ ] **Step 5: 커밋**

```bash
git add CLAUDE.md planning/youtube_content_manager_prd.md
git commit -m "docs: 가사 검색 범위 제한·자막 크기/위치 조절 문서화"
```

---

## 완료 기준

- [ ] `python -m pytest -q` 전부 통과
- [ ] `python -m ruff check <변경 파일들>` 새 위반 없음
- [ ] 앱을 실제로 띄워 확인(`/verify`): 비음악 카테고리 영상이 가사로 안 걸리는지,
      `Ctrl`+휠로 자막이 커지고 `Ctrl+Shift`+휠로 위아래로 움직이는지, 앱을 껐다 켜도
      값이 유지되는지, 전체화면·PiP에서도 같은 크기·위치인지
