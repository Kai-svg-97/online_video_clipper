"""동기화 진행 상태(sync_state.json) — DB 밖에 둔다.

DB 스냅샷 교체와 독립이어야 하므로 DATA_DIR/sync/sync_state.json에 JSON으로 보관한다.
consumed[install]=마지막으로 소비(merge)한 원격 seq, pushed_head=우리 install의 마지막
업로드 로컬 seq.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SyncState:
    provider_key: str = ""
    consumed: dict[str, int] = field(default_factory=dict)
    pushed_head: int = 0
    last_pull_utc: str = ""
    last_push_utc: str = ""

    def to_dict(self) -> dict:
        return {
            "provider_key": self.provider_key,
            "consumed": dict(self.consumed),
            "pushed_head": self.pushed_head,
            "last_pull_utc": self.last_pull_utc,
            "last_push_utc": self.last_push_utc,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SyncState":
        return cls(
            provider_key=d.get("provider_key", ""),
            consumed={k: int(v) for k, v in d.get("consumed", {}).items()},
            pushed_head=int(d.get("pushed_head", 0)),
            last_pull_utc=d.get("last_pull_utc", ""),
            last_push_utc=d.get("last_push_utc", ""),
        )


class SyncStateStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def load(self) -> SyncState:
        if not self._path.exists():
            return SyncState()
        try:
            return SyncState.from_dict(json.loads(self._path.read_text(encoding="utf-8")))
        except Exception:
            logger.exception("sync_state 읽기 실패 — 기본값 사용: %s", self._path)
            return SyncState()

    def save(self, state: SyncState) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)
