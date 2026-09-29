"""숫자·시간·용량을 사람이 읽는 형태로. **언어에 의존하는 포맷만 여기 둔다.**

## 도메인에 남는 것과 여기로 오는 것

가르는 기준은 하나다 — **"영어판이 단어 치환 이상으로 달라지는가?"**

- 도메인에 남는다: `progress_fraction()` 같은 **순수 계산**
- 여기로 온다: `"3일 전"`(단어), `"1.2만 회"`(**구간 경계 자체가 다르다**),
  `"12.3 MB"`(소수 구분자·단위 표기), `"1:23:45"`(구분자·시 생략 규칙)

## 통합하되 출력은 바꾸지 않는다 — 한 곳만 빼고

같은 일을 하는 함수가 재생시간 11곳·용량 6곳·상대시간 3곳에 흩어져 있었는데 **서로
출력이 달랐다**. 하나로 뭉개면 화면이 조용히 바뀌고, 그 변화가 이 정리 탓인지 나중에
알 수 없다. 그래서 다른 것은 파라미터로 남긴다 — 상대시간의 `style`, 용량의 `unit`.

**딱 하나 의도적으로 바꾼 것이 있다**: `stats_panel._fmt_bytes`와
`detail/widgets._fmt_size`가 `b //= 1024`(정수 나눗셈)로 소수를 **잘라 버려**
`393.4 MB`를 `393.0 MB`로, `1.5 MB`를 `1.0 MB`로 보여 주고 있었다. 통합하면서
실수로 옮기지 않고 고친다.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from enum import Enum

from gui.text import active_language, tr

logger = logging.getLogger(__name__)

_KB = 1024
_MB = 1024 * 1024


# ── 재생시간 ──────────────────────────────────────────────────────

def format_duration(
    seconds: float | int | None,
    *,
    always_hours: bool = False,
    none_text: str = "",
) -> str:
    """`H:MM:SS` / `M:SS`. 없거나 음수면 `none_text`(기본 빈 문자열).

    시가 0이면 생략하는 것이 기본이다 — 대부분의 영상이 한 시간 미만이라 `0:03:21`은
    자리만 차지한다. 길이를 아직 모를 때 무엇을 보일지는 화면마다 다르므로
    (`""` 또는 `"—"`) `none_text`로 받는다.
    """
    if seconds is None:
        return none_text
    total = int(seconds)
    if total < 0:
        return none_text
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h or always_hours:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_duration_ms(ms: int | None, *, always_hours: bool = False) -> str:
    """밀리초를 받는 입구 — 플레이어 쪽이 ms 로 센다."""
    if ms is None:
        return ""
    return format_duration(ms // 1000, always_hours=always_hours)


def format_duration_minutes(seconds: int | None) -> str:
    """`M:SS` 고정 — 시를 절대 쓰지 않는 자리(앨범 수록곡처럼 한 곡 단위).

    0이나 없음은 빈 문자열이다. 수록곡 길이를 모를 때 `0:00`을 적으면 "0초짜리 곡"으로
    읽힌다.
    """
    if not seconds:
        return ""
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"


def format_long_duration(seconds: int | None) -> str:
    """누적 시간 — `3일 5시간` / `2시간 7분`. 통계 화면처럼 '얼마나 쌓였나'를 볼 때."""
    if seconds is None or seconds < 0:
        return ""
    h, rem = divmod(int(seconds), 3600)
    m, _ = divmod(rem, 60)
    if h >= 24:
        return tr("{d}일 {h}시간").format(d=h // 24, h=h % 24)
    return tr("{h}시간 {m}분").format(h=h, m=m)


def format_elapsed_span(seconds: float) -> str:
    """경과 시간 — `1시간 5분` / `5분 3초` / `3초`.

    끝을 모르는 라이브 녹화에는 진행률 대신 이것을 보여 준다.
    """
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return tr("{h}시간 {m}분").format(h=hours, m=minutes)
    if minutes:
        return tr("{m}분 {s}초").format(m=minutes, s=secs)
    return tr("{s}초").format(s=secs)


def format_recording_progress(elapsed_sec: float, downloaded_bytes: float) -> str:
    """녹화 진행 한 줄 — `1시간 5분 · 2.4 GB`.

    퍼센트를 쓰지 않는다. 라이브는 끝을 모르므로 백분율이 거짓말이 된다
    (`domain/download/live.py` 모듈 설명 참조).
    """
    return f"{format_elapsed_span(elapsed_sec)} · {format_bytes(downloaded_bytes)}"


# ── 상대 시간 ─────────────────────────────────────────────────────

class RelativeStyle(Enum):
    """같은 '3일 전'이라도 화면마다 잣대가 다르다 — 통합하되 그 차이는 지킨다."""

    PRECISE = "precise"   # 방금 / N분 전 / N시간 전 / N일 전 / N개월 전 / N년 전
    COARSE = "coarse"     # 오늘 / N일 전 / N주 전 / N개월 전 / N년 전


def format_relative_time(
    value: str | None,
    *,
    style: RelativeStyle = RelativeStyle.COARSE,
    now: datetime | None = None,
) -> str:
    """`3일 전` 꼴로 바꾼다. 못 읽으면 빈 문자열(화면을 막지 않는다).

    입력은 세 형태를 모두 받는다 — ISO 일시(타임존 유무 무관), `YYYYMMDD`(yt-dlp),
    `YYYY-MM-DD`.
    """
    if not value:
        return ""
    if style is RelativeStyle.PRECISE:
        return _relative_precise(value, now)
    return _relative_coarse(value, now)


def _relative_precise(iso: str, now: datetime | None) -> str:
    """초 단위로 재는 잣대 — 방금 올라온 것을 '오늘'이라고 뭉뚱그리지 않는다."""
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        s = (current - dt).total_seconds()
    except Exception:
        logger.exception("경과 시간 포맷 변환 실패")
        return ""
    if s < 60:
        return tr("방금")
    if s < 3600:
        return tr("{n}분 전").format(n=int(s // 60))
    if s < 86400:
        return tr("{n}시간 전").format(n=int(s // 3600))
    if s < 86400 * 30:
        return tr("{n}일 전").format(n=int(s // 86400))
    if s < 86400 * 365:
        return tr("{n}개월 전").format(n=int(s // (86400 * 30)))
    return tr("{n}년 전").format(n=int(s // (86400 * 365)))


def _relative_coarse(value: str, now: datetime | None) -> str:
    """날짜 단위로 재는 잣대 — 게시일처럼 시각이 의미 없는 값에 쓴다."""
    try:
        if len(value) == 8 and value.isdigit():            # YYYYMMDD (yt-dlp)
            pub = date(int(value[:4]), int(value[4:6]), int(value[6:]))
        elif "T" in value or " " in value:
            pub = datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        else:
            pub = date.fromisoformat(value)
        today = (now or datetime.now()).date()
        days = (today - pub).days
    except (ValueError, TypeError):
        return ""
    if days < 0:
        return ""
    if days < 7:
        return tr("{n}일 전").format(n=days) if days > 0 else tr("오늘")
    if days < 30:
        return tr("{n}주 전").format(n=days // 7)
    if days < 365:
        return tr("{n}개월 전").format(n=days // 30)
    return tr("{n}년 전").format(n=days // 365)


# ── 용량 ──────────────────────────────────────────────────────────

class ByteUnit(Enum):
    AUTO = "auto"   # B/KB/MB/GB/TB 자동
    MB = "mb"       # 항상 MB — 업데이트 배지처럼 자릿수가 튀면 폭이 흔들리는 자리


def format_bytes(
    num_bytes: float | None,
    *,
    unit: ByteUnit = ByteUnit.AUTO,
    none_text: str = "",
) -> str:
    """`393.4 MB` / `512 B`. `unit=MB`면 `12.3MB`(붙여 쓴다).

    **실수 나눗셈으로 계산한다.** 예전 통계·상세 화면은 정수 나눗셈으로 소수를 잘라
    `393.4 MB`를 `393.0 MB`로 보여 주고 있었다.
    """
    if num_bytes is None:
        return none_text
    size = float(max(0, num_bytes))
    if unit is ByteUnit.MB:
        return f"{size / _MB:.1f}MB"
    if size < _KB:
        return f"{size:.0f} B"     # 바이트는 소수가 뜻이 없다
    for name in ("KB", "MB", "GB"):
        size /= _KB
        if size < _KB:
            return f"{size:.1f} {name}"
    return f"{size / _KB:.1f} TB"


# ── 숫자 ──────────────────────────────────────────────────────────

# (임계값, 나눌 값, 표기) — **이 표 자체가 번역 단위다.**
# 한국어는 천/만/억, 영어는 K/M/B 로 **구간 경계가 다르다**. 문자열을 바꿔치기해서는
# 될 일이 아니라 표를 통째로 갈아야 한다. 그래서 `_view_buckets()`가 언어로 표를 고른다.
_VIEW_BUCKETS_KO: tuple[tuple[int, int, str], ...] = (
    (100_000_000, 100_000_000, "{v:.1f}억"),
    (10_000, 10_000, "{v:.1f}만"),
    (1_000, 1_000, "{v:.1f}천"),
)
_VIEW_BUCKETS_EN: tuple[tuple[int, int, str], ...] = (
    (1_000_000_000, 1_000_000_000, "{v:.1f}B"),
    (1_000_000, 1_000_000, "{v:.1f}M"),
    (1_000, 1_000, "{v:.1f}K"),
)


def _view_buckets() -> tuple[tuple[int, int, str], ...]:
    return _VIEW_BUCKETS_KO if active_language() == "ko" else _VIEW_BUCKETS_EN


def format_view_count(count: int | None) -> str:
    """숫자와 단위만 — `1.2만`. 없으면 빈 문자열."""
    if count is None:
        return ""
    for threshold, divisor, fmt in _view_buckets():
        if count >= threshold:
            return fmt.format(v=count / divisor)
    return str(count)


def views_label(count: int | None) -> str:
    """`조회수 1.2만 회`. 천 미만은 단위를 붙이지 않는다(`조회수 812회`)."""
    if count is None:
        return ""
    if count < 1_000:
        return tr("조회수 {n}회").format(n=count)
    return tr("조회수 {v} 회").format(v=format_view_count(count))


def format_count(n: int) -> str:
    """천단위 구분 — `1,234`."""
    return f"{n:,}"


def format_compact_count(count: int | None, unit: str = "") -> str:
    """`12.3만명` / `1,234개` — 구독자·영상 수처럼 큰 수를 줄여 적는다.

    조회수(`format_view_count`)와 **경계가 다르다**: 여기는 만 미만이면 줄이지 않고
    천단위 구분만 한다(`1,234`). 조회수는 천 단위부터 줄인다(`1.2천`). 화면마다 잣대가
    달랐고, 통합하면서 그 차이를 지킨다.
    """
    if count is None:
        return ""
    if active_language() != "ko":
        if count >= 1_000_000_000:
            return f"{count / 1_000_000_000:.1f}B{unit}"
        if count >= 1_000_000:
            return f"{count / 1_000_000:.1f}M{unit}"
        return f"{count:,}{unit}"
    if count >= 100_000_000:
        return f"{count / 100_000_000:.1f}억{unit}"
    if count >= 10_000:
        return f"{count / 10_000:.1f}만{unit}"
    return f"{count:,}{unit}"
