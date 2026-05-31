"""즐겨찾기 — 카테고리·재생목록·태그를 빠르게 접근하기 위한 고정 항목."""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

try:
    from platformdirs import user_data_dir
    _DATA_ROOT = Path(user_data_dir("online_video_clipper", "kai"))
except Exception:
    _DATA_ROOT = Path.home() / ".online_video_clipper"

_STORE_PATH: Path = _DATA_ROOT / "favorites.json"

_ICONS = {"category": "🏷", "playlist": "▶", "tag": "#"}


@dataclass
class FavoriteItem:
    type: str    # "category" | "playlist" | "tag"
    id: str      # UUID 문자열
    name: str
    order: int = 0

    @property
    def icon(self) -> str:
        return _ICONS.get(self.type, "★")

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> FavoriteItem:
        return FavoriteItem(
            type=d.get("type", "category"),
            id=d.get("id", str(uuid.uuid4())),
            name=d.get("name", ""),
            order=d.get("order", 0),
        )


def load_favorites() -> list[FavoriteItem]:
    if not _STORE_PATH.exists():
        return []
    try:
        with open(_STORE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        items = [FavoriteItem.from_dict(d) for d in data]
        return sorted(items, key=lambda x: x.order)
    except Exception:
        return []


def save_favorites(items: list[FavoriteItem]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    for i, item in enumerate(items):
        item.order = i
    with open(_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump([x.to_dict() for x in items], f, ensure_ascii=False, indent=2)


def add_favorite(fav: FavoriteItem) -> None:
    items = load_favorites()
    if any(x.id == fav.id and x.type == fav.type for x in items):
        return
    fav.order = len(items)
    items.append(fav)
    save_favorites(items)


def remove_favorite(item_id: str, item_type: str) -> None:
    items = [x for x in load_favorites() if not (x.id == item_id and x.type == item_type)]
    save_favorites(items)


def is_favorite(item_id: str, item_type: str) -> bool:
    return any(x.id == item_id and x.type == item_type for x in load_favorites())
