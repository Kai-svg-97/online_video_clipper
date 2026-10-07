"""yt-dlp용 JS 런타임 옵션.

YouTube의 JS 챌린지(서명·n 파라미터)는 JS 런타임이 있어야 풀린다. yt-dlp 기본값은
``{"deno": {}}`` 뿐이라 deno가 없으면 기본(web) 클라이언트가 실패하고 대체 클라이언트로
밀리는데, 그 URL은 처음 60초 분량까지만 열리고 먼 seek은 403으로 막힌다.
그래서 시스템/번들에서 쓸 수 있는 런타임을 찾아 명시적으로 넘긴다.
"""
from __future__ import annotations

import functools
import logging
import shutil
import sys

from utils.resources import get_resource_path

logger = logging.getLogger(__name__)

# 탐지 순서 — yt-dlp가 지원하는 런타임 이름(소문자)
_RUNTIMES = ("deno", "node", "bun", "quickjs")


def _find(name: str) -> str | None:
    """번들(bin/) 우선, 없으면 PATH에서 런타임 실행 파일을 찾는다."""
    for rel in (f"bin/{name}.exe", f"bin/{name}"):
        # 비윈도우에서 .exe를 찾아 헛디디지 않도록 플랫폼에 맞는 것만 본다
        if rel.endswith(".exe") != (sys.platform == "win32"):
            continue
        bundled = get_resource_path(rel)
        if bundled.exists():
            return str(bundled)
    return shutil.which(name)


@functools.lru_cache(maxsize=1)
def js_runtime_opts() -> dict:
    """yt-dlp ``js_runtimes`` 옵션 조각을 돌려준다(프로세스 수명 동안 캐시).

    발견된 런타임만 담는다. 하나도 없으면 ``{}``(= yt-dlp 기본 동작)를 주고 경고를 한 번 남긴다.
    호출부는 ``{**js_runtime_opts(), ...사용자 옵션}`` 순서로 합쳐 사용자 옵션이 우선하게 한다.
    """
    found: dict[str, dict] = {}
    for name in _RUNTIMES:
        path = _find(name)
        if path:
            found[name] = {"path": path}
    if not found:
        logger.warning("JS 런타임이 없어 YouTube 고화질·seek가 제한될 수 있음 (deno/node/bun/quickjs 설치 필요)")
        return {}
    return {"js_runtimes": found}
