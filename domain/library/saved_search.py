"""저장된 검색 — **순수 값 객체 + 직렬화 규칙**. 저장소도 화면도 모른다.

자주 쓰는 조건("안 본 긴 영상", "침착맨 최근 1주")을 매번 다시 고르는 것은 지겹다.
이름을 붙여 두고 한 번에 되부른다.

## 왜 날짜를 값이 아니라 **프리셋 키**로 저장하나

"최근 1주"를 `published_from="2026-09-12"`로 굳혀 저장하면, 다음 달에 그 검색을 열었을
때 **그 주의 영상만** 나온다. 사용자가 기대한 것은 "그때로부터 최근 1주"가 아니라
"지금으로부터 최근 1주"다. 그래서 저장하는 것은 `date_key="7d"`이고, 값으로 푸는 일은
되부를 때마다 새로 한다(`domain/library/filters.py`).

같은 이유로 길이·다운로드·시청도 키로 저장한다 — 프리셋 경계가 나중에 바뀌면 저장된
검색도 함께 따라오는 편이 맞다.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from uuid import UUID, uuid4

# 이름 길이 상한 — 사이드바 한 줄에 들어가야 한다.
MAX_NAME_LEN = 40

# 저장할 수 있는 개수. 무제한이면 목록이 길어져 고르는 것이 더 번거로워진다.
MAX_SAVED = 50


@dataclass(frozen=True, slots=True)
class SavedSearch:
    """이름 붙인 검색 조건 하나.

    필드는 **화면의 필터 막대와 1:1**이다 — 그래야 되부를 때 막대를 그대로 복원하고,
    사용자가 "저장된 것과 지금 화면이 다르다"고 느끼지 않는다.
    """

    id: UUID = field(default_factory=uuid4)
    name: str = ""
    text: str = ""                  # 검색어
    date_key: str = "all"
    duration_key: str = "all"
    download_key: str = "all"
    watched_key: str = "all"
    channel_name: str = ""
    favorite_only: bool = False

    # ── 직렬화 ────────────────────────────────────────────────────

    def to_json(self) -> str:
        """DB에 넣을 한 덩어리. **id·name은 빼고** 조건만 담는다 — 그 둘은 열이다."""
        payload = asdict(self)
        payload.pop("id", None)
        payload.pop("name", None)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, search_id: UUID, name: str, raw: str) -> SavedSearch:
        """JSON → 값 객체. **깨져 있어도 살아남는다**.

        앱을 오르내리며 필드가 늘거나 줄 수 있고, 사용자가 DB를 손볼 수도 있다.
        그때 저장된 검색 하나 때문에 목록 전체가 안 뜨면 안 된다 — 모르는 키는 버리고,
        빠진 키는 기본값으로 채운다.
        """
        try:
            data = json.loads(raw) if raw else {}
            if not isinstance(data, dict):
                data = {}
        except (ValueError, TypeError):
            data = {}
        known = {f for f in cls.__slots__ if f not in ("id", "name")}
        clean = {k: v for k, v in data.items() if k in known}
        return cls(id=search_id, name=name, **clean)

    # ── 판정 ──────────────────────────────────────────────────────

    @property
    def is_empty(self) -> bool:
        """아무 조건도 없는가 — 그런 것을 저장하면 되불러도 아무 일이 없다."""
        return not any(
            (
                self.text.strip(),
                self.channel_name.strip(),
                self.favorite_only,
                self.date_key not in ("", "all"),
                self.duration_key not in ("", "all"),
                self.download_key not in ("", "all"),
                self.watched_key not in ("", "all"),
            )
        )


def normalize_name(name: str) -> str:
    """이름 다듬기 — 앞뒤 공백을 털고 상한까지 자른다."""
    return " ".join((name or "").split())[:MAX_NAME_LEN]


def unique_name(name: str, existing: list[str]) -> str:
    """같은 이름이 있으면 뒤에 번호를 붙인다.

    이름을 거절하고 다시 묻는 대신 붙여 준다 — 저장은 곁가지 행동이라, 거기서
    막아 세우면 하려던 일(영상 찾기)의 흐름이 끊긴다.
    """
    base = normalize_name(name) or "저장된 검색"
    taken = {n for n in existing}
    if base not in taken:
        return base
    for i in range(2, MAX_SAVED + 2):
        candidate = normalize_name(f"{base} {i}")
        if candidate not in taken:
            return candidate
    return base
