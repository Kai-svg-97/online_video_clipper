"""즐겨찾기 — 카테고리·재생목록·태그를 빠르게 접근하기 위한 고정 항목."""
from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

def _data_root() -> Path:
    """즐겨찾기 파일이 사는 곳.

    **여기만 `config.settings.DATA_DIR` 이 아니다** — OS 표준 사용자 데이터 경로를
    쓴다(패키징 규칙). 그래서 `OVC_DATA_DIR` 로 데이터 디렉터리를 갈아끼워도 이 파일은
    따라오지 않아, 설명서 갈무리에 **사용자의 실제 즐겨찾기가 찍혔다**(v1.32.0).
    같은 환경 변수를 여기서도 본다 — 격리하려는 쪽이 한 군데만 보면 되게 한다.
    """
    override = os.environ.get("OVC_DATA_DIR")
    if override:
        return Path(override)
    try:
        from platformdirs import user_data_dir  # noqa: PLC0415

        return Path(user_data_dir("online_video_clipper", "kai"))
    except Exception:
        return Path.home() / ".online_video_clipper"


_DATA_ROOT = _data_root()
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
        logger.exception("즐겨찾기 로드 실패")
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
