from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LyricsLine:
    """가사 한 줄.

    ``original``은 원문, ``translation``은 한글 번역(한국어 노래이거나 번역이 없으면 "").
    비한국어 노래는 원문 1줄 + 한글 1줄을 병행 표기하기 위해 두 값을 함께 담는다.
    """

    original: str
    translation: str = ""


@dataclass(frozen=True, slots=True)
class SongSourceRef:
    """가사·메타데이터를 실제로 가져온 출처(사이트) 참조."""

    name: str          # 표시 이름 (예: "LRCLIB", "Genius", "멜론")
    url: str = ""      # 원본 페이지 URL ("" 가능)
