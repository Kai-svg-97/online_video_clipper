"""DownloadTransferMixin — 다운로드 섹션의 전송 옵션(속도·조각·프록시·예약 시간대)과 SponsorBlock.

    SettingsPanel에 섞여 들어가는 mixin이라 패널 상태(`self._auth`·`self._subtitle_vm`
    같은 주입값, 다른 섹션의 위젯)를 그대로 쓴다(런타임 클래스는 하나다).
"""

from __future__ import annotations

import logging

from PyQt6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from gui.panels.settings.helpers import _t
from gui.text import tr
from gui.text.messages import render

logger = logging.getLogger(__name__)


class DownloadTransferMixin:
    """다운로드 섹션의 전송 옵션(속도·조각·프록시·예약 시간대)과 SponsorBlock."""

    def _build_transfer_rows(self, layout) -> None:
        """전송 옵션(속도 제한·조각 병렬·프록시)과 예약 시간대."""
        from domain.download.schedule import MAX_CONCURRENT, MIN_CONCURRENT  # noqa: PLC0415

        try:
            from config import settings as s
            cur_rate = s.DOWNLOAD_RATE_LIMIT
            cur_frag = s.CONCURRENT_FRAGMENTS
            cur_proxy = s.DOWNLOAD_PROXY
            cur_win_on = s.DOWNLOAD_WINDOW_ENABLED
            cur_win_start = s.DOWNLOAD_WINDOW_START
            cur_win_end = s.DOWNLOAD_WINDOW_END
        except Exception:
            logger.exception("전송 옵션 로드 실패")
            cur_rate, cur_frag, cur_proxy = "", 1, ""
            cur_win_on, cur_win_start, cur_win_end = False, 23, 7

        tr_lbl = QLabel(tr("전송"))
        tr_lbl.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted};"
        )
        layout.addWidget(tr_lbl)
        layout.addSpacing(8)

        rate_row = QHBoxLayout()
        rate_row.setContentsMargins(0, 0, 0, 0)
        rate_lbl = QLabel(tr("속도 제한"))
        rate_lbl.setMinimumWidth(100)
        rate_lbl.setStyleSheet("font-size: 11px;")
        self._rate_edit = QLineEdit(cur_rate)
        self._rate_edit.setPlaceholderText(tr("비우면 무제한 (예: 2M, 500K)"))
        self._rate_edit.editingFinished.connect(self._on_rate_limit_changed)
        rate_row.addWidget(rate_lbl)
        rate_row.addWidget(self._rate_edit, 1)
        layout.addLayout(rate_row)
        layout.addSpacing(10)

        frag_row = QHBoxLayout()
        frag_row.setContentsMargins(0, 0, 0, 0)
        frag_lbl = QLabel(tr("조각 동시 수"))
        frag_lbl.setMinimumWidth(100)
        frag_lbl.setStyleSheet("font-size: 11px;")
        self._frag_spin = QSpinBox()
        self._frag_spin.setRange(1, 16)
        self._frag_spin.setValue(max(1, int(cur_frag or 1)))
        self._frag_spin.setFixedWidth(64)
        self._frag_spin.valueChanged.connect(self._on_fragments_changed)
        frag_hint = QLabel(tr("1이면 끕니다. 고화질 영상에서 체감이 큽니다."))
        frag_hint.setStyleSheet(f"font-size: 10px; color: {_t().text_secondary};")
        frag_row.addWidget(frag_lbl)
        frag_row.addWidget(self._frag_spin)
        frag_row.addWidget(frag_hint)
        frag_row.addStretch()
        layout.addLayout(frag_row)
        layout.addSpacing(10)

        proxy_row = QHBoxLayout()
        proxy_row.setContentsMargins(0, 0, 0, 0)
        proxy_lbl = QLabel(tr("프록시"))
        proxy_lbl.setMinimumWidth(100)
        proxy_lbl.setStyleSheet("font-size: 11px;")
        self._proxy_edit = QLineEdit(cur_proxy)
        self._proxy_edit.setPlaceholderText(tr("비우면 사용 안 함 (예: socks5://127.0.0.1:1080)"))
        self._proxy_edit.editingFinished.connect(self._on_proxy_changed)
        proxy_row.addWidget(proxy_lbl)
        proxy_row.addWidget(self._proxy_edit, 1)
        layout.addLayout(proxy_row)
        layout.addSpacing(14)

        # ── 예약 시간대 ──
        self._window_check = QCheckBox(tr("정해진 시간대에만 받기"))
        self._window_check.setChecked(cur_win_on)
        self._window_check.checkStateChanged.connect(self._on_window_toggled)
        layout.addWidget(self._window_check)

        win_row = QHBoxLayout()
        win_row.setContentsMargins(22, 4, 0, 0)
        self._win_start_spin = QSpinBox()
        self._win_start_spin.setRange(0, 23)
        self._win_start_spin.setValue(int(cur_win_start) % 24)
        self._win_start_spin.setSuffix(tr("시"))
        self._win_start_spin.setFixedWidth(64)
        self._win_start_spin.valueChanged.connect(self._on_window_hours_changed)
        self._win_end_spin = QSpinBox()
        self._win_end_spin.setRange(0, 23)
        self._win_end_spin.setValue(int(cur_win_end) % 24)
        self._win_end_spin.setSuffix(tr("시"))
        self._win_end_spin.setFixedWidth(64)
        self._win_end_spin.valueChanged.connect(self._on_window_hours_changed)
        win_row.addWidget(self._win_start_spin)
        win_row.addWidget(QLabel("~"))
        win_row.addWidget(self._win_end_spin)
        win_row.addStretch()
        layout.addLayout(win_row)

        self._window_hint = QLabel("")
        self._window_hint.setWordWrap(True)
        self._window_hint.setStyleSheet(
            f"font-size: 10px; color: {_t().text_secondary}; margin-left: 22px;"
        )
        layout.addWidget(self._window_hint)
        self._refresh_window_hint()

        tr_hint = QLabel(
            tr(
                "동시에 받는 영상 수는 위 '일반'의 동시 다운로드 수({min}~"
                "{max})를 따릅니다. 자리가 찰 때까지 나머지는 대기합니다."
            ).format(min=MIN_CONCURRENT, max=MAX_CONCURRENT)
        )
        tr_hint.setWordWrap(True)
        tr_hint.setStyleSheet(f"font-size: 10px; color: {_t().text_secondary};")
        layout.addWidget(tr_hint)

    def _refresh_window_hint(self) -> None:
        from domain.download.schedule import DownloadWindow  # noqa: PLC0415

        window = DownloadWindow(
            enabled=self._window_check.isChecked(),
            start_hour=self._win_start_spin.value(),
            end_hour=self._win_end_spin.value(),
        )
        self._window_hint.setText(render(window.describe()))
        for spin in (self._win_start_spin, self._win_end_spin):
            spin.setEnabled(self._window_check.isChecked())

    def _on_rate_limit_changed(self) -> None:
        self._save_setting("download_rate_limit", self._rate_edit.text().strip())

    def _on_fragments_changed(self, value: int) -> None:
        self._save_setting("concurrent_fragments", int(value))

    def _on_proxy_changed(self) -> None:
        self._save_setting("download_proxy", self._proxy_edit.text().strip())

    def _on_window_toggled(self, _state) -> None:
        self._save_setting("download_window_enabled", self._window_check.isChecked())
        self._refresh_window_hint()

    def _on_window_hours_changed(self, _value) -> None:
        self._save_setting("download_window_start", self._win_start_spin.value())
        self._save_setting("download_window_end", self._win_end_spin.value())
        self._refresh_window_hint()

    def _build_sponsorblock_rows(self, layout) -> None:
        """SponsorBlock — 재생 중 건너뛰기 / 다운로드 시 잘라내기."""
        from gui.text.labels import SPONSOR_CATEGORY_LABELS  # noqa: PLC0415

        try:
            from config import settings as s
            cur_skip = s.SPONSORBLOCK_SKIP
            cur_remove = s.SPONSORBLOCK_REMOVE
            cur_cats = {c.strip() for c in s.SPONSORBLOCK_CATEGORIES.split(",") if c.strip()}
        except Exception:
            logger.exception("SponsorBlock 설정 로드 실패")
            cur_skip, cur_remove, cur_cats = True, False, set()

        sb_lbl = QLabel("SponsorBlock")
        sb_lbl.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted};"
        )
        layout.addWidget(sb_lbl)
        layout.addSpacing(8)

        self._sb_skip_check = QCheckBox(tr("재생 중 자동으로 건너뛰기"))
        self._sb_skip_check.setChecked(cur_skip)
        self._sb_skip_check.checkStateChanged.connect(self._on_sb_skip_changed)
        layout.addWidget(self._sb_skip_check)

        self._sb_remove_check = QCheckBox(tr("다운로드한 파일에서 잘라내기"))
        self._sb_remove_check.setChecked(cur_remove)
        self._sb_remove_check.checkStateChanged.connect(self._on_sb_remove_changed)
        layout.addWidget(self._sb_remove_check)

        # 카테고리 — 건너뛰기와 잘라내기가 **같은 목록**을 쓴다.
        self._sb_cat_checks: dict[str, QCheckBox] = {}
        cat_box = QVBoxLayout()
        cat_box.setContentsMargins(22, 4, 0, 0)
        cat_box.setSpacing(2)
        for key, name in SPONSOR_CATEGORY_LABELS.items():
            check = QCheckBox(name)
            check.setChecked(key in cur_cats)
            check.checkStateChanged.connect(self._on_sb_categories_changed)
            self._sb_cat_checks[key] = check
            cat_box.addWidget(check)
        layout.addLayout(cat_box)

        sb_hint = QLabel(
            tr(
                "SponsorBlock은 사용자들이 모은 공개 구간 정보입니다. 조회는 영상 ID를 "
                "그대로 보내지 않고 해시 앞자리만 보내므로 어떤 영상을 보는지 서버가 알 수 "
                "없습니다. 잘라내기는 파일을 실제로 바꾸므로 되돌릴 수 없습니다."
            )
        )
        sb_hint.setWordWrap(True)
        sb_hint.setStyleSheet(
            f"font-size: 10px; color: {_t().text_secondary}; margin-left: 22px;"
        )
        layout.addWidget(sb_hint)

    def _on_sb_skip_changed(self, _state) -> None:
        self._save_setting("sponsorblock_skip", self._sb_skip_check.isChecked())

    def _on_sb_remove_changed(self, _state) -> None:
        self._save_setting("sponsorblock_remove", self._sb_remove_check.isChecked())

    def _on_sb_categories_changed(self, _state) -> None:
        picked = ",".join(k for k, c in self._sb_cat_checks.items() if c.isChecked())
        self._save_setting("sponsorblock_categories", picked)
