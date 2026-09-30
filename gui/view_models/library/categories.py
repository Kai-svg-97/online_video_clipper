"""카테고리 트리 — 로드·경로·생성/이름변경/삭제/이동·영상 배정."""
from __future__ import annotations

import logging
from uuid import UUID

from application.library.commands import (
    AssignCategoryCommand,
    CreateCategoryCommand,
    DeleteCategoryCommand,
    MoveCategoryCommand,
    RenameCategoryCommand,
)
from gui.text import tr
from gui.text.messages import describe_error

logger = logging.getLogger(__name__)


class CategoryMixin:
    """카테고리 트리를 읽고 고친다(변경 시 목록 캐시를 비운다)."""

    def load_categories(self) -> None:
        """카테고리 트리 로드 (백그라운드에서 호출 가능)."""
        try:
            self._categories = self._get_categories.handle()
            self.categories_changed.emit()
        except Exception as exc:
            logger.exception("카테고리 로드 실패: %s", exc)
            self.error_occurred.emit(tr("카테고리 로드 실패: {exc}").format(exc=exc))

    def assign_category(self, video_id: UUID, category_id: UUID | None) -> None:
        try:
            self._assign_category.handle(AssignCategoryCommand(video_id, category_id))
            self._refresh_videos(bust_cache=True)
        except Exception as exc:
            self.error_occurred.emit(describe_error(exc))

    def assign_category_bulk(self, video_ids: list[UUID], category_id: UUID | None) -> None:
        for vid_id in video_ids:
            try:
                self._assign_category.handle(AssignCategoryCommand(vid_id, category_id))
            except Exception as exc:
                self.error_occurred.emit(describe_error(exc))
        self._refresh_videos(bust_cache=True)

    def get_category_path(self, category_id: UUID) -> list[str]:
        """카테고리 계층 경로 반환 (브레드크럼용). 루트→리프 순서."""
        try:
            if not self._categories:
                self._categories = self._get_categories.handle()
            cats = {c.id: c for c in self._categories}
            path: list[str] = []
            current = category_id
            seen: set = set()
            while current and current in cats and current not in seen:
                seen.add(current)
                cat = cats[current]
                path.insert(0, cat.name)
                current = cat.parent_id
            return path
        except Exception:
            logger.debug("카테고리 경로 조회 실패: %s", category_id)

    def get_category_path_with_ids(self, category_id: UUID) -> list[tuple]:
        """카테고리 계층 경로 반환 (이름, ID) 쌍 리스트. 루트→리프 순서. 브레드크럼 클릭용."""
        try:
            if not self._categories:
                self._categories = self._get_categories.handle()
            cats = {c.id: c for c in self._categories}
            path: list[tuple] = []
            current = category_id
            seen: set = set()
            while current and current in cats and current not in seen:
                seen.add(current)
                cat = cats[current]
                path.insert(0, (cat.name, cat.id))
                current = cat.parent_id
            return path
        except Exception:
            logger.debug("카테고리 경로(ID) 조회 실패: %s", category_id)
            return []

    def create_category(self, name: str, parent_id: UUID | None = None) -> None:
        try:
            self._create_category.handle(CreateCategoryCommand(name=name, parent_id=parent_id))
            self._refresh_categories()
        except Exception as exc:
            self.error_occurred.emit(describe_error(exc))

    def rename_category(self, category_id: UUID, new_name: str) -> None:
        try:
            self._rename_category.handle(RenameCategoryCommand(category_id=category_id, new_name=new_name))
            self._refresh_categories()
        except Exception as exc:
            self.error_occurred.emit(describe_error(exc))

    def delete_category(self, category_id: UUID) -> None:
        try:
            self._delete_category.handle(DeleteCategoryCommand(category_id=category_id))
            self._refresh_categories()  # _refresh_categories()가 캐시 무효화 포함
            self._refresh_videos(bust_cache=True)
        except Exception as exc:
            self.error_occurred.emit(describe_error(exc))

    def reparent_category(self, category_id: UUID, new_parent_id: UUID | None) -> None:
        if new_parent_id is not None:
            # Prevent circular reference (can't make a parent a child of its descendant)
            if new_parent_id in set(self._resolve_category_ids(category_id)):
                self.error_occurred.emit(tr("상위 카테고리를 하위 카테고리의 자식으로 설정할 수 없습니다."))
                return
        try:
            self._move_category.handle(MoveCategoryCommand(category_id, new_parent_id))
            self._refresh_categories()
        except Exception as exc:
            self.error_occurred.emit(describe_error(exc))

    def _resolve_category_ids(self, cat_id: UUID) -> list[UUID]:
        """Return cat_id plus all descendant IDs via BFS.

        Uses a `seen` set to terminate safely even if the DB contains a
        circular parent→child reference (which would otherwise loop forever).
        """
        result = [cat_id]
        seen: set = {cat_id}
        queue = [cat_id]
        while queue:
            parent = queue.pop(0)
            for c in self._categories:
                if c.parent_id == parent and c.id not in seen:
                    seen.add(c.id)
                    result.append(c.id)
                    queue.append(c.id)
        return result

    def _refresh_categories(self) -> None:
        self._video_cache.clear()  # 카테고리 트리 변경 시 캐시 무효화
        self._categories = self._get_categories.handle()
        self.categories_changed.emit()
