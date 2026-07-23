from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from domain.song.entities import SongInfo
from domain.song.events import SongInfoUpdated
from domain.song.value_objects import LyricsLine, SongSourceRef


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SongInfoAggregate:
    """노래 정보 애그리게이트 루트. 상태 변경은 모두 이 메서드를 통해서만 이뤄진다.

    - ``apply_fetched``: 외부 조회(등록 시/갱신 시) 결과를 반영하되, 사용자가 직접
      편집한 필드(``manual_fields``)는 보존한다.
    - ``edit_field``/``edit_lyrics``: 사용자의 더블클릭 편집 — 해당 필드를
      ``manual_fields``에 등록해 이후 갱신에서 덮어쓰이지 않게 한다.
    """

    def __init__(self, info: SongInfo) -> None:
        self._info = info
        self._events: list = []

    # ── Factory ───────────────────────────────────────────────────
    @classmethod
    def create(cls, video_id: UUID, *, is_song: bool = False) -> "SongInfoAggregate":
        return cls(SongInfo.create(video_id, is_song=is_song))

    # ── Read accessors ────────────────────────────────────────────
    @property
    def id(self) -> UUID:
        return self._info.video_id

    @property
    def info(self) -> SongInfo:
        return self._info

    # ── State mutation ────────────────────────────────────────────
    def set_song_flag(self, is_song: bool) -> None:
        if self._info.is_song != is_song:
            self._info.is_song = is_song
            self._touch(("is_song",))

    def apply_fetched(
        self,
        *,
        artist: str | None = None,
        album: str | None = None,
        song_title: str | None = None,
        release_year: str | None = None,
        lyrics_lines: list[LyricsLine] | None = None,
        lyrics_language: str | None = None,
        source: SongSourceRef | None = None,
        mark_song: bool | None = None,
        force_lyrics: bool = False,
    ) -> None:
        """조회 결과를 반영한다. 수동 편집 필드는 건너뛴다.

        force_lyrics=True면 사용자가 명시적으로 '다음 출처 검색'을 요청한 경우로, 가사가
        수동 편집으로 표시돼 있어도 새 가사로 교체한다.

        빈 값(빈 문자열/빈 리스트)은 기존 값을 지우지 않도록 무시한다 — 여러 출처를
        단계적으로 시도하며 부족분만 채우는 체인 방식과 맞물려, 뒤 출처가 앞 출처의
        결과를 지우지 않게 한다.
        """
        manual = self._info.manual_fields
        changed: list[str] = []

        if mark_song is not None and self._info.is_song != mark_song:
            self._info.is_song = mark_song
            changed.append("is_song")

        if artist and "artist" not in manual and artist != self._info.artist:
            self._info.artist = artist
            changed.append("artist")
        if album and "album" not in manual and album != self._info.album:
            self._info.album = album
            changed.append("album")
        if song_title and "song_title" not in manual and song_title != self._info.song_title:
            self._info.song_title = song_title
            changed.append("song_title")
        if release_year and "release_year" not in manual and release_year != self._info.release_year:
            self._info.release_year = release_year
            changed.append("release_year")
        if lyrics_lines and (force_lyrics or "lyrics" not in manual) \
                and lyrics_lines != self._info.lyrics_lines:
            self._info.lyrics_lines = list(lyrics_lines)
            if lyrics_language:
                self._info.lyrics_language = lyrics_language
            if source is not None:
                self._info.source = source
            changed.append("lyrics")

        if changed:
            self._touch(tuple(changed))

    def edit_field(self, field: str, value: str) -> None:
        """사용자의 필드 편집(가수/앨범/제목/발매년도) — 수동 필드로 표시."""
        if field not in ("artist", "album", "song_title", "release_year"):
            raise ValueError(f"편집할 수 없는 필드: {field}")
        value = value.strip()
        if getattr(self._info, field) == value:
            return
        setattr(self._info, field, value)
        self._info.manual_fields = self._info.manual_fields | {field}
        self._touch((field,))

    def set_lyrics_translations(self, lines: list[LyricsLine]) -> None:
        """현재 가사를 번역 포함 버전으로 교체한다(출처 유지·수동 표시 안 함).

        표준 '번역' 동작 — 조회와 분리해, 이미 등록된 가사에 한글 번역만 다시 입힌다.
        """
        if not lines or lines == self._info.lyrics_lines:
            return
        self._info.lyrics_lines = list(lines)
        self._touch(("lyrics",))

    def edit_lyrics(self, lines: list[LyricsLine], *, source_name: str = "직접 입력") -> None:
        """사용자의 가사 편집 — 수동 필드로 표시하고 출처를 사용자 입력으로 바꾼다."""
        if lines == self._info.lyrics_lines:
            return
        self._info.lyrics_lines = list(lines)
        self._info.manual_fields = self._info.manual_fields | {"lyrics"}
        self._info.source = SongSourceRef(name=source_name, url="")
        self._touch(("lyrics",))

    # ── Event infrastructure ──────────────────────────────────────
    def _touch(self, changed: tuple[str, ...]) -> None:
        self._info.updated_at = _now()
        self._events.append(SongInfoUpdated(video_id=self._info.video_id, changed_fields=changed))

    def pull_events(self) -> list:
        events = list(self._events)
        self._events.clear()
        return events
