from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class LyricsLineDTO:
    original: str
    translation: str = ""
    start_ms: int | None = None


@dataclass(frozen=True)
class SongInfoDTO:
    video_id: UUID
    is_song: bool
    artist: str = ""
    album: str = ""
    song_title: str = ""
    release_year: str = ""
    lyrics_lines: tuple[LyricsLineDTO, ...] = ()
    lyrics_language: str = ""
    lyrics_offset_ms: int = 0
    source_name: str = ""
    source_url: str = ""

    @property
    def has_lyrics(self) -> bool:
        return bool(self.lyrics_lines)

    @property
    def is_bilingual(self) -> bool:
        """번역이 병행 표기된 가사인지(원문≠한국어)."""
        return any(line.translation for line in self.lyrics_lines)

    @property
    def is_synced(self) -> bool:
        """시간 정보가 있는 줄이 있는지 — 자막·싱크 UI 활성 조건."""
        return any(line.start_ms is not None for line in self.lyrics_lines)


@dataclass(frozen=True)
class LyricsCandidateDTO:
    """가사 검색 후보 한 건 — 출처 하나가 돌려준 결과를 목록에 보여주기 위한 값.

    저장된 노래 정보가 아니라 **아직 채택하지 않은 후보**다. 사용자가 목록에서 고르면
    ``ApplyLyricsCandidateCommand``로 실제 반영한다. ``lines``/``timings``를 그대로
    담고 다니는 이유는, 고른 뒤 같은 출처를 다시 조회하지 않기 위해서다(네트워크 절약 +
    출처가 그새 다른 결과를 주는 일 방지).
    """

    source_name: str            # 표시용 출처 이름(LyricsSource.name)
    provider_key: str = ""
    artist: str = ""
    title: str = ""
    album: str = ""
    release_year: str = ""
    first_line: str = ""        # 목록에 미리보기로 띄우는 가사 첫째 줄
    is_synced: bool = False     # 시간 정보(LRC 타이밍)가 있는지 — 자막 표시 가능 여부
    line_count: int = 0
    popularity: int = 0         # 출처가 준 인기 지표(조회수 등). 0 = 지표 없음
    duration_sec: int | None = None   # 곡 길이(초) — 영상 길이와 비교해 정렬·판별에 쓴다
    source_url: str = ""
    lines: tuple[str, ...] = ()
    timings: tuple[int | None, ...] = ()
    language: str = ""


@dataclass(frozen=True)
class LyricsSourceDTO:
    id: UUID
    name: str
    provider_key: str
    base_url: str = ""
    enabled: bool = True
    priority: int = 100
