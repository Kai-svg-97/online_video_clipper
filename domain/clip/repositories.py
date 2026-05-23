from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from domain.clip.aggregates import ClipAggregate


class IClipRepository(ABC):
    @abstractmethod
    def save(self, aggregate: ClipAggregate) -> None: ...

    @abstractmethod
    def get_by_id(self, clip_id: UUID) -> ClipAggregate | None: ...

    @abstractmethod
    def list_by_video(self, source_video_id: UUID) -> list[ClipAggregate]: ...

    @abstractmethod
    def delete(self, clip_id: UUID) -> None: ...
