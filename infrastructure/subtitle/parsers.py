"""자막 파일 파서 — json3 / WebVTT → (시작ms, 끝ms, 텍스트) 목록.

가사 LRC 파서(`infrastructure/song/lrc.py`)와 같은 자리의 순수 함수다. 네트워크·Qt에
의존하지 않으므로 규칙을 단위 테스트로 못박는다 — 자막은 **한 글자만 어긋나도 바로
보이는** 종류의 기능이라 파싱 규칙이 조용히 바뀌면 곤란하다.

두 형식을 다루는 이유:

* **json3** — YouTube가 주는 가장 깨끗한 형식. 조각(`segs`)을 이어 붙이면 되고 시작·
  지속 시간이 정수 ms라 반올림 오차가 없다. 가능하면 이걸 쓴다.
* **WebVTT** — 그 외 사이트와 일부 트랙의 공통 분모. 다만 YouTube의 자동 생성 vtt는
  단어 단위 타이밍(`<00:00:01.234><c>단어</c>`)과 **한 줄씩 밀려 올라가는 중복 표시**가
  섞여 있어, 태그를 걷어내고 **직전 자막과 같은 줄은 버린다**(안 그러면 같은 문장이
  두 번씩 겹쳐 보인다 — 실제 자동 자막에서 흔한 모양이다).
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# (시작ms, 끝ms, 텍스트)
Cue = tuple[int, int, str]

# vtt 큐 헤더: 00:00:01.000 --> 00:00:03.000 (뒤에 위치 지정자가 붙을 수 있다)
_VTT_TIME = re.compile(
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})\s*-->\s*"
    r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})"
)
_TAG = re.compile(r"<[^>]+>")           # <c>, <00:00:01.234>, <v Speaker> 등
_MIN_DURATION_MS = 300                  # 끝 시각이 없거나 뒤집힌 경우의 최소 노출


def _clean(text: str) -> str:
    """태그를 걷어내고 공백을 정리한다(빈 문자열이면 버릴 신호)."""
    text = _TAG.sub("", text)
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&#39;", "'").replace("&quot;", '"')
    return " ".join(text.split())


def _dedupe(cues: list[Cue]) -> list[Cue]:
    """직전과 같은 문장은 버린다 — 자동 자막의 '밀려 올라가는' 중복 제거."""
    out: list[Cue] = []
    for start, end, text in cues:
        if out and out[-1][2] == text:
            # 같은 문장이 이어지면 앞 자막의 끝을 늘려 하나로 합친다.
            prev_start, prev_end, prev_text = out[-1]
            out[-1] = (prev_start, max(prev_end, end), prev_text)
            continue
        out.append((start, end, text))
    return out


def parse_json3(raw: str) -> list[Cue]:
    """YouTube json3 캡션 → 큐 목록. 형식이 아니면 빈 목록."""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        logger.debug("json3 파싱 실패 — 다른 형식으로 간주")
        return []
    cues: list[Cue] = []
    for event in data.get("events") or []:
        segs = event.get("segs")
        if not segs:
            continue          # 배경 음악 표시 등 텍스트 없는 이벤트
        text = _clean("".join(seg.get("utf8", "") for seg in segs))
        if not text:
            continue
        start = int(event.get("tStartMs") or 0)
        dur = int(event.get("dDurationMs") or 0)
        cues.append((start, start + max(dur, _MIN_DURATION_MS), text))
    return _dedupe(sorted(cues, key=lambda c: c[0]))


def _vtt_ms(h, m, s, ms) -> int:
    return (int(h or 0) * 3600 + int(m) * 60 + int(s)) * 1000 + int((ms or "0").ljust(3, "0"))


def parse_vtt(raw: str) -> list[Cue]:
    """WebVTT → 큐 목록. 시간 줄이 하나도 없으면 빈 목록."""
    cues: list[Cue] = []
    start = end = 0
    buf: list[str] = []
    in_cue = False

    def flush() -> None:
        nonlocal buf
        if in_cue:
            text = _clean(" ".join(buf))
            if text:
                cues.append((start, max(end, start + _MIN_DURATION_MS), text))
        buf = []

    for line in (raw or "").splitlines():
        match = _VTT_TIME.search(line)
        if match:
            flush()
            g = match.groups()
            start = _vtt_ms(g[0], g[1], g[2], g[3])
            end = _vtt_ms(g[4], g[5], g[6], g[7])
            in_cue = True
            continue
        if not line.strip():
            flush()
            in_cue = False
            continue
        if in_cue:
            buf.append(line)
    flush()
    return _dedupe(sorted(cues, key=lambda c: c[0]))


def parse_cues(raw: str, ext: str = "") -> list[Cue]:
    """확장자 힌트로 파서를 고르고, 빗나가면 다른 파서로 한 번 더 시도한다.

    출처가 주는 확장자와 실제 내용이 어긋나는 경우가 있어(리다이렉트·형식 변경)
    힌트를 믿되 결과가 비면 반대쪽도 시도한다 — 자막을 통째로 잃는 것보다 낫다.
    """
    ext = (ext or "").lower()
    first, second = (parse_json3, parse_vtt) if ext == "json3" else (parse_vtt, parse_json3)
    cues = first(raw)
    return cues or second(raw)
