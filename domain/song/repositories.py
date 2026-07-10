from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from domain.song.aggregates import SongInfoAggregate
from domain.song.entities import LyricsSource


class ISongRepository(ABC):
    """노래 정보 + 가사 출처 레지스트리 저장소 인터페이스."""

    # ── SongInfo ──────────────────────────────────────────────────
    @abstractmethod
    def get(self, video_id: UUID) -> SongInfoAggregate | None: ...

    @abstractmethod
    def save(self, aggregate: SongInfoAggregate) -> None: ...

    @abstractmethod
    def delete(self, video_id: UUID) -> None: ...

    @abstractmethod
    def find_video_ids_by(
        self, *, artist: str | None = None, album: str | None = None
    ) -> list[UUID]:
        """노래(is_song=1)로 표시된 영상 중 가수/앨범이 일치하는 video_id 목록.

        artist·album 중 지정된 것만 매칭한다(둘 다 None이면 빈 리스트). 같은 가수/앨범
        영상을 상세화면 재생목록으로 나열하는 데 쓴다.
        """
        ...

    # ── 가사 출처 레지스트리 (관리형 목록) ────────────────────────────
    @abstractmethod
    def list_lyrics_sources(self) -> list[LyricsSource]:
        """priority 오름차순으로 정렬된 전체 출처 목록."""
        ...

    @abstractmethod
    def save_lyrics_source(self, source: LyricsSource) -> None: ...

    @abstractmethod
    def delete_lyrics_source(self, source_id: UUID) -> None: ...

    @abstractmethod
    def set_lyrics_sources_order(self, ordered_ids: list[UUID]) -> None:
        """주어진 순서대로 priority를 재부여한다."""
        ...
