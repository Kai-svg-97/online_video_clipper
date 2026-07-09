from __future__ import annotations

import logging
from uuid import UUID

from application.song.dtos import LyricsLineDTO, LyricsSourceDTO, SongInfoDTO
from domain.song.aggregates import SongInfoAggregate
from domain.song.repositories import ISongRepository

logger = logging.getLogger(__name__)


def song_to_dto(agg: SongInfoAggregate) -> SongInfoDTO:
    info = agg.info
    return SongInfoDTO(
        video_id=info.video_id,
        is_song=info.is_song,
        artist=info.artist,
        album=info.album,
        song_title=info.song_title,
        release_year=info.release_year,
        lyrics_lines=tuple(
            LyricsLineDTO(original=ln.original, translation=ln.translation)
            for ln in info.lyrics_lines
        ),
        lyrics_language=info.lyrics_language,
        source_name=info.source.name if info.source else "",
        source_url=info.source.url if info.source else "",
    )


class GetSongInfoHandler:
    def __init__(self, song_repo: ISongRepository) -> None:
        self._songs = song_repo

    def handle(self, video_id: UUID) -> SongInfoDTO | None:
        agg = self._songs.get(video_id)
        if agg is None:
            return None
        return song_to_dto(agg)


class ListLyricsSourcesHandler:
    def __init__(self, song_repo: ISongRepository) -> None:
        self._songs = song_repo

    def handle(self) -> list[LyricsSourceDTO]:
        return [
            LyricsSourceDTO(
                id=s.id,
                name=s.name,
                provider_key=s.provider_key,
                base_url=s.base_url,
                enabled=s.enabled,
                priority=s.priority,
            )
            for s in self._songs.list_lyrics_sources()
        ]
