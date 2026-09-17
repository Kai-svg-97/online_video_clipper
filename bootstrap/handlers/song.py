"""노래 정보·가사 유스케이스 조립.

**다른 컨텍스트보다 먼저 만들어져야 한다.** `SongHandlers.fetch`(가사·메타데이터 체인
조회)를 라이브러리 등록 경로가 쓴다 — `AddVideoHandler`가 등록 시 노래를 감지해
메타데이터를 기록하고, `EnrichVideoHandler`가 등록 직후 가사를 채운다.
"""

from __future__ import annotations

from application.song.commands import (
    AddLyricsSourceHandler,
    ApplyLyricsCandidateHandler,
    DeleteLyricsSourceHandler,
    FetchSongInfoHandler,
    ReorderLyricsSourcesHandler,
    SearchLyricsCandidatesHandler,
    SetLyricsOffsetHandler,
    SetSongFlagHandler,
    TranslateSongLyricsHandler,
    UpdateLyricsSourceHandler,
    UpdateSongFieldHandler,
    UpdateSongLyricsHandler,
)
from application.song.tagging import SongTagWriter
from application.song.queries import (
    FindSongVideoIdsHandler,
    GetSongInfoHandler,
    ListLyricsSourcesHandler,
)

from bootstrap.context import Repositories, Services, SongHandlers


def build(repos: Repositories, services: Services) -> SongHandlers:
    song, video = repos.song, repos.video
    bus = services.event_bus
    return SongHandlers(
        fetch=FetchSongInfoHandler(
            song,
            video,
            bus,
            lyrics_providers=services.lyrics_providers,
            translator=services.translator,
            media_source=services.media_source,
        ),
        get_info=GetSongInfoHandler(song),
        search_candidates=SearchLyricsCandidatesHandler(
            song, video, lyrics_providers=services.lyrics_providers
        ),
        apply_candidate=ApplyLyricsCandidateHandler(song, bus, services.translator),
        set_flag=SetSongFlagHandler(song, bus),
        update_field=UpdateSongFieldHandler(song, bus),
        update_lyrics=UpdateSongLyricsHandler(song, bus),
        translate_lyrics=TranslateSongLyricsHandler(song, services.translator, bus),
        set_lyrics_offset=SetLyricsOffsetHandler(song, bus),
        find_video_ids=FindSongVideoIdsHandler(song),
        list_sources=ListLyricsSourcesHandler(song),
        add_source=AddLyricsSourceHandler(song),
        update_source=UpdateLyricsSourceHandler(song),
        delete_source=DeleteLyricsSourceHandler(song),
        reorder_sources=ReorderLyricsSourcesHandler(song),
        tag_writer=SongTagWriter(bus, video, song, services.audio_tagger),
    )
