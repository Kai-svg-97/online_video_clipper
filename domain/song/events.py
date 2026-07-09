from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class SongInfoUpdated:
    """노래 정보(가수·앨범·제목·가사·노래여부)가 변경됐을 때 발행."""

    video_id: UUID
    changed_fields: tuple[str, ...]
    occurred_at: datetime = field(default_factory=_now)
