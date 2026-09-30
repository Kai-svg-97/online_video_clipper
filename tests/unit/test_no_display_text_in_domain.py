"""도메인·애플리케이션·인프라에 화면 문구가 다시 들어오는 것을 막는다.

다국어화 1단계로 `domain/` 의 한국어 표시 문자열을 전부 걷어냈다. 이 시험이 없으면
다음에 기능을 더하는 사람이 자연스럽게 `return "하루 종일 받습니다"` 를 쓰고, 그
문장은 **번역할 방법이 없는 채로** 화면까지 흘러간다.

처음에는 `domain/` 만 훑었다. 그 사이 `application/`·`infrastructure/` 는 비어 있는
채로 남아, 보강 결과("가사가 이미 있습니다")·재생목록 오류·업데이트 실패 사유 같은
한국어 문장이 영어 화면에 그대로 올라왔다. 이제 세 계층을 모두 본다. 화면에 닿는
말은 `Message`(키+파라미터)로, 사용자에게 보이는 예외는 `DisplayError` 로 나른다
(`domain/shared/messages.py`).

## 주석·독스트링·로그는 보지 않는다

이 프로젝트는 **주석·독스트링을 한국어로 쓰는 것이 규약**이고, 거기 담긴 설계 근거는
자산이다. "한글 제거"로 오해해 그것까지 밀어버리는 일을 막기 위해, 이 시험은 AST의
문자열 상수만 훑고 독스트링은 명시적으로 제외한다. 로그 호출(`logger.info(...)` 등)의
인자도 개발자가 읽는 글이라 세지 않는다(`tests/unit/gui/test_no_untranslated_gui_text.py`
와 같은 기준).

## 허용 목록 — 화면 문구가 아니라 언어 데이터·저장되는 값

불용어·잡음어 같은 것은 한국어 텍스트를 처리하기 위한 **데이터**다. 번역 대상이
아니고, 지우면 검색·앨범 매칭이 조용히 망가진다. DB에 남는 이름(자막 트랙 라벨·
재생목록 이름)도 번역하면 안 된다 — 언어를 바꿨다고 저장된 값이 바뀌면 안 된다.

항목은 `{경로: 이름 집합}` 이다. 이름은 문자열이 담긴 **대입 대상**(`_STOPWORDS`)이나
**감싼 함수·클래스**(`Database._migrate_song_tables`)다. 빈 집합은 파일 전체를 허용한다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_HANGUL = re.compile(r"[가-힣]")
_SCANNED = ("domain", "application", "infrastructure")
# 로그 호출 — 인자는 개발자가 읽는 글이다.
_LOG_CALLS = {"debug", "info", "warning", "error", "exception", "critical"}

# 화면 문구가 아니라 **언어 데이터·저장되는 값**이다 — 그 계층에 있는 것이 맞다.
_ALLOWED: dict[str, set[str]] = {
    # ── domain ────────────────────────────────────────────────────
    # 한국어 텍스트를 **처리하기 위한** 데이터·정규식. 지우면 검색·앨범 매칭이
    # 조용히 망가진다.
    "domain/library/recommendation.py": {"_STOPWORDS", "_TOKEN_SPLIT"},
    "domain/song/album.py": {
        "_NOISE_WORDS", "_REJECT_KEYWORDS", "_PLACEHOLDER_VALUES",
        "_NON_WORD_RE", "NO_ALBUM_TITLE",
    },
    "domain/library/repositories.py": {"MUSIC_ROOT_CATEGORY_NAMES"},
    "domain/library/duplicates.py": set(),
    "domain/song/aggregates.py": set(),     # 개발자용 예외 메시지
    # 디스크의 **실제 폴더 이름**이다. 번역하면 이미 만들어진 폴더를 잃는다.
    "domain/library/watch_folder.py": {"DONE_DIR_NAME"},

    # ── application ───────────────────────────────────────────────
    # 해시태그 정규식 — 한글 태그를 잡기 위한 문자 범위.
    "application/library/commands.py": {"_HASHTAG_RE"},
    # 노래 제목에서 떼어 낼 부가 표기("가사", "뮤직비디오") — 텍스트 처리용 정규식.
    "application/song/commands.py": {"_TITLE_NOISE_RE"},
    # DB에 저장되는 자막 트랙 라벨 — 언어를 바꿔도 이미 저장된 라벨은 그대로여야 한다.
    "application/library/subtitle_commands.py": {
        "TranscribeVideoHandler.handle", "TranslateSubtitlesHandler.handle",
    },
    # 로컬 사본 재생목록의 **저장되는 이름**("… (로컬 복사)") — 사용자 데이터가 된다.
    "application/library/playlist_commands.py": {"CopyYouTubePlaylistToLocalHandler.handle"},
    # 가져온 노래의 출처 이름("가져오기") — SongSourceRef로 DB에 저장된다.
    "application/transfer/commands.py": {
        "ImportLibraryHandler._apply_song", "ImportLibraryHandler._merge_song",
    },

    # ── infrastructure ────────────────────────────────────────────
    # 한국어 YouTube 화면의 버튼·칩 문구와 Gemini 응답 판정 문구 — 화면을 **읽기 위한**
    # 선택자·데이터다. 재시도 사유 문자열도 로그에만 쓰인다.
    "infrastructure/browser/gemini_extractor.py": set(),
    # 기본 가사 출처 이름("지니"·"벅스"·"멜론") — DB에 시드로 저장되는 값이다.
    "infrastructure/persistence/database.py": {"Database._migrate_song_tables"},
    # 이름 없이 저장할 때의 **저장되는** 기본 이름 — 저장된 뒤에는 사용자 데이터다.
    "infrastructure/persistence/sqlite_saved_search_repository.py": {
        "SqliteSavedSearchRepository.save",
    },
    # 가사 제공자 이름(DB에 출처로 저장) + 한국어 가사 페이지를 긁는 정규식.
    "infrastructure/song/lyrics_providers.py": {
        "MelonProvider", "BugsProvider", "GenieProvider", "GeniusProvider._parse_page",
    },
    # 로그 도우미(`_log_error`)에 넘기는 동작 이름 — 로그에만 남는다.
    "infrastructure/song/album_providers.py": {"ITunesAlbumProvider._get"},
    # 한글 판정 정규식 — 번역 대상인지 가르는 텍스트 처리용.
    "infrastructure/song/translator.py": {"_HANGUL_RE"},
    # 자동 번역 대상 언어 이름 — **자국어 표기**가 의도다("日本語"처럼 "한국어").
    "infrastructure/subtitle/youtube_subtitles.py": {"TRANSLATE_TARGETS"},
}


def _docstring_ids(tree: ast.AST) -> set[int]:
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                out.add(id(body[0].value))
    return out


def _log_call_ids(tree: ast.AST) -> set[int]:
    """`logger.info(...)` 같은 로그 호출 안의 노드."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _LOG_CALLS
        ):
            out.update(id(sub) for sub in ast.walk(node))
    return out


def _owner_names(tree: ast.AST) -> dict[int, set[str]]:
    """문자열 노드 → 그것을 담은 이름들(허용 목록 판정용).

    대입 대상(`_STOPWORDS = …`)과 감싼 함수·클래스의 한정 이름(`Cls`, `Cls.method`)을
    모두 담는다.
    """
    out: dict[int, set[str]] = {}

    def add(node: ast.AST, names: set[str]) -> None:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                out.setdefault(id(sub), set()).update(names)

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qual = f"{prefix}.{child.name}" if prefix else child.name
                add(child, {qual})
                visit(child, qual)
            else:
                visit(child, prefix)

    visit(tree, "")
    for node in ast.walk(tree):
        names: set[str] = set()
        if isinstance(node, ast.Assign):
            names = {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = {node.target.id}
        if names:
            add(node, names)
    return out


def _offenders(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skipped = _docstring_ids(tree) | _log_call_ids(tree)
    owners = _owner_names(tree)
    rel = path.relative_to(_ROOT).as_posix()
    allowed = _ALLOWED.get(rel)
    if allowed == set():          # 파일 전체를 허용한 경우
        return []
    found: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in skipped or not _HANGUL.search(node.value):
            continue
        if allowed is not None and owners.get(id(node), set()) & allowed:
            continue
        found.append(f"{rel}:{node.lineno}  {node.value[:40]!r}")
    return found


_FILES = sorted(
    p
    for layer in _SCANNED
    for p in (_ROOT / layer).rglob("*.py")
    if "__pycache__" not in str(p)
)


@pytest.mark.parametrize(
    "path", _FILES, ids=lambda p: p.relative_to(_ROOT).with_suffix("").as_posix()
)
def test_도메인에_화면_문구가_없다(path: Path):
    offenders = _offenders(path)
    assert not offenders, (
        "한국어 표시 문자열이 있다 — `gui/text/` 로 옮기거나 Message 를 돌려주게 하라"
        "(사용자에게 보이는 예외는 DisplayError):\n  " + "\n  ".join(offenders)
    )


def test_허용_목록이_낡지_않았다():
    """허용 목록에 적힌 파일·이름이 사라졌는데 항목만 남는 것을 막는다."""
    missing = [rel for rel in _ALLOWED if not (_ROOT / rel).exists()]
    assert not missing, f"허용 목록에 없는 파일이 적혀 있다: {missing}"

    stale: list[str] = []
    for rel, names in _ALLOWED.items():
        tree = ast.parse((_ROOT / rel).read_text(encoding="utf-8"))
        hangul_ids = {
            id(n) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and _HANGUL.search(n.value)
        }
        owners = _owner_names(tree)
        used = set().union(*(owners.get(i, set()) for i in hangul_ids)) if hangul_ids else set()
        stale.extend(f"{rel}: {name}" for name in sorted(names - used))
    assert not stale, f"한국어 문자열을 더는 담지 않는 허용 항목: {stale}"
