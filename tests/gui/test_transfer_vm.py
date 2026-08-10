"""LibraryTransferViewModel — 워커 스레드 배선 검증(핸들러는 목으로 대체)."""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from PyQt6.QtWidgets import QApplication

from gui.view_models.transfer_vm import LibraryTransferViewModel


def _vm(**overrides) -> LibraryTransferViewModel:
    kwargs = dict(
        export_handler=MagicMock(),
        preview_handler=MagicMock(),
        conflicts_handler=MagicMock(),
        import_handler=MagicMock(),
    )
    kwargs.update(overrides)
    return LibraryTransferViewModel(**kwargs)


def _wait_worker(vm: LibraryTransferViewModel, timeout_ms: int = 3000) -> None:
    for worker in list(vm._workers):
        worker.wait(timeout_ms)
    # 워커 스레드→메인 스레드 신호는 큐드 커넥션이라 이벤트 루프를 돌려야 전달된다.
    for _ in range(10):
        QApplication.processEvents()


class TestExport:
    def test_내보내기_핸들러에_명령을_넘기고_완료_신호를_낸다(self, qapp_instance):
        handler = MagicMock()
        handler.handle.return_value = "RESULT"
        vm = _vm(export_handler=handler)
        seen = []
        vm.export_finished.connect(seen.append)

        cat_id = uuid4()
        vm.export_library([cat_id], "out.zip")
        _wait_worker(vm)

        cmd = handler.handle.call_args[0][0]
        assert cmd.category_ids == [cat_id]
        assert cmd.dest_path == "out.zip"
        assert seen == ["RESULT"]

    def test_실패하면_error_occurred로_보고된다(self, qapp_instance):
        handler = MagicMock()
        handler.handle.side_effect = RuntimeError("실패했음")
        vm = _vm(export_handler=handler)
        seen = []
        vm.error_occurred.connect(seen.append)

        vm.export_library([], "out.zip")
        _wait_worker(vm)

        assert seen and "실패했음" in seen[0]

    def test_busy_changed가_시작과_종료에_방출된다(self, qapp_instance):
        handler = MagicMock()
        handler.handle.return_value = "R"
        vm = _vm(export_handler=handler)
        seen = []
        vm.busy_changed.connect(seen.append)

        vm.export_library([], "out.zip")
        _wait_worker(vm)

        assert seen == [True, False]


class TestPreviewAndConflictsAndImport:
    def test_미리보기_핸들러_호출(self, qapp_instance):
        handler = MagicMock()
        handler.handle.return_value = "PREVIEW"
        vm = _vm(preview_handler=handler)
        seen = []
        vm.preview_ready.connect(seen.append)

        vm.preview_import("pkg.zip")
        _wait_worker(vm)

        assert handler.handle.call_args[0][0].archive_path == "pkg.zip"
        assert seen == ["PREVIEW"]

    def test_충돌감지_핸들러_호출(self, qapp_instance):
        handler = MagicMock()
        handler.handle.return_value = "CONFLICTS"
        vm = _vm(conflicts_handler=handler)
        seen = []
        vm.conflicts_ready.connect(seen.append)

        vm.detect_conflicts("pkg.zip", ["c1", "c2"])
        _wait_worker(vm)

        cmd = handler.handle.call_args[0][0]
        assert cmd.archive_path == "pkg.zip"
        assert cmd.category_ids == ["c1", "c2"]
        assert seen == ["CONFLICTS"]

    def test_가져오기_핸들러_호출(self, qapp_instance):
        handler = MagicMock()
        handler.handle.return_value = "IMPORTED"
        vm = _vm(import_handler=handler)
        seen = []
        vm.import_finished.connect(seen.append)

        resolutions = {"url": {"title": "incoming"}}
        vm.import_library("pkg.zip", ["c1"], resolutions)
        _wait_worker(vm)

        cmd = handler.handle.call_args[0][0]
        assert cmd.archive_path == "pkg.zip"
        assert cmd.category_ids == ["c1"]
        assert cmd.resolutions == resolutions
        assert seen == ["IMPORTED"]


class TestShutdown:
    def test_shutdown이_예외없이_동작한다(self, qapp_instance):
        vm = _vm()
        vm.shutdown()   # 워커가 없어도 안전
