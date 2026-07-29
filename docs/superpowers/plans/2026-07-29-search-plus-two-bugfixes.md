# 검색 확장 + 로컬 루트 선택 표시 + 중복 실행 수정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "로컬" 루트 선택이 트리에 보이게 하고, 업데이트 후 앱이 하나만 실행되게 하고, 검색을 제목·태그·설명·메모·요약·노래·가사로 확장하면서 각 결과 카드에 일치한 속성을 표시한다.

**Architecture:** 세 항목은 독립적이다. 버그1은 `_PlaylistPanel`에 활성 상태 하나를 추가하는 GUI 변경이다. 버그2는 인스톨러 플래그 한 줄과 `QLocalServer` 기반 단일 인스턴스 가드다. 검색은 `SqliteVideoRepository._build_search_sql`의 FTS 분기를 부분 일치 서브쿼리로 바꾸고, 일치 속성 판정은 현재 페이지에만 실행하는 별도 메서드로 분리해 `VideoDTO`에 실어 GUI 델리게이트가 배지로 그린다.

**Tech Stack:** Python 3.10+, PyQt6 (`QLocalServer`/`QLocalSocket`, `QStyledItemDelegate`), SQLite (`LIKE ... ESCAPE`), pytest / pytest-qt, Inno Setup

**Spec:** `docs/superpowers/specs/2026-07-29-search-plus-two-bugfixes-design.md`

## Global Constraints

- 모든 문서·주석·커밋 메시지는 **한국어**로 작성한다. 코드 식별자·라이브러리명·SQL 키워드는 영어 유지.
- **`lyrics_json`에 SQL `LIKE`를 쓰지 않는다.** JSON 키(`"o"`, `"t"`)에 걸려 검색어 `o`·`t`가 모든 노래를 오탐한다(실측 확인). 반드시 파싱해서 원문·번역 텍스트만 비교한다.
- **`videos_fts`와 동기화 트리거는 제거하지 않는다.** `tests/integration/test_merge_applier.py:173~181`이 동기화 병합 후 FTS 트리거 발화를 검증하는 데 사용한다.
- **`main.py` 종료 tail의 `start "" "<exe>"`(`:524`)는 그대로 둔다.** 배치는 구버전 앱이 만들고 인스톨러는 신버전이므로, `installer.iss`와 배치를 모두 고치면 다음다음 업데이트에서 아무도 앱을 실행하지 않는다.
- SQLite `LIKE`는 ASCII 대소문자를 이미 무시한다(`'ABC' LIKE '%bc%'` → 1). `LOWER()`를 씌우지 않는다.
- 일치 속성 식별자는 도메인/애플리케이션에서 영어 키(`title`·`tags`·`description`·`notes`·`summary`·`song`·`lyrics`)로 다루고, 한글 라벨 매핑은 GUI만 갖는다.
- 모듈마다 `logger = logging.getLogger(__name__)`. 예외를 조용히 삼키지 말고 `logger.exception`/`logger.warning`으로 남긴다.
- 검색어가 비어 있으면 `match_fields`는 빈 튜플이고 배지도 그리지 않는다.
- GUI 파일을 수정하므로 마지막에 `/verify`로 실앱 기동을 확인한다.
- `tests/gui/test_smoke.py`의 3건(`test_widget_has_expected_tabs`, `test_local_root_requests_categorized_only`, `test_playlist_view_not_categorized_only`)은 **작업 전부터 main에서 실패하던 기존 문제**다. 실패 건수가 3보다 늘지 않으면 통과로 본다.

## File Structure

| 파일 | 책임 | 변경 |
| --- | --- | --- |
| `gui/panels/library_panel.py` | 로컬 루트 활성 상태, 검색 배지 델리게이트, 모델 롤 | 수정 |
| `tests/gui/test_local_root_active.py` | 로컬 루트 선택 표시 검증 | 생성 |
| `packaging/installer.iss` | `[Run]`에 `skipifsilent` | 수정 |
| `gui/single_instance.py` | `SingleInstanceGuard` | 생성 |
| `tests/gui/test_single_instance.py` | 가드 동작·인스톨러 플래그 검증 | 생성 |
| `main.py` | 가드 배선 (DB 열기 전) | 수정 |
| `infrastructure/persistence/sqlite_video_repository.py` | 부분 일치 검색 + `match_fields_for` | 수정 |
| `domain/library/repositories.py` | `match_fields_for` 인터페이스 | 수정 |
| `tests/integration/test_search_fields.py` | 필드별 매칭·가사 오탐 회귀·이스케이프 | 생성 |
| `application/library/dtos.py` | `VideoDTO.match_fields` | 수정 |
| `application/library/queries.py` | 핸들러가 match_fields 주입 | 수정 |
| `CLAUDE.md` / `db/AGENTS.md` / `infrastructure/persistence/AGENTS.md` / `planning/youtube_content_manager_prd.md` | 기록 | 수정 |

---

### Task 1: 버그1 — "로컬" 루트 선택 표시

**Files:**
- Modify: `gui/panels/library_panel.py:3010~3016`(`local_hdr` 생성), `:3159~3174`(`select_snapshot`), `hdr_style`(`:4353~` 구역)
- Test: `tests/gui/test_local_root_active.py` (생성)

**Interfaces:**
- Consumes: `_PlaylistPanel.trees -> list[_PlaylistTree]`(기존, `:3112`), `_PlaylistTree.select_for_snapshot(snap) -> bool`(기존)
- Produces: `_PlaylistPanel.set_local_root_active(active: bool) -> None`, `_PlaylistPanel.is_local_root_active() -> bool`

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`tests/gui/test_local_root_active.py` 생성:

```python
"""좌측 트리 최상단 "로컬" 선택이 시각적으로 드러나는지 검증한다.

기존 문제: local_hdr 클릭이 category_selected.emit(None)만 호출해 목록은 바뀌지만
직전에 선택된 카테고리 노드의 선택 표시가 남아 어느 것이 활성인지 헷갈렸다.
"""
from __future__ import annotations

from uuid import uuid4

from gui.panels.library_panel import _PlaylistPanel


class TestLocalRootActive:
    def test_starts_inactive(self, qapp_instance):
        panel = _PlaylistPanel()
        assert panel.is_local_root_active() is False

    def test_header_click_activates_and_emits(self, qapp_instance):
        panel = _PlaylistPanel()
        received: list = []
        panel.category_selected.connect(received.append)

        panel._local_hdr.click()

        assert panel.is_local_root_active() is True
        assert received == [None]

    def test_header_click_clears_tree_selection(self, qapp_instance):
        """핵심 회귀 — 이전에 선택한 노드의 선택이 지워져야 한다."""
        panel = _PlaylistPanel()
        tree = panel.trees[0]
        item = tree._make_category("AI Coding", uuid4(), video_count=1)
        tree.addTopLevelItem(item)
        tree.setCurrentItem(item)
        assert tree.selectedItems() != []

        panel._local_hdr.click()

        assert tree.selectedItems() == [], "로컬 클릭 후에도 트리 선택이 남아 있다"

    def test_clearing_selection_does_not_reemit(self, qapp_instance):
        """선택 해제가 시그널을 타 핸들러를 다시 실행하면 안 된다(이중 실행 방지)."""
        panel = _PlaylistPanel()
        tree = panel.trees[0]
        item = tree._make_category("Movies", uuid4(), video_count=1)
        tree.addTopLevelItem(item)
        tree.setCurrentItem(item)

        received: list = []
        panel.category_selected.connect(received.append)
        panel._local_hdr.click()

        assert received == [None], f"category_selected가 중복 방출됨: {received}"

    def test_tree_selection_deactivates_header(self, qapp_instance):
        panel = _PlaylistPanel()
        panel.set_local_root_active(True)
        tree = panel.trees[0]
        item = tree._make_category("Redis", uuid4(), video_count=1)
        tree.addTopLevelItem(item)

        tree.setCurrentItem(item)

        assert panel.is_local_root_active() is False

    def test_checked_state_follows_active(self, qapp_instance):
        """QSS :checked 규칙이 걸리도록 체크 상태가 동기화돼야 한다."""
        panel = _PlaylistPanel()
        panel.set_local_root_active(True)
        assert panel._local_hdr.isChecked() is True
        panel.set_local_root_active(False)
        assert panel._local_hdr.isChecked() is False
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/gui/test_local_root_active.py -v`
Expected: FAIL — `AttributeError: '_PlaylistPanel' object has no attribute 'is_local_root_active'`

- [ ] **Step 3: 헤더를 인스턴스 속성으로 바꾸고 체크 가능하게 한다**

`gui/panels/library_panel.py`의 `local_hdr` 생성부(`:3010~3016`)를 수정한다. 기존 `local_hdr` 지역 변수를 `self._local_hdr`로 바꾸고 아래 줄들을 반영한다:

```python
        self._local_hdr = QPushButton("📁  로컬")
        self._local_hdr.setObjectName("playlist_section_header_local")
        self._local_hdr.setFlat(True)
        self._local_hdr.setCheckable(True)   # QSS :checked 로 활성 표시
        self._local_hdr.setCursor(Qt.CursorShape.PointingHandCursor)
        self._local_hdr.setToolTip("클릭: 카테고리 전체 영상 표시")
        self._local_hdr.clicked.connect(self._on_local_root_clicked)
        local_hdr_row.addWidget(self._local_hdr, stretch=1)
```

같은 블록 아래에서 `local_hdr`을 참조하는 다른 줄이 있으면 `self._local_hdr`로 함께 바꾼다:
```bash
grep -n "local_hdr" gui/panels/library_panel.py
```

- [ ] **Step 4: 활성 상태 API와 클릭 핸들러를 추가한다**

`_PlaylistPanel`의 `trees` 프로퍼티(`:3112`) 근처에 추가한다:

```python
    # ── "로컬" 루트 활성 상태 ────────────────────────────────────────────────
    def is_local_root_active(self) -> bool:
        return self._local_hdr.isChecked()

    def set_local_root_active(self, active: bool) -> None:
        """"로컬" 헤더의 활성 표시를 켜고 끈다(QSS :checked 규칙이 걸린다)."""
        if self._local_hdr.isChecked() != active:
            self._local_hdr.setChecked(active)

    def _clear_tree_selection(self) -> None:
        """두 트리의 선택을 해제한다.

        blockSignals로 감싸 currentItemChanged가 선택 핸들러를 재실행하지 않게 한다
        (select_snapshot이 쓰는 것과 같은 패턴).
        """
        for tr in self.trees:
            tr.blockSignals(True)
            tr.clearSelection()
            tr.setCurrentItem(None)
            tr.blockSignals(False)

    def _on_local_root_clicked(self) -> None:
        """"로컬" 헤더 클릭 — 트리 선택을 지우고 헤더를 활성으로 표시한다."""
        self._clear_tree_selection()
        self.set_local_root_active(True)
        self.category_selected.emit(None)
```

- [ ] **Step 5: 트리 노드를 선택하면 헤더를 비활성으로 만든다**

`_PlaylistPanel.__init__`에서 두 트리가 만들어진 뒤(`self._yt_tree` 생성 이후) 배선을 추가한다:

```python
        # 트리에서 노드를 선택하면 "로컬" 루트 활성 표시를 해제한다.
        for _tr in self.trees:
            _tr.currentItemChanged.connect(self._on_tree_current_changed)
```

그리고 메서드를 추가한다:

```python
    def _on_tree_current_changed(self, current, _prev) -> None:
        if current is not None:
            self.set_local_root_active(False)
```

- [ ] **Step 6: 뒤로/앞으로 복원 시에도 동기화한다**

`select_snapshot`(`:3159~3174`)의 끝에 한 줄을 더한다. 스냅샷이 어떤 트리 노드와도 일치하지 않으면 로컬 루트로 간주한다:

```python
        # 어떤 트리 노드와도 일치하지 않으면 "로컬" 루트 화면이다.
        self.set_local_root_active(matched is None)
```

- [ ] **Step 7: QSS에 활성 규칙을 추가한다**

`hdr_style`의 `QPushButton#playlist_section_header_local:hover` 규칙 뒤에 추가한다:

```
            QPushButton#playlist_section_header_local:checked {{
                color: {tok.accent};
                background: {tok.bg_overlay};
                border-radius: 4px;
            }}
```

- [ ] **Step 8: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/gui/test_local_root_active.py -v`
Expected: PASS — 6개 통과

`_PlaylistPanel()`이 인자 없이 생성되지 않으면(생성자 시그니처 확인 필요) 테스트에서 필요한 인자를 채운다:
```bash
grep -n "class _PlaylistPanel" -A 8 gui/panels/library_panel.py
```

- [ ] **Step 9: 커밋한다**

```bash
python -m pytest tests/gui/ -q
python -m ruff check tests/gui/test_local_root_active.py
git add gui/panels/library_panel.py tests/gui/test_local_root_active.py
git commit -m "fix: '로컬' 루트를 선택해도 트리 선택이 남던 문제 수정

- local_hdr 클릭이 목록 갱신만 요청하고 트리 선택을 건드리지 않았음
- set_local_root_active()로 헤더 활성 표시(QSS :checked)를 관리하고
  클릭 시 두 트리 선택을 blockSignals로 감싸 해제(이중 실행 방지)
- 트리 노드 선택 시 헤더 비활성, 뒤로/앞으로 복원 시에도 동기화"
```

---

### Task 2: 버그2 — 업데이트 후 중복 실행

**Files:**
- Modify: `packaging/installer.iss` (`[Run]` 항목)
- Create: `gui/single_instance.py`
- Modify: `main.py` (`QApplication` 생성 직후)
- Test: `tests/gui/test_single_instance.py` (생성)

**Interfaces:**
- Produces:
  - `gui.single_instance.SingleInstanceGuard(key: str | None = None)`
  - `.try_acquire() -> bool` — True면 이 프로세스가 유일, False면 이미 실행 중
  - `.set_activate_callback(fn: Callable[[], None]) -> None`
  - `.release() -> None`

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`tests/gui/test_single_instance.py` 생성:

```python
"""단일 인스턴스 가드와 인스톨러 플래그를 검증한다.

업데이트 후 앱이 2개 실행되던 원인은 두 곳이 각각 앱을 띄웠기 때문이다:
1) installer.iss [Run] 항목에 skipifsilent 가 없어 무인 설치에서도 Inno가 실행
2) main.py 종료 tail 배치의 start "" "<exe>"
"""
from __future__ import annotations

from pathlib import Path

from gui.single_instance import SingleInstanceGuard


class TestSingleInstanceGuard:
    def test_first_acquire_succeeds(self, qapp_instance):
        guard = SingleInstanceGuard(key="ovc-test-first")
        try:
            assert guard.try_acquire() is True
        finally:
            guard.release()

    def test_second_acquire_fails(self, qapp_instance):
        """핵심 — 같은 키로 두 번째 획득은 실패해야 한다."""
        first = SingleInstanceGuard(key="ovc-test-second")
        second = SingleInstanceGuard(key="ovc-test-second")
        try:
            assert first.try_acquire() is True
            assert second.try_acquire() is False
        finally:
            second.release()
            first.release()

    def test_reacquire_after_release(self, qapp_instance):
        """정상 종료 후 다시 획득할 수 있어야 한다(잠금이 남지 않음)."""
        guard = SingleInstanceGuard(key="ovc-test-cycle")
        assert guard.try_acquire() is True
        guard.release()

        again = SingleInstanceGuard(key="ovc-test-cycle")
        try:
            assert again.try_acquire() is True
        finally:
            again.release()

    def test_different_keys_do_not_conflict(self, qapp_instance):
        a = SingleInstanceGuard(key="ovc-test-a")
        b = SingleInstanceGuard(key="ovc-test-b")
        try:
            assert a.try_acquire() is True
            assert b.try_acquire() is True
        finally:
            a.release()
            b.release()

    def test_default_key_is_user_scoped(self, qapp_instance):
        """다중 사용자 환경에서 서로 막지 않도록 키에 사용자명이 들어가야 한다."""
        import getpass

        guard = SingleInstanceGuard()
        assert "ovc" in guard.key
        assert getpass.getuser() in guard.key


class TestInstallerFlags:
    def test_run_entry_has_skipifsilent(self):
        """무인 설치에서 Inno가 앱을 실행하지 않도록 skipifsilent 가 있어야 한다."""
        iss = Path("packaging/installer.iss").read_text(encoding="utf-8", errors="replace")
        run_lines = [
            ln for ln in iss.splitlines()
            if ln.strip().startswith("Filename:") and "YouTubeContentManager.exe" in ln
        ]
        assert run_lines, "[Run] 항목을 찾지 못했다"
        for ln in run_lines:
            assert "skipifsilent" in ln, f"skipifsilent 누락: {ln.strip()}"

    def test_exit_tail_still_launches_app(self):
        """배치의 start 줄은 유지돼야 한다 — 양쪽을 모두 막으면 아무도 앱을 띄우지 않는다.

        installer.iss 에 skipifsilent 를 넣었으므로 재실행 주체는 이 배치 하나뿐이다.
        """
        main_src = Path("main.py").read_text(encoding="utf-8", errors="replace")
        bat_lines = [ln for ln in main_src.splitlines() if "_bat_content" in ln]
        assert any("start" in ln for ln in bat_lines), (
            "종료 tail 배치에서 앱을 재실행하는 start 줄이 사라졌다 — "
            "installer.iss 의 skipifsilent 와 함께라면 앱이 아예 실행되지 않는다"
        )
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/gui/test_single_instance.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gui.single_instance'` 및 `skipifsilent 누락`

- [ ] **Step 3: `SingleInstanceGuard`를 구현한다**

`gui/single_instance.py` 생성:

```python
"""단일 인스턴스 가드 — 앱이 두 번 실행되는 것을 막는다.

업데이트 직후 인스톨러와 종료 tail 배치가 각각 앱을 띄워 2개가 실행되는 문제가 있었다.
근본 원인은 `packaging/installer.iss`의 `[Run]` 플래그로 고치지만, 사용자가 아이콘을
연달아 누르는 경우까지 막으려면 앱 자체에도 가드가 필요하다.

QLocalServer/QLocalSocket을 쓴다 — 파일 잠금과 달리 비정상 종료 후 잠금이 남아도
removeServer()로 회수할 수 있고, 두 번째 인스턴스가 기존 창을 앞으로 불러올 수 있다.
"""

from __future__ import annotations

import getpass
import logging
from collections.abc import Callable

from PyQt6.QtCore import QObject
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT_MS = 300


def _default_key() -> str:
    """사용자별 키 — 다중 사용자 환경에서 서로를 막지 않게 한다."""
    try:
        user = getpass.getuser()
    except Exception:
        logger.warning("사용자명 조회 실패 — 공용 키를 쓴다", exc_info=True)
        user = "shared"
    return f"ovc-single-instance-{user}"


class SingleInstanceGuard(QObject):
    """이 프로세스가 유일한 인스턴스인지 판별하고, 두 번째 실행을 기존 창으로 넘긴다."""

    def __init__(self, key: str | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.key = key or _default_key()
        self._server: QLocalServer | None = None
        self._activate: Callable[[], None] | None = None

    def set_activate_callback(self, fn: Callable[[], None]) -> None:
        """두 번째 인스턴스가 접속했을 때 호출된다(기존 창을 앞으로 부르는 용도)."""
        self._activate = fn

    def try_acquire(self) -> bool:
        """유일 인스턴스면 True. 이미 실행 중이면 신호만 보내고 False."""
        probe = QLocalSocket()
        probe.connectToServer(self.key)
        if probe.waitForConnected(_CONNECT_TIMEOUT_MS):
            # 기존 인스턴스가 살아 있다 — 창을 띄우라고 알리고 물러난다.
            probe.write(b"activate")
            probe.flush()
            probe.waitForBytesWritten(_CONNECT_TIMEOUT_MS)
            probe.disconnectFromServer()
            return False
        probe.abort()

        # 비정상 종료로 남은 소켓이 있으면 listen()이 실패하므로 먼저 회수한다.
        QLocalServer.removeServer(self.key)
        server = QLocalServer(self)
        if not server.listen(self.key):
            logger.warning("단일 인스턴스 서버 리스닝 실패(%s) — 가드 없이 계속한다", server.errorString())
            return True
        server.newConnection.connect(self._on_new_connection)
        self._server = server
        return True

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        QLocalServer.removeServer(self.key)

    def _on_new_connection(self) -> None:
        if self._server is None:
            return
        conn = self._server.nextPendingConnection()
        if conn is not None:
            conn.disconnectFromServer()
        if self._activate is not None:
            try:
                self._activate()
            except Exception:
                logger.exception("기존 창 활성화 실패")
```

`PyQt6.QtNetwork`가 설치돼 있는지 확인한다(PyQt6 기본 포함):
```bash
python -c "from PyQt6.QtNetwork import QLocalServer; print('QtNetwork OK')"
```

- [ ] **Step 4: 인스톨러 플래그를 고친다**

`packaging/installer.iss`의 `[Run]` 항목을 수정한다:

```
Filename: "{app}\YouTubeContentManager.exe"; Description: "Launch YouTube Content Manager"; Flags: postinstall nowait skipifsilent
```

그리고 위쪽 주석에 이유를 남긴다(기존 주석이 `RestartApplications=no`만 설명하고 있어 오해를 부른다):

```
; [Run] postinstall 은 무인 설치(/VERYSILENT)에서도 실행되므로 skipifsilent 를 붙인다.
; 업데이트 후 앱 재실행은 main.py 종료 tail 배치가 단독으로 담당한다 — 양쪽이 모두
; 실행하면 인스턴스가 2개가 되고, 양쪽을 모두 막으면 아무도 실행하지 않는다.
```

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/gui/test_single_instance.py -v`
Expected: PASS — 7개 통과

- [ ] **Step 6: `main.py`에 가드를 배선한다**

`main.py`의 `main()`에서 `app = QApplication(...)` 직후, **DB를 열거나 `pre_db_bootstrap()`을 호출하기 전에** 넣는다. 두 프로세스가 같은 DB를 동시에 건드리지 않게 하려면 이 순서가 중요하다.

먼저 현재 위치를 확인한다:
```bash
grep -n "app = QApplication\|pre_db_bootstrap\|_splash" main.py | head
```

`app.setFont(...)` 다음 줄에 추가한다:

```python
    # 단일 인스턴스 가드 — 업데이트 직후 인스톨러/배치가 겹쳐 실행되거나 사용자가
    # 아이콘을 연달아 눌러도 하나만 살아남게 한다. DB를 열기 전에 판단해야
    # 두 프로세스가 같은 DB를 동시에 건드리지 않는다.
    from gui.single_instance import SingleInstanceGuard  # noqa: PLC0415

    _guard = SingleInstanceGuard()
    if not _guard.try_acquire():
        logger.info("이미 실행 중인 인스턴스가 있어 종료한다")
        return 0
```

`window`가 만들어진 뒤(`window.show()` 근처)에 활성화 콜백을 연결한다:

```python
    def _activate_existing() -> None:
        window.showNormal()
        window.raise_()
        window.activateWindow()

    _guard.set_activate_callback(_activate_existing)
```

`app.exec()` 반환 뒤, 종료 tail보다 앞에서 해제한다:

```python
    _guard.release()
```

`logger`가 이 시점에 정의돼 있는지 확인한다(`setup_logging()` 이후여야 한다):
```bash
grep -n "setup_logging()\|^logger = \|logger = logging" main.py | head
```
`logger`가 아직 없으면 `logging.getLogger(__name__).info(...)`를 직접 쓴다.

- [ ] **Step 7: 실앱이 정상 기동하고 두 번째 실행이 즉시 종료되는지 확인한다**

Run:
```bash
timeout 25 python main.py > /tmp/inst1.txt 2>&1 &
sleep 12
timeout 20 python main.py > /tmp/inst2.txt 2>&1; echo "두번째 EXIT=$?"
tail -5 /tmp/inst2.txt
```
Expected: 두 번째 프로세스가 즉시(수 초 내) 종료되고 로그에 "이미 실행 중인 인스턴스가 있어 종료한다"가 남는다. 첫 번째는 계속 실행된다.

- [ ] **Step 8: 커밋한다**

```bash
python -m ruff check gui/single_instance.py main.py tests/gui/test_single_instance.py
git add gui/single_instance.py main.py packaging/installer.iss tests/gui/test_single_instance.py
git commit -m "fix: 업데이트 후 앱이 2개 실행되던 문제 수정

- 원인: installer.iss [Run] 에 skipifsilent 가 없어 무인 설치에서도 Inno가 앱을
  실행하고, main.py 종료 tail 배치의 start 도 실행해 2개가 떴음
- installer.iss 에 skipifsilent 추가 — 재실행 주체를 배치 하나로 고정.
  배치는 구버전이 만들고 인스톨러는 신버전이라 양쪽을 다 고치면 미실행이 됨
- SingleInstanceGuard(QLocalServer) 추가 — 어떤 경로로 겹쳐 실행돼도 하나만 남고
  두 번째는 기존 창을 앞으로 불러온 뒤 종료. DB 열기 전에 판단해 동시 접근 방지"
```

---

### Task 3: 검색 리포지토리 — 부분 일치 + 일치 필드 판정

이 태스크가 기능의 핵심이며 GUI 없이 단독 검증된다.

**Files:**
- Modify: `domain/library/repositories.py` (인터페이스에 `match_fields_for` 추가)
- Modify: `infrastructure/persistence/sqlite_video_repository.py:13~23`(`_sanitize_fts_query` 제거), `:425~439`(FTS 분기 교체), 새 메서드 추가
- Test: `tests/integration/test_search_fields.py` (생성)

**Interfaces:**
- Consumes: `Database(path=...)` + `.initialize()`, `SqliteVideoRepository(db)`, `SearchQuery(text=...)`, `VideoAggregate.create(VideoUrl(url), title)`, `agg.update_metadata(description=…, notes=…, gemini_summary=…)`, `repo.get_or_create_tag(name) -> Tag`, `agg.set_tags([tag_id])`, `SqliteSongRepository(db)`, `SongInfoAggregate.create(video_id)`, `agg.edit_field(field, value)`, `agg.apply_fetched(lyrics_lines=[LyricsLine(...)], mark_song=True)`
- Produces:
  - `MATCH_FIELD_KEYS: tuple[str, ...]` = `("title", "tags", "description", "notes", "summary", "song", "lyrics")` (in `domain/library/repositories.py`)
  - `IVideoRepository.match_fields_for(video_ids: list[UUID], text: str) -> dict[UUID, tuple[str, ...]]`

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`tests/integration/test_search_fields.py` 생성:

```python
"""검색이 제목·태그·설명·메모·요약·노래·가사를 모두 덮는지, 일치 필드를 정확히
보고하는지 검증한다.

핵심 회귀: lyrics_json 은 [{"o": 원문, "t": 번역}] 형태의 JSON 문자열이라
SQL LIKE 를 쓰면 검색어 'o'·'t' 가 JSON 키에 걸려 모든 노래를 오탐한다.
"""
from __future__ import annotations

import pytest

from domain.library.aggregates import VideoAggregate
from domain.library.repositories import SearchQuery
from domain.library.value_objects import VideoUrl
from domain.song.aggregates import SongInfoAggregate
from domain.song.value_objects import LyricsLine
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_song_repository import SqliteSongRepository
from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository


@pytest.fixture
def db(tmp_path):
    d = Database(path=tmp_path / "search.db")
    d.initialize()
    return d


@pytest.fixture
def repo(db):
    return SqliteVideoRepository(db)


@pytest.fixture
def songs(db):
    return SqliteSongRepository(db)


def _add(repo, url, title, **meta):
    agg = VideoAggregate.create(VideoUrl(url), title)
    if meta:
        agg.update_metadata(**meta)
    repo.save(agg)
    return agg


def _ids(results):
    return {a.id for a in results}


class TestFieldCoverage:
    def test_title(self, repo):
        a = _add(repo, "https://youtu.be/t1", "파이썬 강의")
        _add(repo, "https://youtu.be/t2", "자바 강의")
        assert _ids(repo.search(SearchQuery(text="파이썬"))) == {a.id}

    def test_notes(self, repo):
        a = _add(repo, "https://youtu.be/n1", "무제", notes="레디스 캐시 정리")
        _add(repo, "https://youtu.be/n2", "무제2")
        assert _ids(repo.search(SearchQuery(text="레디스"))) == {a.id}

    def test_summary(self, repo):
        a = _add(repo, "https://youtu.be/s1", "무제", gemini_summary="옵시디언 활용법 요약")
        _add(repo, "https://youtu.be/s2", "무제2")
        assert _ids(repo.search(SearchQuery(text="옵시디언"))) == {a.id}

    def test_description(self, repo):
        a = _add(repo, "https://youtu.be/d1", "무제", description="이 영상은 도커를 다룬다")
        _add(repo, "https://youtu.be/d2", "무제2")
        assert _ids(repo.search(SearchQuery(text="도커"))) == {a.id}

    def test_tags(self, repo):
        a = _add(repo, "https://youtu.be/g1", "무제")
        tag = repo.get_or_create_tag("바이브코딩")
        a.set_tags([tag.id])
        repo.save(a)
        _add(repo, "https://youtu.be/g2", "무제2")
        assert _ids(repo.search(SearchQuery(text="바이브"))) == {a.id}

    def test_song_fields(self, repo, songs):
        a = _add(repo, "https://youtu.be/m1", "무제")
        s = SongInfoAggregate.create(a.id)
        s.set_song_flag(True)
        s.edit_field("artist", "모리카와 미호")
        songs.save(s)
        _add(repo, "https://youtu.be/m2", "무제2")
        assert _ids(repo.search(SearchQuery(text="모리카와"))) == {a.id}

    def test_lyrics(self, repo, songs):
        a = _add(repo, "https://youtu.be/l1", "무제")
        s = SongInfoAggregate.create(a.id)
        s.apply_fetched(
            lyrics_lines=[LyricsLine("You will be in my heart", "내 마음속에")],
            mark_song=True,
        )
        songs.save(s)
        _add(repo, "https://youtu.be/l2", "무제2")
        assert _ids(repo.search(SearchQuery(text="heart"))) == {a.id}
        assert _ids(repo.search(SearchQuery(text="마음속"))) == {a.id}


class TestLyricsJsonFalsePositive:
    """가사를 SQL LIKE 로 다루면 안 되는 이유를 고정한다."""

    def test_json_key_does_not_match(self, repo, songs):
        a = _add(repo, "https://youtu.be/j1", "무제")
        s = SongInfoAggregate.create(a.id)
        s.apply_fetched(
            lyrics_lines=[LyricsLine("Sunshine", "햇살")],
            mark_song=True,
        )
        songs.save(s)

        # 'o'·'t' 는 lyrics_json 의 키 이름이다. 원문/번역에 없으므로 매칭되면 안 된다.
        assert _ids(repo.search(SearchQuery(text="o"))) == set()
        assert _ids(repo.search(SearchQuery(text="t"))) == set()

    def test_real_lyrics_word_still_matches(self, repo, songs):
        a = _add(repo, "https://youtu.be/j2", "무제")
        s = SongInfoAggregate.create(a.id)
        s.apply_fetched(lyrics_lines=[LyricsLine("Sunshine", "햇살")], mark_song=True)
        songs.save(s)
        assert _ids(repo.search(SearchQuery(text="Sunshine"))) == {a.id}


class TestSubstringAndEscaping:
    def test_partial_match_inside_word(self, repo):
        """한글 어미가 붙어도 찾아야 한다."""
        a = _add(repo, "https://youtu.be/p1", "가정부라고 개무시 받던")
        assert _ids(repo.search(SearchQuery(text="가정부"))) == {a.id}

    def test_case_insensitive_ascii(self, repo):
        a = _add(repo, "https://youtu.be/c1", "Obsidian 정리")
        assert _ids(repo.search(SearchQuery(text="obsidian"))) == {a.id}

    def test_percent_is_literal(self, repo):
        a = _add(repo, "https://youtu.be/e1", "할인 50% 행사")
        _add(repo, "https://youtu.be/e2", "관계없는 제목")
        assert _ids(repo.search(SearchQuery(text="50%"))) == {a.id}

    def test_underscore_is_literal(self, repo):
        a = _add(repo, "https://youtu.be/e3", "snake_case 규칙")
        _add(repo, "https://youtu.be/e4", "snakeXcase 규칙")
        assert _ids(repo.search(SearchQuery(text="snake_case"))) == {a.id}

    def test_empty_text_returns_all(self, repo):
        _add(repo, "https://youtu.be/a1", "하나")
        _add(repo, "https://youtu.be/a2", "둘")
        assert len(repo.search(SearchQuery(text=""))) == 2


class TestMatchFieldsFor:
    def test_reports_matching_field(self, repo):
        a = _add(repo, "https://youtu.be/f1", "파이썬 강의")
        result = repo.match_fields_for([a.id], "파이썬")
        assert result[a.id] == ("title",)

    def test_reports_multiple_fields(self, repo):
        a = _add(repo, "https://youtu.be/f2", "레디스 입문", notes="레디스 메모")
        result = repo.match_fields_for([a.id], "레디스")
        assert set(result[a.id]) == {"title", "notes"}

    def test_reports_lyrics_field(self, repo, songs):
        a = _add(repo, "https://youtu.be/f3", "무제")
        s = SongInfoAggregate.create(a.id)
        s.apply_fetched(lyrics_lines=[LyricsLine("Moonlight", "달빛")], mark_song=True)
        songs.save(s)
        result = repo.match_fields_for([a.id], "달빛")
        assert result[a.id] == ("lyrics",)

    def test_reports_song_field(self, repo, songs):
        a = _add(repo, "https://youtu.be/f4", "무제")
        s = SongInfoAggregate.create(a.id)
        s.set_song_flag(True)
        s.edit_field("album", "Blue Water")
        songs.save(s)
        result = repo.match_fields_for([a.id], "Blue")
        assert result[a.id] == ("song",)

    def test_empty_text_returns_empty(self, repo):
        a = _add(repo, "https://youtu.be/f5", "무제")
        assert repo.match_fields_for([a.id], "") == {}

    def test_empty_ids_returns_empty(self, repo):
        assert repo.match_fields_for([], "무엇") == {}

    def test_no_match_omits_video(self, repo):
        a = _add(repo, "https://youtu.be/f6", "무제")
        assert repo.match_fields_for([a.id], "없는키워드").get(a.id, ()) == ()

    def test_field_order_follows_match_field_keys(self, repo):
        """표시 순서가 MATCH_FIELD_KEYS 를 따라 실행마다 흔들리지 않아야 한다."""
        from domain.library.repositories import MATCH_FIELD_KEYS

        a = _add(repo, "https://youtu.be/f7", "키워드", notes="키워드", gemini_summary="키워드")
        got = repo.match_fields_for([a.id], "키워드")[a.id]

        assert set(got) == {"title", "notes", "summary"}
        # MATCH_FIELD_KEYS 순서: title < notes < summary
        assert list(got) == [k for k in MATCH_FIELD_KEYS if k in set(got)]
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/integration/test_search_fields.py -q`
Expected: FAIL — `AttributeError: 'SqliteVideoRepository' object has no attribute 'match_fields_for'` 및 설명·태그·노래·가사 검색 미지원으로 다수 실패

- [ ] **Step 3: 필드 키 상수와 인터페이스를 추가한다**

`domain/library/repositories.py`의 `_ALLOWED_SORT_COLUMNS` 아래에 추가한다:

```python
# 검색 일치 속성 식별자 — 표시 순서를 고정한다. 한글 라벨 매핑은 GUI가 갖는다.
MATCH_FIELD_KEYS: tuple[str, ...] = (
    "title", "tags", "description", "notes", "summary", "song", "lyrics",
)
```

`IVideoRepository`에 추상 메서드를 추가한다(`search` 뒤):

```python
    @abstractmethod
    def match_fields_for(
        self, video_ids: list[UUID], text: str
    ) -> dict[UUID, tuple[str, ...]]:
        """각 영상이 검색어와 어느 속성에서 일치했는지 반환한다.

        반환 값은 MATCH_FIELD_KEYS 순서를 따른다. 일치가 없는 영상은 키를 생략한다.
        현재 페이지 분량(기본 50건)만 넘겨 호출하는 것을 전제로 한다.
        """
```

- [ ] **Step 4: 부분 일치 검색으로 교체한다**

`infrastructure/persistence/sqlite_video_repository.py`에서 `_sanitize_fts_query`(`:13~23`) 전체를 삭제하고, 대신 아래 헬퍼들을 같은 위치에 넣는다:

```python
import json
import logging

logger = logging.getLogger(__name__)

# LIKE 패턴에서 특수 취급되는 문자 — ESCAPE 절과 함께 이스케이프한다.
_LIKE_ESCAPE = "\\"


def _like_pattern(text: str) -> str:
    """부분 일치용 LIKE 패턴을 만든다.

    %·_ 는 LIKE 와일드카드이고 백슬래시는 우리가 지정한 ESCAPE 문자이므로 모두
    이스케이프해야 사용자가 입력한 문자 그대로 찾는다.
    """
    escaped = (
        text.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2)
        .replace("%", _LIKE_ESCAPE + "%")
        .replace("_", _LIKE_ESCAPE + "_")
    )
    return f"%{escaped}%"


def _lyrics_text(lyrics_json: str) -> str:
    """lyrics_json 에서 원문·번역 텍스트만 뽑아 이어붙인다.

    JSON 문자열에 LIKE 를 직접 쓰면 검색어 'o'·'t' 가 키 이름에 걸려 모든 노래를
    오탐한다. 그래서 파싱해 값만 비교한다.
    """
    try:
        lines = json.loads(lyrics_json or "[]")
    except (ValueError, TypeError):
        logger.warning("가사 JSON 파싱 실패 — 가사 검색에서 제외한다")
        return ""
    parts: list[str] = []
    for ln in lines:
        if isinstance(ln, dict):
            parts.append(str(ln.get("o", "")))
            parts.append(str(ln.get("t", "")))
    return "\n".join(parts)
```

`SqliteVideoRepository`에 가사 일치 id를 구하는 내부 메서드를 추가한다:

```python
    def _lyrics_match_ids(self, text: str) -> list[str]:
        """가사(원문·번역)에 검색어가 든 video_id 목록을 반환한다."""
        needle = text.lower()
        rows = self._db.connection.execute(
            "SELECT video_id, lyrics_json FROM song_info WHERE lyrics_json <> '[]'"
        ).fetchall()
        hits = []
        for r in rows:
            if needle in _lyrics_text(r["lyrics_json"]).lower():
                hits.append(r["video_id"])
        return hits
```

`_build_search_sql`의 FTS 분기(`:432~439`)를 다음으로 교체한다:

```python
        if query.text:
            like = _like_pattern(query.text)
            clauses = [
                "SELECT id FROM videos WHERE title LIKE ? ESCAPE '\\'",
                "SELECT id FROM videos WHERE notes LIKE ? ESCAPE '\\'",
                "SELECT id FROM videos WHERE gemini_summary LIKE ? ESCAPE '\\'",
                "SELECT video_id FROM video_descriptions WHERE description LIKE ? ESCAPE '\\'",
                "SELECT vt.video_id FROM video_tags vt JOIN tags t ON t.id = vt.tag_id "
                "WHERE t.name LIKE ? ESCAPE '\\'",
                "SELECT video_id FROM song_info WHERE artist LIKE ? ESCAPE '\\' "
                "OR album LIKE ? ESCAPE '\\' OR song_title LIKE ? ESCAPE '\\' "
                "OR release_year LIKE ? ESCAPE '\\'",
            ]
            union = " UNION ".join(clauses)
            # ? 개수를 세어 바인딩한다 — 절을 추가·삭제해도 어긋나지 않는다.
            text_params = [like] * union.count("?")

            lyric_ids = self._lyrics_match_ids(query.text)
            if lyric_ids:
                ph = ",".join("?" * len(lyric_ids))
                where.append(f"(videos.id IN ({union}) OR videos.id IN ({ph}))")
                params.extend(text_params)
                params.extend(lyric_ids)
            else:
                where.append(f"videos.id IN ({union})")
                params.extend(text_params)
```

> 플레이스홀더 개수를 **하드코딩하지 않는다.** 앞 5개 절이 각 `?` 1개, `song_info` 절이 4개로
> 지금은 9개지만, 절을 고치면 어긋난다. `union.count("?")`로 세는 형태를 유지한다.

- [ ] **Step 5: `match_fields_for`를 구현한다**

`SqliteVideoRepository`에 추가한다:

```python
    def match_fields_for(
        self, video_ids: list[UUID], text: str
    ) -> dict[UUID, tuple[str, ...]]:
        """각 영상이 검색어와 어느 속성에서 일치했는지 판정한다.

        현재 페이지(기본 50건)에만 실행하므로 영상당 몇 번의 인덱스 조회로 끝난다.
        """
        if not text or not video_ids:
            return {}

        ids = [str(v) for v in video_ids]
        ph = ",".join("?" * len(ids))
        like = _like_pattern(text)
        conn = self._db.connection
        found: dict[str, set[str]] = {i: set() for i in ids}

        def _mark(sql: str, key: str, extra: int = 1) -> None:
            rows = conn.execute(sql.format(ph=ph), [*ids, *([like] * extra)]).fetchall()
            for r in rows:
                found[r[0]].add(key)

        _mark("SELECT id FROM videos WHERE id IN ({ph}) AND title LIKE ? ESCAPE '\\'", "title")
        _mark("SELECT id FROM videos WHERE id IN ({ph}) AND notes LIKE ? ESCAPE '\\'", "notes")
        _mark(
            "SELECT id FROM videos WHERE id IN ({ph}) AND gemini_summary LIKE ? ESCAPE '\\'",
            "summary",
        )
        _mark(
            "SELECT video_id FROM video_descriptions WHERE video_id IN ({ph}) "
            "AND description LIKE ? ESCAPE '\\'",
            "description",
        )
        _mark(
            "SELECT vt.video_id FROM video_tags vt JOIN tags t ON t.id = vt.tag_id "
            "WHERE vt.video_id IN ({ph}) AND t.name LIKE ? ESCAPE '\\'",
            "tags",
        )
        _mark(
            "SELECT video_id FROM song_info WHERE video_id IN ({ph}) AND ("
            "artist LIKE ? ESCAPE '\\' OR album LIKE ? ESCAPE '\\' "
            "OR song_title LIKE ? ESCAPE '\\' OR release_year LIKE ? ESCAPE '\\')",
            "song",
            extra=4,
        )

        # 가사는 파싱해서 비교한다(JSON 키 오탐 방지).
        needle = text.lower()
        rows = conn.execute(
            f"SELECT video_id, lyrics_json FROM song_info WHERE video_id IN ({ph})", ids
        ).fetchall()
        for r in rows:
            if needle in _lyrics_text(r["lyrics_json"]).lower():
                found[r["video_id"]].add("lyrics")

        out: dict[UUID, tuple[str, ...]] = {}
        for i, keys in found.items():
            if keys:
                out[UUID(i)] = tuple(k for k in MATCH_FIELD_KEYS if k in keys)
        return out
```

파일 상단 import에 `MATCH_FIELD_KEYS`를 추가한다:
```python
from domain.library.repositories import IVideoRepository, MATCH_FIELD_KEYS, SearchQuery
```

`self._db.connection`이 올바른 접근자인지 확인한다:
```bash
grep -n "self._db\." infrastructure/persistence/sqlite_video_repository.py | head -3
```

- [ ] **Step 6: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/integration/test_search_fields.py -v`
Expected: PASS — 24개 통과

- [ ] **Step 7: 기존 검색 테스트와 FTS 트리거 테스트가 깨지지 않았는지 확인한다**

Run: `python -m pytest tests/integration/ -q`
Expected: PASS — 특히 `test_merge_applier.py`의 FTS 트리거 검증이 계속 통과해야 한다(FTS 테이블은 남겼으므로).

`_sanitize_fts_query`를 참조하는 곳이 남았는지 확인한다:
```bash
grep -rn "_sanitize_fts_query" --include=*.py .
```
Expected: 결과 없음

- [ ] **Step 8: 커밋한다**

```bash
python -m ruff check infrastructure/persistence/sqlite_video_repository.py domain/library/repositories.py tests/integration/test_search_fields.py
git add infrastructure/persistence/sqlite_video_repository.py domain/library/repositories.py tests/integration/test_search_fields.py
git commit -m "feat: 검색을 제목·태그·설명·메모·요약·노래·가사로 확장

- videos_fts MATCH(제목·메모만) → 부분 일치 UNION 서브쿼리로 교체
- 한글 어미가 붙어도 찾도록 substring 매칭, %·_ 는 ESCAPE 로 리터럴 처리
- 가사는 lyrics_json 을 파싱해 원문·번역만 비교 — SQL LIKE 는 키('o','t')에
  걸려 검색어 o·t 가 모든 노래를 오탐함(회귀 테스트로 고정)
- match_fields_for(): 현재 페이지에만 실행해 일치 속성을 MATCH_FIELD_KEYS 순서로 반환
- 사용처가 사라진 _sanitize_fts_query 제거. videos_fts 는 동기화 트리거 검증에 쓰여 유지"
```

---

### Task 4: 검색 결과 카드에 일치 속성 배지

**Files:**
- Modify: `application/library/dtos.py:23~38`(`VideoDTO`)
- Modify: `application/library/queries.py:153~179`(`SearchVideosHandler`)
- Modify: `gui/panels/library_panel.py` — `VideoListModel`(`:887~900` 롤, `data()`), `_IconDelegate`(`:603`), `_ListDelegate`(`:742`)
- Test: `tests/unit/application/test_match_field_labels.py` (생성), `tests/gui/test_match_badge.py` (생성)

**Interfaces:**
- Consumes: `IVideoRepository.match_fields_for(video_ids, text) -> dict[UUID, tuple[str, ...]]`(Task 3), `MATCH_FIELD_KEYS`(Task 3), `chip_colors(tokens, selected, data_color=None)`(기존)
- Produces:
  - `VideoDTO.match_fields: tuple[str, ...] = ()`
  - `VideoListModel.MatchFieldsRole = Qt.ItemDataRole.UserRole + 14`
  - `gui.panels.library_panel.MATCH_FIELD_LABELS: dict[str, str]`

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`tests/unit/application/test_match_field_labels.py` 생성:

```python
"""일치 속성 키가 한글 라벨로 온전히 매핑되는지 검증한다.

키(영어)는 도메인/애플리케이션이 다루고 표시 문자열은 GUI만 갖는다.
키를 추가하고 라벨을 빼먹으면 배지에 영어가 노출되므로 테스트로 막는다.
"""
from __future__ import annotations

from domain.library.repositories import MATCH_FIELD_KEYS


class TestMatchFieldLabels:
    def test_every_key_has_korean_label(self):
        from gui.panels.library_panel import MATCH_FIELD_LABELS

        for key in MATCH_FIELD_KEYS:
            assert key in MATCH_FIELD_LABELS, f"라벨 누락: {key}"
            assert MATCH_FIELD_LABELS[key], f"라벨이 비었다: {key}"

    def test_no_extra_labels(self):
        from gui.panels.library_panel import MATCH_FIELD_LABELS

        assert set(MATCH_FIELD_LABELS) == set(MATCH_FIELD_KEYS)

    def test_expected_labels(self):
        from gui.panels.library_panel import MATCH_FIELD_LABELS

        assert MATCH_FIELD_LABELS["title"] == "제목"
        assert MATCH_FIELD_LABELS["lyrics"] == "가사"
        assert MATCH_FIELD_LABELS["summary"] == "요약"
```

`tests/gui/test_match_badge.py` 생성:

```python
"""VideoDTO.match_fields 가 모델 롤로 전달되는지 검증한다."""
from __future__ import annotations

from uuid import uuid4

from application.library.dtos import VideoDTO
from gui.panels.library_panel import VideoListModel


def _dto(match_fields=()):
    return VideoDTO(
        id=uuid4(),
        url="https://youtu.be/x",
        title="제목",
        channel_name="채널",
        thumbnail_path="",
        duration_sec=60,
        favorite=False,
        watched=False,
        category_id=None,
        match_fields=match_fields,
    )


class TestMatchFieldsRole:
    def test_default_is_empty(self, qapp_instance):
        model = VideoListModel()
        model.set_videos([_dto()])
        idx = model.index(0, 0)
        assert model.data(idx, VideoListModel.MatchFieldsRole) == ()

    def test_role_returns_fields(self, qapp_instance):
        model = VideoListModel()
        model.set_videos([_dto(("title", "lyrics"))])
        idx = model.index(0, 0)
        assert model.data(idx, VideoListModel.MatchFieldsRole) == ("title", "lyrics")

    def test_role_id_does_not_collide(self):
        used = {
            v for k, v in vars(VideoListModel).items()
            if k.endswith("Role") and isinstance(v, int)
        }
        assert len(used) == len([
            k for k in vars(VideoListModel) if k.endswith("Role")
        ]), "롤 상수 값이 중복됐다"
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/unit/application/test_match_field_labels.py tests/gui/test_match_badge.py -v`
Expected: FAIL — `ImportError: cannot import name 'MATCH_FIELD_LABELS'`, `VideoDTO()`에 `match_fields` 인자 없음

- [ ] **Step 3: `VideoDTO`에 필드를 추가한다**

`application/library/dtos.py`의 `VideoDTO` 맨 끝에 추가한다:

```python
    # 검색 시 어느 속성이 일치했는지(도메인 MATCH_FIELD_KEYS 순서). 검색어가 없으면 빈 튜플.
    match_fields: tuple[str, ...] = ()
```

- [ ] **Step 4: 검색 핸들러가 match_fields를 채우게 한다**

`application/library/queries.py`의 `SearchVideosHandler.handle`을 수정한다:

```python
    def handle(self, query: SearchVideosQuery) -> list[VideoDTO]:
        cats = _cats_dict(self._repo)
        tag_id_to_name = _tags_dict(self._repo)
        aggs = self._repo.search(
            SearchQuery(
                text=query.text,
                category_id=query.category_id,
                category_ids=query.category_ids,
                tag_ids=query.tag_ids,
                video_ids=query.video_ids,
                categorized_only=query.categorized_only,
                favorite_only=query.favorite_only,
                limit=query.limit,
                offset=query.offset,
                sort_by=query.sort_by,
                sort_asc=query.sort_asc,
                min_duration_sec=query.min_duration_sec,
                max_duration_sec=query.max_duration_sec,
            )
        )
        dtos = [_to_dto(agg, cats, tag_id_to_name) for agg in aggs]
        if not query.text:
            return dtos
        # 일치 속성은 현재 페이지에만 판정한다(전체 스캔 방지).
        matches = self._repo.match_fields_for([d.id for d in dtos], query.text)
        return [
            replace(d, match_fields=matches.get(d.id, ()))
            for d in dtos
        ]
```

파일 상단 import에 `replace`를 추가한다:
```python
from dataclasses import replace
```

- [ ] **Step 5: 모델 롤과 라벨 매핑을 추가한다**

`gui/panels/library_panel.py`의 `VideoListModel`에 롤을 추가한다(`TagNamesRole` 뒤):

```python
    MatchFieldsRole = Qt.ItemDataRole.UserRole + 14
```

`data()`에서 `TagNamesRole` 처리 근처에 추가한다:

```python
        if role == self.MatchFieldsRole:
            return dto.match_fields
```

라벨 매핑을 모듈 상단(`_TAG_PALETTE` 근처)에 추가한다:

```python
# 검색 일치 속성 배지 라벨 — 도메인은 영어 키를 쓰고 표시 문자열은 GUI가 갖는다.
MATCH_FIELD_LABELS: dict[str, str] = {
    "title": "제목",
    "tags": "태그",
    "description": "설명",
    "notes": "메모",
    "summary": "요약",
    "song": "노래",
    "lyrics": "가사",
}
```

- [ ] **Step 6: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/unit/application/test_match_field_labels.py tests/gui/test_match_badge.py -v`
Expected: PASS — 6개 통과

- [ ] **Step 7: 두 델리게이트에 배지를 그린다**

먼저 각 델리게이트가 카드 하단을 어떻게 그리는지 읽는다:
```bash
sed -n '603,742p' gui/panels/library_panel.py
sed -n '742,890p' gui/panels/library_panel.py
```

공용 그리기 헬퍼를 두 델리게이트 앞(`class _IconDelegate` 직전)에 추가한다:

```python
def _paint_match_badges(painter, rect, keys: tuple[str, ...]) -> int:
    """검색 일치 속성 배지를 rect 안 좌측부터 그린다. 그린 높이를 반환한다.

    keys 가 비면 아무것도 그리지 않고 0을 반환한다(검색 중이 아닐 때).
    """
    if not keys:
        return 0
    tokens = ThemeManager.instance().current()
    c = chip_colors(tokens, selected=False)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setFont(QFont("", 7))
    fm = painter.fontMetrics()
    x = rect.left()
    h = 15
    y = rect.top()
    for key in keys:
        label = MATCH_FIELD_LABELS.get(key, key)
        w = fm.horizontalAdvance(label) + 12
        if x + w > rect.right():
            break
        chip = QRect(x, y, w, h)
        painter.setBrush(QBrush(QColor(c["bg"])))
        painter.setPen(QPen(QColor(tokens.accent), 1))
        painter.drawRoundedRect(chip, 7, 7)
        painter.setPen(QColor(tokens.accent))
        painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, label)
        x += w + 4
    painter.restore()
    return h
```

두 델리게이트의 좌표 변수와 삽입 위치는 아래와 같다(사전 확인 완료).

**`_IconDelegate`** — 좌표 변수는 `text_x`·`text_w`·`title_top`이고 마지막 텍스트 행(`row3_rect`)이
`title_top + 60`(높이 16)이다. 배지는 그 아래 `title_top + 78`에 그린다.
`row3_rect`를 그린 뒤(`painter.restore()` 직후, 호버/선택 테두리를 그리기 **전**)에 삽입한다:

```python
        match_keys: tuple = index.data(VideoListModel.MatchFieldsRole) or ()
        if match_keys:
            _paint_match_badges(
                painter, QRect(text_x, title_top + 78, text_w, 15), match_keys
            )
```

높이 확보: `_ITEM_H = _TH_ICON + _ICON_TEXT_H`(`:608`)이므로 `_ICON_TEXT_H`에 `_MATCH_ROW_H`를
더한다. 검색 중일 때만 높이를 바꾸면 타이핑마다 그리드가 리플로우되므로 **항상** 확보한다.

**`_ListDelegate`** — 좌표 변수는 `text_x`·`text_w`·`text_top`이고 태그 행(`tag_rect`)이
`text_top + 82`(높이 16)이다. 배지는 `text_top + 100`에 그린다. 같은 위치 규칙으로 삽입한다:

```python
        match_keys: tuple = index.data(VideoListModel.MatchFieldsRole) or ()
        if match_keys:
            _paint_match_badges(
                painter, QRect(text_x, text_top + 100, text_w, 15), match_keys
            )
```

높이 확보: `_ROW_H = _TH_LIST + 40`(`:745`)을 `_TH_LIST + 40 + _MATCH_ROW_H`로 바꾼다.

모듈 상단에 상수를 둔다:

```python
_MATCH_ROW_H = 18   # 검색 일치 속성 배지 한 줄 높이(항상 확보해 리플로우 방지)
```

- [ ] **Step 8: 실앱에서 배지를 확인한다**

`/verify` 스킬로 앱을 실행해 다음을 확인한다:
1. 검색창에 라이브러리에 있는 단어를 입력하면 결과가 나오고, 각 카드 하단에 `제목`·`태그` 등 배지가 보이는가
2. 노래 가사에만 있는 단어로 검색하면 그 영상이 나오고 배지에 `가사`가 표시되는가
3. 검색어를 지우면 배지가 사라지는가
4. 그리드 뷰와 리스트 뷰 **양쪽** 모두에서 배지가 보이는가

- [ ] **Step 9: 커밋한다**

```bash
python -m pytest tests/ -q
python -m ruff check application/library/dtos.py application/library/queries.py tests/unit/application/test_match_field_labels.py tests/gui/test_match_badge.py
git add application/library/dtos.py application/library/queries.py gui/panels/library_panel.py tests/unit/application/test_match_field_labels.py tests/gui/test_match_badge.py
git commit -m "feat: 검색 결과 카드에 일치 속성 배지 표시

- VideoDTO.match_fields 추가, SearchVideosHandler 가 현재 페이지만 판정해 채움
- VideoListModel.MatchFieldsRole 로 전달하고 그리드·리스트 델리게이트 양쪽에 배지
- 한글 라벨(MATCH_FIELD_LABELS)은 GUI가 보유 — 도메인은 영어 키만 다룸
- 검색어가 없으면 배지를 그리지 않음"
```

---

### Task 5: 문서 갱신

**Files:**
- Modify: `CLAUDE.md`, `db/AGENTS.md`, `infrastructure/persistence/AGENTS.md`, `planning/youtube_content_manager_prd.md`

**Interfaces:**
- Consumes: Task 1~4의 최종 동작
- Produces: 없음 (문서)

- [ ] **Step 1: 사실과 달라진 AGENTS.md 두 곳을 고친다**

`db/AGENTS.md:19`와 `:28~29`는 "FTS5로 검색한다"고 적고 있으나 이제 사실이 아니다. 다음으로 바꾼다:

```markdown
- 영상 검색은 **부분 일치(LIKE)** 로 제목·태그·설명·메모·요약·노래·가사를 덮는다.
  `videos_fts`(FTS5)는 검색에 쓰지 않지만, 동기화 병합 후 트리거 발화를 검증하는
  `tests/integration/test_merge_applier.py`가 사용하므로 유지한다.
```

`infrastructure/persistence/AGENTS.md:28`도 같은 취지로 고친다:

```markdown
- `SqliteVideoRepository.search()`는 부분 일치(LIKE + ESCAPE) UNION 서브쿼리를 쓴다.
  가사는 `lyrics_json` 을 파싱해 비교한다 — JSON 키(`"o"`,`"t"`)에 LIKE 가 걸려
  검색어 `o`·`t` 가 모든 노래를 오탐하기 때문이다.
```

- [ ] **Step 2: `CLAUDE.md`에 설계 결정을 기록한다**

Key Design Decisions에 불릿을 추가한다:

```markdown
- **영상 검색 (부분 일치)** — `SqliteVideoRepository._build_search_sql`이 **제목·태그·설명·메모·요약·노래(가수/앨범/제목/발매년도)·가사**를 부분 일치(`LIKE ... ESCAPE '\'`)로 덮는다. 과거에는 `videos_fts`(FTS5)가 **제목·메모 두 열만** 덮었다. FTS5 대신 부분 일치를 쓰는 이유: ① 한글은 어미가 붙어 단어 단위 매칭이 자주 빗나간다 ② 어느 속성이 일치했는지 판정이 정확하다 ③ 규모가 작다(영상 수백 건). **가사는 절대 SQL `LIKE`로 다루지 않는다** — `lyrics_json`이 `[{"o":원문,"t":번역}]` 형태라 검색어 `o`·`t`가 JSON 키에 걸려 모든 노래를 오탐한다(회귀 테스트 `tests/integration/test_search_fields.py::TestLyricsJsonFalsePositive`로 고정). 일치 속성은 `match_fields_for(video_ids, text)`가 **현재 페이지 50건에만** 실행해 `MATCH_FIELD_KEYS` 순서로 반환하고, `VideoDTO.match_fields`로 실려 `VideoListModel.MatchFieldsRole`을 거쳐 그리드·리스트 델리게이트가 배지로 그린다. 한글 라벨(`MATCH_FIELD_LABELS`)은 GUI만 갖는다. `LIKE '%...%'`는 인덱스를 타지 않으므로 라이브러리가 수만 건이 되면 통합 FTS 테이블로 되돌리는 것이 맞다. `videos_fts`와 트리거는 `test_merge_applier.py`가 동기화 병합 후 발화를 검증하는 데 쓰므로 **제거하지 않았다**.
- **단일 인스턴스 가드** — `gui/single_instance.py`의 `SingleInstanceGuard`(QLocalServer/QLocalSocket)가 앱 중복 실행을 막는다. `main.py`가 **DB를 열기 전에** `try_acquire()`를 호출해 두 프로세스가 같은 DB를 동시에 건드리지 않게 하고, 이미 실행 중이면 기존 창을 앞으로 부른 뒤 조용히 종료한다. 서버 이름은 사용자별(`ovc-single-instance-<username>`)이며 비정상 종료로 남은 소켓은 `removeServer()`로 회수한다. **업데이트 후 2개 실행의 근본 원인은 `packaging/installer.iss`의 `[Run]`에 `skipifsilent`가 없어 무인 설치에서도 Inno가 앱을 실행한 것**이었다(배치의 `start`와 중복). **재실행 주체는 배치 하나로 고정한다** — 배치는 구버전 앱이 만들고 인스톨러는 신버전이라, 양쪽을 모두 막으면 다음다음 업데이트에서 아무도 앱을 실행하지 않는다.
```

- [ ] **Step 3: `gui/` 파일 맵을 갱신한다**

`CLAUDE.md`의 `gui/` 트리에 `single_instance.py`를 추가하고 `library_panel.py` 설명에 배지·로컬 루트 활성 상태를 덧붙인다:

- `gui/` 트리에 한 줄 추가:
  ```
  │   ├── single_instance.py           # SingleInstanceGuard — QLocalServer 기반 중복 실행 방지(main.py가 DB 열기 전 호출)
  ```
- `library_panel.py` 설명 끝에 추가:
  ```
  . **"로컬" 루트 활성 표시**: `_PlaylistPanel.set_local_root_active()`가 `local_hdr`의 체크 상태(QSS `:checked`)를 관리하고, 헤더 클릭 시 두 트리 선택을 `blockSignals`로 감싸 해제한다(이중 실행 방지). 트리 노드 선택 시 비활성, `select_snapshot` 복원 시 `matched is None`이면 활성. **검색 일치 속성 배지**는 `_paint_match_badges`가 그리드·리스트 델리게이트 양쪽에서 그린다(`MatchFieldsRole` → `MATCH_FIELD_LABELS`)
  ```

- [ ] **Step 4: PRD에 요구사항을 추가한다**

`planning/youtube_content_manager_prd.md`의 `### 6. 검색 & 필터` 섹션(`:114` 부근)을 읽고, 검색 대상 확장을 반영한다:

```markdown
- **전 속성 검색**: 검색어를 입력하면 영상 제목·태그·설명·메모·요약·노래 정보(가수/앨범/제목/발매년도)·가사에서 찾는다. 부분 일치이므로 "가정부"로 "가정부라고"도 찾는다.
- **일치 속성 표시**: 각 결과 카드 하단에 어느 속성에서 일치했는지 배지로 표시해, 그 영상이 왜 검색됐는지 바로 알 수 있다.
```

문서 맨 끝 로드맵에도 항목을 추가한다(직전이 `### v1.9+`이므로 그 뒤):

```markdown
### v1.10+ — 검색 강화 & 안정성

1. **전 속성 검색**: 제목만이 아니라 태그·설명·메모·요약·노래 정보·가사까지 한 번에 찾는다. 각 결과 카드 하단에 일치한 속성을 배지로 보여준다.
2. **"로컬" 선택 표시**: 좌측 트리 최상단 "로컬"을 눌렀을 때 이전 카테고리 선택이 남아 헷갈리던 문제를 고친다. 이제 "로컬"이 활성으로 표시되고 트리 선택은 해제된다.
3. **중복 실행 방지**: 업데이트 후 앱이 2개 실행되던 문제를 고친다. 인스톨러와 재실행 배치가 각각 앱을 띄우던 것을 하나로 정리하고, 어떤 경로로든 중복 실행되면 기존 창을 앞으로 불러온다.
```

- [ ] **Step 5: 커밋한다**

```bash
git add CLAUDE.md db/AGENTS.md infrastructure/persistence/AGENTS.md planning/youtube_content_manager_prd.md
git commit -m "docs: 검색 확장·중복 실행 방지·로컬 루트 표시 기록

- CLAUDE.md: 부분 일치 검색 전환 근거, 가사 JSON 오탐 주의, 단일 인스턴스 가드,
  installer.iss 와 배치 중 한쪽만 고쳐야 하는 이유
- AGENTS.md 2곳: 'FTS5로 검색' 서술이 사실과 달라져 수정
- PRD: 검색 & 필터 항목 보강 + v1.10+ 로드맵"
```
