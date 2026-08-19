"""앨범 캐시 저장소 인터페이스 + 그 저장 단위(레코드).

앨범은 저장되는 아그리게이트가 **아니다** — 노래 정보에서 파생되는 묶음이다. 여기 담는
것은 (1) 외부에서 받아온 자켓·발매일·수록곡을 다시 조회하지 않기 위한 캐시, (2) 라이브러리에
없는 수록곡에 자동으로 붙인 스트리밍 영상, (3) 앨범을 못 찾은 곡의 재조회 방지 기록뿐이다.
전부 지워도 다시 조회하면 복구되므로 동기화 대상이 아니다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from uuid import UUID

from domain.song.ports import AlbumTrackInfo


@dataclass(slots=True)
class AlbumCacheRecord:
    """외부에서 받아 저장해 둔 앨범 정보 1건."""

    album_key: str
    album_title: str = ""
    artist: str = ""
    artwork_url: str = ""
    artwork_path: str = ""      # THUMBNAIL_DIR 기준 상대경로 ("" = 미다운로드)
    description: str = ""
    release_date: str = ""
    genre: str = ""
    copyright: str = ""
    track_count: int = 0
    tracks: list[AlbumTrackInfo] = field(default_factory=list)
    source_name: str = ""
    source_url: str = ""
    fetched_at: str = ""


# 자동 매핑 링크의 origin 값.
TRACK_LINK_AUTO = "auto"          # 자동 검색으로 붙인 스트리밍 영상
# 사용자가 "이 음원은 이 곡이 아니다"라고 지운 자리. 행을 지우지 않고 이 표시로 남기는
# 이유는, 그냥 지우면 **앨범을 다시 열 때 자동 채우기가 같은 영상을 도로 붙이기**
# 때문이다(실측 — 지우는 기능이 사실상 무력했다). 사용자가 '빠진 곡 찾기'를 직접
# 누르면 그때만 다시 시도한다.
TRACK_LINK_REJECTED = "rejected"


@dataclass(slots=True)
class AlbumTrackLink:
    """라이브러리에 없는 수록곡에 자동으로 붙인 스트리밍 영상.

    키는 (album_key, disc_no, track_no)다 — 번호만 쓰면 2장짜리 앨범에서 disc1·disc2의
    같은 번호가 서로를 덮어써 두 곡이 같은 영상을 가리킨다.
    """

    album_key: str
    track_no: int
    disc_no: int = 1
    track_title: str = ""
    stream_url: str = ""
    stream_title: str = ""
    stream_channel: str = ""
    stream_yt_id: str = ""
    duration_sec: int | None = None
    origin: str = "auto"


class IAlbumRepository(ABC):
    """앨범 캐시/자동 매핑 저장소."""

    @abstractmethod
    def get_album(self, album_key: str) -> AlbumCacheRecord | None: ...

    @abstractmethod
    def save_album(self, record: AlbumCacheRecord) -> None: ...

    @abstractmethod
    def list_albums(self, album_keys: list[str]) -> dict[str, AlbumCacheRecord]:
        """여러 앨범 캐시를 한 번에 읽는다(앨범 그리드용 — 건별 조회를 피한다)."""
        ...

    @abstractmethod
    def get_track_links(self, album_key: str) -> dict[tuple[int, int], AlbumTrackLink]:
        """(disc_no, track_no) → 자동 매핑된 스트리밍 영상."""
        ...

    @abstractmethod
    def save_track_link(self, link: AlbumTrackLink) -> None: ...

    @abstractmethod
    def clear_track_links(self, album_key: str) -> None:
        """자동 매핑을 모두 지운다(다시 찾기)."""
        ...

    @abstractmethod
    def reject_track_link(self, album_key: str, disc_no: int, track_no: int) -> None:
        """자동 매핑 1건을 '거부됨'으로 표시한다(잘못 붙은 음원을 사용자가 제거).

        스트림 정보를 비워 그 수록곡은 다시 '없음'으로 보이지만, 행 자체는
        ``origin=rejected``로 남는다 — 행을 지워 버리면 앨범을 다시 열 때 자동
        채우기가 같은 영상을 도로 붙인다. 사용자가 '빠진 곡 찾기'를 직접 누를 때만
        다시 시도한다.
        """
        ...

    @abstractmethod
    def mark_album_lookup(self, video_id: UUID, found: bool) -> None:
        """앨범 미상 곡의 외부 조회 시도를 기록한다(실패 재조회 방지)."""
        ...

    @abstractmethod
    def filter_unlooked(self, video_ids: list[UUID]) -> list[UUID]:
        """아직 앨범 조회를 시도하지 않은 video_id만 남긴다."""
        ...
