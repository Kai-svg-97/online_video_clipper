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

from domain.shared.messages import Message

# ── 업로드 날짜 ────────────────────────────────────────────────────
# (키, 며칠 전부터). None = 제한 없음.
#
# **표시 이름은 여기 없다.** 화면 문구는 `gui/text/labels.py` 가 갖는다 — 도메인이
# 한국어를 들고 있으면 화면 언어를 바꿀 수 없다.
DATE_PRESETS: tuple[tuple[str, int | None], ...] = (
    ("all", None),
    ("7d", 7),
    ("30d", 30),
    ("90d", 90),
    ("365d", 365),
)

# ── 영상 길이 ──────────────────────────────────────────────────────
# (키, 표시 이름, 최소초, 최대초). 경계는 YouTube 의 흔한 구분(4분·20분)을 따른다 —
# 4분 미만은 쇼츠·클립, 20분 이상은 강의·팟캐스트·실황이 몰린다.
DURATION_PRESETS: tuple[tuple[str, int | None, int | None], ...] = (
    ("all", None, None),
    ("short", None, 239),
    ("medium", 240, 1199),
    ("long", 1200, None),
)

# ── 다운로드 여부 ──────────────────────────────────────────────────
DOWNLOAD_PRESETS: tuple[tuple[str, bool | None], ...] = (
    ("all", None),
    ("yes", True),
    ("no", False),
)

# ── 시청 여부 ──────────────────────────────────────────────────────
WATCHED_PRESETS: tuple[tuple[str, bool | None], ...] = (
    ("all", None),
    ("yes", True),
    ("no", False),
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
    for k, lo, hi in DURATION_PRESETS:
        if k == key:
            return lo, hi
    return None, None


def resolve_download_preset(key: str) -> bool | None:
    return _lookup(DOWNLOAD_PRESETS, key)


def resolve_watched_preset(key: str) -> bool | None:
    return _lookup(WATCHED_PRESETS, key)


def describe_filters(
    *,
    date_key: str = "all",
    duration_key: str = "all",
    download_key: str = "all",
    watched_key: str = "all",
    channel_name: str = "",
    favorite_only: bool = False,
) -> tuple[Message, ...]:
    """지금 걸린 필터를 **조각 목록으로** 돌려준다 — 화면이 한 줄로 잇는다.

    목록이 비었을 때 **왜 비었는지**를 말해 주는 근거다(CLAUDE.md — 상태를 말하지
    않는 화면을 만들지 않는다).

    문장이 아니라 조각 목록인 이유: 잇는 구분자(` · `)도 언어 설정이고, 조각마다
    번역이 달라야 한다. 여기서 한 줄로 만들어 버리면 화면이 손댈 수 없다.
    """
    out: list[Message] = []
    for group, key in (
        ("date", date_key),
        ("duration", duration_key),
        ("download", download_key),
        ("watched", watched_key),
    ):
        if key and key != "all":
            out.append(Message.of(f"filter.{group}.{key}"))
    if channel_name.strip():
        out.append(Message.of("filter.channel", name=channel_name.strip()))
    if favorite_only:
        out.append(Message.of("filter.favorite"))
    return tuple(out)


def _lookup(presets, key: str):
    """(키, 값) 짝에서 값을 꺼낸다. 모르는 키면 첫 줄(= `all`)로 떨어진다.

    표시 이름을 걷어내면서 값의 자리가 `row[2]` 에서 `row[1]` 로 당겨졌다.
    """
    for row in presets:
        if row[0] == key:
            return row[1]
    return presets[0][1]


