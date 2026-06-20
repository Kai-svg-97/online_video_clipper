"""SemVer 비교 유틸리티 (X.Y.Z 형식, 외부 의존성 없음)."""
from __future__ import annotations


def parse_semver(s: str) -> tuple[int, int, int]:
    """'v1.2.3' 또는 '1.2.3' → (1, 2, 3). 파싱 실패 시 ValueError."""
    s = s.strip().lstrip("v")
    parts = s.split(".")
    if len(parts) != 3:
        raise ValueError(f"버전 형식 오류: {s!r}")
    return (int(parts[0]), int(parts[1]), int(parts[2]))


def is_newer(latest: str, current: str) -> bool:
    """latest 가 current 보다 높은 버전이면 True. 파싱 실패 시 False."""
    try:
        return parse_semver(latest) > parse_semver(current)
    except ValueError:
        return False
