"""통계 대시보드 패널 — 라이브러리 및 다운로드 현황 시각화."""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QPainter
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from application.library.dtos import CategoryStatDTO, ChannelStatDTO, LibraryStatsDTO
from application.library.queries import LibraryStatsHandler
from gui.themes.manager import ThemeManager


def _card_qss(tokens) -> str:
    """요약/채널 카드 공통 배경 — 배경 위에 떠 보이도록 표면색 + 약한 테두리."""
    return (
        f"background: {tokens.bg_elevated};"
        f" border: 1px solid {tokens.border_muted};"
        " border-radius: 8px;"
    )


def _danger_color(tokens) -> str:
    """오류 문구 색 — 밝은 테마에서 연한 빨강은 읽히지 않으므로 톤을 나눈다."""
    return "#dc2626" if tokens.is_light else "#f87171"


class _FlowLayout(QLayout):
    """폭에 맞춰 아이템을 줄바꿈하는 흐름 레이아웃(표준 Qt 레시피)."""

    def __init__(self, parent=None, hspacing: int = 6, vspacing: int = 4) -> None:
        super().__init__(parent)
        self._items: list = []
        self._hspace = hspacing
        self._vspace = vspacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # type: ignore[override]
        self._items.append(item)

    def count(self) -> int:  # type: ignore[override]
        return len(self._items)

    def itemAt(self, index: int):  # type: ignore[override]
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # type: ignore[override]
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # type: ignore[override]
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # type: ignore[override]
        return True

    def heightForWidth(self, width: int) -> int:  # type: ignore[override]
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:  # type: ignore[override]
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:  # type: ignore[override]
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # type: ignore[override]
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        x = rect.x()
        y = rect.y()
        line_height = 0
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + self._hspace
            if next_x - self._hspace > rect.right() and line_height > 0:
                x = rect.x()
                y = y + line_height + self._vspace
                next_x = x + hint.width() + self._hspace
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y()


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

    def __init__(self, label: str, value: str, tokens, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        self.setFrameShape = lambda _: None  # noqa
        self.setAutoFillBackground(True)
        self.setStyleSheet(_card_qss(tokens))

        val_lbl = QLabel(value)
        val_lbl.setStyleSheet(
            "font-size: 20pt; font-weight: 700; background: transparent;"
            f" border: none; color: {tokens.text_primary};"
        )
        val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(val_lbl)

        lbl = QLabel(label)
        lbl.setStyleSheet(
            "font-size: 9pt; background: transparent; border: none;"
            f" color: {tokens.text_secondary};"
        )
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(80)
        self._value_lbl = val_lbl

    def set_value(self, value: str) -> None:
        self._value_lbl.setText(value)


class _BarChart(QWidget):
    """카테고리별 영상 수 수평 막대 차트 (QPainter 사용)."""

    def __init__(self, data: list[CategoryStatDTO], tokens, parent=None) -> None:
        super().__init__(parent)
        self._data = data
        self._tokens = tokens
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

        accent = QColor(self._tokens.accent)
        text_color = QColor(self._tokens.text_secondary)
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
    # 채널 섹션에서 카테고리를 클릭하면 해당 category_id로 방출 → 라이브러리로 이동
    category_selected = pyqtSignal(object)   # category UUID

    def __init__(self, stats_handler: LibraryStatsHandler, parent=None) -> None:
        super().__init__(parent)
        self._handler = stats_handler
        self._build_ui()
        self._refresh()
        # 카드·차트 색은 위젯 스타일시트/QPainter로 직접 칠하므로 전역 QSS 교체만으로는
        # 갱신되지 않는다. 테마가 바뀌면 다시 그린다.
        ThemeManager.instance().theme_changed.connect(lambda _=None: self._refresh())

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
        tokens = ThemeManager.instance().current()
        # 기존 콘텐츠 제거 — 레이아웃(카드 행)도 함께 지워야 재구성 시 겹치지 않는다.
        self._clear_content()

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
            cards_row.addWidget(_SummaryCard(label, value, tokens))
        self._content_layout.addLayout(cards_row)

        section_qss = (
            f"font-size: 10pt; font-weight: 600; color: {tokens.text_primary};"
        )

        # 카테고리별 차트
        if stats.category_stats:
            chart_lbl = QLabel("카테고리별 영상 수")
            chart_lbl.setStyleSheet(section_qss)
            self._content_layout.addWidget(chart_lbl)
            chart = _BarChart(stats.category_stats, tokens)
            self._content_layout.addWidget(chart)

        # 채널별 카테고리 섹션
        if stats.channel_stats:
            ch_lbl = QLabel("채널별 카테고리")
            ch_lbl.setStyleSheet(section_qss)
            self._content_layout.addWidget(ch_lbl)
            for ch in stats.channel_stats:
                self._content_layout.addWidget(self._make_channel_row(ch, tokens))

        # 다운로드 요약
        dl_lbl = QLabel("다운로드 통계")
        dl_lbl.setStyleSheet(section_qss)
        self._content_layout.addWidget(dl_lbl)

        dl_row = QHBoxLayout()
        dl_row.setSpacing(12)
        dl_cards = [
            ("완료 다운로드", f"{stats.total_downloads:,}개"),
            ("총 파일 용량", _fmt_bytes(stats.total_download_bytes)),
        ]
        for label, value in dl_cards:
            dl_row.addWidget(_SummaryCard(label, value, tokens))
        dl_row.addStretch()
        self._content_layout.addLayout(dl_row)

        self._content_layout.addStretch()

    def _clear_content(self) -> None:
        """콘텐츠 영역을 비운다 — 중첩 레이아웃까지 재귀적으로 제거한다."""

        def _drop(layout) -> None:
            while layout.count():
                item = layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()
                    continue
                child = item.layout()
                if child is not None:
                    _drop(child)
                    child.deleteLater()

        _drop(self._content_layout)

    def _make_channel_row(self, ch: ChannelStatDTO, tokens) -> QWidget:
        """채널 하나 — 이름 + 카테고리 경로 링크(클릭 시 해당 카테고리로 이동)."""
        card = QWidget()
        card.setStyleSheet(_card_qss(tokens))
        v = QVBoxLayout(card)
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(6)

        # 채널명 줄: URL이 있으면 클릭 시 브라우저로 열고, URL 복사 버튼을 둔다.
        name_row = QHBoxLayout()
        name_row.setSpacing(6)
        url = ch.channel_url or ""
        if url:
            name_btn = QPushButton(ch.channel_name)
            name_btn.setFlat(True)
            name_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            name_btn.setToolTip(f"브라우저에서 채널 열기\n{url}")
            name_btn.setStyleSheet(
                "QPushButton { font-weight:600; background:transparent;"
                f" color:{tokens.accent};"
                " border:none; text-align:left; padding:0; }"
                f"QPushButton:hover {{ color:{tokens.accent_hover};"
                " text-decoration:underline; }"
            )
            name_btn.clicked.connect(lambda _=False, u=url: self._open_url(u))
            name_row.addWidget(name_btn)

            copy_btn = QToolButton()
            copy_btn.setText("📋")
            copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            copy_btn.setToolTip("채널 URL 복사")
            copy_btn.setAutoRaise(True)
            copy_btn.setStyleSheet(
                "QToolButton { background:transparent; border:none; padding:0 2px;"
                f" color:{tokens.text_secondary}; }}"
            )
            copy_btn.clicked.connect(lambda _=False, u=url, b=copy_btn: self._copy_url(u, b))
            name_row.addWidget(copy_btn)
        else:
            plain = QLabel(ch.channel_name)
            plain.setStyleSheet(
                "font-weight:600; background:transparent; border:none;"
                f" color:{tokens.text_primary};"
            )
            name_row.addWidget(plain)

        total_lbl = QLabel(f"·  {ch.total:,}개")
        total_lbl.setStyleSheet(
            f"color:{tokens.text_secondary}; background:transparent; border:none;"
        )
        name_row.addWidget(total_lbl)
        name_row.addStretch()
        v.addLayout(name_row)

        links_host = QWidget()
        links_host.setStyleSheet("background: transparent; border: none;")
        flow = _FlowLayout(links_host, hspacing=6, vspacing=6)
        link_qss = (
            "QPushButton {"
            f" color:{tokens.accent}; background:{tokens.bg_overlay};"
            f" border:1px solid {tokens.border};"
            " border-radius:6px; padding:2px 8px; font-size:9pt; text-align:left; }"
            f"QPushButton:hover {{ background:{tokens.accent};"
            f" color:{tokens.text_on_accent}; border-color:{tokens.accent}; }}"
        )
        for cat in ch.categories:
            link = QPushButton(f"{cat.category_path} ({cat.count})")
            link.setFlat(True)
            link.setCursor(Qt.CursorShape.PointingHandCursor)
            link.setStyleSheet(link_qss)
            link.clicked.connect(
                lambda _checked=False, cid=cat.category_id: self.category_selected.emit(cid)
            )
            flow.addWidget(link)
        v.addWidget(links_host)
        return card

    def _open_url(self, url: str) -> None:
        """채널 URL을 기본 브라우저로 연다."""
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _copy_url(self, url: str, btn: QToolButton | None = None) -> None:
        """채널 URL을 클립보드에 복사하고, 버튼에 잠깐 확인 표시(✓)를 준다."""
        if not url:
            return
        QApplication.clipboard().setText(url)
        if btn is not None:
            btn.setText("✓")
            QTimer.singleShot(1200, lambda: btn.setText("📋"))

    def _show_error(self, msg: str) -> None:
        self._clear_content()
        err_lbl = QLabel(f"통계 로드 실패: {msg}")
        err_lbl.setStyleSheet(f"color: {_danger_color(ThemeManager.instance().current())};")
        self._content_layout.addWidget(err_lbl)
        self._content_layout.addStretch()
