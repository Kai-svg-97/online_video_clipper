"""SponsorBlock 구간의 **순수 규칙** — I/O 없음.

SponsorBlock은 영상의 스폰서·자기홍보·인트로 같은 구간을 사용자들이 모아 둔 공개
데이터베이스다. 이 앱에서 쓰는 곳은 두 군데다.

- **재생 중 건너뛰기**: 스트리밍·로컬 재생 어느 쪽이든 현재 위치가 구간 안에 들어가면
  그 끝으로 넘긴다.
- **다운로드 시 제거**: yt-dlp가 자체 후처리기로 잘라낸다(이 모듈은 관여하지 않는다).

구간 데이터는 **여러 사람이 제출한 것을 그대로 받는다** — 겹치고, 순서가 뒤섞이고,
시작이 끝보다 큰 것도 온다. 그대로 쓰면 건너뛰기가 앞뒤로 튀므로 `normalize_segments`가
정리한 결과만 쓴다.
"""

from __future__ import annotations

from dataclasses import dataclass

# 화면에 보여줄 이름. 키는 SponsorBlock API의 category 값 그대로다.
# 이 목록에 없는 카테고리는 무시한다(API가 새 값을 추가해도 조용히 지나간다).
SKIP_CATEGORY_NAMES: dict[str, str] = {
    "sponsor": "스폰서 광고",
    "selfpromo": "자기 홍보·후원",
    "interaction": "구독 요청",
    "intro": "인트로·오프닝",
    "outro": "아웃트로·엔딩",
    "preview": "예고·재탕 요약",
    "filler": "잡담·곁가지",
    "music_offtopic": "음악 외 구간",
}

# 기본으로 켜 두는 카테고리 — 광고성만 고른다.
# 인트로·아웃트로·잡담은 "그걸 보려고 튼" 사람도 있어 기본에서 뺀다.
DEFAULT_SKIP_CATEGORIES: tuple[str, ...] = ("sponsor", "selfpromo", "interaction")

# 이보다 짧은 구간은 건너뛰지 않는다. 1초짜리를 넘기면 화면만 덜컥거리고
# 얻는 게 없다(제출 오차로 0.x초짜리가 종종 섞여 온다).
MIN_SEGMENT_SEC = 1.0


@dataclass(frozen=True, slots=True)
class SkipSegment:
    """건너뛸 구간 하나."""

    category: str
    start_sec: float
    end_sec: float

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec

    @property
    def display_name(self) -> str:
        return SKIP_CATEGORY_NAMES.get(self.category, self.category)


def normalize_segments(
    raw: list[tuple[str, float, float]],
    *,
    categories: tuple[str, ...] | None = None,
) -> list[SkipSegment]:
    """제출된 구간 목록을 건너뛰기에 쓸 수 있는 형태로 정리한다.

    1. 아는 카테고리만 남긴다(``categories``를 주면 그중에서도 고른 것만).
    2. 시작<끝이고 `MIN_SEGMENT_SEC` 이상인 것만 남긴다.
    3. 시작 순으로 정렬하고 **겹치거나 맞닿은 구간은 합친다** — 합치지 않으면
       앞 구간 끝으로 넘긴 자리가 다시 다음 구간 안이라 건너뛰기가 연달아 튄다.

    합쳐진 구간의 카테고리는 **먼저 시작한 쪽**을 쓴다(안내 문구용이라 하나면 된다).
    """
    allowed = set(categories) if categories else set(SKIP_CATEGORY_NAMES)
    clean = [
        SkipSegment(cat, float(start), float(end))
        for cat, start, end in raw
        if cat in allowed
        and cat in SKIP_CATEGORY_NAMES
        and end - start >= MIN_SEGMENT_SEC
        and start >= 0
    ]
    clean.sort(key=lambda s: (s.start_sec, s.end_sec))

    merged: list[SkipSegment] = []
    for seg in clean:
        if merged and seg.start_sec <= merged[-1].end_sec:
            last = merged[-1]
            if seg.end_sec > last.end_sec:
                merged[-1] = SkipSegment(last.category, last.start_sec, seg.end_sec)
            continue
        merged.append(seg)
    return merged


def segment_at(segments: list[SkipSegment], position_sec: float) -> SkipSegment | None:
    """현재 위치를 품고 있는 구간(없으면 None).

    끝 경계는 **포함하지 않는다** — 포함하면 구간 끝으로 넘긴 직후 같은 구간이
    다시 잡혀 무한히 제자리에서 튄다.
    """
    for seg in segments:
        if seg.start_sec <= position_sec < seg.end_sec:
            return seg
        if seg.start_sec > position_sec:
            break  # 정렬돼 있으므로 더 볼 필요가 없다
    return None
