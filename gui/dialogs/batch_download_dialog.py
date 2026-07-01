"""일괄 다운로드 설정 다이얼로그."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

from domain.download.value_objects import DownloadSettings, MediaFormat, Quality


class BatchDownloadDialog(QDialog):
    """다중 선택 일괄 다운로드 설정 다이얼로그."""

    def __init__(self, count: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("일괄 다운로드")
        self.setMinimumWidth(320)
        self._build_ui(count)

    def _build_ui(self, count: int) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        info = QLabel(f"선택한 <b>{count}</b>개 영상을 다운로드합니다.")
        layout.addWidget(info)

        form = QFormLayout()
        form.setSpacing(8)

        self._quality_combo = QComboBox()
        quality_options = [
            ("자동 (최고 품질)", Quality.BEST),
            ("1080p / FHD", Quality.P1080),
            ("720p / HD", Quality.P720),
            ("480p", Quality.P480),
            ("360p", Quality.P360),
        ]
        for label, q in quality_options:
            self._quality_combo.addItem(label, q)
        self._quality_combo.setCurrentIndex(1)  # 기본 1080p
        form.addRow("품질:", self._quality_combo)

        self._format_combo = QComboBox()
        for fmt in MediaFormat:
            self._format_combo.addItem(fmt.value, fmt)
        form.addRow("포맷:", self._format_combo)

        layout.addLayout(form)

        self._skip_check = QCheckBox("이미 다운로드된 항목 건너뜀")
        self._skip_check.setChecked(True)
        layout.addWidget(self._skip_check)

        self._gemini_check = QCheckBox("Gemini AI 요약을 메모에 자동 저장 (YouTube 로그인 필요)")
        self._gemini_check.setChecked(False)
        self._gemini_check.setToolTip(
            "다운로드 완료 후 YouTube의 Gemini Ask 버튼을 자동으로 클릭해\n"
            "AI 요약 텍스트를 라이브러리 영상 메모에 저장합니다.\n"
            "YouTube 계정 로그인 필요 / 영상당 약 30초 추가됩니다."
        )
        layout.addWidget(self._gemini_check)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def build_settings(self) -> DownloadSettings:
        quality: Quality = self._quality_combo.currentData()
        fmt: MediaFormat = self._format_combo.currentData()
        return DownloadSettings(
            quality=quality,
            fmt=fmt,
            capture_gemini=self._gemini_check.isChecked(),
        )

    @property
    def skip_existing(self) -> bool:
        return self._skip_check.isChecked()
