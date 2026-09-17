"""재생 중 건너뛸 구간 조회 유스케이스.

**캐시가 이 핸들러의 존재 이유다.** 상세화면은 같은 영상을 되풀이해 연다(뒤로가기,
재생목록 왕복, 앨범 이어재생). 매번 SponsorBlock에 물으면 쓸데없는 왕복이 쌓이고,
결과가 늦게 오면 이미 그 구간을 지난 뒤다. 영상당 한 번만 묻고 세션 동안 들고 있는다.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass

from domain.clip.sponsor import SkipSegment, normalize_segments
from domain.library.value_objects import extract_youtube_video_id
from domain.shared.ports import ISkipSegmentSource

logger = logging.getLogger(__name__)

# 캐시 상한 — 저사양 PC가 목표라 무제한으로 두지 않는다. 구간 목록은 영상당
# 수십 바이트 수준이지만, 긴 세션에서 수천 개가 쌓이는 것을 막는다.
_CACHE_MAX = 256


@dataclass
class GetSkipSegmentsQuery:
    url: str


class GetSkipSegmentsHandler:
    """URL → 건너뛸 구간. 배경 QThread에서 호출한다(네트워크).

    YouTube가 아니면 빈 목록이다 — SponsorBlock은 YouTube 영상만 다룬다.
    """

    def __init__(self, source: ISkipSegmentSource) -> None:
        self._source = source
        self._cache: OrderedDict[tuple[str, tuple[str, ...]], list[SkipSegment]] = OrderedDict()

    def handle(self, query: GetSkipSegmentsQuery) -> list[SkipSegment]:
        from config import settings as cfg  # noqa: PLC0415 (런타임 토글)

        if not cfg.SPONSORBLOCK_SKIP:
            return []
        categories = parse_categories(cfg.SPONSORBLOCK_CATEGORIES)
        if not categories:
            return []

        video_id = extract_youtube_video_id(query.url)
        if not video_id:
            return []

        key = (video_id, categories)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached

        raw = self._source.fetch_segments(video_id, categories)
        segments = normalize_segments(raw, categories=categories)
        self._cache[key] = segments
        while len(self._cache) > _CACHE_MAX:
            self._cache.popitem(last=False)
        if segments:
            logger.info("SponsorBlock 구간 %d개: %s", len(segments), video_id)
        return segments


def parse_categories(raw: str) -> tuple[str, ...]:
    """``"sponsor, selfpromo"`` → ``("sponsor", "selfpromo")``."""
    return tuple(part.strip() for part in raw.split(",") if part.strip())
