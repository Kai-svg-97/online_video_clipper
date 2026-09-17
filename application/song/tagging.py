"""다운로드된 음원에 라이브러리의 노래 정보를 태그로 기록하는 애플리케이션 서비스.

**왜 이벤트 구독인가**: download 컨텍스트가 song 컨텍스트를 직접 부르면 두 컨텍스트가
붙는다(CLAUDE.md의 DDD 규칙 — 컨텍스트 간 통신은 도메인 이벤트나 애플리케이션
서비스로만). 여기서는 `DownloadCompleted`를 구독해 **download 쪽이 song을 전혀
모르도록** 둔다.

**왜 설정을 직접 읽는가**: 태깅 여부는 작업별 값이 아니라 사용자 전역 설정이다.
이걸 `DownloadSettings`에 담으면 도메인 이벤트에 설정까지 실어 보내야 해서 이벤트가
무거워진다.

`DownloadCompleted`는 다운로드 워커 스레드에서 발행되므로 이 핸들러도 그 스레드에서
돈다 — Qt 객체를 만지지 않는다(파일 I/O와 저장소 조회뿐).
"""

from __future__ import annotations

import logging
from pathlib import Path

from config.settings import THUMBNAIL_DIR, resolve_media_path
from domain.download.events import DownloadCompleted
from domain.download.value_objects import AUDIO_FORMAT_VALUES
from domain.library.repositories import IVideoRepository
from domain.shared.ports import AudioTags, IAudioTagger, IEventBus
from domain.song.entities import SongInfo
from domain.song.repositories import ISongRepository

logger = logging.getLogger(__name__)


def _format_lrc_time(ms: int) -> str:
    total_cs = max(0, ms) // 10
    minutes, rem_cs = divmod(total_cs, 6000)
    seconds, cs = divmod(rem_cs, 100)
    return f"[{minutes:02d}:{seconds:02d}.{cs:02d}]"


def build_lyrics_text(info: SongInfo) -> str:
    """태그에 넣을 가사 문자열.

    싱크 가사면 LRC(``[mm:ss.xx]`` 접두)로 만든다 — 다른 플레이어에서도 줄이 따라
    흐른다. 싱크가 없으면 평문이다. 번역이 있으면 원문 아래 줄에 함께 넣는다(앱
    안의 병행 표기와 같은 모양).

    ``lyrics_offset_ms``는 **반영하지 않는다**. 그 값은 '이 영상과 이 가사의 어긋남'을
    보정하는 값이라 다른 파일·다른 플레이어에서는 의미가 없다.
    """
    lines: list[str] = []
    for line in info.lyrics_lines:
        prefix = _format_lrc_time(line.start_ms) if line.start_ms is not None else ""
        if line.original:
            lines.append(f"{prefix}{line.original}")
        if line.translation:
            lines.append(f"{prefix}{line.translation}")
    return "\n".join(lines)


def build_audio_tags(info: SongInfo, cover_path: Path | None) -> AudioTags:
    """노래 정보 → 태그 값객체. 비어 있는 필드는 비운 채 둔다(빈 값으로 덮어쓰지 않음)."""
    return AudioTags(
        title=info.song_title,
        artist=info.artist,
        album=info.album,
        year=info.release_year,
        lyrics=build_lyrics_text(info),
        cover_path=cover_path,
    )


class SongTagWriter:
    """`DownloadCompleted` → 음원이면 노래 정보를 태그로 기록."""

    def __init__(
        self,
        event_bus: IEventBus,
        video_repo: IVideoRepository,
        song_repo: ISongRepository,
        tagger: IAudioTagger,
    ) -> None:
        self._videos = video_repo
        self._songs = song_repo
        self._tagger = tagger
        event_bus.subscribe(DownloadCompleted, self._on_completed)

    def _on_completed(self, event: DownloadCompleted) -> None:
        try:
            self._tag(event.url, event.file_path)
        except Exception:
            # 태깅은 부가 산출물이다 — 실패해도 다운로드 결과를 뒤집지 않는다.
            logger.exception("음원 태그 기록 실패 (무시): %s", event.file_path)

    # ------------------------------------------------------------------

    def _tag(self, url: str, file_path: str) -> None:
        from config import settings as cfg  # noqa: PLC0415 (런타임 토글)

        if not cfg.WRITE_SONG_TAGS:
            return
        path = Path(resolve_media_path(file_path or ""))
        if path.suffix.lstrip(".").lower() not in AUDIO_FORMAT_VALUES:
            return

        agg = self._videos.get_by_url(url)
        if agg is None:
            logger.debug("라이브러리에 없는 URL이라 태깅 생략: %s", url)
            return
        song = self._songs.get(agg.id)
        if song is None or not song.info.is_song:
            return

        tags = build_audio_tags(song.info, self._cover_for(agg.video.thumbnail_path))
        if self._tagger.write_tags(path, tags):
            logger.info("음원 태그 기록: %s (%s - %s)", path.name, tags.artist, tags.title)

    @staticmethod
    def _cover_for(thumbnail_rel: str) -> Path | None:
        """썸네일 상대경로 → 실제 파일 경로. 없으면 None(표지 없이 태깅한다)."""
        if not thumbnail_rel:
            return None
        path = THUMBNAIL_DIR / thumbnail_rel
        return path if path.exists() else None
