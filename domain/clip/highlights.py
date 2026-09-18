"""자막에서 '볼 만한 구간'을 뽑는 **순수 규칙** — I/O 없음, 모델 호출 없음.

**왜 규칙 기반인가**: 이 기능의 값은 "어디부터 볼까"를 줄여 주는 데 있지, 완벽한
편집점을 찾는 데 있지 않다. 외부 AI를 부르면 영상마다 비용·대기가 생기고 오프라인에서
죽는데, 얻는 것은 '그럴듯한 순서'뿐이다. 이미 손에 있는 자막만으로 충분히 쓸 만한
후보를 만들 수 있다.

**무엇을 신호로 보는가**

- **말이 몰린 구간** — 같은 시간에 글자가 많을수록 설명·핵심일 확률이 높다.
  잡담·정적은 자연히 아래로 내려간다.
- **챕터 경계** — 업로더가 직접 나눈 지점이라 가장 믿을 만하다. 겹치면 그쪽으로 당긴다.
- **시작부는 다른 후보가 있으면 뺀다** — 인사·구독 요청은 빠르게 말해서 글자 밀도가
  본론보다 훨씬 높다. 배수로 깎는 방식은 밀도 차가 조금만 커도 무력해져(실측: 0.35배로
  깎아도 3.3배 촘촘한 인사말이 1등이었다) 아예 후보에서 뺀다. 다만 **다른 후보가 하나도
  없으면 그거라도 준다** — 짧은 영상은 전부가 시작부다.

**제안일 뿐이다.** 여기서 나온 구간은 클립 탭의 후보로 보여 주고, 자를지는 사람이
정한다 — 자동으로 잘라 두면 쓰지도 않을 파일이 쌓인다.
"""

from __future__ import annotations

from dataclasses import dataclass

# 후보 한 구간의 목표 길이(초). 너무 짧으면 맥락이 없고, 너무 길면 '클립'이 아니다.
TARGET_SEC = 60.0
MIN_SEC = 20.0
MAX_SEC = 180.0

# 이 시각 이전은 인사·구독 요청이 몰린다 — 글자는 많지만 볼 이유는 없다.
INTRO_SEC = 45.0

# 후보끼리 이만큼 겹치면 같은 구간으로 본다(둘 중 점수가 높은 쪽만 남긴다).
OVERLAP_RATIO = 0.5


@dataclass(frozen=True, slots=True)
class Highlight:
    """제안 구간 하나."""

    start_sec: float
    end_sec: float
    score: float
    title: str = ""

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec


def _density_windows(
    cues: list[tuple[int, int, str]], window_sec: float
) -> list[tuple[float, float, float]]:
    """자막 줄을 훑으며 `(시작, 끝, 글자수)` 창을 만든다.

    창은 **자막 줄 경계에서 시작**한다 — 고정 간격으로 자르면 문장 한복판에서
    끊긴 구간이 후보로 올라온다.
    """
    windows: list[tuple[float, float, float]] = []
    for i, (start_ms, _end_ms, _text) in enumerate(cues):
        start = start_ms / 1000.0
        end = start + window_sec
        chars = 0
        for cue_start, cue_end, text in cues[i:]:
            if cue_start / 1000.0 >= end:
                break
            chars += len(text)
            end_actual = cue_end / 1000.0
        else:
            end_actual = end
        if chars:
            windows.append((start, min(end, max(end_actual, start + MIN_SEC)), float(chars)))
    return windows


def _overlaps(a: Highlight, b: Highlight) -> bool:
    overlap = min(a.end_sec, b.end_sec) - max(a.start_sec, b.start_sec)
    if overlap <= 0:
        return False
    shorter = min(a.duration_sec, b.duration_sec) or 1.0
    return overlap / shorter >= OVERLAP_RATIO


def _snap_to_chapter(
    start: float, chapters: list[tuple[str, float, float]]
) -> tuple[float, str]:
    """구간 시작을 가까운 챕터 경계로 당긴다.

    업로더가 직접 나눈 지점이라 기계가 고른 경계보다 낫다. 30초 넘게 떨어져 있으면
    남의 챕터이므로 당기지 않는다.
    """
    best: tuple[float, str] | None = None
    for title, ch_start, _ch_end in chapters or []:
        gap = abs(ch_start - start)
        if gap <= 30.0 and (best is None or gap < abs(best[0] - start)):
            best = (ch_start, title)
    return best if best else (start, "")


def suggest_highlights(
    cues: list[tuple[int, int, str]],
    duration_sec: float,
    chapters: list[tuple[str, float, float]] | None = None,
    limit: int = 5,
) -> list[Highlight]:
    """자막(+챕터) → 제안 구간 목록(점수 높은 순).

    자막이 없으면 빈 목록이다 — 이 기능은 **자막 위에서만** 성립한다.
    """
    if not cues or duration_sec <= 0 or limit <= 0:
        return []

    raw: list[Highlight] = []
    for start, end, chars in _density_windows(cues, TARGET_SEC):
        span = max(MIN_SEC, min(MAX_SEC, end - start))
        end = min(duration_sec, start + span)
        if end - start < MIN_SEC:
            continue
        snapped, title = _snap_to_chapter(start, chapters or [])
        score = chars / span
        if title:
            # 챕터 경계와 맞은 구간은 한 단계 올려 준다(사람이 나눈 지점이다).
            score *= 1.25
        raw.append(
            Highlight(
                start_sec=snapped,
                end_sec=min(duration_sec, snapped + span),
                score=score,
                title=title,
            )
        )

    # 시작부는 다른 후보가 있을 때만 뺀다(모듈 설명 참조).
    after_intro = [h for h in raw if h.start_sec >= INTRO_SEC]
    raw = after_intro or raw
    raw.sort(key=lambda h: h.score, reverse=True)

    picked: list[Highlight] = []
    for candidate in raw:
        if any(_overlaps(candidate, chosen) for chosen in picked):
            continue
        picked.append(candidate)
        if len(picked) >= limit:
            break
    # 화면에는 **시간 순**으로 보여준다 — 점수 순으로 늘어놓으면 영상의 흐름을 잃는다.
    picked.sort(key=lambda h: h.start_sec)
    return picked
