"""sync 조회 유스케이스 — 동기화 상태 DTO."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SyncStatusDTO:
    provider_key: str
    connected: bool
    account_name: str | None
    last_pull_utc: str
    last_push_utc: str
    pushed_head: int
    known_installs: int


@dataclass
class GetSyncStatusHandler:
    state_store: object            # SyncStateStore
    provider: object | None = None  # ICloudSyncProvider | None

    def handle(self) -> SyncStatusDTO:
        state = self.state_store.load()
        connected = bool(self.provider and self.provider.is_authenticated())
        account = self.provider.account_name() if connected else None
        return SyncStatusDTO(
            provider_key=state.provider_key,
            connected=connected,
            account_name=account,
            last_pull_utc=state.last_pull_utc,
            last_push_utc=state.last_push_utc,
            pushed_head=state.pushed_head,
            known_installs=len(state.consumed),
        )
