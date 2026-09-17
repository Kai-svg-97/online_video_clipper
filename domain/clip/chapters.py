"""영상 설명에서 챕터 구간을 뽑아내는 **순수 규칙** — I/O 없음.

상세화면은 이미 설명 속 타임스탬프를 seek 링크로 바꿔 쓰고 있었다. 여기서는 같은
타임스탬프를 **구간**(시작~끝)으로 해석해 클립 추출에 바로 쓸 수 있게 한다.

가장 어려운 부분은 **오탐 제거**다. 설명 본문에는 "10:30에 촬영" 같은 시각 표기가
흔해서, 아무 타임스탬프나 챕터로 보면 목록이 쓰레기가 된다. 그래서:

1. 타임스탬프가 **줄의 맨 앞이나 맨 뒤**에 있을 때만 챕터 후보로 본다
   (YouTube 챕터 표기 관행이고, 본문 중간의 시각 언급을 대부분 걸러낸다).
2. 시작 시각이 **앞 챕터보다 커야** 한다 — 뒤로 가는 값은 본문 속 시각이다.
3. 후보가 **2개 이상**일 때만 챕터로 인정한다(1개는 우연일 확률이 높다).
   상세화면 설명 렌더링이 쓰는 기준과 같다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 줄 맨 앞/맨 뒤의 (H:)MM:SS. 본문 중간의 시각 표기를 걸러내려고 위치를 고정한다.
# 앞쪽은 불릿·번호·괄호 같은 장식을 먼저 흘려보낸다: "- (0:00) 인트로"
_LEADING_TS = re.compile(r"^[\s\-–—*•·\[\(<]*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})[\s\]\)>]*")
_TRAILING_TS = re.compile(r"[\s\-–—\[\(<]*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})[\s\]\)>]*$")

# 타임스탬프를 떼어낸 뒤 제목 앞뒤에 남는 구분 기호.
_TITLE_TRIM = " \t-–—:·•*|>[](){}<>"

# 챕터로 인정하는 최소 개수 — 1개는 본문 속 시각 표기일 확률이 높다.
MIN_CHAPTERS = 2


@dataclass(frozen=True, slots=True)
class Chapter:
    """설명에서 뽑은 챕터 한 구간."""

    title: str
    start_sec: float
    end_sec: float

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec


def _to_seconds(hh: str | None, mm: str, ss: str) -> float | None:
    minutes, seconds = int(mm), int(ss)
    if seconds >= 60:
        return None
    if hh is None and minutes >= 60:
        # 시가 없는데 분이 60 이상이면 타임스탬프가 아니다(예: "99:99").
        return None
    return int(hh or 0) * 3600 + minutes * 60 + seconds


def _parse_line(line: str) -> tuple[float, str] | None:
    """한 줄에서 (시작초, 제목)을 뽑는다. 챕터 줄이 아니면 None."""
    stripped = line.strip()
    if not stripped:
        return None

    match = _LEADING_TS.match(stripped)
    if match:
        start = _to_seconds(*match.groups())
        title = stripped[match.end():]
    else:
        match = _TRAILING_TS.search(stripped)
        if not match:
            return None
        start = _to_seconds(*match.groups())
        title = stripped[: match.start()]

    if start is None:
        return None
    return start, title.strip(_TITLE_TRIM).strip()


def parse_chapters(description: str, duration_sec: float) -> list[Chapter]:
    """설명 + 영상 길이 → 챕터 목록. 챕터가 아니면 빈 목록.

    각 챕터의 끝은 **다음 챕터의 시작**이고, 마지막 챕터의 끝은 영상 길이다.
    영상 길이를 모르거나(0) 마지막 시작보다 작으면 **마지막 챕터를 버린다** —
    끝을 모르는 구간은 추출할 수 없고, 길이를 억지로 추측하면 잘린 클립이 나온다.
    """
    if not description:
        return []

    marks: list[tuple[float, str]] = []
    for line in description.splitlines():
        parsed = _parse_line(line)
        if parsed is None:
            continue
        start, title = parsed
        if marks and start <= marks[-1][0]:
            continue  # 뒤로 가는 값 = 본문 속 시각 표기
        marks.append((start, title))

    if len(marks) < MIN_CHAPTERS:
        return []

    chapters: list[Chapter] = []
    for i, (start, title) in enumerate(marks):
        if i + 1 < len(marks):
            end = marks[i + 1][0]
        elif duration_sec > start:
            end = float(duration_sec)
        else:
            break  # 끝을 모르는 마지막 구간은 버린다
        chapters.append(
            Chapter(title=title or f"챕터 {i + 1}", start_sec=float(start), end_sec=float(end))
        )

    # 마지막을 버리고 나서 1개만 남으면 챕터로 볼 수 없다.
    return chapters if len(chapters) >= MIN_CHAPTERS else []
