"""새 영상 감시 규칙 — **순수 판정**, 네트워크도 저장도 없다.

구독 채널에 새 영상이 올라와도 앱을 열어 피드를 눌러 봐야만 알 수 있었다. 감시는
그 간격을 메운다 — 배경에서 주기적으로 피드를 훑고, 지난번에 없던 것이 있으면
트레이로 알린다.

## 왜 날짜가 아니라 주소로 비교하나

"지난번 이후"를 날짜로 판정하는 것이 자연스러워 보이지만, `published_at`은 출처마다
표기가 다르다(yt-dlp 플랫 추출은 `YYYYMMDD`, YouTube API는 ISO 8601, 어떤 경로는
"3일 전" 같은 상대 표기를 준다). 형식을 잘못 짚으면 **조용히 틀린다** — 알림이 안
오거나, 매번 전부를 새 영상으로 본다.

대신 **지난번에 본 주소 목록**과 비교한다. 형식에 의존하지 않고, 영상이 피드에서
순서가 바뀌거나 잠깐 사라졌다 돌아와도 흔들리지 않는다. 목록은 피드 한 쪽 분량이라
무한정 늘지 않는다.
"""

from __future__ import annotations

# 감시 주기(분). 너무 촘촘하면 YouTube가 요청을 막고, 너무 뜸하면 감시의 뜻이 없다.
DEFAULT_INTERVAL_MIN = 30
MIN_INTERVAL_MIN = 10
MAX_INTERVAL_MIN = 360

# 기억해 둘 주소 수. 피드 한 쪽보다 넉넉해야 한다 — 부족하면 아직 피드에 남아 있는
# 영상이 기억에서 밀려나 **다시 '새 영상'이 된다**(같은 알림이 반복된다).
SEEN_LIMIT = 300

# 한 번에 알릴 최대 건수. 오래 꺼 뒀다 켜면 수십 건이 한꺼번에 새 영상이 되는데,
# 그걸 다 적으면 알림이 읽히지 않는다.
NOTIFY_SAMPLE = 3


def clamp_interval(minutes: int) -> int:
    """설정 값이 어떤 값이든 쓸 수 있는 범위로 접는다."""
    try:
        value = int(minutes)
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_MIN
    return max(MIN_INTERVAL_MIN, min(MAX_INTERVAL_MIN, value))


def select_new(current: list[str], seen: list[str]) -> list[str]:
    """지난번에 없던 주소들(피드 순서 유지).

    **처음 켠 것은 새 영상이 아니다.** 기억이 비어 있으면 빈 목록을 돌려준다 —
    설치 직후 구독 피드 전체를 '새 영상'이라고 알리면 알림이 수십 개 뜨고,
    사용자는 그 길로 알림을 꺼 버린다.
    """
    if not seen:
        return []
    known = set(seen)
    out: list[str] = []
    for url in current:
        if url and url not in known and url not in out:
            out.append(url)
    return out


def next_seen(current: list[str], seen: list[str], limit: int = SEEN_LIMIT) -> list[str]:
    """다음 비교에 쓸 기억 — 이번 피드를 앞에 두고 상한까지 이전 것을 잇는다.

    이전 것을 남기는 이유는, 피드가 짧아지는 순간(채널 하나가 잠시 응답하지 않는 등)
    **이미 본 영상이 기억에서 통째로 빠져** 다음 조회에서 전부 새 영상이 되는 것을
    막기 위해서다.
    """
    out: list[str] = []
    known: set[str] = set()
    for url in list(current) + list(seen):
        if url and url not in known:
            out.append(url)
            known.add(url)
        if len(out) >= limit:
            break
    return out


def summarize(titles: list[str], total: int) -> str:
    """알림 본문 — 제목 몇 개만 적고 나머지는 수로 줄인다."""
    shown = [t for t in titles[:NOTIFY_SAMPLE] if t]
    if not shown:
        return f"새 영상 {total}개"
    body = "\n".join(shown)
    rest = total - len(shown)
    return f"{body}\n… 외 {rest}개" if rest > 0 else body
