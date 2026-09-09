"""패널을 파괴한 뒤에도 안전한가 — 실행 중 애니메이션 · 싱글턴 신호 수명 회귀.

여기서 막는 두 가지 결함은 원인이 다르지만 **같은 조사에서 함께 드러났다.**

## 결함 1 — 실행 중 애니메이션을 위젯의 자식으로 두면 프로세스가 죽는다

`LibraryPanel`을 만들고 파괴하면 access violation으로 프로세스가 즉사했다. 원인은
프로젝트가 이미 QThread에 대해 문서화한 것과 **똑같은 구조**다
(`gui/workers.py`: "워커를 위젯의 부모로 매달면, 그 위젯을 지우는 순간 C++가 자식
스레드까지 지운다"):

```python
anim = QVariantAnimation(self)   # 부모 = 패널
anim.valueChanged.connect(_step) # _step 은 위젯을 캡처한 클로저
anim.start()                     # 실행 중
```

패널이 파괴될 때 소멸자가 **실행 중인** 자식 애니메이션을 함께 지운다.
`~QAbstractAnimation`은 암묵적으로 `stop()`을 부르고 그것이 신호를 발화하는데, 그
시점의 수신 슬롯은 이미 파괴 중이라 해제된 메모리를 건드린다.

실측으로 좁힌 과정:

| 조건 | 결과 |
| --- | --- |
| 애니메이션 객체만 만들고 `start()` 안 함 | 정상 |
| 클로저를 연결하고 `start()` 안 함 | 정상 |
| 실행 중 + 파괴 | **크래시** |
| 실행 중 + `destroyed`에서 `stop()` | **크래시**(stop이 신호를 죽어가는 슬롯에 쏜다) |
| 실행 중 + `destroyed`에서 `disconnect()` | **크래시**(그 시점엔 이미 늦다) |
| **부모 없이** 생성 + 실행 중 + 파괴 | **정상** |

해결: `gui/anim.py:track_animation()` — `track_thread()`와 같은 방식으로 부모를 떼고
멈출 때까지 모듈 레지스트리가 붙든다.

## 결함 2 — 싱글턴 신호에 위젯 캡처 람다를 연결하면 죽은 위젯을 건드린다

`LibraryPanel`이 `ThemeManager.instance().theme_changed`에 위젯을 캡처한 람다를
연결하고 있었다. 싱글턴은 앱 수명 내내 살아 있어 패널보다 오래 사는데, 람다는 Qt의
자동 연결 해제 보호를 받지 못한다 — 패널이 파괴된 뒤 테마가 바뀌면 이미 지워진
`_PlaylistTree`를 건드려 터졌다:

```
RuntimeError: wrapped C/C++ object of type _PlaylistTree has been deleted
```

해결: 인자를 받아 버리는 **바운드 메서드**(`_on_theme_changed`)로 연결한다. 수신자가
QObject의 바운드 메서드면 Qt가 그 객체 파괴 시 연결을 끊는다.

## 왜 자식 프로세스인가

access violation은 파이썬 예외가 아니라 **프로세스를 즉사시킨다** — pytest가 일반
실패로 보고할 수 없고 스위트 전체가 중단된다. 그래서 재현을 자식 프로세스에서 돌리고
**종료 코드와 출력**을 본다. 결함 2도 같은 프로세스에서 검사한다 — 싱글턴
`theme_changed`를 실제로 emit해야 하는데, 그러면 다른 테스트가 만든 위젯까지 전부
발화해 실패가 엉뚱한 곳에서 나타난다(`tests/gui/test_theme_transition.py`가 싱글턴을
우회하는 이유가 그것이다).

## `deleteLater()`만으로는 지워지지 않는다

`QApplication.processEvents()`는 **DeferredDelete 이벤트를 처리하지 않는다**(Qt 규약).
`sendPostedEvents(None, QEvent.Type.DeferredDelete)`를 함께 불러야 C++ 객체가 실제로
지워진다. 이걸 몰라 한동안 "C++ 객체가 아직 살아 있는 상태"를 파괴 후라고 착각하며
측정했으므로, 재현 스크립트는 `_DRAIN`으로 그 절차를 고정한다.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_HEAD = """
import faulthandler, gc, sys, traceback
sys.path.insert(0, r"{repo}")
faulthandler.enable()
from PyQt6.QtCore import QEvent
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from PyQt6 import sip
from unittest.mock import MagicMock
import config.settings as settings
settings.save_setting = lambda *a, **k: None
_DD = QEvent.Type.DeferredDelete

def drain():
    # processEvents()는 DeferredDelete 를 처리하지 않는다 — 함께 비워야 실제로 지워진다.
    for _ in range(4):
        app.processEvents()
        app.sendPostedEvents(None, _DD)
    gc.collect()

def _h(rv=None):
    m = MagicMock(); m.handle.return_value = rv if rv is not None else []
    return m

def make_library_vm():
    from gui.view_models.library_vm import LibraryViewModel
    vm = LibraryViewModel(
        get_videos=_h([]), search_videos=_h([]), get_categories=_h([]),
        get_tags=_h([]), add_video=MagicMock(), update_video=MagicMock(),
        delete_video=MagicMock(), mark_watched=MagicMock(),
        create_category=MagicMock(), rename_category=MagicMock(),
        delete_category=MagicMock(), move_category=MagicMock(),
        delete_tag=MagicMock(), assign_category=MagicMock(),
        get_video_detail=_h(None), refresh_metadata=MagicMock(),
        enrich_video=MagicMock(),
    )
    vm.load = lambda *a, **k: None
    return vm
"""


def _run(body: str, *, rounds: int = 6) -> subprocess.CompletedProcess:
    script = _HEAD.format(repo=REPO.as_posix()) + textwrap.dedent(body).format(
        rounds=rounds
    )
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        cwd=REPO,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def _out(result: subprocess.CompletedProcess) -> str:
    return (result.stdout or "") + (result.stderr or "")


def _assert_no_crash(result: subprocess.CompletedProcess, what: str) -> None:
    """자식 프로세스가 살아서 끝났는지.

    마커는 ASCII다 — 자식 출력이 콘솔 코드페이지에서 깨질 수 있어 한글로 판정하면
    통과해야 할 때도 실패한다(실제로 겪었다).
    """
    combined = _out(result)
    assert "access violation" not in combined.lower(), (
        f"{what}에서 access violation이 났다 — 실행 중 애니메이션이 위젯 소멸자와 함께 "
        "파괴되면 해제된 메모리를 건드린다. gui/anim.py의 track_animation()으로 부모를 "
        f"떼고 멈출 때까지 붙들 것.\n--- 자식 출력 ---\n{combined[-2500:]}"
    )
    assert result.returncode == 0, (
        f"{what} 재현이 실패했다 (exit={result.returncode}).\n"
        f"--- 자식 출력 ---\n{combined[-2500:]}"
    )
    assert "HARNESS-OK" in combined, (
        f"{what} 재현 스크립트가 끝까지 돌지 않았다:\n{combined[-2500:]}"
    )


class TestRunningAnimationTeardown:
    """결함 1 — 실행 중 애니메이션이 위젯과 함께 파괴돼도 죽지 않는다."""

    def test_library_panel_create_destroy_loop(self):
        result = _run(
            """
            from gui.panels.library_panel import LibraryPanel

            for i in range({rounds}):
                vm = make_library_vm()
                p = LibraryPanel(vm=vm)
                p.deleteLater()
                drain()
                assert sip.isdeleted(p), "C++-NOT-DELETED"
                del p
                drain()
                vm.shutdown()
            print("HARNESS-OK", flush=True)
            """
        )
        _assert_no_crash(result, "LibraryPanel 생성/파괴 반복")

    def test_panel_dropped_without_delete_later(self):
        """파이썬 참조만 놓아도 안전한가 — GC가 C++ 객체를 지우는 경로.

        `deleteLater()`를 부르지 않고 참조만 버리면 PyQt가 C++ 객체를 파괴한다.
        원래 크래시가 이 경로에서 났다(테스트 종료 시 픽스처가 위젯을 놓는 상황).
        """
        result = _run(
            """
            from gui.panels.library_panel import LibraryPanel

            for i in range({rounds}):
                vm = make_library_vm()
                p = LibraryPanel(vm=vm)
                del p              # deleteLater 없이 참조만 버린다
                drain()
                vm.shutdown()
            print("HARNESS-OK", flush=True)
            """
        )
        _assert_no_crash(result, "LibraryPanel 참조만 버리기")

    def test_panel_is_fully_reclaimed(self):
        """패널이 실제로 회수되는가 — 싱글턴 람다 누수의 최종 확인.

        예전에는 `ThemeManager` 싱글턴이 위젯 캡처 람다를 강한 참조로 붙들어 **패널이
        영영 회수되지 않았다.** 바운드 메서드로 바꾼 뒤에는 회수된다.

        애니메이션이 도는 동안에는 그 `_done` 클로저 하나가 패널을 붙들므로, 멈출
        시간을 준 뒤에 판정한다(`track_animation`이 부모를 떼는 대가다).
        """
        result = _run(
            """
            import time, weakref
            from gui.panels.library_panel import LibraryPanel
            from gui.anim import running_animation_count

            def settle(ms=600):
                end = time.monotonic() + ms / 1000
                while time.monotonic() < end:
                    app.processEvents()
                    app.sendPostedEvents(None, _DD)
                drain()

            for i in range({rounds}):
                vm = make_library_vm()
                p = LibraryPanel(vm=vm)
                wr = weakref.ref(p)
                p.deleteLater()
                del p
                settle()
                assert running_animation_count() == 0, "ANIM-STILL-TRACKED"
                assert wr() is None, "PANEL-WRAPPER-LEAKED"
                vm.shutdown()
            print("HARNESS-OK", flush=True)
            """,
            rounds=3,
        )
        combined = _out(result)
        assert "PANEL-WRAPPER-LEAKED" not in combined, (
            "패널이 회수되지 않았다 — 무언가 `self`를 캡처한 채 패널보다 오래 사는 "
            "곳(싱글턴 신호·레지스트리)에 남아 있다.\n"
            f"--- 자식 출력 ---\n{combined[-2500:]}"
        )
        _assert_no_crash(result, "LibraryPanel 회수")

    def test_fade_in_target_dropped_mid_animation(self):
        """`fade_in`을 걸어 둔 위젯을 애니메이션 도중에 버려도 안전한가.

        `fade_in`은 썸네일이 비동기로 도착할 때마다 불리므로, 목록을 빠르게 넘기면
        애니메이션이 끝나기 전에 카드가 사라지는 일이 실제로 일어난다. 측정 시점에
        이 경로는 크래시하지 않았지만 `_recommend_anim`과 **같은 패턴**이었으므로
        같은 규약(`track_animation`)으로 옮기고 여기서 지킨다.
        """
        result = _run(
            """
            from PyQt6.QtWidgets import QLabel
            from gui.anim import fade_in, running_animation_count

            for i in range({rounds}):
                w = QLabel("x")
                assert fade_in(w), "FADE-NOT-APPLIED"
                assert running_animation_count() > 0, "ANIM-NOT-TRACKED"
                w.deleteLater()
                del w
                drain()
            print("HARNESS-OK", flush=True)
            """
        )
        _assert_no_crash(result, "fade_in 대상 위젯")


class TestThemeSignalAfterDestroy:
    """결함 2 — 패널을 파괴한 뒤 테마가 바뀌어도 죽은 위젯을 건드리지 않는다."""

    def test_theme_change_after_panel_destroyed(self):
        result = _run(
            """
            from gui.panels.library_panel import LibraryPanel
            from gui.themes.manager import ThemeManager
            from gui.themes.tokens import PRESETS

            mgr = ThemeManager.instance()
            vm = make_library_vm()
            p = LibraryPanel(vm=vm)
            p.deleteLater()
            drain()
            assert sip.isdeleted(p), "C++-NOT-DELETED"
            del p
            drain()
            vm.shutdown()

            # 슬롯에서 난 예외는 전파되지 않고 excepthook 으로 간다 — 가로채 본다.
            errors = []
            sys.excepthook = lambda t, v, tb: errors.append(
                "".join(traceback.format_exception(t, v, tb))
            )
            mgr.theme_changed.emit(next(iter(PRESETS.values())))
            app.processEvents()
            if errors:
                print("DEAD-WIDGET-TOUCHED")
                print(errors[0][-900:])
            else:
                print("HARNESS-OK", flush=True)
            """,
            rounds=1,
        )
        combined = _out(result)
        assert "DEAD-WIDGET-TOUCHED" not in combined, (
            "패널을 파괴한 뒤 테마를 바꾸자 죽은 위젯을 건드렸다 — 싱글턴 신호에 "
            "위젯을 캡처한 람다가 남아 있다. 인자를 받아 버리는 바운드 메서드를 두고 "
            f"그것을 연결할 것.\n--- 자식 출력 ---\n{combined[-2500:]}"
        )
        _assert_no_crash(result, "패널 파괴 후 테마 변경")
