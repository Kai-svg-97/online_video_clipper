from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from uuid import UUID

from domain.library.entities import Video
from domain.library.events import VideoAdded, VideoDeleted, VideoMarkedWatched, VideoUpdated
from domain.library.value_objects import ChannelInfo, Duration, VideoUrl

_now_lock = threading.Lock()
_last_now: datetime | None = None


def _now() -> datetime:
    """현재 UTC 시각을 반환하되, 이전 호출보다 항상 뒤로 가도록 보정한다.

    `last_played_at`은 "최근 재생순" 정렬(`ORDER BY last_played_at DESC`)의 유일한
    근거인데, OS 시계 해상도가 낮은 환경(실측: Windows)에서는 아주 짧은 간격으로 연속
    호출한 `datetime.now()`가 완전히 같은 값을 반환할 수 있다. 값이 같으면 SQL이 동률을
    임의 순서로 매겨 "나중에 본 영상이 앞에 온다"는 계약이 깨진다(간헐적으로 재현됨 —
    `tests/integration/test_resume_playback.py::TestQueries::test_최근_재생순으로_정렬된다`).
    시계가 멈춰 보이면 마이크로초 하나를 더해 최소한의 순서를 보장한다.
    """
    global _last_now
    with _now_lock:
        now = datetime.now(timezone.utc)
        if _last_now is not None and now <= _last_now:
            now = _last_now + timedelta(microseconds=1)
        _last_now = now
        return now


class VideoAggregate:
    def __init__(
        self,
        video: Video,
        category_id: UUID | None = None,
        tag_ids: list[UUID] | None = None,
    ) -> None:
        self._video = video
        self._category_id = category_id
        self._tag_ids: list[UUID] = tag_ids or []
        self._events: list = []

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        url: VideoUrl,
        title: str,
        *,
        channel: ChannelInfo | None = None,
        duration: Duration | None = None,
        published_at: datetime | None = None,
        view_count: int | None = None,
        favorite: bool = False,
        category_id: UUID | None = None,
    ) -> VideoAggregate:
        video = Video.create(
            url=url,
            title=title,
            channel=channel,
            duration=duration,
            published_at=published_at,
            view_count=view_count,
            favorite=favorite,
        )
        agg = cls(video, category_id=category_id)
        agg._raise(VideoAdded(video_id=video.id, url=str(url), title=title))
        return agg

    # ------------------------------------------------------------------
    # Read accessors
    # ------------------------------------------------------------------

    @property
    def id(self) -> UUID:
        return self._video.id

    @property
    def video(self) -> Video:
        return self._video

    @property
    def category_id(self) -> UUID | None:
        return self._category_id

    @property
    def tag_ids(self) -> list[UUID]:
        return list(self._tag_ids)

    # ------------------------------------------------------------------
    # State-mutating methods (all state changes go through here)
    # ------------------------------------------------------------------

    def mark_watched(self) -> None:
        if not self._video.watched:
            self._video.watched = True
            self._video.updated_at = _now()
            self._raise(VideoMarkedWatched(video_id=self._video.id))

    def update_metadata(
        self,
        *,
        title: str | None = None,
        notes: str | None = None,
        favorite: bool | None = None,
        thumbnail_path: str | None = None,
        description: str | None = None,
        channel: ChannelInfo | None = None,
        duration: Duration | None = None,
        published_at: datetime | None = None,
        view_count: int | None = None,
        gemini_summary: str | None = None,
    ) -> None:
        changed: list[str] = []
        if title is not None and title != self._video.title:
            self._video.title = title
            changed.append("title")
        if notes is not None and notes != self._video.notes:
            self._video.notes = notes
            changed.append("notes")
        if favorite is not None and favorite != self._video.favorite:
            self._video.favorite = favorite
            changed.append("favorite")
        if thumbnail_path is not None and thumbnail_path != self._video.thumbnail_path:
            self._video.thumbnail_path = thumbnail_path
            changed.append("thumbnail_path")
        if description is not None and description != self._video.description:
            self._video.description = description
            changed.append("description")
        if channel is not None and channel != self._video.channel:
            self._video.channel = channel
            changed.append("channel")
        if duration is not None and duration != self._video.duration:
            self._video.duration = duration
            changed.append("duration")
        if published_at is not None and published_at != self._video.published_at:
            self._video.published_at = published_at
            changed.append("published_at")
        if view_count is not None and view_count != self._video.view_count:
            self._video.view_count = view_count
            changed.append("view_count")
        if gemini_summary is not None and gemini_summary != self._video.gemini_summary:
            self._video.gemini_summary = gemini_summary
            changed.append("gemini_summary")
        if changed:
            self._video.updated_at = _now()
            self._raise(VideoUpdated(video_id=self._video.id, changed_fields=tuple(changed)))

    # 이어보기 위치를 '거의 다 본' 것으로 취급할 비율. 이 뒤는 다음에 열 때
    # 처음부터 보는 게 자연스럽다(끝나기 직전으로 되돌아가면 오히려 불편하다).
    _NEAR_END_RATIO = 0.97
    # 이보다 앞이면 저장하지 않는다 — 잠깐 눌렀다 만 것까지 '보던 영상'이 되면
    # 이어보기 목록이 금세 쓰레기통이 된다.
    _MIN_RESUME_MS = 15_000

    def update_playback_position(self, position_ms: int, now: datetime | None = None) -> None:
        """재생 위치를 기록한다(끝까지 봤으면 위치를 지우고 시청 표시).

        길이를 아는 영상은 끝 근처에서 위치를 0으로 되돌리고 `watched`를 세운다.
        길이를 모르면(라이브·메타데이터 부족) 위치만 남긴다.
        """
        position_ms = max(0, int(position_ms))
        duration = self._video.duration
        near_end = False
        if duration is not None and duration.seconds > 0:
            near_end = position_ms >= duration.seconds * 1000 * self._NEAR_END_RATIO
        if near_end:
            self._video.last_position_ms = 0
            self._video.watched = True
        elif position_ms >= self._MIN_RESUME_MS:
            self._video.last_position_ms = position_ms
        else:
            self._video.last_position_ms = 0
        self._video.last_played_at = now or _now()
        self._video.updated_at = self._video.last_played_at

    def assign_category(self, category_id: UUID | None) -> None:
        if self._category_id != category_id:
            self._category_id = category_id
            self._video.updated_at = _now()
            self._raise(VideoUpdated(video_id=self._video.id, changed_fields=("category",)))

    def set_tags(self, tag_ids: list[UUID]) -> None:
        if set(self._tag_ids) != set(tag_ids):
            self._tag_ids = list(tag_ids)
            self._video.updated_at = _now()
            self._raise(VideoUpdated(video_id=self._video.id, changed_fields=("tags",)))

    def delete(self) -> None:
        self._raise(VideoDeleted(video_id=self._video.id))

    # ------------------------------------------------------------------
    # Event infrastructure
    # ------------------------------------------------------------------

    def _raise(self, event: object) -> None:
        self._events.append(event)

    def pull_events(self) -> list:
        events = list(self._events)
        self._events.clear()
        return events
