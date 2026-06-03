"""스마트 폴더 — 저장된 검색 필터 조합."""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from platformdirs import user_data_dir
    _DATA_ROOT = Path(user_data_dir("online_video_clipper", "kai"))
except Exception:
    _DATA_ROOT = Path.home() / ".online_video_clipper"

_STORE_PATH: Path = _DATA_ROOT / "smart_folders.json"


@dataclass
class SmartFolder:
    name: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tag_ids: list[str] = field(default_factory=list)
    favorite_only: bool = False
    watched: bool | None = None
    min_duration_sec: int | None = None
    max_duration_sec: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> SmartFolder:
        return SmartFolder(
            id=d.get("id", str(uuid.uuid4())),
            name=d.get("name", ""),
            tag_ids=d.get("tag_ids", []),
            favorite_only=d.get("favorite_only", False),
            watched=d.get("watched"),
            min_duration_sec=d.get("min_duration_sec"),
            max_duration_sec=d.get("max_duration_sec"),
        )


def load_smart_folders() -> list[SmartFolder]:
    if not _STORE_PATH.exists():
        return []
    try:
        with open(_STORE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return [SmartFolder.from_dict(d) for d in data]
    except Exception:
        logger.exception("스마트 폴더 로드 실패")
        return []


def save_smart_folders(folders: list[SmartFolder]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump([sf.to_dict() for sf in folders], f, ensure_ascii=False, indent=2)
