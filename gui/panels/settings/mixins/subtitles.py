"""SubtitleIndexMixin — 자막 색인 섹션 — 전체 자막 색인 진행과 음성 인식 모델 고르기·지우기.

    SettingsPanel에 섞여 들어가는 mixin이라 패널 상태(`self._auth`·`self._subtitle_vm`
    같은 주입값, 다른 섹션의 위젯)를 그대로 쓴다(런타임 클래스는 하나다).
"""

from __future__ import annotations

import logging

from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
)

from gui.panels.settings.helpers import _t
from gui.text import tr
from gui.text.labels import (
    transcribe_model_name,
    transcribe_model_note,
)

logger = logging.getLogger(__name__)


class SubtitleIndexMixin:
    """자막 색인 섹션 — 전체 자막 색인 진행과 음성 인식 모델 고르기·지우기."""

    def _build_subtitle_index_section(self, layout) -> None:
        """자막 색인 — 라이브러리 전체를 훑어 자막을 모아 둔다.

        **자동으로 돌지 않는다.** 영상당 네트워크 왕복이 1초 안팎이라 수백 건이면
        10분을 넘긴다 — 사용자가 시작을 누르고, 언제든 그만둘 수 있어야 한다.
        뷰모델이 없으면(다른 진입점에서 연 설정 화면) 섹션 자체를 만들지 않는다.
        """
        if self._subtitle_vm is None:
            return

        self._add_divider(layout)
        sub_label = QLabel(tr("자막 색인"))
        sub_label.setStyleSheet(
            "font-size: 9px; font-weight: 600; letter-spacing: 0.8px; "
            f"text-transform: uppercase; color: {_t().text_muted};"
        )
        layout.addWidget(sub_label)
        layout.addSpacing(8)

        self._sub_cover_lbl = QLabel("")
        self._sub_cover_lbl.setStyleSheet("font-size: 11px;")
        layout.addWidget(self._sub_cover_lbl)

        row = QHBoxLayout()
        row.setContentsMargins(0, 6, 0, 0)
        self._sub_index_btn = QPushButton(tr("전체 자막 색인 시작"))
        self._sub_index_btn.clicked.connect(self._on_bulk_subtitle_clicked)
        row.addWidget(self._sub_index_btn)
        row.addStretch()
        layout.addLayout(row)

        self._sub_index_bar = QProgressBar()
        self._sub_index_bar.setVisible(False)
        self._sub_index_bar.setTextVisible(True)
        self._sub_index_bar.setMaximumHeight(16)
        layout.addWidget(self._sub_index_bar)

        self._sub_index_status = QLabel("")
        self._sub_index_status.setWordWrap(True)
        self._sub_index_status.setStyleSheet(
            f"font-size: 10px; color: {_t().text_secondary};"
        )
        layout.addWidget(self._sub_index_status)

        hint = QLabel(
            tr(
                "색인해 두면 라이브러리 검색이 영상 속 대사까지 찾고, 상세화면 자막 탭에서 "
                "그 대사가 나온 시점으로 바로 건너뛸 수 있습니다. 영상마다 인터넷에 한 번씩 "
                "물어보므로 시간이 걸리며, 이미 색인된 영상은 건너뜁니다."
            )
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(f"font-size: 10px; color: {_t().text_secondary};")
        layout.addWidget(hint)

        self._build_transcribe_rows(layout)
        layout.addSpacing(24)

        self._subtitle_vm.bulk_progress.connect(self._on_bulk_subtitle_progress)
        self._subtitle_vm.bulk_finished.connect(self._on_bulk_subtitle_finished)
        self._refresh_subtitle_coverage()

    # ── 음성 인식(자막 만들기) ────────────────────────────────────

    def _build_transcribe_rows(self, layout) -> None:
        """음성 인식 모델 고르기 + 받아 둔 모델 지우기.

        **크기가 곧 정확도이자 시간**이라 고를 수 있어야 한다. 목표 사양이 저사양 PC라
        "가장 좋은 것"을 기본값으로 두면 대부분에게 "몇 시간째 안 끝난다"가 된다
        (`domain/library/transcribe.py`). 그래서 콤보에 **디스크 크기**를 같이 적고,
        고른 것의 설명을 바로 아래에 띄운다.

        모델 파일은 한 번 받으면 계속 남으므로(small 은 484MB) **지우는 길**도 둔다.
        """
        from domain.library.transcribe import MODELS  # noqa: PLC0415 (도메인 카탈로그)

        layout.addSpacing(14)
        asr_label = QLabel(tr("음성 인식으로 자막 만들기"))
        asr_label.setStyleSheet(
            f"font-size: 9px; font-weight: 600; letter-spacing: 0.5px; "
            f"color: {_t().text_secondary};"
        )
        layout.addWidget(asr_label)

        model_row = QHBoxLayout()
        m_lbl = QLabel(tr("모델"))
        m_lbl.setMinimumWidth(100)
        self._asr_model_combo = QComboBox()
        for model in MODELS:
            self._asr_model_combo.addItem(
                f"{transcribe_model_name(model.key)} · {model.disk_mb}MB", model.key
            )
        current = self._subtitle_vm.transcribe_model_key if self._subtitle_vm else ""
        idx = self._asr_model_combo.findData(current)
        self._asr_model_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._asr_model_combo.setMinimumWidth(220)
        self._asr_model_combo.currentIndexChanged.connect(self._on_asr_model_changed)
        model_row.addWidget(m_lbl)
        model_row.addWidget(self._asr_model_combo)
        model_row.addStretch()
        layout.addLayout(model_row)

        self._asr_model_note = QLabel("")
        self._asr_model_note.setWordWrap(True)
        self._asr_model_note.setStyleSheet(
            f"font-size: 10px; color: {_t().text_secondary};"
        )
        layout.addWidget(self._asr_model_note)

        del_row = QHBoxLayout()
        del_row.setContentsMargins(0, 4, 0, 0)
        self._asr_installed_lbl = QLabel("")
        self._asr_installed_lbl.setWordWrap(True)
        self._asr_installed_lbl.setStyleSheet(
            f"font-size: 10px; color: {_t().text_secondary};"
        )
        self._asr_delete_btn = QPushButton(tr("받아 둔 모델 지우기"))
        self._asr_delete_btn.setMinimumWidth(140)
        self._asr_delete_btn.clicked.connect(self._on_asr_delete_clicked)
        del_row.addWidget(self._asr_installed_lbl, 1)
        del_row.addWidget(self._asr_delete_btn)
        layout.addLayout(del_row)

        asr_hint = QLabel(
            tr(
                "YouTube가 자막을 주지 않는 영상에서 씁니다. 상세화면 자막 탭의 "
                "'음성 인식으로 만들기'를 누르면 받아 둔 파일의 소리를 듣고 자막을 만듭니다. "
                "모델은 처음 한 번만 내려받으며, 인터넷 없이 이 PC에서 계산합니다."
            )
        )
        asr_hint.setWordWrap(True)
        asr_hint.setStyleSheet(f"font-size: 10px; color: {_t().text_secondary};")
        layout.addWidget(asr_hint)

        self._refresh_transcribe_rows()

    def _refresh_transcribe_rows(self) -> None:
        """고른 모델의 설명과 '받아 둔 모델' 표시를 다시 채운다."""
        key = self._asr_model_combo.currentData() or ""
        self._asr_model_note.setText(transcribe_model_note(key))

        installed = self._subtitle_vm.installed_models() if self._subtitle_vm else set()
        if key in installed:
            disk = self._subtitle_vm.model_disk_mb(key) if self._subtitle_vm else 0
            self._asr_installed_lbl.setText(
                tr("받아 둔 모델입니다 ({disk}MB) — 바로 쓸 수 있습니다.").format(disk=disk)
                if disk
                else tr("받아 둔 모델입니다 — 바로 쓸 수 있습니다.")
            )
            self._asr_delete_btn.setEnabled(True)
            return
        # 아직 안 받은 모델 — 처음 쓸 때 받는다는 것을 미리 알린다(몇 분이 걸린다).
        others = sorted(installed)
        if others:
            self._asr_installed_lbl.setText(
                tr("처음 쓸 때 내려받습니다. (받아 둔 것: {models})").format(
                    models=", ".join(others)
                )
            )
        else:
            self._asr_installed_lbl.setText(tr("처음 쓸 때 내려받습니다."))
        self._asr_delete_btn.setEnabled(False)

    def _on_asr_model_changed(self, _index: int) -> None:
        if self._subtitle_vm is None:
            return
        key = self._asr_model_combo.currentData()
        if key:
            self._subtitle_vm.set_transcribe_model(str(key))
        self._refresh_transcribe_rows()

    def _on_asr_delete_clicked(self) -> None:
        """받아 둔 모델을 지운다 — small 은 484MB라 되찾을 값이 있다."""
        if self._subtitle_vm is None:
            return
        key = str(self._asr_model_combo.currentData() or "")
        if not key:
            return
        if self._subtitle_vm.delete_model(key):
            self._asr_installed_lbl.setText(tr("지웠습니다. 다음에 쓸 때 다시 받습니다."))
            self._asr_delete_btn.setEnabled(False)
        else:
            self._asr_installed_lbl.setText(tr("지우지 못했습니다. 로그를 확인하세요."))

    def _refresh_subtitle_coverage(self) -> None:
        coverage = self._subtitle_vm.coverage() if self._subtitle_vm else None
        if coverage is None:
            self._sub_cover_lbl.setText(tr("색인 현황을 읽을 수 없습니다."))
            return
        self._sub_cover_lbl.setText(
            tr("영상 {total}개 중 {indexed}개 색인됨 (남은 {remaining}개)").format(
                total=coverage.total_videos,
                indexed=coverage.indexed_videos,
                remaining=coverage.remaining,
            )
        )

    def _on_bulk_subtitle_clicked(self) -> None:
        if self._subtitle_vm is None:
            return
        if self._subtitle_vm.is_bulk_running:
            self._subtitle_vm.stop_bulk_index()
            self._sub_index_btn.setText(tr("중지하는 중…"))
            self._sub_index_btn.setEnabled(False)
            return
        if not self._subtitle_vm.start_bulk_index():
            self._sub_index_status.setText(tr("색인을 시작할 수 없습니다."))
            return
        self._sub_index_bar.setValue(0)
        self._sub_index_bar.setVisible(True)
        self._sub_index_btn.setText(tr("중지"))
        self._sub_index_status.setText(tr("색인 중…"))

    def _on_bulk_subtitle_progress(self, current: int, total: int, title: str) -> None:
        self._sub_index_bar.setMaximum(max(1, total))
        self._sub_index_bar.setValue(current)
        self._sub_index_bar.setFormat(f"{current}/{total}")
        self._sub_index_status.setText(tr("확인 중 — {title}").format(title=title))

    def _on_bulk_subtitle_finished(self, result) -> None:
        self._sub_index_bar.setVisible(False)
        self._sub_index_btn.setText(tr("전체 자막 색인 시작"))
        self._sub_index_btn.setEnabled(True)
        if result is None:
            self._sub_index_status.setText(tr("색인 중 오류가 발생했습니다. 로그를 확인하세요."))
            return
        parts = [tr("{n}개 색인").format(n=result.indexed)]
        if result.no_subtitle:
            parts.append(tr("{n}개는 자막 없음").format(n=result.no_subtitle))
        if result.stopped:
            parts.append(tr("중단됨"))
        self._sub_index_status.setText(" · ".join(parts))
        self._refresh_subtitle_coverage()
