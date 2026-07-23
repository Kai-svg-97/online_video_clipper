"""pending 업데이트 마커 기록.

다운로드된 인스톨러를 '앱 종료 시 설치' 대상으로 등록한다. 앱이 종료되면 `main.py`의
종료 tail이 이 마커(`ovc_pending_update.txt`)를 읽어 조용히 설치하고 앱을 재실행한다.

마커 포맷(2줄): 1) 인스톨러 경로, 2) 재실행할 exe 경로(frozen 빌드일 때만, 아니면 빈 줄).
자동 다운로드 컨트롤러와 UpdateDialog가 공유한다(동일 계약).
"""

from __future__ import annotations

import logging
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

PENDING_MARKER = "ovc_pending_update.txt"


def pending_marker_path() -> Path:
    return Path(tempfile.gettempdir()) / PENDING_MARKER


def write_pending_update(installer_path: str) -> bool:
    """인스톨러를 종료 시 설치 대상으로 등록한다(win32 전용).

    반환: 마커를 기록했으면 True(win32 성공), 아니면 False(비win32 또는 실패).
    """
    if sys.platform != "win32":
        return False
    try:
        exe = sys.executable if getattr(sys, "frozen", False) else ""
        pending_marker_path().write_text(f"{installer_path}\n{exe}", encoding="utf-8")
        return True
    except OSError:
        logger.exception("pending update 마커 작성 실패")
        return False
