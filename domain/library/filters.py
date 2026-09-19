"""복합 필터의 사람 말 ↔ 값 변환 — **순수 규칙**, 저장소도 화면도 모른다.

엔진(`SearchQuery`)은 `published_from="2026-09-12"`, `min_duration_sec=1200` 같은
정확한 값을 받는다. 그런데 사람은 그렇게 생각하지 않는다 — "최근 일주일", "20분 넘는
것"이다. 그 사이를 여기서 옮긴다.

**왜 직접 입력이 아니라 프리셋인가**: 날짜 두 칸을 직접 채우게 하면 대부분 안 쓴다
(형식을 맞춰야 하고, 오늘 날짜를 계산해야 한다). 흔한 구간을 이름으로 고르게 하면
한 번에 끝난다. 정확한 구간이 필요한 사람은 드물고, 그 사람은 검색어를 쓴다.

**왜 여기 두나**: "최근 7일이 어디부터인가"는 화면이 아니라 규칙이다. 화면에 두면
테스트할 때 날짜를 고정하기 어렵고, 같은 계산이 필터 막대와 저장된 검색 두 곳에
생긴다.
"""

from __future__ import annotations

from datetime import date, timedelta

# ── 업로드 날짜 ────────────────────────────────────────────────────
# (키, 표시 이름, 며칠 전부터). None = 제한 없음.
DATE_PRESETS: tuple[tuple[str, str, int | None], ...] = (
    ("all", "전체 기간", None),
    ("7d", "최근 1주", 7),
    ("30d", "최근 1개월", 30),
    ("90d", "최근 3개월", 90),
    ("365d", "최근 1년", 365),
)

# ── 영상 길이 ──────────────────────────────────────────────────────
# (키, 표시 이름, 최소초, 최대초). 경계는 YouTube 의 흔한 구분(4분·20분)을 따른다 —
# 4분 미만은 쇼츠·클립, 20분 이상은 강의·팟캐스트·실황이 몰린다.
DURATION_PRESETS: tuple[tuple[str, str, int | None, int | None], ...] = (
    ("all", "전체 길이", None, None),
    ("short", "4분 미만", None, 239),
    ("medium", "4~20분", 240, 1199),
    ("long", "20분 이상", 1200, None),
)

# ── 다운로드 여부 ──────────────────────────────────────────────────
DOWNLOAD_PRESETS: tuple[tuple[str, str, bool | None], ...] = (
    ("all", "전체", None),
    ("yes", "받아 둔 것만", True),
    ("no", "안 받은 것만", False),
)

# ── 시청 여부 ──────────────────────────────────────────────────────
WATCHED_PRESETS: tuple[tuple[str, str, bool | None], ...] = (
    ("all", "전체", None),
    ("yes", "본 것만", True),
    ("no", "안 본 것만", False),
)


def resolve_date_preset(key: str, today: date | None = None) -> tuple[str, str]:
    """날짜 프리셋 → `(published_from, published_to)`.

    끝 경계를 비워 두는 이유는 **미래 날짜 영상이 있기 때문**이다(예약 공개가 걸린
    영상은 업로드 날짜가 내일일 수 있다). "최근 1주"에서 그것까지 빼면 사용자는
    분명히 목록에 있던 영상이 사라졌다고 본다.
    """
    days = _lookup(DATE_PRESETS, key)
    if days is None:
        return "", ""
    base = today or date.today()
    return (base - timedelta(days=days)).isoformat(), ""


def resolve_duration_preset(key: str) -> tuple[int | None, int | None]:
    """길이 프리셋 → `(min_duration_sec, max_duration_sec)`."""
    for k, _name, lo, hi in DURATION_PRESETS:
        if k == key:
            return lo, hi
    return None, None


def resolve_download_preset(key: str) -> bool | None:
    return _lookup(DOWNLOAD_PRESETS, key)


def resolve_watched_preset(key: str) -> bool | None:
    return _lookup(WATCHED_PRESETS, key)


def describe(
    *,
    date_key: str = "all",
    duration_key: str = "all",
    download_key: str = "all",
    watched_key: str = "all",
    channel_name: str = "",
    favorite_only: bool = False,
) -> str:
    """지금 걸린 필터를 한 줄로 — 화면이 "무엇으로 좁혔는지" 보여준다.

    목록이 비었을 때 **왜 비었는지**를 말해 주는 근거다(CLAUDE.md — 상태를 말하지
    않는 화면을 만들지 않는다).
    """
    parts: list[str] = []
    for presets, key in (
        (DATE_PRESETS, date_key),
        (DURATION_PRESETS, duration_key),
    ):
        if key and key != "all":
            name = next((p[1] for p in presets if p[0] == key), "")
            if name:
                parts.append(name)
    if download_key and download_key != "all":
        parts.append(_name_of(DOWNLOAD_PRESETS, download_key))
    if watched_key and watched_key != "all":
        parts.append(_name_of(WATCHED_PRESETS, watched_key))
    if channel_name.strip():
        parts.append(f"채널 '{channel_name.strip()}'")
    if favorite_only:
        parts.append("즐겨찾기")
    return " · ".join(p for p in parts if p)


def _lookup(presets, key: str):
    for row in presets:
        if row[0] == key:
            return row[2]
    return presets[0][2]


def _name_of(presets, key: str) -> str:
    return next((p[1] for p in presets if p[0] == key), "")
