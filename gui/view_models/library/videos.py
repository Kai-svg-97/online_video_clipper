"""영상 한 건 단위의 조회·저장 — 메인 스레드에서 바로 부르는 가벼운 호출들.

상세 화면·빠른 이동·이어보기처럼 결과가 작고 조회가 짧은 경로다. 워커를 띄우는
비용이 쿼리보다 커서 동기로 부른다(무거운 것은 `listing.py`·`refresh.py`).
"""
from __future__ import annotations

import logging
from uuid import UUID

from application.library.commands import (
    DeleteVideoCommand,
    MarkWatchedCommand,
    UpdateVideoCommand,
)
from application.library.dtos import VideoDetailDTO
from application.library.playlist_queries import GetPlaylistItemsQuery
from application.library.queries import GetDownloadedFormatsQuery, GetVideosQuery
from gui.text.messages import describe_error

logger = logging.getLogger(__name__)


class VideoQueryMixin:
    """영상 한 건(또는 소수)을 찾고, 메모·요약·이어보기 위치를 저장한다."""

    def get_playlist_video_ids(self, playlist_id: UUID) -> list[UUID]:
        """재생목록에 속한 영상 ID 목록을 반환한다."""
        if self._get_playlist_items is None:
            return []
        try:
            items = self._get_playlist_items.handle(
                GetPlaylistItemsQuery(playlist_id=playlist_id, limit=500)
            )
            return [item.video_id for item in items]
        except Exception:
            logger.exception("재생목록 영상 ID 조회 실패")
            return []

    def get_playlist_first_item(self, playlist_id: "UUID"):
        """재생목록의 첫 번째 영상 아이템을 반환한다 (폴더 카드 썸네일용)."""
        if self._get_playlist_items is None:
            return None
        try:
            from application.library.playlist_queries import GetPlaylistItemsQuery  # noqa: PLC0415
            items = self._get_playlist_items.handle(
                GetPlaylistItemsQuery(playlist_id=playlist_id, limit=1, offset=0)
            )
            return items[0] if items else None
        except Exception:
            logger.exception("재생목록 첫 영상 조회 실패")
            return None

    def quick_search_videos(self, text: str, limit: int = 12) -> list:
        """빠른 이동(Ctrl+K)용 영상 검색 — 현재 필터를 무시하고 라이브러리 전체에서 찾는다.

        메인 스레드에서 바로 부른다: 결과 수가 작고(기본 12건) 조회가 짧아, 워커를
        띄우는 비용이 더 크다. 검색어가 없으면 최근에 보던 것부터 보여 준다.
        """
        if self._search_videos is None or self._get_videos is None:
            return []
        try:
            from application.library.queries import (  # noqa: PLC0415
                GetVideosQuery,
                SearchVideosQuery,
            )

            if text.strip():
                return self._search_videos.handle(
                    SearchVideosQuery(text=text.strip(), limit=limit, offset=0)
                )
            return self._get_videos.handle(
                GetVideosQuery(
                    limit=limit, offset=0,
                    sort_by="last_played_at", sort_asc=False, in_progress_only=True,
                )
            )
        except Exception:
            logger.exception("빠른 이동 검색 실패: %r", text)
            return []

    def save_playback_position(self, video_id: UUID, position_ms: int) -> None:
        """이어보기 위치를 기록한다(가벼운 UPDATE라 메인 스레드에서 바로 쓴다).

        재생 중 몇 초 간격으로 불리므로 워커를 새로 띄우지 않는다 — 스레드 생성 비용이
        쿼리보다 크다.
        """
        if self._update_position is None:
            return
        try:
            from application.library.commands import (  # noqa: PLC0415
                UpdatePlaybackPositionCommand,
            )

            self._update_position.handle(
                UpdatePlaybackPositionCommand(video_id=video_id, position_ms=position_ms)
            )
        except Exception:
            logger.exception("이어보기 위치 저장 실패: %s", video_id)

    def get_video_id_by_url(self, url: str) -> "UUID | None":
        """URL로 라이브러리 영상 ID를 조회한다(없으면 None)."""
        if self._get_video_id_by_url is None:
            return None
        try:
            return self._get_video_id_by_url.handle(url)
        except Exception:
            logger.exception("URL로 영상 ID 조회 실패: %s", url)
            return None

    def delete_video(self, video_id: UUID) -> None:
        try:
            self._delete_video.handle(DeleteVideoCommand(video_id))
            self._refresh_videos(bust_cache=True)
        except Exception as exc:
            self.error_occurred.emit(describe_error(exc))

    def mark_watched(self, video_id: UUID) -> None:
        try:
            self._mark_watched.handle(MarkWatchedCommand(video_id))
            self._refresh_videos(bust_cache=True)
        except Exception as exc:
            self.error_occurred.emit(describe_error(exc))

    def get_video_detail(self, video_id: UUID) -> VideoDetailDTO | None:
        try:
            return self._get_video_detail.handle(video_id)
        except Exception as exc:
            self.error_occurred.emit(describe_error(exc))
            return None

    def get_downloaded_flags(self, urls: list[str]) -> dict[str, tuple[bool, bool]]:
        """URL별 (영상 받음, 음원 받음)을 한 번의 쿼리로 조회한다(표 뷰 배지용)."""
        if self._get_downloaded_formats is None or not urls:
            return {}
        try:
            return self._get_downloaded_formats.handle(
                GetDownloadedFormatsQuery(urls=list(urls))
            )
        except Exception:
            logger.exception("다운로드 포맷 일괄 조회 실패")
            return {}

    def find_video_id_by_url(self, url: str) -> UUID | None:
        if self._get_video_id_by_url is None:
            return None
        try:
            return self._get_video_id_by_url.handle(url)
        except Exception:
            logger.exception("URL로 영상 ID 조회 실패: %s", url)
            return None

    def find_thumbnail_by_url(self, url: str) -> str | None:
        """URL로 라이브러리 영상의 로컬 썸네일 절대 경로 반환. 없으면 None."""
        try:
            vid = self.find_video_id_by_url(url)
            if vid is None:
                return None
            detail = self._get_video_detail.handle(vid)
            if not detail or not detail.thumbnail_path:
                return None
            from config.settings import THUMBNAIL_DIR  # noqa: PLC0415
            from pathlib import Path  # noqa: PLC0415
            p = Path(THUMBNAIL_DIR) / detail.thumbnail_path
            return str(p) if p.exists() else None
        except Exception:
            logger.debug("URL로 썸네일 경로 조회 실패: %s", url)
            return None

    def find_title_by_url(self, url: str) -> str | None:
        """URL로 라이브러리 영상의 제목 반환. 없으면 None."""
        try:
            vid = self.find_video_id_by_url(url)
            if vid is None:
                return None
            detail = self._get_video_detail.handle(vid)
            if not detail or not detail.title or detail.title == url:
                return None
            return detail.title
        except Exception:
            logger.debug("URL로 제목 조회 실패: %s", url)
            return None

    def get_category_videos(self, category_id: UUID, limit: int = 30) -> list:
        """카테고리 소속 영상 목록 반환 (연관 영상 구성용)."""
        try:
            return self._get_videos.handle(
                GetVideosQuery(category_id=category_id, limit=limit)
            )
        except Exception:
            logger.exception("카테고리 영상 조회 실패: %s", category_id)
            return []

    def get_videos_by_song(self, field: str, value: str, limit: int = 100) -> list:
        """같은 가수/앨범(field='artist'|'album')의 영상 목록 반환 (상세화면 필터용).

        song_info에서 매칭 video_id를 구해 기존 라이브러리 쿼리로 VideoDTO를 조회한다.
        """
        if self._find_song_videos is None:
            return []
        try:
            ids = self._find_song_videos.handle(field, value)
            if not ids:
                return []
            return self._get_videos.handle(GetVideosQuery(video_ids=ids, limit=limit))
        except Exception:
            logger.exception("같은 %s 영상 조회 실패: %s", field, value)
            return []

    def save_notes(self, video_id: UUID, notes: str) -> None:
        """영상 메모 저장."""
        try:
            self._update_video.handle(UpdateVideoCommand(video_id=video_id, notes=notes))
        except Exception:
            logger.exception("메모 저장 실패: %s", video_id)

    def save_gemini_summary(self, video_id: UUID, lang: str, summary: str) -> None:
        """Gemini AI 요약 저장 — 그 언어의 칸에(빈 문자열이면 그 언어의 요약을 지운다)."""
        try:
            self._update_video.handle(
                UpdateVideoCommand(video_id=video_id, gemini_summary=summary, summary_lang=lang)
            )
        except Exception:
            logger.exception("Gemini 요약 저장 실패: %s (%s)", video_id, lang)

    def save_summary_status(self, video_id: UUID, lang: str, status: str) -> None:
        """요약 실패 사유 저장(빈 문자열이면 삭제).

        상세 화면이 다음에 열릴 때도 "질문하기 버튼이 없어 실패" 같은 정확한 안내를
        띄우기 위한 진단 상태다. 저장 실패는 기능에 영향이 없어 로그만 남긴다.
        """
        try:
            self._update_video.handle(
                UpdateVideoCommand(video_id=video_id, summary_status=status, summary_lang=lang)
            )
        except Exception:
            logger.exception("요약 상태 저장 실패: %s (%s)", video_id, lang)
