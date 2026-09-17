"""미디어 서버용 사이드카 내보내기 — `.nfo`는 미디어 파일 옆에, `.m3u`는 지정한 곳에.

**`.nfo`의 위치를 사용자가 고르지 않는다.** 서버는 미디어 파일과 **같은 폴더의 같은
이름**만 읽는다. 다른 곳에 두면 아무 일도 일어나지 않는데 화면에는 "내보냈다"고 뜨는
것이 가장 나쁜 결과라, 위치를 규약으로 못 박는다.

다운로드한 파일이 없는 영상은 건너뛴다 — 서버가 읽을 미디어가 없으니 사이드카만
남겨 봐야 쓸모가 없다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from domain.library.media_server import (
    M3uEntry,
    MediaServerEntry,
    build_m3u,
    build_nfo,
    nfo_path_for,
)
from domain.library.repositories import IVideoRepository, SearchQuery
from domain.song.repositories import ISongRepository

logger = logging.getLogger(__name__)


@dataclass
class ExportMediaServerCommand:
    category_ids: list[UUID] = field(default_factory=list)
    write_nfo: bool = True
    m3u_path: str = ""          # 비우면 재생목록을 만들지 않는다


@dataclass
class MediaServerExportResult:
    nfo_written: int = 0
    m3u_entries: int = 0
    skipped_no_file: int = 0     # 다운로드한 파일이 없어 건너뛴 영상
    failed: list[str] = field(default_factory=list)
    m3u_path: str = ""


class ExportMediaServerHandler:
    """선택한 카테고리의 영상에 사이드카를 쓴다. 배경 QThread에서 호출한다(파일 I/O)."""

    def __init__(
        self,
        video_repo: IVideoRepository,
        song_repo: ISongRepository,
        download_repo,
    ) -> None:
        self._videos = video_repo
        self._songs = song_repo
        self._downloads = download_repo

    def handle(self, cmd: ExportMediaServerCommand) -> MediaServerExportResult:
        result = MediaServerExportResult(m3u_path=cmd.m3u_path)
        tag_names = {t.id: t.name for t in self._videos.list_tags()}
        m3u_entries: list[M3uEntry] = []

        for agg in self._collect(cmd.category_ids):
            media_path = self._local_file(agg.video.url)
            if not media_path:
                result.skipped_no_file += 1
                continue

            entry = self._to_entry(agg, media_path, tag_names)
            m3u_entries.append(
                M3uEntry(
                    path=media_path,
                    title=entry.display_title(),
                    duration_sec=entry.duration_sec,
                )
            )
            if cmd.write_nfo and not self._write_nfo(entry, result):
                continue
            if cmd.write_nfo:
                result.nfo_written += 1

        if cmd.m3u_path and m3u_entries:
            self._write_m3u(cmd.m3u_path, m3u_entries, result)
        result.m3u_entries = len(m3u_entries)

        logger.info(
            "미디어 서버 내보내기: nfo %d개, m3u %d줄, 파일없음 %d개, 실패 %d개",
            result.nfo_written, result.m3u_entries, result.skipped_no_file,
            len(result.failed),
        )
        return result

    # ── 내부 ───────────────────────────────────────────────────────

    def _collect(self, category_ids: list[UUID]) -> list:
        """선택한 카테고리의 영상(설명·태그까지 채워진 아그리게이트)."""
        out: list = []
        seen: set = set()
        # 카테고리를 주지 않으면 **라이브러리 전체**다. `categorized_only=True`로 두면
        # 미분류 영상이 통째로 빠지는데, 화면에는 "완료"로 보여 원인을 찾기 어렵다.
        targets = list(category_ids) or [None]
        for cid in targets:
            query = SearchQuery(
                category_id=cid, categorized_only=False, limit=1_000_000
            )
            for summary in self._videos.search(query):
                if summary.id in seen:
                    continue
                seen.add(summary.id)
                # 설명은 지연 로딩이라 요약본에는 없다 — 상세를 다시 읽어야 plot 이 찬다.
                out.append(self._videos.get_by_id(summary.id) or summary)
        return out

    def _local_file(self, url) -> str:
        """그 영상의 **존재하는** 다운로드 파일 경로(없으면 빈 문자열).

        같은 영상을 여러 화질로 받아 뒀을 수 있어 목록을 훑는다. 경로만 남고 파일이
        지워진 기록도 흔해서 `exists()`까지 확인한다.
        """
        try:
            jobs = self._downloads.find_completed_by_url(str(url))
        except Exception:
            logger.exception("다운로드 이력 조회 실패: %s", url)
            return ""
        for job in jobs or []:
            path = getattr(job, "file_path", "") or ""
            if path and Path(path).exists():
                return path
        return ""

    def _to_entry(self, agg, media_path: str, tag_names: dict) -> MediaServerEntry:
        video = agg.video
        song = None
        try:
            song_agg = self._songs.get(agg.id)
            song = song_agg.info if song_agg else None
        except Exception:
            logger.exception("노래 정보 조회 실패 (무시): %s", agg.id)

        return MediaServerEntry(
            title=video.title,
            file_path=media_path,
            url=str(video.url),
            channel_name=(video.channel.name if video.channel else ""),
            description=video.description or "",
            published_at=(video.published_at.isoformat() if video.published_at else ""),
            duration_sec=(video.duration.seconds if video.duration else 0),
            tags=tuple(
                tag_names[tid] for tid in getattr(agg, "tag_ids", []) if tid in tag_names
            ),
            thumbnail_path=video.thumbnail_path or "",
            is_song=bool(song and song.is_song),
            artist=(song.artist if song else ""),
            album=(song.album if song else ""),
            song_title=(song.song_title if song else ""),
            release_year=(song.release_year if song else ""),
        )

    def _write_nfo(self, entry: MediaServerEntry, result: MediaServerExportResult) -> bool:
        path = Path(nfo_path_for(entry.file_path))
        try:
            path.write_text(build_nfo(entry), encoding="utf-8")
        except OSError as exc:
            # 한 건이 실패해도 나머지를 계속한다 — 읽기 전용 폴더 하나 때문에
            # 전체 내보내기가 무산되면 어디까지 됐는지 알 수 없다.
            logger.warning("nfo 쓰기 실패: %s (%s)", path, exc)
            result.failed.append(str(path))
            return False
        return True

    def _write_m3u(
        self, m3u_path: str, entries: list[M3uEntry], result: MediaServerExportResult
    ) -> None:
        path = Path(m3u_path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # **UTF-8 고정**. 한글 제목이 들어가는데 기본 인코딩(Windows=cp949)으로
            # 쓰면 다른 기기에서 목록이 깨진다.
            path.write_text(build_m3u(entries), encoding="utf-8")
        except OSError as exc:
            logger.warning("m3u 쓰기 실패: %s (%s)", path, exc)
            result.failed.append(str(path))
