"""메인 창이 띄우는 QThread 워커.

부모 없이 만들고 `gui/workers.py:track_thread`로 붙든다 — 창이 먼저 닫혀도 실행 중
스레드가 파괴되지 않게(`MainWindow._start_db_backup`).
"""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal


class _DbBackupWorker(QThread):
    """하루 한 번 DB 사본을 남긴다 — **배경에서**.

    큰 라이브러리는 복사에 몇 초가 걸린다. 시작 경로에서 동기로 돌리면 그만큼
    창이 멈춰 보인다(CLAUDE.md 의 시작 성능 규칙).
    """

    done = pyqtSignal(object)   # 만든 경로(str) 또는 None

    def __init__(self, backup) -> None:
        # 부모를 주지 않는다 — 창이 먼저 닫힐 때 실행 중 스레드가 파괴되면
        # Qt가 프로세스를 즉시 종료한다(gui/workers.py).
        super().__init__(None)
        self._backup = backup

    def run(self) -> None:
        made = self._backup.run_daily()
        self.done.emit(str(made) if made else None)
