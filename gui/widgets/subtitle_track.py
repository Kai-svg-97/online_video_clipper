"""영상 자막 트랙 — 재생 위치로 현재 자막을 찾는 순수 로직.

`LyricsTrack`(가사)과 나란히 두지만 **규칙이 다르다**. 가사 줄은 시작 시각만 있어
"다음 줄이 시작할 때까지" 떠 있지만, 영상 자막은 **끝 시각이 따로 있어** 말이 없는
구간에서는 아무것도 뜨지 않아야 한다. 그 차이를 흐리면 대사가 끝난 뒤에도 자막이
화면에 남는다.

Qt에 의존하지 않으므로 QApplication 없이 단위 테스트한다.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

# 싱크 보정 한계 — 가사 자막과 같은 값을 쓴다(±30초). 사용자가 두 기능에서 서로 다른
# 한계를 만나면 혼란스럽다.
from domain.song.aggregates import MAX_LYRICS_OFFSET_MS

MAX_SUBTITLE_OFFSET_MS = MAX_LYRICS_OFFSET_MS


@dataclass(frozen=True, slots=True)
class SubtitleCue:
    start_ms: int
    end_ms: int
    text: str


class SubtitleTrack:
    """시작·끝이 있는 자막 큐 모음. **Qt 비의존 순수 로직.**

    겹치는 큐는 뒤엣것을 택한다(자동 자막에서 앞 문장이 늦게 끝나는 경우가 흔하다).
    """

    def __init__(self, cues: list[SubtitleCue], offset_ms: int = 0,
                 lang: str = "", label: str = "") -> None:
        self._cues = sorted(cues, key=lambda c: c.start_ms)
        self._starts = [c.start_ms for c in self._cues]
        self._offset_ms = 0
        self.offset_ms = offset_ms
        self.lang = lang
        self.label = label

    @classmethod
    def from_tuples(cls, cues, offset_ms: int = 0, lang: str = "",
                    label: str = "") -> "SubtitleTrack":
        """`(시작ms, 끝ms, 텍스트)` 목록으로 트랙을 만든다(파서 출력 그대로)."""
        return cls(
            [SubtitleCue(int(s), int(e), t) for s, e, t in (cues or []) if t],
            offset_ms=offset_ms, lang=lang, label=label,
        )

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
            -MAX_SUBTITLE_OFFSET_MS, min(MAX_SUBTITLE_OFFSET_MS, int(value))
        )

    def cue_at(self, pos_ms: int) -> SubtitleCue | None:
        """이 시점에 떠 있어야 할 자막(없으면 None — 대사가 없는 구간)."""
        if not self._cues:
            return None
        target = pos_ms - self._offset_ms
        idx = bisect.bisect_right(self._starts, target) - 1
        if idx < 0:
            return None
        cue = self._cues[idx]
        return cue if target < cue.end_ms else None

    def text_at(self, pos_ms: int) -> str:
        cue = self.cue_at(pos_ms)
        return cue.text if cue else ""
