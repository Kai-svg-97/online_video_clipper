"""시스템 트레이 아이콘 + 알림.

다운로드는 몇 분에서 몇 시간이 걸린다. 그동안 사용자는 이 앱을 보고 있지 않다 —
다른 창을 쓰거나 자리를 비운다. 앱 안의 토스트·상태바는 **보고 있을 때만** 쓸모가
있어서, 끝났다는 소식이 사실상 전달되지 않았다.

**트레이가 없는 환경이 있다.** 리눅스 데스크톱 일부는 트레이 영역 자체가 없고,
그런 곳에서 `QSystemTrayIcon`을 띄우면 아이콘이 어디에도 안 보이면서 `show()`는
성공한다. 그래서 `is_available()`로 먼저 묻고, 없으면 **아무것도 만들지 않는다** —
기능 하나가 조용히 빠질 뿐 앱은 그대로 돈다.

**알림은 시끄러우면 꺼진다.** 매 건마다 창을 띄우면 사용자가 OS 설정에서 앱 알림을
통째로 막아 버린다. 그래서 (1) 설정으로 끌 수 있고, (2) **창이 활성일 때는 보내지
않는다**(보고 있는 사람에게 알릴 이유가 없다 — 그 경우는 이미 토스트가 있다).
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

logger = logging.getLogger(__name__)

# 알림이 화면에 머무는 시간. 너무 짧으면 못 읽고, 길면 방해가 된다.
_MSG_MSEC = 5000


class AppTray(QObject):
    """트레이 아이콘 하나와 그 위의 알림.

    창을 소유하지 않는다 — 창을 앞으로 부르는 일은 `activated` 신호로 알리고,
    무엇을 할지는 창이 정한다(트레이가 창의 수명에 얽히지 않게 하기 위해서다).
    """

    show_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    @staticmethod
    def is_available() -> bool:
        """이 환경에 트레이가 있는가."""
        try:
            return bool(QSystemTrayIcon.isSystemTrayAvailable())
        except Exception:
            logger.exception("트레이 지원 여부 확인 실패 — 없는 것으로 본다")
            return False

    def __init__(self, icon: QIcon | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._icon = QSystemTrayIcon(self)
        self._icon.setIcon(icon or self._fallback_icon())
        self._icon.setToolTip("YouTube Content Manager")

        menu = QMenu()
        open_act = QAction("창 열기", menu)
        open_act.triggered.connect(self.show_requested)
        quit_act = QAction("종료", menu)
        quit_act.triggered.connect(self.quit_requested)
        menu.addAction(open_act)
        menu.addSeparator()
        menu.addAction(quit_act)
        # 메뉴를 지역 변수로 두면 파이썬이 회수해 트레이 우클릭이 죽는다.
        self._menu = menu
        self._icon.setContextMenu(menu)

        self._icon.activated.connect(self._on_activated)
        self._icon.show()

    # ── 알림 ──────────────────────────────────────────────────────

    def notify(self, title: str, message: str, *, ok: bool = True) -> None:
        """풍선 알림. 실패해도 조용히 넘어간다(알림은 부가 기능이다)."""
        icon = (
            QSystemTrayIcon.MessageIcon.Information
            if ok
            else QSystemTrayIcon.MessageIcon.Warning
        )
        try:
            self._icon.showMessage(title, message, icon, _MSG_MSEC)
        except Exception:
            logger.exception("트레이 알림 실패 (무시): %s", title)

    def hide(self) -> None:
        """종료 시 아이콘을 내린다 — 남겨 두면 유령 아이콘이 트레이에 붙어 있다."""
        try:
            self._icon.hide()
        except RuntimeError:
            logger.debug("트레이 아이콘이 이미 파괴됨 — 무시")

    # ── 입력 ──────────────────────────────────────────────────────

    def _on_activated(self, reason) -> None:
        """아이콘을 (더블)클릭하면 창을 앞으로 부른다."""
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_requested.emit()

    # ── 내부 ──────────────────────────────────────────────────────

    @staticmethod
    def _fallback_icon() -> QIcon:
        """앱 아이콘을 못 찾을 때 — **빈 아이콘을 주면 안 된다**.

        빈 QIcon 으로 트레이를 띄우면 어떤 데스크톱에서는 아이콘이 보이지 않아
        '떴는데 안 보인다'가 된다. 창 아이콘을 물려받고, 그마저 없으면 표준 아이콘을 쓴다.
        """
        app = QApplication.instance()
        icon = app.windowIcon() if app is not None else QIcon()
        if not icon.isNull():
            return icon
        from PyQt6.QtWidgets import QStyle  # noqa: PLC0415

        if app is not None:
            return app.style().standardIcon(
                QStyle.StandardPixmap.SP_ComputerIcon
            )
        return QIcon()
