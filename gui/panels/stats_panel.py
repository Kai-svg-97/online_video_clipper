"""통계 대시보드 패널 — 라이브러리 및 다운로드 현황 시각화."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from application.library.dtos import CategoryStatDTO, LibraryStatsDTO
from application.library.queries import LibraryStatsHandler


def _fmt_dur(sec: int) -> str:
    h, rem = divmod(sec, 3600)
    m, _ = divmod(rem, 60)
    if h >= 24:
        d = h // 24
        return f"{d}일 {h % 24}시간"
    return f"{h}시간 {m}분"


def _fmt_bytes(b: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b //= 1024
    return f"{b:.1f} TB"


class _SummaryCard(QWidget):
    """단일 수치 요약 카드."""

    def __init__(self, label: str, value: str, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        self.setFrameShape = lambda _: None  # noqa
        self.setAutoFillBackground(True)

        val_lbl = QLabel(value)
        val_lbl.setStyleSheet("font-size: 20pt; font-weight: 700;")
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(val_lbl)

        lbl = QLabel(label)
        lbl.setStyleSheet("font-size: 9pt; color: #888;")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(80)
        self._value_lbl = val_lbl

    def set_value(self, value: str) -> None:
        self._value_lbl.setText(value)


class _BarChart(QWidget):
    """카테고리별 영상 수 수평 막대 차트 (QPainter 사용)."""

    def __init__(self, data: list[CategoryStatDTO], parent=None) -> None:
        super().__init__(parent)
        self._data = data
        self.setMinimumHeight(max(len(data) * 28 + 8, 40))

    def paintEvent(self, event) -> None:  # type: ignore[override]
        if not self._data:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        bar_h = min(20, (h - 8) // max(len(self._data), 1))
        label_w = 100
        bar_area_w = w - label_w - 60
        max_cnt = max((d.count for d in self._data), default=1) or 1

        accent = QColor("#5e81f4")
        text_color = QColor("#cccccc")
        for i, item in enumerate(self._data):
            y = 4 + i * (bar_h + 6)
            # Label
            p.setPen(text_color)
            p.drawText(0, y, label_w - 4, bar_h, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, item.name)
            # Bar
            bar_w = int(bar_area_w * item.count / max_cnt)
            p.fillRect(label_w, y, bar_w, bar_h, accent)
            # Count
            p.drawText(label_w + bar_w + 4, y, 50, bar_h, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, str(item.count))

        p.end()


class StatsPanel(QWidget):
    def __init__(self, stats_handler: LibraryStatsHandler, parent=None) -> None:
        super().__init__(parent)
        self._handler = stats_handler
        self._build_ui()
        self._refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 헤더
        header_row = QHBoxLayout()
        header_row.setContentsMargins(16, 12, 16, 8)
        header_lbl = QLabel("통계")
        header_lbl.setStyleSheet("font-size: 13pt; font-weight: 600;")
        header_row.addWidget(header_lbl)
        header_row.addStretch()
        refresh_btn = QPushButton("새로고침")
        refresh_btn.setFixedHeight(28)
        refresh_btn.clicked.connect(self._refresh)
        header_row.addWidget(refresh_btn)
        root.addLayout(header_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(sep)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(16, 16, 16, 16)
        self._content_layout.setSpacing(16)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

    def _refresh(self) -> None:
        try:
            stats = self._handler.handle()
        except Exception as e:
            self._show_error(str(e))
            return
        self._populate(stats)

    def _populate(self, stats: LibraryStatsDTO) -> None:
        # 기존 콘텐츠 제거
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 요약 카드 4개
        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)
        cards = [
            ("총 영상", f"{stats.total_videos:,}개"),
            ("총 재생시간", _fmt_dur(stats.total_duration_sec)),
            ("시청 완료", f"{stats.watched_count:,}개"),
            ("즐겨찾기", f"{stats.favorite_count:,}개"),
        ]
        for label, value in cards:
            card = _SummaryCard(label, value)
            card.setStyleSheet("background: #1e1e2e; border-radius: 8px;")
            cards_row.addWidget(card)
        self._content_layout.addLayout(cards_row)

        # 카테고리별 차트
        if stats.category_stats:
            chart_lbl = QLabel("카테고리별 영상 수")
            chart_lbl.setStyleSheet("font-size: 10pt; font-weight: 600;")
            self._content_layout.addWidget(chart_lbl)
            chart = _BarChart(stats.category_stats)
            self._content_layout.addWidget(chart)

        # 다운로드 요약
        dl_lbl = QLabel("다운로드 통계")
        dl_lbl.setStyleSheet("font-size: 10pt; font-weight: 600;")
        self._content_layout.addWidget(dl_lbl)

        dl_row = QHBoxLayout()
        dl_row.setSpacing(12)
        dl_cards = [
            ("완료 다운로드", f"{stats.total_downloads:,}개"),
            ("총 파일 용량", _fmt_bytes(stats.total_download_bytes)),
        ]
        for label, value in dl_cards:
            card = _SummaryCard(label, value)
            card.setStyleSheet("background: #1e1e2e; border-radius: 8px;")
            dl_row.addWidget(card)
        dl_row.addStretch()
        self._content_layout.addLayout(dl_row)

        self._content_layout.addStretch()

    def _show_error(self, msg: str) -> None:
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        err_lbl = QLabel(f"통계 로드 실패: {msg}")
        err_lbl.setStyleSheet("color: #f44336;")
        self._content_layout.addWidget(err_lbl)
        self._content_layout.addStretch()
