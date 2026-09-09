"""뷰모델이 공유하는 QThread 워커 수명 관리.

`gui/workers.py`는 "실행 중인 워커를 누가 붙들 것인가"를 해결하는 **전역
레지스트리**다. 이 파일은 그 위에 **뷰모델 쪽 관례**를 얹는다 — 워커를 하나
띄우고, 끝나면 놓아 주고, 앱이 닫힐 때 남은 것을 기다리는 그 세 가지가 뷰모델
11개에 각각 손으로 적혀 있었고, 그 과정에서 세 개(`clip`·`monitoring`·`playlist`)가
`shutdown()`을 아예 빼먹었다. 규약을 문서가 아니라 코드로 들고 있어야 새 뷰모델을
추가할 때 자동으로 지켜진다.

## 왜 리스트만으로는 부족한가

뷰모델들은 원래 `self._workers` 리스트로만 워커를 붙들었다. GC는 막아 주지만
`MainWindow.closeEvent`의 `wait_all()`은 **전역 레지스트리만** 안다 — 리스트에만
담긴 워커는 기다려지지 않는다. `CLAUDE.md`가 `_ThumbBgLoader` 사례로 지적한
구멍과 똑같다. 그래서 `_adopt_worker`는 **둘 다** 한다: `track_thread`로 전역
등록하고, 종료 시 기다릴 대상을 알기 위해 믹스인 자신의 목록에도 담는다.

## 왜 `sender()`인가

끝난 워커를 목록에서 빼려면 어느 워커가 끝났는지 알아야 하는데, 람다로 워커를
캡처하면 Qt의 자동 연결 해제 보호를 못 받는다(`gui/workers.py` 문서). 대신
**바운드 메서드 + `sender()`**로 받는다 — 뷰모델이 사라지면 Qt가 연결을 끊고,
살아 있으면 `sender()`가 신호를 보낸 그 워커를 정확히 준다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QThread, pyqtSignal

from gui.workers import retire_thread, track_thread

logger = logging.getLogger(__name__)

# 종료 시 워커 하나를 기다리는 기본 시간. 기존 뷰모델들이 쓰던 값과 같다.
DEFAULT_SHUTDOWN_WAIT_MS = 3000


class CallWorker(QThread):
    """호출 하나를 백그라운드로 실행하고 결과를 신호로 보낸다.

    뷰모델의 워커 대부분은 "핸들러 하나를 부르고 결과나 오류를 알린다"가 전부인데,
    그 형태가 클래스로 40번 가까이 반복돼 있었다(`transfer_vm._CommandWorker`가
    이미 일반화된 형태였지만 다른 곳에서 재사용되지 않았다).

    `fn`은 **인자 없이 부를 수 있는 것**이어야 한다 — 호출부에서 `functools.partial`
    이나 람다로 인자를 미리 묶는다. 워커가 인자 시그니처를 몰라야 어떤 핸들러에도
    붙는다.

    `context`는 결과와 함께 되돌려 받고 싶은 값이다(예: `append` 플래그, 대상
    video_id). 늦게 도착한 결과를 버릴지 판단할 근거를 호출부가 잃지 않게 한다.
    """

    done = pyqtSignal(object, object)     # (결과, context)
    failed = pyqtSignal(str, object)      # (오류 메시지, context)

    def __init__(
        self,
        fn: Callable[[], Any],
        context: Any = None,
        *,
        error_label: str = "백그라운드 작업 실패",
    ) -> None:
        # 부모를 주지 않는다 — 소유자가 사라질 때 실행 중 스레드가 파괴되는 것을
        # 막는 것이 track_thread의 전제다(gui/workers.py).
        super().__init__(None)
        self._fn = fn
        self._context = context
        self._error_label = error_label

    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:
            # 조용히 삼키지 않는다 — 폴백 경로의 흔적을 남기는 것이 프로젝트 규칙이다.
            logger.exception("%s", self._error_label)
            self.failed.emit(str(exc), self._context)
        else:
            self.done.emit(result, self._context)


class WorkerOwnerMixin:
    """워커를 띄우는 뷰모델에 수명 관리를 얹는다.

    `QObject`(보통 뷰모델)와 함께 상속한다. 상태는 첫 사용 시 스스로 만들기 때문에
    기존 뷰모델의 `__init__`을 건드리지 않고도 섞을 수 있다.

    ## 뷰모델의 자체 기록을 건드리지 않는다

    믹스인은 `_tracked_workers`라는 **자기 이름**으로만 기록한다. 뷰모델들은 이미
    취소·중복 판정·큐 관리를 위해 각자 자료구조를 갖고 있고(그 형태도 다르다 —
    `download_vm`은 job_id → 워커 `dict`, `feed_vm`은 동시 실행 상한이 걸린
    리스트), 그것들이 하는 일은 수명 관리와 별개다. 그래서 통합의 방식은 "각
    뷰모델의 기록을 하나로 합치기"가 아니라 **수명 관리만 걷어 올리기**다 —
    호출부는 워커를 만든 뒤 `_adopt_worker(worker)` 한 줄만 더하면 된다.
    """

    @property
    def _tracked_workers(self) -> list[QThread]:
        # `__init__`에서 초기화하지 않는다 — 기존 뷰모델 11개의 생성자를 모두 고치지
        # 않고 섞을 수 있어야 한다(super() 호출 순서 사고를 피한다).
        workers = getattr(self, "_tracked_workers_list", None)
        if workers is None:
            workers = []
            self._tracked_workers_list = workers
        return workers

    @property
    def tracked_workers(self) -> tuple[QThread, ...]:
        """현재 붙들고 있는 워커 (읽기 전용 — 진단·테스트용).

        테스트가 "워커가 끝나기를 기다린다"를 하려면 대상 목록을 알아야 하는데,
        예전에는 뷰모델마다 다른 사설 이름(`_workers`·`_list_workers`·
        `_enrich_workers`…)을 직접 들여다봤다. 이름이 바뀌면 테스트가 깨지고,
        테스트를 고치려면 어느 이름이 맞는지 매번 찾아야 했다. 공개 이름 하나로
        고정한다.
        """
        return tuple(self._tracked_workers)

    def wait_for_workers(self, msec: int = DEFAULT_SHUTDOWN_WAIT_MS) -> None:
        """붙들고 있는 워커가 끝나기를 기다린다(목록은 비우지 않는다).

        `shutdown()`은 종료 경로라 목록까지 비우지만, 테스트는 "이번 작업이 끝났나"만
        확인하고 뷰모델을 계속 쓰는 경우가 많아 둘을 나눠 둔다.
        """
        for worker in list(self._tracked_workers):
            try:
                if worker.isRunning():
                    worker.wait(msec)
            except RuntimeError:
                pass

    def _adopt_worker(self, worker: QThread) -> QThread:
        """워커를 붙들고 끝나면 스스로 놓게 한다. **시작 전에** 부른다.

        전역 레지스트리(`track_thread`)와 믹스인 자신의 목록 **양쪽**에 등록한다 —
        전자는 소유자가 사라져도 워커가 파괴되지 않게, 후자는 `shutdown()`이
        기다릴 대상을 알기 위해 필요하다.
        """
        track_thread(worker)
        self._tracked_workers.append(worker)
        worker.finished.connect(self._on_worker_finished)
        return worker

    def _start_worker(self, worker: QThread) -> QThread:
        """붙든 뒤 시작한다 — `_adopt_worker()` + `start()`.

        순서가 중요하다: `start()`를 먼저 부르면 아주 짧은 작업이 등록 전에 끝나
        `finished`를 놓칠 수 있다. 호출부가 그 순서를 매번 기억하지 않도록 묶어 둔다.
        """
        self._adopt_worker(worker)
        worker.start()
        return worker

    def _on_worker_finished(self) -> None:
        """끝난 워커를 목록에서 뺀다 (바운드 메서드 + sender — 람다 캡처 금지)."""
        sender = getattr(self, "sender", None)
        worker = sender() if callable(sender) else None
        if worker is None:
            return
        try:
            self._tracked_workers.remove(worker)
        except ValueError:
            pass   # 이미 빠졌다(취소 경로 등) — 정상

    def _retire_worker(self, worker: QThread | None, *signal_names: str) -> None:
        """결과 신호를 끊고 놓아 준다(실행 중이면 전역 레지스트리가 계속 붙든다)."""
        if worker is None:
            return
        retire_thread(worker, *signal_names)
        try:
            self._tracked_workers.remove(worker)
        except ValueError:
            pass

    def shutdown(self) -> None:
        """종료 시 남은 워커가 끝나기를 기다린다 (`MainWindow.closeEvent`에서 호출).

        `wait()`만 하고 `deleteLater()`는 부르지 않는다 — 끝난 워커를 지우면 아직
        참조를 들고 있는 쪽에서 `RuntimeError`가 난다(`gui/workers.py` 문서).
        """
        for worker in list(self._tracked_workers):
            try:
                if worker.isRunning():
                    worker.wait(DEFAULT_SHUTDOWN_WAIT_MS)
            except RuntimeError:
                pass   # 이미 정리된 워커 — 할 일이 없다
        self._tracked_workers.clear()


def shutdown_all(owner: object) -> None:
    """`owner`가 들고 있는 모든 뷰모델의 `shutdown()`을 부른다.

    **목록을 손으로 적지 않는다.** `MainWindow.closeEvent`에는 정리 대상 뷰모델이
    직접 나열돼 있었고, 그 목록에서 `clip`·`monitoring`·`playlist` 세 개가 빠져
    있었다 — 뷰모델을 추가할 때 이 목록 갱신을 잊는 것이 기본값이기 때문이다.
    대신 `shutdown()`을 가진 속성을 발견해서 훑는다.

    하나가 터져도 나머지를 계속 정리한다 — 종료 경로에서 정리를 중단하면 남은
    워커가 파괴되며 프로세스가 죽는다.
    """
    for name, value in list(vars(owner).items()):
        if value is None:
            continue
        shutdown = getattr(value, "shutdown", None)
        if not callable(shutdown):
            continue
        try:
            shutdown()
        except Exception:
            logger.exception("%s.shutdown() 실패 — 나머지 정리를 계속한다", name)
