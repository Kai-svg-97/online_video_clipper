"""실행 중인 QThread를 안전하게 붙들고 놓아 주는 공용 도우미.

**Qt는 실행 중인 QThread가 파괴되면 프로세스를 즉시 종료한다**
(`QThread: Destroyed while thread '' is still running` → abort). 파이썬에서 이 조건은
아주 쉽게 만들어진다:

* 워커를 위젯의 **부모로 매달면**, 그 위젯을 지우는 순간 C++가 자식 스레드까지 지운다.
  카드 그리드를 다시 채우거나 상세를 닫는 것만으로 실행 중인 썸네일 로더가 파괴된다.
* 부모가 없어도 **위젯 속성 하나로만 붙들고 있으면**, 위젯이 GC될 때 참조가 사라져
  같은 일이 벌어진다.
* `quit()` + `deleteLater()`도 안전하지 않다 — `quit()`은 그 스레드의 **이벤트 루프**만
  끝내므로, 네트워크 요청 같은 블로킹 작업을 도는 `run()`은 계속 실행된다. 이후 이벤트
  루프가 객체를 삭제하면 그대로 파괴 조건이다.

실제로 스트림 URL을 받는 도중 뒤로가기를 누르면 앱이 통째로 꺼지는 증상이 있었다.
그래서 워커는 **부모 없이 만들고**, 여기 레지스트리가 끝날 때까지 강한 참조로 붙든 뒤
`finished`에서 놓아 준다. 소유 위젯이 먼저 사라져도 스레드는 자기 일을 마치고 조용히
정리된다.

슬롯은 **QObject의 바운드 메서드**로 연결할 것 — 수신 객체가 사라지면 Qt가 연결을
자동으로 끊는다. 람다로 위젯을 캡처하면 그 보호를 못 받아 죽은 위젯을 건드린다.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import QThread

logger = logging.getLogger(__name__)

# 실행 중인 워커의 강한 참조. 끝나면 스스로 빠진다.
_RUNNING: set[QThread] = set()


def track_thread(thread: QThread) -> QThread:
    """워커가 끝날 때까지 붙든다(소유 위젯이 사라져도 파괴되지 않게).

    부모가 있으면 떼어 낸다 — 부모 위젯이 지워질 때 함께 파괴되는 것을 막는다.
    """
    if thread in _RUNNING:
        return thread
    try:
        if thread.parent() is not None:
            thread.setParent(None)
    except RuntimeError:
        return thread   # 이미 정리된 워커
    _RUNNING.add(thread)
    thread.finished.connect(lambda t=thread: _release(t))
    return thread


def _release(thread: QThread) -> None:
    """레지스트리에서 놓는다 — **deleteLater는 부르지 않는다.**

    끝난 워커를 `deleteLater`로 지우면 C++ 객체가 사라지는데, 아직 그 워커를 들고 있는
    쪽(예: 플레이어의 `self._worker`)이 나중에 접근하면
    ``RuntimeError: wrapped C/C++ object ... has been deleted``가 난다 — 실제로 재생 중
    뒤로가기에서 그 오류가 났다. 참조만 놓으면 마지막 참조가 사라질 때 파이썬이
    정리하며, 그때 스레드는 이미 끝나 있어 안전하다.
    """
    _RUNNING.discard(thread)


def retire_thread(thread: QThread | None, *signal_names: str) -> None:
    """워커를 놓아 준다 — 결과 신호를 끊고, 실행 중이면 끝날 때까지 붙든다.

    신호는 **객체가 아니라 이름**으로 받는다. 호출부에서 ``worker.finished_ok``처럼
    꺼내려는 순간 이미 정리된 객체면 거기서 RuntimeError가 나기 때문에, 접근 자체를
    이 안에서 감싼다(호출부는 워커의 생사를 몰라도 된다).
    """
    if thread is None:
        return
    for name in signal_names:
        try:
            getattr(thread, name).disconnect()
        except (TypeError, RuntimeError, AttributeError):
            logger.debug("워커 신호 %s가 이미 해제됨 — 무시", name)
    try:
        running = thread.isRunning()
    except RuntimeError:
        return   # 이미 정리된 워커 — 할 일이 없다
    if running:
        track_thread(thread)


def running_count() -> int:
    """레지스트리에 남아 있는 워커 수(테스트·진단용)."""
    return len(_RUNNING)


def wait_all(msec: int = 3000) -> None:
    """남은 워커가 끝나기를 기다린다(앱 종료 시 마지막 정리용)."""
    for thread in list(_RUNNING):
        if thread.isRunning():
            thread.wait(msec)
