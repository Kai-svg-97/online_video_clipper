# 등록 시 요약·가사 자동 채우기 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 단건 등록 직후, 음원용 영상이면 "노래" 탭 가사를, 아니면 "요약" 탭(`gemini_summary`)을 백그라운드에서 자동으로 채운다.

**Architecture:** 등록(`AddVideoHandler`)은 지금처럼 즉시 끝내고 `video_id`를 반환한다. `LibraryViewModel`이 별도 `QThread`로 새 `EnrichVideoHandler`를 호출하며, 이 핸들러가 `song_info.is_song`을 읽어 가사 조회(`FetchSongInfoHandler`)와 요약 추출(`ISummarySource`) 중 하나만 실행한다. 일괄 임포트 경로는 `AddVideoHandler`를 직접 호출하고 ViewModel을 지나지 않으므로 자동으로 제외된다.

**Tech Stack:** Python 3.10+, PyQt6 (`QThread` + 시그널), pytest / pytest-qt, Playwright 기반 `GeminiExtractor`(기존), yt-dlp(기존)

**Spec:** `docs/superpowers/specs/2026-07-28-auto-enrich-on-add-design.md`

## Global Constraints

- 모든 대화·문서·코드 주석은 **한국어**로 작성한다. 코드 식별자·라이브러리명·SQL 키워드는 영어 유지.
- DDD 계층 의존 규칙 준수: `gui → application → domain ← infrastructure`. application 레이어는 infrastructure의 구체 클래스를 직접 import 하지 않고 `domain/shared/ports.py`의 Protocol에 의존한다.
- 모듈마다 `logger = logging.getLogger(__name__)`를 정의한다. 예외를 조용히 삼키지 말고 `logger.exception("맥락")` 또는 `logger.warning`으로 흔적을 남긴다.
- 백그라운드 워커를 만드는 ViewModel은 `shutdown()`에서 워커를 정리한다. 협조적 취소 훅이 없으면 `terminate()` 후 `wait()`.
- GUI 파일(`gui/` 하위)을 수정했으면 마지막에 `/verify` 스킬로 실앱을 실행해 확인한다.
- 새 설정 키는 `config/settings.py`의 `_load_bool` 패턴 + `save_setting`의 `mapping` 딕셔너리에 **둘 다** 등록해야 런타임 갱신이 동작한다.
- 커밋 메시지는 한국어, `feat:`/`fix:`/`docs:`/`chore:` 접두 + 핵심 변경 불릿.
- 일괄 임포트 경로(`ImportYouTubePlaylistToCategoryHandler`, `ImportYouTubePlaylistHandler`, `AddUrlToPlaylistHandler`)는 **수정하지 않는다**.

## File Structure

| 파일 | 책임 | 변경 |
| --- | --- | --- |
| `domain/shared/ports.py` | `ISummarySource` Protocol 추가 | 수정 |
| `application/library/commands.py` | `EnrichVideoCommand`·`EnrichVideoResult`·`EnrichVideoHandler` | 수정 |
| `tests/unit/application/test_enrich_video.py` | 분기·건너뛰기·폴백 없음 검증 | 생성 |
| `tests/gui/test_auto_enrich_toggle.py` | 설정 OFF·동시 1건 큐 검증 | 생성 |
| `tests/gui/conftest.py` | `library_vm` 픽스처에 `enrich_video` 추가 | 수정 |
| `config/settings.py` | `AUTO_ENRICH_ON_ADD` 토글 | 수정 |
| `gui/panels/settings_panel.py` | 일반 섹션에 체크박스 | 수정 |
| `gui/view_models/library_vm.py` | `_EnrichWorker`, 시그널, 동시 1건 큐, shutdown | 수정 |
| `gui/main_window.py` | 상태바 진행/실패 표시 | 수정 |
| `gui/panels/library_panel.py` | 보강 완료 시 열린 상세 재로드 | 수정 |
| `main.py` | `EnrichVideoHandler` 조립·주입 | 수정 |
| `CLAUDE.md` / `planning/youtube_content_manager_prd.md` | 규칙·요구사항 기록 | 수정 |

---

### Task 1: `ISummarySource` 포트 + `EnrichVideoHandler`

분기 정책의 전부가 여기 들어간다. GUI 없이 단독으로 테스트되는 유일한 태스크다.

**Files:**
- Modify: `domain/shared/ports.py` (파일 끝 `IClipExtractor` 뒤에 추가)
- Modify: `application/library/commands.py` (`AddVideoHandler` 뒤, `UpdateVideoHandler` 앞)
- Test: `tests/unit/application/test_enrich_video.py` (생성)

**Interfaces:**
- Consumes:
  - `domain.library.repositories.IVideoRepository` — `get_by_id(video_id: UUID) -> VideoAggregate | None`, `save(agg) -> None`
  - `domain.song.repositories.ISongRepository` — `get(video_id: UUID) -> SongInfoAggregate | None`
  - `application.song.commands.FetchSongInfoHandler.handle(FetchSongInfoCommand) -> SongInfoAggregate | None`
  - `domain.library.aggregates.VideoAggregate` — `.id`, `.video.url`, `.video.gemini_summary`, `.update_metadata(gemini_summary=…)`, `.pull_events()`
  - `domain.song.aggregates.SongInfoAggregate` — `.info.is_song`, `.info.lyrics_lines`
- Produces:
  - `ISummarySource` Protocol — `extract(self, url: str) -> str`
  - `EnrichVideoCommand(video_id: UUID)`
  - `EnrichVideoResult(kind: str, ok: bool, detail: str = "")` — `kind`는 `"song" | "summary" | "skipped"`
  - `EnrichVideoHandler(repo, song_repo, song_fetch=None, summary_source=None, event_bus=None)`
    - `.handle(cmd: EnrichVideoCommand) -> EnrichVideoResult`
    - `.is_song_video(video_id: UUID) -> bool` — 상태바 라벨용 사전 판정

- [ ] **Step 1: 실패하는 테스트를 작성한다**

`tests/unit/application/test_enrich_video.py` 생성:

```python
"""EnrichVideoHandler 단위 테스트 — 등록 시 요약/가사 자동 보강 분기.

핵심 규약:
- is_song=True면 가사만 조회하고 요약 추출기는 건드리지 않는다.
- is_song=False면 요약만 추출한다.
- 가사를 찾지 못하면 **폴백 없이 종료**한다(요약으로 넘어가지 않는다).
- 이미 값이 있으면 건너뛴다(kind="skipped" 또는 ok=True + 안내 detail).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from application.library.commands import (
    EnrichVideoCommand,
    EnrichVideoHandler,
)


class _FakeSummarySource:
    """호출 횟수를 기록하는 가짜 요약 추출기."""

    def __init__(self, summary: str = "요약 본문") -> None:
        self._summary = summary
        self.calls: list[str] = []

    def extract(self, url: str) -> str:
        self.calls.append(url)
        return self._summary


def _video_agg(gemini_summary: str = "", url: str = "https://youtu.be/abc"):
    """VideoAggregate 대역 — 핸들러가 쓰는 속성만 갖춘다."""
    return SimpleNamespace(
        id=uuid4(),
        video=SimpleNamespace(url=url, gemini_summary=gemini_summary),
        update_metadata=MagicMock(),
        pull_events=MagicMock(return_value=[]),
    )


def _song_agg(is_song: bool, lyrics_lines=None):
    return SimpleNamespace(
        info=SimpleNamespace(is_song=is_song, lyrics_lines=list(lyrics_lines or []))
    )


def _make(video_agg, song_agg, song_fetch=None, summary_source=None):
    repo = MagicMock()
    repo.get_by_id.return_value = video_agg
    song_repo = MagicMock()
    song_repo.get.return_value = song_agg
    handler = EnrichVideoHandler(
        repo=repo,
        song_repo=song_repo,
        song_fetch=song_fetch,
        summary_source=summary_source,
        event_bus=MagicMock(),
    )
    return handler, repo, song_repo


class TestSongBranch:
    def test_song_fetches_lyrics_and_never_touches_summary(self):
        """노래 영상은 가사만 조회하고 요약 추출기는 호출되지 않는다."""
        song_fetch = MagicMock()
        song_fetch.handle.return_value = _song_agg(True, ["1행", "2행"])
        summary = _FakeSummarySource()
        handler, _repo, _ = _make(
            _video_agg(), _song_agg(True), song_fetch, summary
        )

        result = handler.handle(EnrichVideoCommand(video_id=uuid4()))

        assert result.kind == "song"
        assert result.ok is True
        assert summary.calls == []          # 요약은 절대 시도하지 않는다
        cmd = song_fetch.handle.call_args.args[0]
        assert cmd.fetch_lyrics is True

    def test_lyrics_not_found_does_not_fall_back_to_summary(self):
        """가사를 못 찾아도 요약으로 폴백하지 않는다(확정된 정책)."""
        song_fetch = MagicMock()
        song_fetch.handle.return_value = _song_agg(True, [])   # 가사 없음
        summary = _FakeSummarySource()
        handler, _repo, _ = _make(
            _video_agg(), _song_agg(True), song_fetch, summary
        )

        result = handler.handle(EnrichVideoCommand(video_id=uuid4()))

        assert result.kind == "song"
        assert result.ok is False
        assert summary.calls == []

    def test_existing_lyrics_skipped(self):
        """가사가 이미 있으면 재조회하지 않는다."""
        song_fetch = MagicMock()
        handler, _repo, _ = _make(
            _video_agg(), _song_agg(True, ["이미 있음"]), song_fetch, _FakeSummarySource()
        )

        result = handler.handle(EnrichVideoCommand(video_id=uuid4()))

        assert result.ok is True
        assert song_fetch.handle.call_count == 0

    def test_song_fetch_exception_isolated(self):
        """가사 조회가 예외를 던져도 ok=False로 변환되고 전파되지 않는다."""
        song_fetch = MagicMock()
        song_fetch.handle.side_effect = RuntimeError("네트워크 실패")
        handler, _repo, _ = _make(_video_agg(), _song_agg(True), song_fetch, None)

        result = handler.handle(EnrichVideoCommand(video_id=uuid4()))

        assert result.kind == "song"
        assert result.ok is False
        assert "네트워크 실패" in result.detail


class TestSummaryBranch:
    def test_non_song_extracts_summary_and_saves(self):
        """비노래 영상은 요약을 추출해 저장한다."""
        summary = _FakeSummarySource("이 영상은 …")
        video = _video_agg(url="https://youtu.be/xyz")
        handler, repo, _ = _make(video, _song_agg(False), MagicMock(), summary)

        result = handler.handle(EnrichVideoCommand(video_id=uuid4()))

        assert result.kind == "summary"
        assert result.ok is True
        assert summary.calls == ["https://youtu.be/xyz"]
        video.update_metadata.assert_called_once_with(gemini_summary="이 영상은 …")
        repo.save.assert_called_once_with(video)

    def test_no_song_row_treated_as_non_song(self):
        """노래 정보 행이 없으면(yt-dlp 조회 실패 등) 비노래로 취급한다."""
        summary = _FakeSummarySource()
        handler, _repo, _ = _make(_video_agg(), None, MagicMock(), summary)

        result = handler.handle(EnrichVideoCommand(video_id=uuid4()))

        assert result.kind == "summary"
        assert len(summary.calls) == 1

    def test_existing_summary_skipped(self):
        """요약이 이미 있으면 추출하지 않는다."""
        summary = _FakeSummarySource()
        handler, repo, _ = _make(
            _video_agg(gemini_summary="기존 요약"), _song_agg(False), MagicMock(), summary
        )

        result = handler.handle(EnrichVideoCommand(video_id=uuid4()))

        assert result.kind == "skipped"
        assert summary.calls == []
        repo.save.assert_not_called()

    def test_empty_summary_reports_cookie_hint(self):
        """빈 문자열 반환(미로그인)은 쿠키 안내 메시지로 보고한다."""
        handler, repo, _ = _make(
            _video_agg(), _song_agg(False), MagicMock(), _FakeSummarySource("")
        )

        result = handler.handle(EnrichVideoCommand(video_id=uuid4()))

        assert result.ok is False
        assert "쿠키" in result.detail
        repo.save.assert_not_called()

    def test_missing_summary_source_skipped(self):
        """요약 추출기가 주입되지 않아도 예외 없이 skipped."""
        handler, _repo, _ = _make(_video_agg(), _song_agg(False), MagicMock(), None)

        result = handler.handle(EnrichVideoCommand(video_id=uuid4()))

        assert result.kind == "skipped"
        assert result.ok is False


class TestGuards:
    def test_missing_video_skipped(self):
        handler, repo, _ = _make(None, None, MagicMock(), _FakeSummarySource())

        result = handler.handle(EnrichVideoCommand(video_id=uuid4()))

        assert result.kind == "skipped"
        assert result.ok is False

    def test_is_song_video_label_helper(self):
        """상태바 라벨용 사전 판정."""
        handler, _repo, _ = _make(_video_agg(), _song_agg(True))
        assert handler.is_song_video(uuid4()) is True

        handler2, _r2, _ = _make(_video_agg(), _song_agg(False))
        assert handler2.is_song_video(uuid4()) is False

    def test_is_song_video_swallows_repo_error(self):
        handler, _repo, song_repo = _make(_video_agg(), _song_agg(True))
        song_repo.get.side_effect = RuntimeError("DB 오류")
        assert handler.is_song_video(uuid4()) is False
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `python -m pytest tests/unit/application/test_enrich_video.py -v`
Expected: FAIL — `ImportError: cannot import name 'EnrichVideoCommand' from 'application.library.commands'`

- [ ] **Step 3: `ISummarySource` 포트를 추가한다**

`domain/shared/ports.py` 파일 맨 끝(`IClipExtractor` 클래스 뒤)에 추가:

```python
class ISummarySource(Protocol):
    """YouTube Gemini AI 요약 추출 추상화.

    구현체: infrastructure.browser.gemini_extractor.GeminiExtractor

    로그인 쿠키가 없거나 요약 버튼을 찾지 못하면 예외 대신 빈 문자열을 반환한다.
    """

    def extract(self, url: str) -> str: ...
```

- [ ] **Step 4: `EnrichVideoHandler`를 구현한다**

`application/library/commands.py`의 `AddVideoHandler._register_song` 메서드 뒤, `class UpdateVideoHandler` 앞에 추가한다.

먼저 파일 상단 import에 `ISummarySource`를 더한다 (기존 줄을 수정):

```python
from domain.shared.ports import IEventBus, IMediaSource, ISummarySource
```

그리고 커맨드 dataclass는 `AddVideoCommand` 정의들 근처(`DeleteVideoCommand` 뒤)에 추가한다:

```python
@dataclass
class EnrichVideoCommand:
    """등록 직후 요약/가사를 자동 보강한다(단건 등록 경로에서만 호출)."""
    video_id: UUID


@dataclass
class EnrichVideoResult:
    """보강 결과 — GUI 상태바 표시용.

    kind: "song"(가사 조회) | "summary"(요약 추출) | "skipped"(대상 아님·이미 있음)
    """
    kind: str
    ok: bool
    detail: str = ""
```

핸들러 본문:

```python
class EnrichVideoHandler:
    """등록된 영상의 성격에 따라 가사 또는 요약 한쪽만 자동으로 채운다.

    분기 기준은 `song_info.is_song`이다 — 등록 시 `AddVideoHandler._register_song`이
    이미 기록해 두므로 yt-dlp를 다시 조회하지 않는다.

    - 노래 영상: 가사만 조회한다(메타데이터는 등록 시점에 채워져 있고, 체인은 빈 값만
      채우므로 실질적으로 가사만 추가된다). 가사를 못 찾아도 **요약으로 폴백하지 않는다.**
    - 그 외: Gemini 요약을 추출해 `gemini_summary`에 저장한다.

    모든 실패는 EnrichVideoResult(ok=False)로 변환해 등록 결과에 영향을 주지 않는다.
    """

    def __init__(
        self,
        repo: IVideoRepository,
        song_repo: "object",              # ISongRepository
        song_fetch: "object | None" = None,   # FetchSongInfoHandler
        summary_source: ISummarySource | None = None,
        event_bus: IEventBus | None = None,
    ) -> None:
        self._repo = repo
        self._songs = song_repo
        self._song_fetch = song_fetch
        self._summary = summary_source
        self._bus = event_bus

    def is_song_video(self, video_id: UUID) -> bool:
        """상태바 라벨용 사전 판정.

        실제 실행 분기는 handle()이 단독으로 결정한다 — 이 값은 표시용일 뿐이다.
        """
        try:
            agg = self._songs.get(video_id)
        except Exception:
            logger.exception("노래 여부 조회 실패: %s", video_id)
            return False
        return bool(agg is not None and agg.info.is_song)

    def handle(self, cmd: EnrichVideoCommand) -> EnrichVideoResult:
        video_agg = self._repo.get_by_id(cmd.video_id)
        if video_agg is None:
            return EnrichVideoResult("skipped", False, "영상을 찾을 수 없습니다")

        try:
            song_agg = self._songs.get(cmd.video_id)
        except Exception:
            logger.exception("노래 정보 조회 실패: %s", cmd.video_id)
            song_agg = None

        if song_agg is not None and song_agg.info.is_song:
            return self._enrich_lyrics(cmd.video_id, song_agg)
        return self._enrich_summary(video_agg)

    # ------------------------------------------------------------------
    def _enrich_lyrics(self, video_id: UUID, song_agg) -> EnrichVideoResult:
        if song_agg.info.lyrics_lines:
            return EnrichVideoResult("song", True, "가사가 이미 있습니다")
        if self._song_fetch is None:
            return EnrichVideoResult("skipped", False, "가사 조회기가 설정되지 않았습니다")

        try:
            from application.song.commands import FetchSongInfoCommand  # noqa: PLC0415
            result = self._song_fetch.handle(
                FetchSongInfoCommand(video_id=video_id, fetch_lyrics=True)
            )
        except Exception as exc:
            logger.exception("가사 자동 조회 실패: %s", video_id)
            return EnrichVideoResult("song", False, str(exc))

        lines = list(result.info.lyrics_lines) if result is not None else []
        if not lines:
            # 폴백 없음 — 요약으로 넘어가지 않는다(확정된 정책).
            logger.warning("가사를 찾지 못했습니다: %s", video_id)
            return EnrichVideoResult("song", False, "가사를 찾지 못했습니다")
        return EnrichVideoResult("song", True, f"{len(lines)}줄")

    def _enrich_summary(self, video_agg) -> EnrichVideoResult:
        if video_agg.video.gemini_summary:
            return EnrichVideoResult("skipped", True, "요약이 이미 있습니다")
        if self._summary is None:
            return EnrichVideoResult("skipped", False, "요약 추출기가 설정되지 않았습니다")

        url = str(video_agg.video.url)
        try:
            summary = self._summary.extract(url)
        except Exception as exc:
            logger.exception("요약 자동 추출 실패: %s", url)
            return EnrichVideoResult("summary", False, str(exc))

        if not summary:
            # 미로그인·쿠키 미설정에서 흔한 정상 실패 — 트레이스백 없이 안내만 남긴다.
            logger.warning("요약을 가져오지 못했습니다(YouTube 쿠키 확인): %s", url)
            return EnrichVideoResult(
                "summary", False, "요약을 가져오지 못했습니다(YouTube 쿠키 확인)"
            )

        video_agg.update_metadata(gemini_summary=summary)
        self._repo.save(video_agg)
        if self._bus is not None:
            self._bus.publish_all(video_agg.pull_events())
        return EnrichVideoResult("summary", True, f"{len(summary)}자")
```

> 설계 문서는 저장에 `UpdateVideoHandler`를 쓴다고 적었지만, 이미 `video_agg`를 손에 들고 있어 `repo.save`를 직접 호출하면 DB 읽기가 한 번 줄고 코드도 짧다. 계층 규칙에는 영향이 없다(`IVideoRepository`는 domain 인터페이스).

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `python -m pytest tests/unit/application/test_enrich_video.py -v`
Expected: PASS — 12개 테스트 전부 통과

- [ ] **Step 6: 린트 후 커밋한다**

```bash
ruff check domain/shared/ports.py application/library/commands.py tests/unit/application/test_enrich_video.py
git add domain/shared/ports.py application/library/commands.py tests/unit/application/test_enrich_video.py
git commit -m "feat: 등록 영상 자동 보강 핸들러(EnrichVideoHandler) 추가

- is_song 기준으로 가사 조회 또는 Gemini 요약 추출 중 하나만 실행
- 가사 미발견 시 요약으로 폴백하지 않음(확정 정책)
- 이미 값이 있거나 추출기 미주입이면 skipped, 모든 예외는 결과로 변환
- domain/shared/ports.py에 ISummarySource Protocol 추가"
```

---

### Task 2: 설정 토글 `AUTO_ENRICH_ON_ADD`

**Files:**
- Modify: `config/settings.py:127` 부근 (설정 변수), `config/settings.py:160-174` (`save_setting` mapping)
- Modify: `gui/panels/settings_panel.py:793-843` (일반 섹션), `:1186-1189` 부근 (핸들러)

**Interfaces:**
- Produces: `config.settings.AUTO_ENRICH_ON_ADD: bool` (기본 `True`), config.yaml 키 `auto_enrich_on_add`

- [ ] **Step 1: 설정 변수를 추가한다**

`config/settings.py`의 `AUTO_UPDATE_CHECK` 줄 바로 아래에 추가:

```python
# 단건 등록 직후 요약(비노래)·가사(노래) 자동 보강. 일괄 임포트는 대상이 아니다.
AUTO_ENRICH_ON_ADD: bool = _load_bool("auto_enrich_on_add", True)
```

같은 파일 `save_setting`의 `mapping` 딕셔너리에 한 줄 추가 (`"auto_update_check"` 항목 뒤):

```python
        "auto_enrich_on_add": "AUTO_ENRICH_ON_ADD",
```

- [ ] **Step 2: 설정이 읽히고 저장되는지 확인한다**

Run:
```bash
python -c "import config.settings as s; print(s.AUTO_ENRICH_ON_ADD); s.save_setting('auto_enrich_on_add', False); print(s.AUTO_ENRICH_ON_ADD); s.save_setting('auto_enrich_on_add', True); print(s.AUTO_ENRICH_ON_ADD)"
```
Expected: `True` / `False` / `True` — mapping이 빠지면 두 번째 줄이 `True`로 남는다.

- [ ] **Step 3: 설정 패널에 체크박스를 추가한다**

`gui/panels/settings_panel.py`의 일반 섹션에서 현재 값을 함께 읽는다. `cur_clipboard = s.CLIPBOARD_MONITORING` 줄 뒤에 추가:

```python
            cur_auto_enrich = s.AUTO_ENRICH_ON_ADD
```

같은 `except Exception:` 폴백 블록의 `cur_clipboard = True` 뒤에도 추가:

```python
            cur_auto_enrich = True
```

`self._clipboard_check`를 `layout`에 추가하는 블록(`layout.addSpacing(28)` 직전) 뒤에 체크박스와 안내 라벨을 넣는다:

```python
        # 등록 시 요약·가사 자동 채우기
        self._auto_enrich_check = QCheckBox("등록 시 요약·가사 자동 채우기")
        self._auto_enrich_check.setChecked(cur_auto_enrich)
        self._auto_enrich_check.checkStateChanged.connect(self._on_auto_enrich_changed)
        layout.addWidget(self._auto_enrich_check)

        enrich_hint = QLabel(
            "영상을 한 건씩 등록할 때 음원용 영상은 가사를, 그 외 영상은 Gemini 요약을 "
            "백그라운드에서 채웁니다. 재생목록·채널 일괄 가져오기는 대상이 아닙니다.\n"
            "요약은 YouTube 로그인 쿠키가 필요합니다 — Chrome 127 이상은 쿠키 자동 추출이 "
            "불가하므로 아래 인증 섹션에서 쿠키 파일을 직접 등록해야 합니다."
        )
        enrich_hint.setWordWrap(True)
        enrich_hint.setStyleSheet("font-size: 10px; color: #777; margin-left: 22px;")
        layout.addWidget(enrich_hint)
        layout.addSpacing(28)
```

`_on_clipboard_changed` 메서드 뒤에 핸들러를 추가한다:

```python
    def _on_auto_enrich_changed(self, state) -> None:
        from config import settings as s
        checked = (state == Qt.CheckState.Checked)
        s.save_setting("auto_enrich_on_add", checked)
```

- [ ] **Step 4: 설정 패널이 뜨는지 스모크 확인한다**

Run: `python -m pytest tests/gui/ -v`
Expected: PASS — 기존 GUI 스모크 테스트가 깨지지 않아야 한다. `QCheckBox`·`Qt`는 이 파일에 이미 import되어 있다(`_clipboard_check`가 같은 API를 쓴다). `ruff check gui/panels/settings_panel.py`로 미사용 import가 없는지도 확인한다.

- [ ] **Step 5: 커밋한다**

```bash
ruff check config/settings.py gui/panels/settings_panel.py
git add config/settings.py gui/panels/settings_panel.py
git commit -m "feat: '등록 시 요약·가사 자동 채우기' 설정 토글 추가

- config.settings.AUTO_ENRICH_ON_ADD (기본 ON) + save_setting mapping 등록
- 설정 일반 섹션에 체크박스와 안내(쿠키 필요·일괄 임포트 제외) 추가"
```

---

### Task 3: `LibraryViewModel` 보강 워커

**Files:**
- Modify: `gui/view_models/library_vm.py` — `_AddVideoWorker`(`:63-82`), 시그널 선언(`:202-216`), `__init__`(`:218-303`), `shutdown`(`:309-332`), `add_video`(`:481-489`), `_on_add_ok`(`:970-973`)

**Interfaces:**
- Consumes: `application.library.commands.EnrichVideoHandler`, `EnrichVideoCommand`, `EnrichVideoResult` (Task 1)
- Produces:
  - `LibraryViewModel.__init__(..., enrich_video: EnrichVideoHandler | None = None, ...)` — `find_song_videos` 뒤, `parent` 앞에 추가
  - 시그널 `enrich_started = pyqtSignal(str, str)` — `(url, kind)`, `kind`는 `"song" | "summary"`
  - 시그널 `enrich_finished = pyqtSignal(str, str, bool, str)` — `(url, kind, ok, detail)`

- [ ] **Step 1: `_AddVideoWorker`가 `video_id`를 전달하게 바꾼다**

`gui/view_models/library_vm.py`의 `_AddVideoWorker`를 수정한다:

```python
class _AddVideoWorker(QThread):
    finished_ok = pyqtSignal(object)   # video_id: UUID — 등록 후 보강에 사용
    finished_err = pyqtSignal(str)

    def __init__(
        self,
        handler: AddVideoHandler,
        cmd: AddVideoCommand,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._handler = handler
        self._cmd = cmd

    def run(self) -> None:
        try:
            agg = self._handler.handle(self._cmd)
            self.finished_ok.emit(agg.id)
        except Exception as exc:
            self.finished_err.emit(str(exc))
```

- [ ] **Step 2: `_EnrichWorker`를 추가한다**

`_AddVideoWorker` 클래스 바로 뒤에 삽입:

```python
class _EnrichWorker(QThread):
    """등록 직후 요약/가사 자동 보강을 백그라운드에서 실행한다.

    Gemini 요약 추출은 Playwright 브라우저를 띄워 수십 초가 걸리므로
    ViewModel이 동시 1건으로 직렬화한다.
    """
    finished_result = pyqtSignal(str, str, bool, str)   # url, kind, ok, detail

    def __init__(self, handler, cmd, url: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._handler = handler
        self._cmd = cmd
        self._url = url

    def run(self) -> None:
        try:
            result = self._handler.handle(self._cmd)
            self.finished_result.emit(self._url, result.kind, result.ok, result.detail)
        except Exception as exc:
            logger.exception("영상 보강 워커 실패: %s", self._url)
            self.finished_result.emit(self._url, "skipped", False, str(exc))
```

- [ ] **Step 3: 시그널·상태·주입을 추가한다**

시그널 선언부(`loading_key_changed` 줄 뒤)에 추가:

```python
    # 등록 직후 자동 보강 — (url, kind) / (url, kind, ok, detail)
    enrich_started  = pyqtSignal(str, str)
    enrich_finished = pyqtSignal(str, str, bool, str)
```

`__init__` 시그니처에서 `find_song_videos=None,` 뒤, `parent` 앞에 추가:

```python
        enrich_video=None,       # EnrichVideoHandler | None — 등록 후 요약/가사 자동 보강
```

`__init__` 본문의 `self._find_song_videos = find_song_videos` 뒤에 추가:

```python
        self._enrich_video = enrich_video
        # 보강은 동시 1건만 — Gemini가 브라우저를 띄우므로 병렬 실행을 막는다.
        self._enrich_workers: list[_EnrichWorker] = []
        self._pending_enrich: deque = deque()   # (video_id, url)
```

`shutdown()`의 워커 순회 리스트에 `*self._enrich_workers,`를 추가하고, `clear()` 구간에 다음 두 줄을 추가한다:

```python
        self._enrich_workers.clear()
        self._pending_enrich.clear()
```

- [ ] **Step 4: 등록 완료 후 보강을 시작한다**

`add_video`를 수정한다 (`finished_ok`가 이제 인자를 하나 넘긴다):

```python
    def add_video(self, url: str, category_id: UUID | None = None) -> None:
        cmd = AddVideoCommand(url=url, category_id=category_id)
        worker = _AddVideoWorker(self._add_video, cmd, self)
        worker.finished_ok.connect(lambda vid: self._on_add_ok(url, vid))
        worker.finished_err.connect(lambda err: self._on_add_err(url, err))
        worker.finished.connect(lambda: self._add_workers.remove(worker))
        self._add_workers.append(worker)
        worker.start()
        self.video_add_started.emit(url)
```

`_on_add_ok`를 수정한다:

```python
    def _on_add_ok(self, url: str, video_id: object = None) -> None:
        self._refresh_videos(bust_cache=True)
        self._refresh_tags()
        self.video_add_finished.emit(url)
        if isinstance(video_id, UUID):
            self._maybe_enrich(video_id, url)
```

`_on_add_err` 뒤에 보강 큐 메서드를 추가한다:

```python
    def _maybe_enrich(self, video_id: UUID, url: str) -> None:
        """설정이 켜져 있으면 보강을 큐에 넣는다(동시 1건)."""
        if self._enrich_video is None:
            return
        try:
            import config.settings as _s  # noqa: PLC0415
            if not getattr(_s, "AUTO_ENRICH_ON_ADD", True):
                return
        except Exception:
            logger.exception("자동 보강 설정 조회 실패")
            return
        self._pending_enrich.append((video_id, url))
        self._drain_enrich()

    def _drain_enrich(self) -> None:
        """대기 중인 보강 작업을 하나 꺼내 실행한다(이미 실행 중이면 대기)."""
        if self._enrich_workers or not self._pending_enrich:
            return
        video_id, url = self._pending_enrich.popleft()
        from application.library.commands import EnrichVideoCommand  # noqa: PLC0415

        # kind는 상태바 라벨용 사전 판정 — 실제 분기는 핸들러가 결정한다.
        try:
            kind = "song" if self._enrich_video.is_song_video(video_id) else "summary"
        except Exception:
            logger.exception("보강 종류 판정 실패: %s", video_id)
            kind = "summary"

        worker = _EnrichWorker(
            self._enrich_video, EnrichVideoCommand(video_id=video_id), url, self
        )
        worker.finished_result.connect(self._on_enrich_done)
        worker.finished.connect(lambda: self._release_enrich(worker))
        self._enrich_workers.append(worker)
        worker.start()
        self.enrich_started.emit(url, kind)

    def _release_enrich(self, worker) -> None:
        if worker in self._enrich_workers:
            self._enrich_workers.remove(worker)
        self._drain_enrich()

    def _on_enrich_done(self, url: str, kind: str, ok: bool, detail: str) -> None:
        self.enrich_finished.emit(url, kind, ok, detail)
```

`deque`는 이 파일에 이미 import되어 있다(`self._pending_list`가 사용). `UUID`도 이미 import되어 있다.

- [ ] **Step 5: 설정 OFF면 워커가 생기지 않는지 테스트한다**

먼저 `tests/gui/conftest.py:29-46`의 기존 `library_vm` 픽스처에 새 인자를 추가한다
(`refresh_metadata=MagicMock(),` 뒤):

```python
        enrich_video=MagicMock(),
```

그 다음 `tests/gui/test_auto_enrich_toggle.py`를 생성한다. 이 프로젝트는 pytest-qt의 `qapp`이 아니라
`tests/gui/conftest.py`가 제공하는 `qapp_instance`·`library_vm` 픽스처를 쓴다:

```python
"""AUTO_ENRICH_ON_ADD 토글이 보강 워커 생성을 실제로 막는지 검증한다."""
from __future__ import annotations

from uuid import uuid4


class TestAutoEnrichToggle:
    def test_skipped_when_setting_off(self, library_vm, monkeypatch):
        """설정이 꺼져 있으면 워커도 큐도 생기지 않는다."""
        import config.settings as s
        monkeypatch.setattr(s, "AUTO_ENRICH_ON_ADD", False)

        library_vm._maybe_enrich(uuid4(), "https://youtu.be/abc")

        assert library_vm._enrich_workers == []
        assert len(library_vm._pending_enrich) == 0

    def test_queued_when_setting_on(self, library_vm, monkeypatch):
        """설정이 켜져 있으면 워커가 하나 생성된다."""
        import config.settings as s
        monkeypatch.setattr(s, "AUTO_ENRICH_ON_ADD", True)
        library_vm._enrich_video.is_song_video.return_value = True

        library_vm._maybe_enrich(uuid4(), "https://youtu.be/abc")

        assert len(library_vm._enrich_workers) == 1
        library_vm.shutdown()

    def test_skipped_when_handler_missing(self, library_vm, monkeypatch):
        """보강 핸들러가 주입되지 않았으면 아무것도 하지 않는다."""
        import config.settings as s
        monkeypatch.setattr(s, "AUTO_ENRICH_ON_ADD", True)
        library_vm._enrich_video = None

        library_vm._maybe_enrich(uuid4(), "https://youtu.be/abc")

        assert library_vm._enrich_workers == []

    def test_second_add_queues_behind_first(self, library_vm, monkeypatch):
        """동시 1건 — 두 번째 요청은 큐에서 대기한다."""
        import config.settings as s
        monkeypatch.setattr(s, "AUTO_ENRICH_ON_ADD", True)
        library_vm._enrich_video.is_song_video.return_value = False

        library_vm._pending_enrich.append((uuid4(), "https://youtu.be/first"))
        library_vm._enrich_workers.append(object())   # 실행 중인 것처럼 위장
        library_vm._maybe_enrich(uuid4(), "https://youtu.be/second")

        # 실행 중인 워커가 있으므로 새 워커를 만들지 않고 큐에만 쌓는다.
        assert len(library_vm._enrich_workers) == 1
        assert len(library_vm._pending_enrich) == 2
        library_vm._enrich_workers.clear()
        library_vm._pending_enrich.clear()
```

Run: `python -m pytest tests/gui/test_auto_enrich_toggle.py -v`
Expected: PASS — 4개 통과

- [ ] **Step 6: 기존 테스트가 깨지지 않는지 확인한다**

Run: `python -m pytest tests/ -q`
Expected: PASS — `finished_ok` 시그니처가 바뀌었으니 `_AddVideoWorker`를 참조하는 코드가 더 있는지 확인한다.

Run: `python -c "import ast,sys; print('_AddVideoWorker refs OK')"` 대신 실제 검색:
```bash
grep -rn "_AddVideoWorker\|finished_ok" --include=*.py . | grep -v "\.pyc"
```
Expected: `library_vm.py` 안의 정의·사용과 다른 워커 클래스들의 자체 `finished_ok`만 나온다. `_AddVideoWorker.finished_ok`를 외부에서 직접 연결하는 곳은 없어야 한다.

- [ ] **Step 7: 커밋한다**

```bash
ruff check gui/view_models/library_vm.py
git add gui/view_models/library_vm.py tests/gui/conftest.py tests/gui/test_auto_enrich_toggle.py
git commit -m "feat: 등록 직후 요약·가사 자동 보강 워커 추가

- _AddVideoWorker.finished_ok가 video_id를 전달
- _EnrichWorker(QThread) + enrich_started/enrich_finished 시그널
- 동시 1건 큐(_pending_enrich)로 Gemini 브라우저 병렬 실행 방지
- AUTO_ENRICH_ON_ADD가 꺼져 있으면 워커를 만들지 않음
- shutdown()에서 보강 워커 정리"
```

---

### Task 4: 상태바 표시 · 상세 재로드 · 배선

이 태스크가 끝나면 기능이 실제로 동작한다.

**Files:**
- Modify: `gui/main_window.py:575-578` (시그널 연결), `:613-623` (핸들러 뒤에 추가)
- Modify: `gui/panels/library_panel.py` — VM 시그널을 연결하는 구간, `_on_video_metadata_refreshed`(`:4870`) 뒤
- Modify: `main.py:281` 부근 (핸들러 조립), `:372-397` (`library_vm` 주입)

**Interfaces:**
- Consumes: `LibraryViewModel.enrich_started(url, kind)` / `enrich_finished(url, kind, ok, detail)` (Task 3), `EnrichVideoHandler` (Task 1)
- Produces: 사용자에게 보이는 최종 동작

- [ ] **Step 1: `main.py`에서 핸들러를 조립·주입한다**

`main.py`의 import 구간에서 `application.library.commands`를 가져오는 블록에 `EnrichVideoHandler`를 추가한다 (`AddVideoHandler`가 이미 들어 있는 그 블록).

`_gemini_extractor`는 현재 `# 10. Application handlers — Download` 구간(`:308-309`)에서 생성된다. `EnrichVideoHandler`가 이를 써야 하므로 **생성 위치를 `# 9. Application handlers — Library` 앞으로 올린다.** `fetch_song = FetchSongInfoHandler(...)` 정의 앞에 다음을 두고, 기존 `:308-309`의 두 줄은 삭제한다:

```python
    # Gemini 요약 추출기 — 등록 후 자동 보강(EnrichVideoHandler)과 다운로드 완료 캡처가 공유
    from infrastructure.browser.gemini_extractor import GeminiExtractor
    _gemini_extractor = GeminiExtractor()
```

`add_video = AddVideoHandler(...)` 줄 뒤에 추가:

```python
    enrich_video        = EnrichVideoHandler(
        video_repo, song_repo,
        song_fetch=fetch_song,
        summary_source=_gemini_extractor,
        event_bus=event_bus,
    )
```

`library_vm = LibraryViewModel(` 인자 목록의 `find_song_videos=...` 줄 뒤에 추가:

```python
        enrich_video=enrich_video,
```

- [ ] **Step 2: 상태바에 진행·실패를 표시한다**

`gui/main_window.py`의 `_setup_signals`에서 `video_add_finished` 연결 줄 뒤에 추가:

```python
        self._library_vm.enrich_started.connect(self._on_enrich_started)
        self._library_vm.enrich_finished.connect(self._on_enrich_finished)
```

`_on_add_finished` 메서드 뒤에 핸들러를 추가한다:

```python
    # ------------------------------------------------------------------
    _ENRICH_LABEL = {"song": "가사 조회", "summary": "요약 생성"}

    def _on_enrich_started(self, url: str, kind: str) -> None:
        label = self._ENRICH_LABEL.get(kind, "정보 보강")
        short = url.split("/")[2] if url.count("/") >= 2 else url[:40]
        self.statusBar().showMessage(f"{label} 중: {short}", 0)
        self._add_progress.show()

    def _on_enrich_finished(self, url: str, kind: str, ok: bool, detail: str) -> None:
        self._add_progress.hide()
        label = self._ENRICH_LABEL.get(kind, "정보 보강")
        if kind == "skipped" and ok:
            self.statusBar().clearMessage()
            return
        if ok:
            suffix = f" ({detail})" if detail else ""
            self.statusBar().showMessage(f"{label} 완료{suffix}", 5000)
        else:
            reason = detail or "알 수 없는 오류"
            self.statusBar().showMessage(f"{label} 실패: {reason}", 8000)
```

`_on_add_started`/`_on_add_finished`가 쓰는 `url.split("\\")` 는 원본 코드의 표기이므로 건드리지 않는다. 새 메서드는 위 코드대로 `"/"`를 쓴다.

- [ ] **Step 3: 보강 완료 시 열린 상세를 재로드한다**

`gui/panels/library_panel.py`에서 `_on_video_metadata_refreshed`를 VM에 연결하는 줄 근처에 다음 연결을 추가한다 (`self._vm.video_metadata_refreshed.connect(...)` 를 찾아 그 뒤):

```python
        self._vm.enrich_finished.connect(self._on_enrich_finished)
```

`_on_video_metadata_refreshed` 메서드 뒤에 추가:

```python
    def _on_enrich_finished(self, url: str, kind: str, ok: bool, detail: str) -> None:
        """등록 후 자동 보강 완료 — 그 영상 상세가 열려 있으면 제자리 재로드.

        요약 추출은 수십 초가 걸려 그 사이 사용자가 영상을 열어 볼 수 있다.
        _reload_detail_in_place가 상세 DTO와 노래 정보를 함께 다시 읽으므로
        요약 탭·노래 탭 어느 쪽이 채워졌든 반영된다.
        """
        if not ok:
            return
        video_id = self._detail_widget.current_detail_id()
        if video_id is None:
            return
        try:
            enriched_id = self._vm.get_video_id_by_url(url)
        except Exception:
            logger.exception("보강 완료 영상 조회 실패: %s", url)
            return
        if enriched_id != video_id:
            return
        self._reload_detail_in_place(video_id)
```

`LibraryViewModel`에는 이 메서드가 **아직 없으므로 반드시 추가한다.** `self._get_video_id_by_url`
핸들러는 `__init__`에서 이미 주입받고 있고, `GetVideoIdByUrlHandler.handle(url: str) -> UUID | None`
(`application/library/queries.py:263`)이라 쿼리 객체 없이 URL 문자열을 직접 넘긴다.
`library_vm.py`의 `get_playlist_first_item` 메서드 뒤에 추가:

```python
    def get_video_id_by_url(self, url: str) -> "UUID | None":
        """URL로 라이브러리 영상 ID를 조회한다(없으면 None)."""
        if self._get_video_id_by_url is None:
            return None
        try:
            return self._get_video_id_by_url.handle(url)
        except Exception:
            logger.exception("URL로 영상 ID 조회 실패: %s", url)
            return None
```

- [ ] **Step 4: 전체 테스트를 실행한다**

Run: `python -m pytest tests/ -q`
Expected: PASS

Run: `ruff check .`
Expected: 새로 만든/수정한 파일에 경고 없음

- [ ] **Step 5: 실앱으로 확인한다**

`/verify` 스킬을 호출해 앱을 실행하고 다음을 확인한다:
1. 앱이 오류 없이 뜨고 설정 패널 일반 섹션에 "등록 시 요약·가사 자동 채우기" 체크박스가 보인다
2. 라이브러리에서 **음원용 YouTube URL**을 카테고리에 등록 → 상태바에 "가사 조회 중: …" → 완료 후 상세 "노래" 탭에 가사가 채워져 있다
3. **일반 영상 URL**을 등록 → 상태바에 "요약 생성 중: …" → 쿠키가 설정돼 있으면 "요약" 탭이 채워지고, 없으면 상태바에 "요약 생성 실패: 요약을 가져오지 못했습니다(YouTube 쿠키 확인)"가 뜬다
4. 체크박스를 끄고 등록하면 보강 메시지가 전혀 뜨지 않는다

- [ ] **Step 6: 커밋한다**

```bash
git add main.py gui/main_window.py gui/panels/library_panel.py gui/view_models/library_vm.py
git commit -m "feat: 등록 시 자동 보강 배선 — 상태바 표시·상세 재로드

- main.py: EnrichVideoHandler 조립(GeminiExtractor 생성 위치를 Library 구간 앞으로)
- main_window: enrich_started/finished를 상태바 진행·실패 메시지로 표시
- library_panel: 보강 완료 시 열려 있는 상세를 제자리 재로드"
```

---

### Task 5: 문서 갱신

CLAUDE.md의 "Requirement & Planning Updates"가 필수로 지정한 기록이다.

**Files:**
- Modify: `CLAUDE.md` (Key Design Decisions, `gui/` 파일 맵)
- Modify: `planning/youtube_content_manager_prd.md`

**Interfaces:**
- Consumes: Task 1~4의 최종 동작
- Produces: 없음 (문서)

- [ ] **Step 1: `CLAUDE.md`의 Key Design Decisions에 항목을 추가한다**

"Gemini AI 요약 자동 메모 저장" 항목 뒤에 다음 불릿을 추가한다:

```markdown
- **등록 시 요약·가사 자동 보강** — **단건 등록**(`LibraryViewModel.add_video`)이 끝나면 `EnrichVideoHandler`(application/library/commands.py)가 `song_info.is_song`을 읽어 한쪽만 채운다: 노래 영상이면 `FetchSongInfoCommand(fetch_lyrics=True)`로 **가사만**(메타데이터는 등록 시 이미 채워졌고 체인은 빈 값만 채운다), 아니면 `ISummarySource.extract`(=`GeminiExtractor`)로 **요약**(`gemini_summary`)을 채운다. **가사를 못 찾아도 요약으로 폴백하지 않는다.** 이미 값이 있으면 건너뛴다. 설정 `AUTO_ENRICH_ON_ADD`(기본 ON)로 끌 수 있다. **재생목록·채널 일괄 임포트는 대상이 아니다** — 그 경로들은 `AddVideoHandler`를 직접 호출하고 ViewModel을 지나지 않으므로 자연히 제외되며, Gemini가 영상당 브라우저를 띄워 수십 초 걸리기 때문에 의도된 제외다. 보강은 `_EnrichWorker`(QThread)에서 **동시 1건**으로 직렬화한다(브라우저 병렬 실행 방지). 진행·실패는 `MainWindow` 상태바에 표시하고, 완료 시 그 영상 상세가 열려 있으면 `_reload_detail_in_place`로 재로드한다. `ISummarySource`는 `domain/shared/ports.py`의 Protocol이라 application 레이어가 infrastructure를 직접 import하지 않는다.
```

- [ ] **Step 2: `gui/` 파일 맵을 갱신한다**

`CLAUDE.md`의 `gui/` 트리에서 세 줄을 수정한다:

- `library_vm.py` 설명 끝에 추가: `. 등록 직후 자동 보강(`_EnrichWorker` — 동시 1건 큐 `_pending_enrich`, `enrich_started`/`enrich_finished` 시그널)`
- `main_window.py` 설명 끝에 추가: `. **등록 후 자동 보강 상태 표시**: `enrich_started`→상태바 "가사 조회 중"/"요약 생성 중", `enrich_finished`→완료(5초)/실패(8초)`
- `settings_panel.py` 설명에 추가: `일반 섹션에 **"등록 시 요약·가사 자동 채우기"** 체크박스(`_auto_enrich_check` → `auto_enrich_on_add`)`

- [ ] **Step 3: PRD의 노래 정보 섹션을 갱신한다**

`planning/youtube_content_manager_prd.md:145`의 불릿은 현재 동작과 어긋난다 — "가사는 상세 최초 진입 시
자동 조회"라고 적혀 있지만 실제로는 가사 검색 버튼을 눌러야만 조회한다. 이 줄을 다음으로 **교체**한다:

```markdown
- **등록 시 조회 + 정보 갱신**: 등록 시 노래 정보를 조회해 기록하고, 정보 갱신(⟳) 버튼으로 재수집한다. 상세화면에서 가사는 가사 검색 버튼을 눌러야 조회하며(자동 조회 안 함), 이미 가사가 있으면 다음 출처부터 순환 조회한다.
- **단건 등록 시 자동 보강**: 영상을 한 건씩 등록하면 음원용 영상은 **가사**를, 그 외 영상은 **Gemini 요약**을 백그라운드에서 자동으로 채운다(설정으로 끌 수 있고 기본 ON). 판정 기준은 등록 시 기록된 노래 여부(YouTube Music 카테고리 또는 음악 메타데이터)다. 가사를 찾지 못하면 요약으로 대체하지 않는다. 재생목록·채널 일괄 가져오기는 대상이 아니다(영상당 수십 초가 걸려 대량 처리에 부적합). 요약은 YouTube 로그인 쿠키가 필요하다.
```

- [ ] **Step 3b: PRD 로드맵에 버전 항목을 추가한다**

문서 맨 끝 `### v1.5+ — 구독 채널 재동기화` 뒤에 같은 형식으로 추가한다(최신 릴리스가 v1.7.0이므로 v1.8+):

```markdown
### v1.8+ — 등록 시 요약·가사 자동 보강

1. **성격에 따른 자동 보강**: 영상을 단건으로 카테고리에 등록하면 등록 직후 백그라운드에서 한쪽만 채운다 — 음원용 영상이면 상세 "노래" 탭의 **가사**를, 그 외 영상이면 "요약" 탭의 **Gemini 요약**을 채운다. 노래 영상의 가수·앨범·제목·발매년도는 등록 시점에 이미 기록되므로 실질적으로 가사만 추가된다.
2. **폴백 없음**: 가사를 찾지 못해도 요약으로 넘어가지 않는다. 이미 값이 있는 영상은 건너뛴다.
3. **일괄 임포트 제외**: 재생목록·채널 일괄 가져오기는 대상이 아니다. Gemini 요약 추출이 영상당 브라우저를 띄워 수십 초 걸리므로 수백 건 임포트에 걸면 끝나지 않는다.
4. **직렬 실행 + 상태 표시**: 보강은 동시 1건으로 직렬화하고(브라우저 병렬 실행 방지), 진행·실패를 상태바에 표시한다. 완료 시 그 영상 상세가 열려 있으면 즉시 반영된다.
5. **설정 토글**: 설정 일반 섹션의 "등록 시 요약·가사 자동 채우기"로 끌 수 있다(기본 ON). 요약은 YouTube 로그인 쿠키가 필요하며 Chrome 127 이상은 쿠키 파일을 직접 등록해야 한다.
```

- [ ] **Step 4: 커밋한다**

```bash
git add CLAUDE.md planning/youtube_content_manager_prd.md
git commit -m "docs: 등록 시 요약·가사 자동 보강 규칙·요구사항 기록

- CLAUDE.md Key Design Decisions에 보강 분기·폴백 없음·일괄 임포트 제외 명시
- gui 파일 맵의 library_vm·main_window·settings_panel 설명 갱신
- PRD에 기능 요구사항 추가"
```
