"""뷰모델의 QThread 워커 수명 규약 회귀 테스트.

`CLAUDE.md`의 "QThread Lifecycle Management" 규칙은 **워커를 만드는 뷰모델은
`shutdown()`을 제공하고 `MainWindow.closeEvent`에서 호출한다**고 못박고 있다.
실행 중인 QThread가 파괴되면 Qt가 프로세스를 즉시 종료하기 때문이다
(`gui/workers.py` 문서 — 실측 `exit 0xC0000409`).

그런데 실제로는 `clip_vm`·`monitoring_vm`·`playlist_vm` 세 뷰모델이 워커를 7개나
띄우면서 `shutdown()`이 없었고, `MainWindow.closeEvent`의 정리 목록에도 빠져 있었다.
재생목록 가져오기·YouTube 푸시·클립 추출이 도는 중에 창을 닫으면 그대로 파괴
조건이었다. 규칙이 문서에만 있어서 새 뷰모델을 추가할 때마다 조용히 재발할 수 있는
구조였으므로, 여기서 **코드로** 고정한다.

세 가지를 지킨다:

1. `gui/view_models/`에서 QThread 워커를 선언하는 모듈은 그 뷰모델 클래스에
   `shutdown()`을 노출한다 — 새 뷰모델을 추가하면 이 테스트가 먼저 깨진다.
2. 워커를 만드는 뷰모델은 `gui.workers.track_thread`로도 등록한다 — 자체
   `_workers` 리스트만으로는 앱 종료 시 `wait_all()`이 기다려 주지 못한다
   (`CLAUDE.md`가 `_ThumbBgLoader` 사례로 명시한 구멍과 같다).
3. `shutdown_all()`은 소유자가 들고 있는 뷰모델을 **빠짐없이** 훑는다 — 손으로
   적은 목록은 새 뷰모델이 추가될 때 갱신을 잊는다(실제로 세 개를 잊었다).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

VM_DIR = Path(__file__).resolve().parents[2] / "gui" / "view_models"


def _vm_modules() -> list[Path]:
    return sorted(p for p in VM_DIR.glob("*_vm.py"))


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _base_names(node: ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for base in node.bases:
        if isinstance(base, ast.Name):
            names.add(base.id)
        elif isinstance(base, ast.Attribute):
            names.add(base.attr)
    return names


def _worker_classes(tree: ast.Module) -> list[str]:
    return [
        n.name
        for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and "QThread" in _base_names(n)
    ]


def _viewmodel_classes(tree: ast.Module) -> list[ast.ClassDef]:
    return [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and n.name.endswith("ViewModel")
    ]


def _method_names(node: ast.ClassDef) -> set[str]:
    return {
        n.name
        for n in node.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


WORKER_MODULES = [p for p in _vm_modules() if _worker_classes(_parse(p))]


class TestShutdownContract:
    """워커를 띄우는 뷰모델은 반드시 shutdown()을 노출한다."""

    def test_worker_modules_found(self):
        """스캐너가 실제로 뭔가 찾았는지 — 0건이면 아래 테스트가 공허하게 통과한다."""
        assert WORKER_MODULES, "gui/view_models/에서 QThread 워커를 하나도 못 찾았다"

    @pytest.mark.parametrize("path", WORKER_MODULES, ids=lambda p: p.name)
    def test_viewmodel_exposes_shutdown(self, path: Path):
        """직접 정의하거나 `WorkerOwnerMixin`에서 물려받으면 된다.

        믹스인을 섞는 쪽이 권장 경로다 — 그러면 `track_thread` 등록과 대기 규칙이
        한곳에만 있어 뷰모델마다 어긋날 여지가 없다.
        """
        tree = _parse(path)
        workers = _worker_classes(tree)
        vms = _viewmodel_classes(tree)
        assert vms, f"{path.name}은 워커 {workers}를 선언하는데 뷰모델 클래스가 없다"
        for vm in vms:
            has_own = "shutdown" in _method_names(vm)
            inherits = "WorkerOwnerMixin" in _base_names(vm)
            assert has_own or inherits, (
                f"{path.name}의 {vm.name}이 워커 {workers}를 띄우는데 shutdown()이 없다 — "
                "앱 종료 시 실행 중 QThread가 파괴되어 프로세스가 죽는다. "
                "WorkerOwnerMixin을 섞거나 shutdown()을 직접 정의할 것."
            )


def _imports_track_thread(tree: ast.Module) -> bool:
    """`gui.workers.track_thread`를 실제로 임포트하는가 (주석·문자열은 세지 않는다)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "gui.workers":
            if any(a.name == "track_thread" for a in node.names):
                return True
    return False


class TestTrackThreadContract:
    """자체 리스트만으로는 `wait_all()`이 기다려 주지 못한다.

    **소스에 `track_thread`라는 글자가 있는지 보지 않는다** — 그렇게 검사했더니
    "붙드는 일은 track_thread가 한다"는 **주석** 때문에 등록하지 않는 모듈이
    통과했다. 실제 계약은 "믹스인을 섞었거나 직접 임포트해 부른다"이므로 AST로
    확인한다.
    """

    @pytest.mark.parametrize("path", WORKER_MODULES, ids=lambda p: p.name)
    def test_viewmodel_registers_with_track_thread(self, path: Path):
        tree = _parse(path)
        via_mixin = any(
            "WorkerOwnerMixin" in _base_names(vm) for vm in _viewmodel_classes(tree)
        )
        assert via_mixin or _imports_track_thread(tree), (
            f"{path.name}이 워커를 만들면서 전역 레지스트리에 등록하지 않는다 — "
            "앱 종료 시 wait_all()이 이 워커를 기다리지 못해, 실행 중 QThread가 "
            "파괴되며 프로세스가 죽는다. WorkerOwnerMixin을 섞을 것."
        )


class TestShutdownAllDiscovery:
    """정리 대상을 손으로 적지 않고 발견한다."""

    def test_discovers_every_viewmodel_attribute(self):
        from gui.view_models.base import shutdown_all

        calls: list[str] = []

        class _Stub:
            def __init__(self, tag: str) -> None:
                self._tag = tag

            def shutdown(self) -> None:
                calls.append(self._tag)

        class _Owner:
            def __init__(self) -> None:
                self._library_vm = _Stub("library")
                self._clip_vm = _Stub("clip")
                self._monitoring_vm = _Stub("monitoring")
                self._playlist_vm = _Stub("playlist")
                self._update_controller = _Stub("updater")
                self._not_a_vm = object()      # shutdown 없음 — 건너뛴다
                self._absent_vm = None         # None — 건너뛴다

        shutdown_all(_Owner())

        assert sorted(calls) == [
            "clip",
            "library",
            "monitoring",
            "playlist",
            "updater",
        ]

    def test_one_failure_does_not_stop_the_rest(self):
        """한 뷰모델이 터져도 나머지는 정리돼야 한다 — 종료 경로다."""
        from gui.view_models.base import shutdown_all

        calls: list[str] = []

        class _Boom:
            def shutdown(self) -> None:
                raise RuntimeError("의도된 실패")

        class _Ok:
            def shutdown(self) -> None:
                calls.append("ok")

        class _Owner:
            def __init__(self) -> None:
                self._boom_vm = _Boom()
                self._ok_vm = _Ok()

        shutdown_all(_Owner())
        assert calls == ["ok"]
