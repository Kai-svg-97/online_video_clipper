"""pending 업데이트 마커 기록.

다운로드된 인스톨러를 '앱 종료 시 설치' 대상으로 등록한다. 앱이 종료되면 `main.py`의
종료 tail이 이 마커(`ovc_pending_update.txt`)를 읽어 조용히 설치하고 앱을 재실행한다.

마커 포맷(2줄): 1) 인스톨러 경로, 2) 재실행할 exe 경로(frozen 빌드일 때만, 아니면 빈 줄).
`UpdateController`와 `UpdateDialog`가 공유한다(동일 계약).
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


def update_failure_path() -> Path:
    """설치 배치가 실패 종료 코드를 남기는 자리.

    배치는 조용히 죽는다 — 디스크가 모자라거나 인스톨러가 거부돼도 아무도 모르고,
    사용자는 "업데이트를 눌렀는데 버전이 그대로"인 상태에 남는다. 여기 흔적이 있으면
    다음 기동에서 알려 줄 수 있다.
    """
    return Path(tempfile.gettempdir()) / "ovc_update_failed.txt"


def take_update_failure() -> str:
    """지난 설치가 실패했으면 종료 코드를 돌려주고 흔적을 지운다(한 번만 알린다)."""
    path = update_failure_path()
    try:
        if not path.exists():
            return ""
        code = path.read_text(encoding="ascii", errors="replace").strip()
        path.unlink(missing_ok=True)
        return code
    except OSError:
        logger.exception("업데이트 실패 기록을 읽지 못했다")
        return ""
