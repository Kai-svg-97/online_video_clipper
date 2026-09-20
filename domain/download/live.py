"""라이브 방송 판정과 녹화 표기의 **순수 규칙** — I/O 없음.

녹화는 일반 다운로드와 성질이 다르다. 그 차이가 규칙의 전부다.

- **끝을 모른다.** 총 크기가 없으므로 진행률(%)이 성립하지 않는다. 0%나 NaN을
  보여주면 멈춘 것처럼 보이므로, 경과 시간과 받은 용량으로 대신 알린다.
- **지금 아니면 못 받는다.** 예약 시간대·동시 실행 한도에 걸려 대기하면 방송이
  끝나 버린다. 그래서 녹화는 그 게이트를 우회하되, 대신 **자기 상한**을 갖는다
  (녹화 여러 개가 디스크·대역폭을 독차지하지 않게).
"""

from __future__ import annotations

# yt-dlp가 돌려주는 `live_status` 값 → 우리 상태.
# 오래된 추출기는 `live_status` 없이 `is_live` 불리언만 주므로 둘 다 받는다.
LIVE_NOW = "live"           # 방송 중 — 지금 녹화할 수 있다
LIVE_UPCOMING = "upcoming"  # 예정 — 아직 받을 것이 없다
LIVE_ENDED = "ended"        # 끝난 방송 — 일반 다운로드로 받으면 된다
NOT_LIVE = "not_live"       # 애초에 라이브가 아니다

_STATUS_MAP: dict[str, str] = {
    "is_live": LIVE_NOW,
    "is_upcoming": LIVE_UPCOMING,
    "was_live": LIVE_ENDED,
    # 방송은 끝났지만 다시보기가 아직 준비 중인 상태. 받을 수는 있어도 조각이
    # 빠질 수 있어 '끝남'으로 본다(사용자에겐 결과가 같다).
    "post_live": LIVE_ENDED,
    "not_live": NOT_LIVE,
}

# 동시 녹화 상한. 녹화는 몇 시간씩 이어지므로, 일반 다운로드와 달리
# 사용자가 쌓아 두면 디스크가 먼저 찬다.
MAX_CONCURRENT_RECORDINGS = 2


def classify_live_status(info: dict) -> str:
    """메타데이터 → 라이브 상태.

    `live_status`를 먼저 보고, 없으면 `is_live`로 되돌아간다. 둘 다 없으면
    라이브가 아니다(대부분의 영상이 여기 해당한다).
    """
    raw = (info or {}).get("live_status")
    if isinstance(raw, str) and raw in _STATUS_MAP:
        return _STATUS_MAP[raw]
    if (info or {}).get("is_live"):
        return LIVE_NOW
    # `was_live`만 따로 오는 추출기가 있다.
    if (info or {}).get("was_live"):
        return LIVE_ENDED
    return NOT_LIVE


def is_recordable(status: str) -> bool:
    """지금 녹화를 시작할 수 있는가.

    예정(`upcoming`)은 **아니다** — 시작 시각까지 yt-dlp가 대기하게 두면 워커가
    몇 시간씩 잡혀 있고, 그동안 사용자에게는 '녹화 중'으로 보인다.
    """
    return status == LIVE_NOW


# 경과 시간·용량·진행 한 줄을 만드는 일은 **표시 계층이 한다**(`gui/text/formats.py`).
# 여기 있던 `format_elapsed`·`format_size`·`format_recording_progress`는 그리로 옮겼다 —
# 도메인이 "1시간 5분" 같은 완성된 한국어를 만들면 화면 언어를 바꿀 수 없다.
