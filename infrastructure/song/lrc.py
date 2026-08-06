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

    - 한 줄에 타임스탐프가 여러 개면 같은 가사를 각 시각으로 전개한다(반복 구간 표기).
    - ``[ar:]``·``[ti:]`` 등 메타 태그는 버리고, ``[offset:±ms]``는 모든 시각에 더한다
      (LRC 표준. 음수 결과는 0으로 보정).
    - 타임스탐프가 없는 줄은 ``(None, 줄)``로 보존한다 — 텍스트를 잃지 않기 위함이며,
      정렬 시 시각이 있는 줄 뒤로 밀린다.
    - 실패해도 예외를 던지지 않는다(파싱 가능한 것만 돌려준다).
    """
    if not text.strip():
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
