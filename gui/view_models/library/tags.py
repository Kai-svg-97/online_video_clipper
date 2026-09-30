"""태그 — 전체/스코프 인기 태그 집계·삭제·영상 태그 편집."""
from __future__ import annotations

import logging
from uuid import UUID

from application.library.commands import DeleteTagCommand, UpdateVideoCommand
from application.library.queries import GetTagsQuery
from gui.text.messages import describe_error

logger = logging.getLogger(__name__)


class TagMixin:
    """태그 목록을 집계하고 영상의 태그를 고친다."""

    def refresh_scoped_tags(self) -> None:
        """현재 활성 필터(카테고리 서브트리 또는 재생목록 영상)에 맞춘 인기 태그를
        집계한다. 카테고리·재생목록 모두 없으면(로컬 루트) 라이브러리 전체.

        피드/채널 등 로컬 태그가 없는 뷰에서는 패널이 이 메서드를 호출하지 않고
        인기 태그 패널 자체를 숨긴다.
        """
        category_ids = (
            self._resolve_category_ids(self._filter_category_id)
            if self._filter_category_id is not None
            else []
        )
        video_ids = list(self._filter_playlist_video_ids)
        try:
            self._scoped_tags = self._get_tags.handle(
                GetTagsQuery(category_ids=category_ids, video_ids=video_ids)
            )
        except Exception as exc:
            logger.exception("스코프 태그 집계 실패")
            self._scoped_tags = []
            self.error_occurred.emit(describe_error(exc))
            return
        self.scoped_tags_changed.emit()

    def delete_tag(self, tag_id: UUID) -> None:
        try:
            self._delete_tag.handle(DeleteTagCommand(tag_id))
            # Clear from active filter if it was being used
            if tag_id in self._filter_tag_ids:
                self._filter_tag_ids = [t for t in self._filter_tag_ids if t != tag_id]
            self._refresh_tags()
            self._refresh_videos(bust_cache=True)
        except Exception as exc:
            self.error_occurred.emit(describe_error(exc))

    def _refresh_tags(self) -> None:
        self._tags = self._get_tags.handle()
        self.tags_changed.emit()

    def update_video_tags(self, video_id: UUID, tag_names: list[str]) -> None:
        """Replace the tag list for a single video (used from detail panel)."""
        try:
            self._update_video.handle(UpdateVideoCommand(video_id=video_id, tags=tag_names))
            self._refresh_tags()
            self._refresh_videos(bust_cache=True)
        except Exception as exc:
            self.error_occurred.emit(describe_error(exc))

    def add_tags_bulk(self, video_ids: list[UUID], tag_names: list[str]) -> None:
        """Append *tag_names* to each video in *video_ids*, preserving existing tags."""
        for vid_id in video_ids:
            try:
                detail = self._get_video_detail.handle(vid_id)
                if detail is None:
                    continue
                merged = list(dict.fromkeys(list(detail.tags) + tag_names))
                self._update_video.handle(UpdateVideoCommand(video_id=vid_id, tags=merged))
            except Exception as exc:
                self.error_occurred.emit(describe_error(exc))
        self._refresh_tags()
        self._refresh_videos(bust_cache=True)
