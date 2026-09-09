"""프로세스 시작·종료 절차 — Qt 앱, 스플래시, 중복 실행 가드, 업데이트 설치 tail.

여기 있는 것들은 **조립이 아니라 절차**다. 순서가 곧 의미이고(스플래시는 무거운
임포트 전에, 중복 실행 판단은 DB 열기 전에, 업데이트 설치는 앱이 완전히 종료된
뒤에) 그 이유가 각 함수 문서에 붙어 있다.

이 모듈은 **가볍게 유지한다** — `main.py`가 스플래시를 띄우기 전에 임포트하기
때문이다. 인프라·GUI 패널을 여기서 임포트하면 스플래시가 늦게 뜬다.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap, QPixmapCache
from PyQt6.QtWidgets import QApplication, QSplashScreen

from utils.resources import get_resource_path

logger = logging.getLogger(__name__)

_APP_NAME = "YouTube Content Manager"
_APP_USER_MODEL_ID = "YTContentManager.App.1.0"
_PIXMAP_CACHE_KB = 30720   # 30 MB — 저사양 PC 대응 규칙


def suppress_av_log() -> None:
    """PyQt6 번들 avutil의 INFO·WARNING 로그를 끈다.

    Qt Multimedia의 FFmpeg 백엔드가 `av_log`로 stderr에 직접 쓰는 메시지
    (`[h264] Late SEI`·`Input #0`·`Stream #` 등)를 억제한다. `AV_LOG_QUIET = -8`.

    **DLL 이름을 바깥 루프로 돈다** — 번들 경로에 없는 버전을 시스템 경로에서
    찾는 것보다, 최신 버전을 두 경로에서 먼저 찾는 쪽이 맞다.

    실패해도 무해하므로 조용히 넘어간다(로그 잡음이 남을 뿐이다).
    """
    import ctypes
    import importlib.util

    spec = importlib.util.find_spec("PyQt6")
    qt_bin = ""
    if spec and spec.submodule_search_locations:
        qt_bin = os.path.join(list(spec.submodule_search_locations)[0], "Qt6", "bin")

    for name in ("avutil-59.dll", "avutil-58.dll", "avutil-57.dll", "avutil-56.dll"):
        for base in ([qt_bin] if qt_bin else []) + [""]:
            path = os.path.join(base, name) if base else name
            try:
                ctypes.CDLL(path).av_log_set_level(-8)
                return
            except OSError:
                pass
    logger.debug("avutil DLL을 찾지 못해 FFmpeg 로그 억제를 건너뛴다")


def build_splash_pixmap() -> QPixmap:
    """스플래시 화면 이미지를 만든다 — 앱 아이콘 + 이름.

    치수·색·문구는 기존 화면 그대로다(이 리팩터링은 보이는 것을 바꾸지 않는다).
    """
    W, H = 480, 240
    pix = QPixmap(W, H)
    pix.fill(QColor("#242424"))

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    icon_path = get_resource_path("assets/icon.ico")
    if icon_path.exists():
        icon_pix = QPixmap(str(icon_path)).scaled(
            80,
            80,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawPixmap((W - icon_pix.width()) // 2, 28, icon_pix)

    painter.setPen(QColor("#ffffff"))
    painter.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
    painter.drawText(
        QRect(0, 122, W, 36), Qt.AlignmentFlag.AlignHCenter, _APP_NAME
    )

    painter.setPen(QColor("#888888"))
    painter.setFont(QFont("Segoe UI", 9))
    painter.drawText(QRect(0, 172, W, 26), Qt.AlignmentFlag.AlignHCenter, "로딩 중…")

    painter.end()
    return pix


def install_qt_message_filter() -> None:
    """Qt 내부의 무해한 경고를 걸러 낸다.

    `QFFmpeg` 객체가 소멸할 때 나오는 `QObject::disconnect` 경고는 우리가 고칠 수
    있는 것이 아니고 양이 많아 실제 경고를 묻는다.
    """
    from PyQt6.QtCore import QtMsgType, qInstallMessageHandler

    muted = ("wildcard call disconnects from destroyed signal",)

    def handler(msg_type: QtMsgType, _ctx, message: str) -> None:
        if any(p in message for p in muted):
            return
        if msg_type in (
            QtMsgType.QtWarningMsg,
            QtMsgType.QtCriticalMsg,
            QtMsgType.QtFatalMsg,
        ):
            print(f"[Qt] {message}", file=sys.stderr)

    qInstallMessageHandler(handler)


def create_qt_app(argv: list[str]) -> QApplication:
    """`QApplication`을 가장 먼저 만든다 — 스플래시를 즉시 띄우기 위해서다.

    무거운 초기화보다 **앞에** 있어야 사용자가 아이콘을 누른 직후 창을 본다.
    """
    app = QApplication(argv)
    app.setApplicationName(_APP_NAME)
    app.setFont(QFont("Segoe UI", 9))
    QPixmapCache.setCacheLimit(_PIXMAP_CACHE_KB)

    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                _APP_USER_MODEL_ID
            )
        except Exception:
            logger.debug("AppUserModelID 설정 실패 — 작업표시줄 아이콘 그룹화만 영향")

    icon_path = get_resource_path("assets/icon.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    return app


def show_splash(app: QApplication) -> QSplashScreen:
    """스플래시를 띄우고 **즉시 그린다**.

    `processEvents()`가 없으면 이어지는 무거운 임포트가 이벤트 루프를 막아 스플래시가
    빈 창으로만 남는다(띄운 의미가 없어진다).
    """
    splash = QSplashScreen(build_splash_pixmap())
    splash.show()
    app.processEvents()
    return splash


def install_pending_update() -> None:
    """앱이 완전히 종료된 뒤 대기 중인 업데이트 인스톨러를 실행한다.

    **실행 중에는 설치할 수 없다**(자기 파일이 잠겨 있다). 그래서 배치 파일로
    지연 실행한다: 5초 대기 → 무인 설치 → 설치 후 앱 재실행.

    재실행 주체는 **배치 하나로 고정한다.** 인스톨러(`installer.iss`)의 `[Run]`에도
    실행 항목이 있으면 업데이트 후 앱이 두 개 뜬다 — 예전에 `skipifsilent`가 빠져
    실제로 그랬다. 반대로 양쪽을 다 막으면 다음 업데이트에서 아무도 앱을 실행하지
    않으므로, 한쪽만 남기는 것이 맞다(배치는 구버전 앱이 만들고 인스톨러는 신버전
    이라, 지금 손댈 수 있는 쪽이 배치다).
    """
    if sys.platform != "win32":
        return

    marker = Path(tempfile.gettempdir()) / "ovc_pending_update.txt"
    if not marker.exists():
        return

    try:
        lines = marker.read_text(encoding="utf-8").splitlines()
        installer = lines[0].strip() if lines else ""
        exe = lines[1].strip() if len(lines) > 1 else ""
    except OSError:
        logger.exception("pending 업데이트 파일 읽기 실패")
        installer = exe = ""

    marker.unlink(missing_ok=True)
    if not installer or not Path(installer).exists():
        return

    try:
        bat = Path(tempfile.gettempdir()) / "ovc_update_launcher.bat"
        content = (
            "@echo off\r\n"
            "timeout /t 5 /nobreak >nul\r\n"
            f'"{installer}" /VERYSILENT /NORESTART\r\n'
        )
        if exe:
            content += f'start "" "{exe}"\r\n'
        content += 'del "%~f0"\r\n'
        bat.write_text(content, encoding="mbcs")
        subprocess.Popen(
            ["cmd", "/c", str(bat)],
            creationflags=subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    except (OSError, IOError):
        logger.exception("업데이트 launcher 실행 실패")
