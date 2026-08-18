"""앨범 보기 DTO — GUI가 읽는 읽기 전용 표현."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

# 수록곡 1건이 어디서 왔는지 — 목록에 배지로 표시한다.
TRACK_ORIGIN_LIBRARY = "library"   # 내가 등록한 라이브러리 영상
TRACK_ORIGIN_AUTO = "auto"         # 자동 검색으로 붙인 스트리밍 영상(official 음원 추정)
TRACK_ORIGIN_MISSING = "missing"   # 아직 못 찾음


@dataclass(frozen=True, slots=True)
class AlbumCardDTO:
    """앨범 그리드의 자켓 카드 1장."""

    key: str                      # "" = 앨범 미상 묶음
    album_title: str
    artist: str
    artwork_url: str = ""         # 외부 자켓 URL
    artwork_path: str = ""        # 내려받은 자켓(THUMBNAIL_DIR 기준 상대경로)
    fallback_thumb_path: str = "" # 자켓이 없을 때 쓸 대표 영상 썸네일
    library_count: int = 0        # 내가 가진 곡 수
    track_count: int = 0          # 외부 정보 기준 전체 수록곡 수(모르면 library_count)
    release_date: str = ""
    first_video_id: UUID | None = None   # 카드에서 바로 재생할 때의 시작 곡


@dataclass(frozen=True, slots=True)
class AlbumTrackDTO:
    """앨범 상세의 수록곡 1행."""

    track_no: int
    title: str
    artist: str = ""
    duration_sec: int | None = None
    # 트랙 번호는 디스크 안에서만 유일하다 — 행의 신원은 (disc_no, track_no) 쌍이다.
    disc_no: int = 1
    origin: str = TRACK_ORIGIN_MISSING
    video_id: UUID | None = None      # origin=library일 때
    stream_url: str = ""              # origin=auto일 때
    stream_title: str = ""
    stream_channel: str = ""
    stream_yt_id: str = ""
    thumbnail_path: str = ""

    @property
    def playable(self) -> bool:
        return self.origin in (TRACK_ORIGIN_LIBRARY, TRACK_ORIGIN_AUTO)

    @property
    def slot(self) -> tuple[int, int]:
        """수록곡 자리(디스크, 트랙) — 행 갱신·자동 매핑 저장의 키."""
        return (self.disc_no, self.track_no)


@dataclass(frozen=True, slots=True)
class AlbumDetailDTO:
    """앨범 상세 화면 전체."""

    key: str
    album_title: str
    artist: str
    artwork_url: str = ""
    artwork_path: str = ""
    fallback_thumb_path: str = ""
    description: str = ""
    release_date: str = ""
    genre: str = ""
    source_name: str = ""
    source_url: str = ""
    tracks: list[AlbumTrackDTO] = field(default_factory=list)

    @property
    def library_count(self) -> int:
        return sum(1 for t in self.tracks if t.origin == TRACK_ORIGIN_LIBRARY)

    @property
    def auto_count(self) -> int:
        return sum(1 for t in self.tracks if t.origin == TRACK_ORIGIN_AUTO)

    @property
    def missing_count(self) -> int:
        return sum(1 for t in self.tracks if t.origin == TRACK_ORIGIN_MISSING)
