"""설정 화면 공용 도우미 — 현재 테마 토큰과 폴더 열기.

`open_folder`는 사용자가 경로를 직접 찾지 않아도 되게 탐색기를 띄운다
(대상 사용자가 AppData 경로를 모른다는 실제 신고에서 나온 기능).
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices

from gui.themes.manager import ThemeManager



logger = logging.getLogger(__name__)


def _t():
    return ThemeManager.instance().current()

def open_folder(path) -> None:
    """OS 파일 탐색기로 폴더를 연다 — 경로를 직접 찾아 입력할 필요를 없앤다."""
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
