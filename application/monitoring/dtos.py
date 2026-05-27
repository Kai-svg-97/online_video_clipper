from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class SubscriptionDTO:
    id: UUID
    channel_id: str
    channel_name: str
    channel_url: str
    auto_download: bool
    is_active: bool
