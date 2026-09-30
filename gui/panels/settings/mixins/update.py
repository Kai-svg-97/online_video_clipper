"""UpdateHeaderMixin — 헤더 우측 업데이트 상태 — 자동 확인 토글·확인·설치 버튼과 공개 set_update_* API.

    SettingsPanel에 섞여 들어가는 mixin이라 패널 상태(`self._auth`·`self._subtitle_vm`
    같은 주입값, 다른 섹션의 위젯)를 그대로 쓴다(런타임 클래스는 하나다).
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from gui.panels.settings.helpers import _t
from gui.text import tr
from gui.themes.colors import sem
from version import __version__

logger = logging.getLogger(__name__)


class UpdateHeaderMixin:
    """헤더 우측 업데이트 상태 — 자동 확인 토글·확인·설치 버튼과 공개 set_update_* API."""

    def _build_update_header(self) -> QWidget:
        """헤더 우측 컴팩트 업데이트 위젯 — 자동확인 토글 + 상태 + (준비 시)설치 버튼."""
        try:
            from config import settings as s  # noqa: PLC0415
            cur_auto = s.AUTO_UPDATE_CHECK
        except Exception:
            logger.exception("업데이트 설정 로드 실패")
            cur_auto = True
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self._auto_update_check = QCheckBox(tr("자동 업데이트"))
        # 확인만 자동이고 **받는 것은 누를 때**다 — 문구가 동작과 어긋나면
        # 사용자는 받는 줄 알고 기다린다.
        self._auto_update_check.setToolTip(
            tr("새 버전이 나왔는지 자동으로 확인합니다(내려받기는 눌러야 시작됩니다)")
        )
        self._auto_update_check.setChecked(cur_auto)
        self._auto_update_check.checkStateChanged.connect(self._on_auto_update_changed)
        row.addWidget(self._auto_update_check)
        self._upd_status_lbl = QLabel(f"v{__version__}")
        self._upd_status_lbl.setStyleSheet(f"font-size: 11px; color: {_t().text_secondary};")
        row.addWidget(self._upd_status_lbl)
        # 수동 확인 — 자동 확인은 1시간 간격이라, 실패한 뒤 바로 다시 시도할 길이 필요하다.
        self._upd_check_btn = QPushButton(tr("확인"))
        self._upd_check_btn.setToolTip(tr("지금 업데이트를 확인합니다"))
        self._upd_check_btn.clicked.connect(self.check_update_requested.emit)
        row.addWidget(self._upd_check_btn)
        self._upd_install_btn = QPushButton(tr("지금 설치"))
        self._upd_install_btn.setToolTip(tr("앱을 재시작하여 업데이트를 설치합니다"))
        self._upd_install_btn.clicked.connect(self._on_install_update)
        self._upd_install_btn.hide()
        row.addWidget(self._upd_install_btn)
        return w

    def set_update_ready(self, dto) -> None:
        """다운로드 완료 — 헤더 상태를 '준비됨'으로 바꾸고 설치 버튼을 노출한다."""
        self._pending_dto = dto
        self._upd_status_lbl.setText(tr("업데이트 준비됨 · v{version}").format(version=dto.version))
        self._upd_status_lbl.setStyleSheet(
            f"font-size: 11px; color: {sem('danger')}; font-weight: 600;"
        )
        self._upd_install_btn.setText(tr("지금 설치"))
        self._upd_install_btn.setToolTip(tr("앱을 재시작하여 업데이트를 설치합니다"))
        self._upd_install_btn.show()

    def set_update_available(self, dto) -> None:
        """새 버전을 찾았지만 아직 받지 않은 상태(또는 받다가 실패한 상태).

        예전에는 이때 기어의 빨간 점만 켜지고 설정 화면은 그대로여서, 사용자가
        업데이트를 진행할 방법이 화면에 없었다. 여기서 직접 내려받을 버튼을 준다.
        """
        self._pending_dto = dto
        self._upd_status_lbl.setText(tr("업데이트 있음 · v{version}").format(version=dto.version))
        self._upd_status_lbl.setStyleSheet(
            f"font-size: 11px; color: {sem('warning')}; font-weight: 600;"
        )
        self._upd_install_btn.setText(tr("설치하기"))
        self._upd_install_btn.setToolTip(tr("업데이트를 내려받아 설치합니다"))
        self._upd_install_btn.show()

    def set_update_busy(self, busy: bool) -> None:
        """확인·다운로드 진행 중 표시(중복 요청 방지)."""
        self._upd_check_btn.setEnabled(not busy)
        if busy:
            self._upd_status_lbl.setText(tr("확인 중…"))
            self._upd_status_lbl.setStyleSheet(
                f"font-size: 11px; color: {_t().text_secondary};"
            )
        elif self._pending_dto is None:
            self._upd_status_lbl.setText(f"v{__version__}")
            self._upd_status_lbl.setStyleSheet(
                f"font-size: 11px; color: {_t().text_secondary};"
            )

    def scroll_and_flash_update_section(self) -> None:
        # 업데이트 상태가 헤더에 상시 노출되므로 스크롤/플래시는 불필요(no-op).
        pass

    def _on_install_update(self) -> None:
        """'지금 설치' — 저장된 DTO로 설치를 요청한다(앱 재시작 후 pending 설치)."""
        if self._pending_dto is not None:
            self.install_update_requested.emit(self._pending_dto)

    def _on_auto_update_changed(self, state) -> None:
        from config import settings as s
        s.save_setting("auto_update_check", state == Qt.CheckState.Checked)
