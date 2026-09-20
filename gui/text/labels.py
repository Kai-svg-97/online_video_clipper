"""닫힌 키 집합 → 표시 이름.

도메인은 영어 키를 갖고(`STATUS_OK = "ok"`, SponsorBlock 카테고리 값) 표시 이름은
여기가 갖는다. 프로젝트가 이미 세 번 내린 판단을 한곳으로 모은 것이다 —
`gui/panels/library/constants.py`의 `MATCH_FIELD_LABELS`, `gui/panels/album_panel.py`의
`ORIGIN_LABELS`, `gui/panels/detail/text_format.py`의 `_SUMMARY_STATUS_LABELS`.

**한 패널만 쓰는 라벨은 옮기지 않는다** — 위 셋은 지금 자리 그대로 둔다. 여기로
오는 것은 도메인에서 걷어낸, 여러 곳에서 쓰이는 라벨이다.

키마다 라벨이 있는지(그리고 남는 라벨이 없는지)는
`tests/unit/gui/test_label_coverage.py`가 지킨다 — 도메인에 키를 더하고 라벨을
빠뜨리면 화면에 키가 그대로 뜬다.

덩어리 C2에서 채워진다.
"""

from __future__ import annotations


# ── SponsorBlock 건너뛰기 구간 ────────────────────────────────────
# 키는 SponsorBlock API 의 category 값 그대로다(`domain/clip/sponsor.py`).
SPONSOR_CATEGORY_LABELS: dict[str, str] = {
    "sponsor": "스폰서 광고",
    "selfpromo": "자기 홍보·후원",
    "interaction": "구독 요청",
    "intro": "인트로·오프닝",
    "outro": "아웃트로·엔딩",
    "preview": "예고·재탕 요약",
    "filler": "잡담·곁가지",
    "music_offtopic": "음악 외 구간",
}


def sponsor_category_label(key: str) -> str:
    """모르는 카테고리는 키를 그대로 — API 가 새 값을 추가해도 화면이 비지 않는다."""
    return SPONSOR_CATEGORY_LABELS.get(key, key)


# ── 원본 확인 상태 ────────────────────────────────────────────────
# 키는 `domain/library/availability.py` 의 STATUS_* 상수다.
AVAILABILITY_LABELS: dict[str, str] = {
    "ok": "정상",
    "removed": "삭제됨",
    "private": "비공개",
    "unknown": "확인 불가",
}


def availability_label(status: str) -> str:
    return AVAILABILITY_LABELS.get(status, status)


# ── 복합 필터 프리셋 ──────────────────────────────────────────────
# (그룹, 키) → 표시 이름. 값(며칠 전부터·초 범위)은 `domain/library/filters.py` 에 있다.
FILTER_PRESET_LABELS: dict[tuple[str, str], str] = {
    ("date", "all"): "전체 기간",
    ("date", "7d"): "최근 1주",
    ("date", "30d"): "최근 1개월",
    ("date", "90d"): "최근 3개월",
    ("date", "365d"): "최근 1년",
    ("duration", "all"): "전체 길이",
    ("duration", "short"): "4분 미만",
    ("duration", "medium"): "4~20분",
    ("duration", "long"): "20분 이상",
    ("download", "all"): "전체",
    ("download", "yes"): "받아 둔 것만",
    ("download", "no"): "안 받은 것만",
    ("watched", "all"): "전체",
    ("watched", "yes"): "본 것만",
    ("watched", "no"): "안 본 것만",
}


def filter_preset_label(group: str, key: str) -> str:
    return FILTER_PRESET_LABELS.get((group, key), key)
