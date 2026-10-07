"""화질 강등 안내 판정 — 순수 함수(PyQt 의존 없음)라 헤드리스로 시험한다.

고화질 스트리밍에서 먼 위치로 seek하면 원본이 먼 오프셋을 거부해 병합 폴백으로
내려가고, 병합이 막히면 360p 합본만 받는 일이 있다. 설정은 최고 화질인데 낮은
화질로 재생되므로 사용자에게 이유를 알려야 한다 — 그 안내가 필요한지만 판정한다.
"""
from __future__ import annotations

import re

from gui.widgets.player.constants import _QUALITY_HEIGHTS

_HEIGHT_RE = re.compile(r"(\d+)")


def parse_height(label: str) -> int | None:
    """`"360p"` 같은 라벨에서 세로 해상도를 읽는다. 읽을 수 없으면 None."""
    m = _HEIGHT_RE.search(label or "")
    return int(m.group(1)) if m else None


def requested_height(quality_key: str) -> int | None:
    """사용자가 고른 화질 키의 상한 높이. `auto`·모르는 키는 판정 불가라 None."""
    return _QUALITY_HEIGHTS.get(quality_key)


def should_notify_downgrade(quality_key: str, received_label: str) -> bool:
    """요청한 상한보다 실제로 받은 화질이 낮을 때만 True.

    요청 상한이나 받은 높이를 알 수 없으면 False — 모르는 것을 단정해 알리지 않는다.
    """
    want = requested_height(quality_key)
    got = parse_height(received_label)
    if want is None or got is None:
        return False
    return got < want
