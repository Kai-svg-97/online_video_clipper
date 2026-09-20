"""상세 설명서 열기 — F1과 설정 화면이 같은 곳을 가리킨다.

**오프라인을 먼저 본다.** 설치해 쓰는 데스크톱 앱이라 인터넷이 없을 때도 설명서를
볼 수 있어야 하고, 무엇보다 **지금 깔린 버전의 설명서**여야 한다(GitHub의 문서는
이미 다음 버전을 설명하고 있을 수 있다). 그래서 번들된 HTML을 먼저 찾고, 없을 때만
저장소 문서로 보낸다.

번들 HTML은 `scripts/build_manual.py`가 `docs/manual.md`에서 만들어 낸다 —
설명서 원본은 하나뿐이고, 두 벌을 손으로 맞추지 않는다.
"""

from __future__ import annotations

import logging

from utils.resources import get_resource_path

logger = logging.getLogger(__name__)

# 번들에 HTML이 없을 때 갈 곳(개발 중이거나 빌드에서 빠졌을 때).
MANUAL_URL = (
    "https://github.com/Kai-svg-97/online_video_clipper/blob/main/docs/manual.md"
)

_LOCAL_MANUAL = "docs/manual/index.html"


def manual_target() -> str:
    """브라우저로 열 상세 설명서 주소.

    로컬 파일은 `file://` URI로 돌려준다 — 경로를 그대로 넘기면 Windows에서
    드라이브 문자(`C:`)가 스킴으로 해석돼 열리지 않는다.
    """
    try:
        local = get_resource_path(_LOCAL_MANUAL)
        if local.exists():
            return local.as_uri()
    except Exception:
        logger.warning("번들 설명서 경로 확인 실패 — 온라인 문서로", exc_info=True)
    return MANUAL_URL


def open_manual() -> bool:
    """기본 브라우저로 상세 설명서를 연다. 성공 여부를 돌려준다."""
    from PyQt6.QtCore import QUrl  # noqa: PLC0415
    from PyQt6.QtGui import QDesktopServices  # noqa: PLC0415

    target = manual_target()
    ok = QDesktopServices.openUrl(QUrl(target))
    if not ok:
        logger.warning("상세 설명서를 열지 못했다: %s", target)
    return ok
