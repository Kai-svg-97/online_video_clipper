from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID

from domain.song.aggregates import SongInfoAggregate
from domain.song.entities import LyricsSource


@dataclass(frozen=True, slots=True)
class SongFields:
    """앨범 그루핑용 최소 노래 정보 — 아그리게이트 전체(가사 포함)를 읽지 않기 위해 둔다.

    카테고리 하나에 수백 곡이 있을 수 있는데, 그룹을 만드는 데 필요한 건 가수·앨범·제목뿐이다.
    가사 JSON까지 파싱해 올리면 앨범 화면을 열 때마다 불필요한 비용이 든다.
    """

    is_song: bool = False
    artist: str = ""
    album: str = ""
    song_title: str = ""


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

    @abstractmethod
    def list_song_fields(self, video_ids: list[UUID]) -> dict[UUID, SongFields]:
        """여러 영상의 노래 정보(가수·앨범·제목)를 한 번에 읽는다.

        노래 정보가 없는 영상은 결과에 없다(호출부가 기본값으로 다룬다).
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
