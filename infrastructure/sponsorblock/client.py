"""SponsorBlock 공개 API 어댑터.

**해시 접두 조회를 쓴다.** `/api/skipSegments?videoID=...`는 서버에 "내가 지금 이
영상을 본다"를 그대로 알려 주지만, `/api/skipSegments/{sha256(videoID)[:4]}`는
같은 접두를 가진 여러 영상의 결과를 한꺼번에 돌려주므로 서버가 어느 것인지 알 수
없다. 응답에서 우리 영상만 골라내는 건 클라이언트 몫이다.

네트워크는 배경 QThread에서만 호출한다. 실패는 예외 대신 빈 목록이다 — 건너뛰기는
부가 기능이라 SponsorBlock이 죽어 있다고 재생을 막으면 안 된다.
"""

from __future__ import annotations

import hashlib
import json
import logging

import requests

logger = logging.getLogger(__name__)

_API_BASE = "https://sponsor.ajay.app/api/skipSegments"

# 조회를 오래 붙들지 않는다 — 재생을 시작하기 전에 답이 와야 의미가 있고,
# 늦게 오면 어차피 그 구간을 이미 지났다.
_TIMEOUT = (4, 6)   # (connect, read)

# 해시 접두 길이. 4자면 한 번에 수백 개 영상이 섞여 와 어느 것인지 특정되지 않는다.
_HASH_PREFIX_LEN = 4


class SponsorBlockClient:
    """`ISkipSegmentSource` 구현."""

    def __init__(self, base_url: str = _API_BASE) -> None:
        self._base = base_url.rstrip("/")

    def fetch_segments(
        self, video_id: str, categories: tuple[str, ...]
    ) -> list[tuple[str, float, float]]:
        """(카테고리, 시작초, 끝초) 목록. 실패하거나 없으면 빈 목록."""
        if not video_id or not categories:
            return []
        prefix = hashlib.sha256(video_id.encode("utf-8")).hexdigest()[:_HASH_PREFIX_LEN]
        try:
            resp = requests.get(
                f"{self._base}/{prefix}",
                params={"categories": json.dumps(list(categories))},
                timeout=_TIMEOUT,
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 404:
                return []          # 등록된 구간이 하나도 없는 정상 응답이다
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException:
            # 네트워크 실패는 흔하고 복구 수단도 없다 — 트레이스백 없이 한 줄만.
            logger.warning("SponsorBlock 조회 실패: video_id=%s", video_id)
            return []
        except ValueError:
            logger.warning("SponsorBlock 응답이 JSON이 아님: video_id=%s", video_id)
            return []

        return list(_extract(payload, video_id))


def _extract(payload: object, video_id: str):
    """해시 접두 응답에서 우리 영상의 구간만 골라낸다.

    응답 형태: ``[{"videoID": "...", "segments": [{"category": ..., "segment": [s, e]}]}]``
    형식이 조금이라도 어긋나면 그 항목만 건너뛴다 — 공개 API라 우리가 고칠 수 없고,
    한 항목 때문에 전체를 버리면 멀쩡한 구간까지 날아간다.
    """
    if not isinstance(payload, list):
        return
    for entry in payload:
        if not isinstance(entry, dict) or entry.get("videoID") != video_id:
            continue
        for seg in entry.get("segments") or []:
            try:
                start, end = seg["segment"]
                yield str(seg["category"]), float(start), float(end)
            except (KeyError, TypeError, ValueError):
                logger.debug("SponsorBlock 구간 형식 이상 — 건너뜀: %r", seg)
