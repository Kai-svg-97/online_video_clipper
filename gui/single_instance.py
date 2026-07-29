"""단일 인스턴스 가드 — 앱이 두 번 실행되는 것을 막는다.

업데이트 직후 인스톨러와 종료 tail 배치가 각각 앱을 띄워 2개가 실행되는 문제가 있었다.
근본 원인은 `packaging/installer.iss`의 `[Run]` 플래그로 고치지만, 사용자가 아이콘을
연달아 누르는 경우까지 막으려면 앱 자체에도 가드가 필요하다.

QLocalServer/QLocalSocket을 쓴다 — 파일 잠금과 달리 비정상 종료 후 잠금이 남아도
removeServer()로 회수할 수 있고, 두 번째 인스턴스가 기존 창을 앞으로 불러올 수 있다.
"""

from __future__ import annotations

import getpass
import logging
from collections.abc import Callable

from PyQt6.QtCore import QObject
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT_MS = 300


def _default_key() -> str:
    """사용자별 키 — 다중 사용자 환경에서 서로를 막지 않게 한다."""
    try:
        user = getpass.getuser()
    except Exception:
        logger.warning("사용자명 조회 실패 — 공용 키를 쓴다", exc_info=True)
        user = "shared"
    return f"ovc-single-instance-{user}"


class SingleInstanceGuard(QObject):
    """이 프로세스가 유일한 인스턴스인지 판별하고, 두 번째 실행을 기존 창으로 넘긴다."""

    def __init__(self, key: str | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.key = key or _default_key()
        self._server: QLocalServer | None = None
        self._activate: Callable[[], None] | None = None

    def set_activate_callback(self, fn: Callable[[], None]) -> None:
        """두 번째 인스턴스가 접속했을 때 호출된다(기존 창을 앞으로 부르는 용도)."""
        self._activate = fn

    def try_acquire(self) -> bool:
        """유일 인스턴스면 True. 이미 실행 중이면 신호만 보내고 False."""
        probe = QLocalSocket()
        probe.connectToServer(self.key)
        if probe.waitForConnected(_CONNECT_TIMEOUT_MS):
            # 기존 인스턴스가 살아 있다 — 창을 띄우라고 알리고 물러난다.
            probe.write(b"activate")
            probe.flush()
            probe.waitForBytesWritten(_CONNECT_TIMEOUT_MS)
            probe.disconnectFromServer()
            return False
        probe.abort()

        # 비정상 종료로 남은 소켓이 있으면 listen()이 실패하므로 먼저 회수한다.
        QLocalServer.removeServer(self.key)
        server = QLocalServer(self)
        if not server.listen(self.key):
            logger.warning(
                "단일 인스턴스 서버 리스닝 실패(%s) — 가드 없이 계속한다",
                server.errorString(),
            )
            return True
        server.newConnection.connect(self._on_new_connection)
        self._server = server
        return True

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        QLocalServer.removeServer(self.key)

    def _on_new_connection(self) -> None:
        if self._server is None:
            return
        conn = self._server.nextPendingConnection()
        if conn is not None:
            conn.disconnectFromServer()
        if self._activate is not None:
            try:
                self._activate()
            except Exception:
                logger.exception("기존 창 활성화 실패")
