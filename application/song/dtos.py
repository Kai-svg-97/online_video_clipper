from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class LyricsLineDTO:
    original: str
    translation: str = ""


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
    source_name: str = ""
    source_url: str = ""

    @property
    def has_lyrics(self) -> bool:
        return bool(self.lyrics_lines)

    @property
    def is_bilingual(self) -> bool:
        """번역이 병행 표기된 가사인지(원문≠한국어)."""
        return any(line.translation for line in self.lyrics_lines)


@dataclass(frozen=True)
class LyricsSourceDTO:
    id: UUID
    name: str
    provider_key: str
    base_url: str = ""
    enabled: bool = True
    priority: int = 100
