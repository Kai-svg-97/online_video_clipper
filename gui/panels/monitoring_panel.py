"""채널 모니터링 UI 패널."""
from __future__ import annotations

from uuid import UUID

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from application.monitoring.dtos import SubscriptionDTO
from domain.monitoring.value_objects import MonitoringRule
from gui.view_models.monitoring_vm import MonitoringViewModel


class _SubscriptionRow(QWidget):
    def __init__(
        self,
        sub: SubscriptionDTO,
        on_select,
        on_unsubscribe,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.sub_id = sub.id
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)

        name_lbl = QLabel(sub.channel_name or sub.channel_url)
        name_lbl.setMinimumWidth(140)
        name_lbl.setMaximumWidth(200)
        url_lbl = QLabel(sub.channel_url)
        url_lbl.setStyleSheet("font-size: 9pt; color: #888;")
        url_lbl.setMaximumWidth(240)
        auto_lbl = QLabel("자동DL" if sub.auto_download else "수동")
        auto_lbl.setFixedWidth(52)
        edit_btn = QPushButton("규칙 설정")
        edit_btn.setFixedWidth(68)
        edit_btn.clicked.connect(lambda: on_select(sub.id))
        unsub_btn = QPushButton("해제")
        unsub_btn.setFixedWidth(44)
        unsub_btn.clicked.connect(lambda: on_unsubscribe(sub.id))

        layout.addWidget(name_lbl)
        layout.addWidget(url_lbl, 1)
        layout.addWidget(auto_lbl)
        layout.addWidget(edit_btn)
        layout.addWidget(unsub_btn)


class _RuleEditor(QWidget):
    """선택된 구독의 모니터링 규칙 편집 패널."""

    def __init__(self, vm: MonitoringViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vm = vm
        self._sub_id: UUID | None = None
        self._build_ui()
        self.setEnabled(False)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QLabel("모니터링 규칙")
        header.setStyleSheet("font-size: 11pt; font-weight: 600;")
        layout.addWidget(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        # 키워드
        kw_lbl = QLabel("키워드 필터 (쉼표 구분)")
        kw_lbl.setStyleSheet("font-size: 9pt;")
        layout.addWidget(kw_lbl)
        self._kw_edit = QLineEdit()
        self._kw_edit.setPlaceholderText("예: 리뷰, 언박싱")
        layout.addWidget(self._kw_edit)

        # 최소/최대 길이
        dur_row = QHBoxLayout()
        dur_row.setContentsMargins(0, 0, 0, 0)
        min_lbl = QLabel("최소(분)")
        min_lbl.setFixedWidth(56)
        min_lbl.setStyleSheet("font-size: 9pt;")
        self._min_spin = QSpinBox()
        self._min_spin.setRange(0, 600)
        self._min_spin.setSpecialValueText("없음")
        max_lbl = QLabel("최대(분)")
        max_lbl.setFixedWidth(56)
        max_lbl.setStyleSheet("font-size: 9pt;")
        self._max_spin = QSpinBox()
        self._max_spin.setRange(0, 600)
        self._max_spin.setSpecialValueText("없음")
        dur_row.addWidget(min_lbl)
        dur_row.addWidget(self._min_spin)
        dur_row.addSpacing(12)
        dur_row.addWidget(max_lbl)
        dur_row.addWidget(self._max_spin)
        dur_row.addStretch()
        layout.addLayout(dur_row)

        # 자동 다운로드
        self._auto_dl_check = QCheckBox("조건 충족 시 자동 다운로드")
        layout.addWidget(self._auto_dl_check)

        # 저장 버튼
        save_btn = QPushButton("저장")
        save_btn.setFixedWidth(72)
        save_btn.clicked.connect(self._save)
        layout.addWidget(save_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("font-size: 9pt; color: #4caf50;")
        layout.addWidget(self._status_lbl)

        layout.addStretch()

    def load_subscription(self, sub_id: UUID) -> None:
        self._sub_id = sub_id
        self._kw_edit.clear()
        self._min_spin.setValue(0)
        self._max_spin.setValue(0)
        self._auto_dl_check.setChecked(False)
        self._status_lbl.clear()
        self.setEnabled(True)

    def _save(self) -> None:
        if self._sub_id is None:
            return
        kw_text = self._kw_edit.text().strip()
        keywords = tuple(k.strip() for k in kw_text.split(",") if k.strip()) if kw_text else ()
        min_sec = self._min_spin.value() * 60 if self._min_spin.value() > 0 else None
        max_sec = self._max_spin.value() * 60 if self._max_spin.value() > 0 else None
        rule = MonitoringRule(
            keywords=keywords,
            min_duration_sec=min_sec,
            max_duration_sec=max_sec,
            auto_download=self._auto_dl_check.isChecked(),
        )
        self._vm.set_rule(self._sub_id, rule)
        self._status_lbl.setText("저장되었습니다.")


class MonitoringPanel(QWidget):
    def __init__(
        self, vm: MonitoringViewModel, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._vm = vm
        self._rows: dict[UUID, _SubscriptionRow] = {}
        self._build_ui()
        vm.subscriptions_changed.connect(self._refresh_list)
        vm.error_occurred.connect(self._show_error)
        vm.import_yt_finished.connect(self._on_import_finished)
        QTimer.singleShot(0, vm.load)

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 헤더
        header = QLabel("채널 모니터링")
        header.setStyleSheet("font-size: 13pt; font-weight: 600; padding: 12px 16px 8px 16px;")
        outer.addWidget(header)

        # URL 입력 바
        input_row = QHBoxLayout()
        input_row.setContentsMargins(12, 4, 12, 8)
        input_row.setSpacing(8)
        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("채널 URL 입력 (예: https://www.youtube.com/@channel)")
        self._url_input.returnPressed.connect(self._subscribe)
        sub_btn = QPushButton("구독")
        sub_btn.setFixedWidth(60)
        sub_btn.clicked.connect(self._subscribe)
        input_row.addWidget(self._url_input, 1)
        input_row.addWidget(sub_btn)
        outer.addLayout(input_row)

        # YouTube 구독 일괄 가져오기 행
        yt_row = QHBoxLayout()
        yt_row.setContentsMargins(12, 0, 12, 6)
        yt_row.setSpacing(8)

        self._yt_import_btn = QPushButton("YouTube 구독 채널 가져오기")
        self._yt_import_btn.clicked.connect(self._import_from_youtube)
        yt_row.addWidget(self._yt_import_btn)
        yt_row.addStretch()

        outer.addLayout(yt_row)

        self._error_lbl = QLabel("")
        self._error_lbl.setStyleSheet("color: #f44336; font-size: 9pt; padding: 0 12px;")
        outer.addWidget(self._error_lbl)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        outer.addWidget(sep)

        # 스플리터: 목록 + 규칙 편집
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 좌측: 구독 목록
        list_widget = QWidget()
        list_layout = QVBoxLayout(list_widget)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(0)

        list_header = QLabel("구독 채널")
        list_header.setStyleSheet("font-size: 9pt; font-weight: 600; padding: 6px 8px; color: #888;")
        list_layout.addWidget(list_header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(0)
        self._list_layout.addStretch()
        self._empty_lbl = QLabel("구독 중인 채널이 없습니다.")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_lbl.setStyleSheet("color: #666; font-size: 10pt; padding: 32px;")
        self._list_layout.insertWidget(0, self._empty_lbl)
        scroll.setWidget(self._list_container)
        list_layout.addWidget(scroll, 1)

        # 우측: 규칙 편집
        self._rule_editor = _RuleEditor(self._vm)

        splitter.addWidget(list_widget)
        splitter.addWidget(self._rule_editor)
        splitter.setSizes([500, 320])

        outer.addWidget(splitter, 1)

    def _subscribe(self) -> None:
        url = self._url_input.text().strip()
        if not url:
            return
        self._error_lbl.clear()
        self._vm.subscribe_channel(url)
        self._url_input.clear()

    def _refresh_list(self) -> None:
        subs = self._vm.subscriptions
        self._empty_lbl.setVisible(len(subs) == 0)

        current_ids = {s.id for s in subs}
        for sub_id in list(self._rows):
            if sub_id not in current_ids:
                row = self._rows.pop(sub_id)
                self._list_layout.removeWidget(row)
                row.deleteLater()

        for sub in subs:
            if sub.id not in self._rows:
                row = _SubscriptionRow(
                    sub,
                    on_select=self._rule_editor.load_subscription,
                    on_unsubscribe=self._vm.unsubscribe_channel,
                    parent=self._list_container,
                )
                self._rows[sub.id] = row
                self._list_layout.insertWidget(self._list_layout.count() - 1, row)

    def _show_error(self, msg: str) -> None:
        if "Could not copy" in msg and "cookie" in msg.lower():
            self._error_lbl.setText(
                "쿠키 읽기 실패 — 사이드바 계정 버튼에서 로그인하세요."
            )
        else:
            self._error_lbl.setText(f"오류: {msg}")

    def _import_from_youtube(self) -> None:
        self._error_lbl.clear()
        self._yt_import_btn.setEnabled(False)
        self._yt_import_btn.setText("가져오는 중…")
        self._vm.import_from_youtube()

    def _on_import_finished(self, count: int) -> None:
        self._yt_import_btn.setEnabled(True)
        self._yt_import_btn.setText("YouTube 구독 채널 가져오기")
        self._error_lbl.setStyleSheet("color: #4caf50; font-size: 9pt; padding: 0 12px;")
        self._error_lbl.setText(f"YouTube 구독 채널 {count}개를 가져왔습니다.")
