"""워치 폴더 규칙 — **순수 판정**, 파일을 읽지도 옮기지도 않는다.

브라우저에서 주소를 앱까지 끌어다 놓으려면 앱이 떠 있어야 한다. 폴더 하나를 정해
두면 앱이 꺼져 있어도 거기 모아 뒀다가 켤 때 한꺼번에 담을 수 있다 — 윈도우에서는
링크를 폴더로 끌면 `.url` 파일이 그대로 생기므로, 그것만으로 수집이 끝난다.

## 왜 방금 만들어진 파일을 건너뛰나

파일이 복사되는 **중간**에 읽으면 주소가 잘린 채 들어온다(큰 HTML 북마크 파일에서
실제로 일어난다). 수정 시각이 몇 초 지난 것만 읽는다 — 늦게 담는 것은 괜찮지만
반쯤 담는 것은 되돌리기 어렵다.

## 왜 처리한 파일을 옮기나

기록을 따로 두면 그 기록과 실제 폴더가 어긋난다(사용자가 파일을 지우거나 되돌려
놓는다). 옮기면 **폴더를 보는 것만으로** 무엇이 처리됐는지 알 수 있고, 다시 담고
싶으면 도로 꺼내면 된다.
"""

from __future__ import annotations

import re

# 훑을 확장자. `.url`은 윈도우가 링크를 폴더로 끌 때 만드는 파일이다.
WATCHED_SUFFIXES: tuple[str, ...] = (".txt", ".url", ".html", ".htm")

# 처리한 파일을 옮길 하위 폴더 이름.
DONE_DIR_NAME = "처리됨"

# 파일이 이만큼 조용해야 읽는다(초). 복사 중인 파일을 반쯤 읽는 것을 막는다.
SETTLE_SECONDS = 3.0

# 한 번에 담을 최대 주소 수 — 각 건이 네트워크 조회를 한 번씩 한다.
MAX_PER_SCAN = 100

_URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+", re.IGNORECASE)
# `.url` 파일은 INI 형식이다: [InternetShortcut] / URL=https://...
_INTERNET_SHORTCUT_RE = re.compile(r"^\s*URL\s*=\s*(\S+)", re.IGNORECASE | re.MULTILINE)
# 주소 끝에 붙어 오는 문장부호 — 잘라 내지 않으면 받을 수 없는 주소가 된다.
_TRAILING = ".,;:!?«»“”'\")]}"


def is_watched(name: str) -> bool:
    """훑을 파일인가 — 확장자만 본다(폴더 안의 다른 파일은 건드리지 않는다)."""
    lowered = (name or "").lower()
    return any(lowered.endswith(suffix) for suffix in WATCHED_SUFFIXES)


def is_settled(age_seconds: float) -> bool:
    """읽어도 되는가 — 복사가 끝났다고 볼 만큼 조용한가."""
    return age_seconds >= SETTLE_SECONDS


def extract_urls(content: str, limit: int = MAX_PER_SCAN) -> list[str]:
    """글에서 주소를 뽑는다(파일에 적힌 순서, 중복 제거).

    `.url` 파일의 `URL=` 줄을 먼저 본다 — 그 형식에는 설명이나 아이콘 경로가 함께
    들어 있어, 통째로 정규식을 돌리면 엉뚱한 것까지 주소로 잡힌다.
    """
    if not content:
        return []

    shortcut = _INTERNET_SHORTCUT_RE.findall(content)
    found = shortcut if shortcut else _URL_RE.findall(content)

    out: list[str] = []
    seen: set[str] = set()
    for raw in found:
        url = raw.rstrip(_TRAILING)
        if not url.lower().startswith(("http://", "https://")):
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
        if len(out) >= limit:
            break
    return out


def done_name(name: str, taken: list[str]) -> str:
    """처리됨 폴더에서 쓸 이름 — 같은 이름이 있으면 번호를 붙인다.

    덮어쓰면 **사용자가 되돌릴 수 없다**. 같은 파일을 여러 번 떨구는 일이 흔하다.
    """
    existing = set(taken)
    if name not in existing:
        return name
    stem, dot, suffix = name.rpartition(".")
    if not dot:
        stem, suffix = name, ""
    for i in range(2, 1000):
        candidate = f"{stem} ({i}){dot}{suffix}"
        if candidate not in existing:
            return candidate
    return name
