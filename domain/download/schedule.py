"""다운로드를 지금 시작해도 되는지 판단하는 **순수 규칙** — I/O 없음.

두 가지를 함께 본다.

- **예약 시간대**: "밤에만 받기"처럼 허용 시간대를 정한다. 자정을 넘기는 구간
  (23시~07시)이 오히려 흔한 설정이라, 단순 비교(`start <= now < end`)로 짜면
  **밤 시간대가 통째로 막힌다**. 그래서 넘어가는 경우를 따로 다룬다.
- **동시 실행 수**: 큐가 몇 개를 동시에 돌릴지. 이 값은 예전에도 설정 화면에 있었지만
  아무 데서도 쓰이지 않아(뷰모델이 요청마다 워커를 바로 띄웠다) 실제로는 무제한이었다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

# 동시 실행 수의 허용 범위 — 설정 화면의 스핀박스와 같은 값을 쓴다.
MIN_CONCURRENT = 1
MAX_CONCURRENT = 8


@dataclass(frozen=True, slots=True)
class DownloadWindow:
    """다운로드를 허용하는 시간대(시 단위).

    ``start_hour == end_hour``는 "하루 종일"로 읽는다 — 폭 0의 창은 아무것도 받지
    못한다는 뜻이 되어, 실수로 같은 값을 고른 사용자가 원인을 찾기 어렵다.
    """

    enabled: bool = False
    start_hour: int = 0
    end_hour: int = 0

    def allows(self, now: time) -> bool:
        if not self.enabled:
            return True
        start, end = self.start_hour % 24, self.end_hour % 24
        if start == end:
            return True                      # 하루 종일
        if start < end:
            return start <= now.hour < end   # 같은 날 안에서 끝난다
        return now.hour >= start or now.hour < end   # 자정을 넘긴다

    def describe(self) -> str:
        """설정 화면에 보여줄 한 줄 설명."""
        if not self.enabled:
            return "언제든 받습니다"
        start, end = self.start_hour % 24, self.end_hour % 24
        if start == end:
            return "하루 종일 받습니다"
        crossing = " (다음 날)" if start > end else ""
        return f"{start:02d}:00 ~ {end:02d}:00{crossing} 에만 받습니다"


def clamp_concurrent(value: int) -> int:
    """동시 실행 수를 허용 범위로 자른다(설정 파일이 손으로 고쳐질 수 있다)."""
    return max(MIN_CONCURRENT, min(MAX_CONCURRENT, int(value)))


def slots_available(running: int, limit: int) -> int:
    """지금 새로 시작해도 되는 개수(음수가 되지 않는다)."""
    return max(0, clamp_concurrent(limit) - running)
