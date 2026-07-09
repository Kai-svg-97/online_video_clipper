from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4

from domain.song.value_objects import LyricsLine, SongSourceRef


def _now() -> datetime:
    return datetime.now(timezone.utc)


# 수동 편집 보존 대상 필드명 — 정보 갱신 시 사용자가 직접 고친 필드는 덮어쓰지 않는다.
MANUAL_FIELDS = frozenset({"artist", "album", "song_title", "release_year", "lyrics"})


@dataclass
class SongInfo:
    """영상 1건에 대한 노래 정보 (Video와 1:1, video_id가 식별자).

    ``is_song``은 자동 감지(YouTube Music 카테고리·track/artist 존재) 또는 사용자의
    수동 토글 결과다. ``manual_fields``는 사용자가 더블클릭으로 직접 편집한 필드명
    집합으로, 정보 갱신(⟳) 시 이 필드들은 재수집 값으로 덮어쓰지 않는다.
    """

    video_id: UUID
    is_song: bool = False
    artist: str = ""
    album: str = ""
    song_title: str = ""
    release_year: str = ""
    lyrics_lines: list[LyricsLine] = field(default_factory=list)
    lyrics_language: str = ""          # "" 미상, "ko", "en" 등 (ISO 639-1)
    source: SongSourceRef | None = None
    manual_fields: frozenset[str] = frozenset()
    updated_at: datetime = field(default_factory=_now)

    @classmethod
    def create(cls, video_id: UUID, *, is_song: bool = False) -> "SongInfo":
        return cls(video_id=video_id, is_song=is_song)


@dataclass
class LyricsSource:
    """가사·메타데이터 출처(사이트) 레지스트리 항목.

    ``provider_key``는 인프라의 제공자 구현과 매핑되는 키(예: "lrclib", "genius",
    "melon", "bugs", "genie"). ``enabled``/``priority``로 조회 체인의 사용 여부와
    순서를 제어한다(작을수록 먼저 시도). 관리형 목록이라 사용자가 추가·삭제·정렬할 수 있다.
    """

    id: UUID
    name: str
    provider_key: str
    base_url: str = ""
    enabled: bool = True
    priority: int = 100

    @classmethod
    def create(
        cls,
        name: str,
        provider_key: str,
        *,
        base_url: str = "",
        enabled: bool = True,
        priority: int = 100,
    ) -> "LyricsSource":
        return cls(
            id=uuid4(),
            name=name,
            provider_key=provider_key,
            base_url=base_url,
            enabled=enabled,
            priority=priority,
        )
