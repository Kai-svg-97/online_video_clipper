"""업데이트 체크 워커 수명 및 다이얼로그 표시를 관리하는 컨트롤러."""
from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QMessageBox

from application.updater.commands import DownloadUpdateHandler
from application.updater.dtos import UpdateDTO
from application.updater.queries import CheckForUpdateHandler
from domain.shared.ports import UpdateInfo
from gui.updater.pending import pending_marker_path, write_pending_update
from gui.updater.update_checker_worker import UpdateCheckWorker, UpdateDownloadWorker
from gui.updater.update_dialog import UpdateDialog

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SEC = 3_600  # 1시간


class UpdateController(QObject):
    """업데이트 확인·자동 다운로드·설치 트리거를 담당. MainWindow가 소유하며 shutdown()으로 정리."""

    update_notification = pyqtSignal(object)   # UpdateDTO — 새 버전을 찾았지만 아직 준비 안 됨
    update_ready = pyqtSignal(object)          # UpdateDTO — 다운로드 완료(누르면 설치)
    check_started = pyqtSignal()               # 확인 시작 — 설정 화면 상태 표시용
    check_finished = pyqtSignal()              # 확인/다운로드 종료(성공·실패 무관)
    download_progress = pyqtSignal(int, int)   # (받은 바이트, 전체 바이트) — 배지 채움
    download_failed = pyqtSignal(str)          # 사유 — 배지가 이유를 보여 주고 재시도를 받는다
    install_started = pyqtSignal()             # 설치 착수 — 곧 앱이 닫힌다

    def __init__(
        self,
        check_handler: CheckForUpdateHandler,
        download_handler: DownloadUpdateHandler,
        parent_window,
    ) -> None:
        super().__init__(parent_window)
        self._check_handler = check_handler
        self._download_handler = download_handler
        self._parent_window = parent_window
        self._worker: UpdateCheckWorker | None = None
        self._dl_worker: UpdateDownloadWorker | None = None
        self._downloaded_version: str | None = None   # 세션 중 중복 다운로드 방지
        self._last_dto: UpdateDTO | None = None
        self._last_info: UpdateInfo | None = None
        self._dl_dto: UpdateDTO | None = None   # 지금 받고 있는 대상
        self._installing = False                # 설치 착수 후에는 아무것도 새로 시작하지 않는다
        # "나중에"는 현재 세션만 억제 — 시작 시 스누즈를 초기화한다
        try:
            from config import settings as s  # noqa: PLC0415
            if getattr(s, "SNOOZED_UPDATE_VERSION", ""):
                s.save_setting("snoozed_update_version", "")
        except Exception:
            logger.exception("snoozed_update_version 초기화 실패")

    # ------------------------------------------------------------------
    def check_silently(self) -> None:
        """시작 시 조용히 확인. 새 버전 있을 때만 다이얼로그 표시."""
        if not self._should_check():
            return
        self._run_check(interactive=False)

    def check_interactively(self) -> None:
        """설정 버튼에서 호출 — '최신 버전입니다'도 표시."""
        self._run_check(interactive=True)

    def shutdown(self) -> None:
        for w in (self._worker, self._dl_worker):
            if w and w.isRunning():
                w.terminate()
                w.wait(3000)

    # ------------------------------------------------------------------
    def _should_check(self) -> bool:
        """AUTO_UPDATE_CHECK 설정이 켜져 있고, 마지막 확인 후 1시간이 지났는지 확인."""
        try:
            from config import settings as s  # noqa: PLC0415
            if not getattr(s, "AUTO_UPDATE_CHECK", True):
                return False
            last = getattr(s, "LAST_UPDATE_CHECK", 0) or 0
            return (time.time() - float(last)) >= _CHECK_INTERVAL_SEC
        except Exception:
            logger.exception("업데이트 체크 조건 확인 실패")
            return True

    @staticmethod
    def _mark_checked() -> None:
        """자동 확인 인터벌(1시간)을 소진 처리한다.

        **성공적으로 끝난 경우에만** 호출한다. 예전에는 확인을 시작하자마자 기록해,
        다운로드가 실패해도 다음 1시간 동안 재시도가 막혔다 — 앱을 다시 켜도 배지조차
        뜨지 않아 사용자가 업데이트할 방법이 없었다.
        """
        try:
            from config import settings as s  # noqa: PLC0415
            s.save_setting("last_update_check", time.time())
        except Exception:
            logger.exception("last_update_check 저장 실패")

    def _run_check(self, *, interactive: bool) -> None:
        if self._worker and self._worker.isRunning():
            return
        # 받는 중이거나 이미 설치에 들어갔으면 새 확인을 시작하지 않는다.
        # 예전에는 확인 워커만 봐서, 다운로드 도중 1시간 타이머가 돌면 같은 버전을
        # 다시 찾아 배지 상태를 진행률에서 '발견'으로 되돌렸다.
        if self._installing:
            return
        if self._dl_worker and self._dl_worker.isRunning():
            return

        self.check_started.emit()
        self._worker = UpdateCheckWorker(self._check_handler, self)
        self._worker.found.connect(
            lambda dto: self._on_found(dto, interactive=interactive)
        )
        self._worker.none_found.connect(
            lambda: self._on_none_found(interactive=interactive)
        )
        self._worker.failed.connect(
            lambda msg: self._on_failed(msg, interactive=interactive)
        )
        self._worker.start()

    def _on_found(self, dto: UpdateDTO, *, interactive: bool) -> None:
        if not interactive:
            try:
                from config import settings as s  # noqa: PLC0415
                if dto.version == getattr(s, "SNOOZED_UPDATE_VERSION", ""):
                    self._mark_checked()
                    self.check_finished.emit()
                    return
            except Exception:
                logger.exception("snoozed_update_version 확인 실패")

        self._last_dto = dto
        self._last_info = UpdateInfo(
            version=dto.version,
            asset_name=dto.asset_name,
            download_url=dto.download_url,
            size_bytes=dto.size_bytes,
            sha256=dto.sha256,
            release_notes=dto.release_notes,
        )

        self.check_finished.emit()
        if interactive:
            self._show_update_dialog(dto)
            return

        # **여기서 받지 않는다.** 사용자가 배지를 눌러야 받기 시작한다 — 그래야
        # 진행률 연출이 보이고, 원치 않는 사람의 회선·디스크를 쓰지 않는다.
        #
        # 그리고 `_mark_checked()`를 부르지 **않는다.** 발견은 종결된 결과가 아니다.
        # 여기서 1시간 인터벌을 소진하면, 앱을 껐다 켰을 때 확인을 건너뛰어 배지가
        # 뜨지 않고 사용자는 업데이트할 방법을 잃는다(예전에 실제로 그랬다).
        self.update_notification.emit(dto)

    # ------------------------------------------------------------------
    def start_download(self, *_args) -> None:
        """배지·설정 헤더가 공유하는 다운로드 진입점.

        인자를 받아 버리는 이유는 시그널마다 실어 보내는 것이 다르기 때문이다
        (설정 헤더는 DTO를 싣고, 배지는 아무것도 싣지 않는다). 대상은 어차피
        마지막으로 찾은 버전 하나뿐이라 인자를 볼 필요가 없다.
        """
        if self._last_dto is not None:
            self._start_download(self._last_dto)

    def _start_download(self, dto: UpdateDTO) -> None:
        if self._downloaded_version == dto.version:
            self.update_ready.emit(dto)   # 이미 이 버전 준비됨
            return
        if self._dl_worker and self._dl_worker.isRunning():
            return
        if self._last_info is None:
            return
        self._dl_dto = dto
        dest_dir = Path(tempfile.mkdtemp(prefix="ovc_update_"))
        self._dl_worker = UpdateDownloadWorker(
            self._download_handler, self._last_info, dest_dir, self
        )
        # 바운드 메서드로 연결한다 — 워커 신호에 람다를 매다는 것은 이 저장소가
        # 금지한 형태다(수신자가 사라져도 Qt가 끊어 주지 못한다).
        self._dl_worker.progress.connect(self._on_download_progress)
        self._dl_worker.done.connect(self._on_worker_done)
        self._dl_worker.failed.connect(self._on_worker_failed)
        self._dl_worker.start()

    def _on_download_progress(self, downloaded: int, total: int) -> None:
        self.download_progress.emit(downloaded, total)

    def _on_worker_done(self, installer_path: str) -> None:
        self._on_download_done(installer_path, self._dl_dto)

    def _on_worker_failed(self, msg: str) -> None:
        self._on_download_failed(msg, self._dl_dto)

    def _on_download_done(self, installer_path: str, dto: UpdateDTO) -> None:
        self._downloaded_version = dto.version
        self._mark_checked()
        self.check_finished.emit()
        if write_pending_update(installer_path):
            # 앱 종료 시 main.py tail이 설치. 지금은 준비 완료만 알림.
            self.update_ready.emit(dto)
        else:
            # 비win32 등 마커 미기록 — 수동 알림으로 폴백.
            self.update_notification.emit(dto)

    def _on_download_failed(self, msg: str, dto: UpdateDTO | None) -> None:
        # 인터벌을 소진하지 않는다 — 다음 실행에서 곧바로 다시 시도할 수 있어야 한다.
        logger.warning("업데이트 다운로드 실패: %s", msg)
        self.check_finished.emit()
        self.download_failed.emit(msg)       # 배지가 이유를 보여 주고 재시도를 받는다
        if dto is not None:
            self.update_notification.emit(dto)   # 설정 헤더에 설치 버튼

    def install_now(self, *_args) -> None:
        """'지금 설치' — 앱을 종료하면 종료 tail이 설치하고 새 버전을 띄운다.

        설치 착수를 **먼저 알린다.** 말없이 창이 닫히면 사용자는 앱이 죽은 줄 안다.
        """
        if pending_marker_path().exists():
            self._installing = True
            self.install_started.emit()
            QApplication.instance().quit()
        elif self._last_dto is not None:
            # 마커 없음 — 아직 받지 않았다면 지금 받는다.
            self._start_download(self._last_dto)

    def _show_update_dialog(self, dto: UpdateDTO) -> None:
        dlg = UpdateDialog(
            dto=dto,
            info=self._last_info,
            download_handler=self._download_handler,
            parent=self._parent_window,
        )
        dlg.exec()

    def _on_none_found(self, *, interactive: bool) -> None:
        self._mark_checked()
        self.check_finished.emit()
        if interactive:
            QMessageBox.information(
                self._parent_window,
                "업데이트 확인",
                "현재 최신 버전을 사용 중입니다.",
            )

    def _on_failed(self, msg: str, *, interactive: bool) -> None:
        # 확인 자체가 실패했으면 인터벌을 소진하지 않는다(다음 실행에서 재시도).
        logger.warning("업데이트 확인 실패: %s", msg)
        self.check_finished.emit()
        if interactive:
            QMessageBox.warning(
                self._parent_window,
                "업데이트 확인 실패",
                f"업데이트를 확인하지 못했습니다.\n\n{msg}",
            )
