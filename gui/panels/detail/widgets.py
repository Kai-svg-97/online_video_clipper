"""상세화면 공용 소형 위젯 — 태그 칩·흐름 레이아웃·자동 높이 편집기·인라인 편집 필드.

어느 탭에서나 쓰는 부품이라 한곳에 모았다. `_FlowLayout`은 폭에 맞춰 줄바꿈하는 실제
`QLayout` 서브클래스이고, `_AutoHeight*`는 내용 높이를 sizeHint로 노출해 스크롤을 줄인다.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from PyQt6.QtCore import (
    QPoint,
    QRect,
    QSize,
    QTimer,
    Qt,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QDesktopServices,
    QFont,
    QIcon,
    QTransform,
)
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


from gui.themes.manager import ThemeManager

logger = logging.getLogger(__name__)


def _t():
    return ThemeManager.instance().current()

def _fmt_size(b: int | None) -> str:
    if b is None:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b //= 1024
    return f"{b:.1f} TB"

class _TagChip(QPushButton):
    """Small pill-shaped button for a single tag.

    폭은 태그 글자 길이에 맞춰 최소화한다(Fixed 사이즈 정책 + 좁은 padding).
    """

    def __init__(self, tag_id: UUID, tag_name: str, parent=None) -> None:
        super().__init__(f"#{tag_name}", parent)
        self.tag_id = tag_id
        self.tag_name = tag_name
        self.setFlat(True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        tok = _t()
        self.setStyleSheet(
            f"QPushButton{{"
            f"  border:1px solid {tok.border_muted}; border-radius:10px;"
            f"  background:{tok.bg_elevated}; color:{tok.text_secondary};"
            f"  padding:2px 8px; font-size:8pt;"
            f"}}"
            f"QPushButton:hover{{background:{tok.bg_overlay}; color:{tok.text_primary};}}"
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)

class _FlowLayout(QLayout):
    """가로로 채우다 폭이 부족하면 다음 줄로 넘기는 표준 flow 레이아웃.

    각 아이템은 자신의 sizeHint 폭만 차지하므로 태그 칩이 글자 길이만큼만
    넓어지고, 사용 가능한 폭에 맞춰 자동으로 줄바꿈된다.
    """

    def __init__(self, parent: QWidget | None = None, spacing: int = 4) -> None:
        super().__init__(parent)
        self._items: list = []
        self.setSpacing(spacing)
        if parent is not None:
            self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(
            margins.left() + margins.right(), margins.top() + margins.bottom()
        )
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        x = rect.x() + margins.left()
        y = rect.y() + margins.top()
        line_height = 0
        spacing = self.spacing()
        eff_right = rect.right() - margins.right()
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + spacing
            if next_x - spacing > eff_right and line_height > 0:
                x = rect.x() + margins.left()
                y = y + line_height + spacing
                next_x = x + hint.width() + spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()

class _TagFlow(QWidget):
    """Wrapping flow layout of tag chips."""

    tag_clicked = pyqtSignal(object, str)  # (tag_id: UUID, tag_name: str)

    def __init__(self, tags: list[str], tag_ids: dict[str, UUID], parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = _FlowLayout(self, spacing=4)
        for name in tags:
            tid = tag_ids.get(name)
            if tid is None:
                continue
            chip = _TagChip(tid, name, self)
            chip.clicked.connect(lambda _, i=tid, n=name: self.tag_clicked.emit(i, n))
            layout.addWidget(chip)

class _AutoHeightBrowser(QTextBrowser):
    """내용 높이를 ``sizeHint``로 노출하는 QTextBrowser(설명 섹션용).

    세로 여유가 있으면 내용 높이(sizeHint)만큼만 차지해 스크롤 없이 전체가 보이고,
    공간이 부족하면 ``minimumSizeHint``까지 줄며 그때만 내부 스크롤을 쓴다. 레이아웃이
    남는 세로 공간을 이 위젯에 몰아줄 수 있어(설명이 길수록 더 넓게) 스크롤이 최소화되며,
    아래 메모의 최소 높이는 메모 위젯 자체가 고정 확보한다.
    """

    def __init__(self, min_h: int = 48, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._min_h = min_h
        self._content_h = min_h
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.document().documentLayout().documentSizeChanged.connect(
            lambda _=None: self._recalc()
        )

    def _recalc(self) -> None:
        doc = self.document()
        self._content_h = max(
            self._min_h, int(doc.size().height() + 2 * doc.documentMargin()) + 2
        )
        self.updateGeometry()

    def sizeHint(self) -> QSize:
        return QSize(super().sizeHint().width(), self._content_h)

    def minimumSizeHint(self) -> QSize:
        return QSize(super().minimumSizeHint().width(), self._min_h)

    def resizeEvent(self, event) -> None:
        self.document().setTextWidth(self.viewport().width())
        super().resizeEvent(event)
        self._recalc()

class _AutoHeightPlainEdit(QPlainTextEdit):
    """내용 줄 수에 맞춰 ``min_lines``~``max_lines`` 사이에서 높이를 조절(메모용)."""

    def __init__(
        self, min_lines: int = 1, max_lines: int = 5, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._min_lines = min_lines
        self._max_lines = max_lines
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.document().documentLayout().documentSizeChanged.connect(
            lambda _=None: self._sync_height()
        )
        self._sync_height()

    def _sync_height(self) -> None:
        line_h = self.fontMetrics().lineSpacing()
        doc_lines = self.document().size().height()  # QPlainTextEdit: 줄 수 단위
        lines = max(self._min_lines, min(int(round(doc_lines)) or 1, self._max_lines))
        doc_margin = self.document().documentMargin()
        h = int(line_h * lines + 2 * doc_margin + 2 * self.frameWidth() + 4)
        self.setFixedHeight(h)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_height()

class _DblClickLabel(QLabel):
    """더블클릭 시 신호를 내는 QLabel — 노래 정보 필드 인라인 편집 진입용."""

    double_clicked = pyqtSignal()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)

class _EditableField(QStackedWidget):
    """더블클릭하면 QLineEdit로 바뀌어 편집, Enter/포커스아웃 시 저장하는 값 위젯.

    가수/앨범/노래제목/발매년도 필드에 재사용한다. 값이 비면 '—'(muted)로 표시하고,
    편집 가능(``editable``)일 때만 더블클릭이 편집을 연다.
    """

    edited = pyqtSignal(str)
    action_clicked = pyqtSignal()   # 값 오른쪽 » 아이콘(같은 가수/앨범 필터) — with_action=True일 때만

    def __init__(
        self,
        placeholder: str = "정보 없음",
        with_action: bool = False,
        action_tip: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._value = ""
        self._editable = True
        self._placeholder = placeholder
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        # index 0: 표시 페이지 = [값 라벨(내용 폭)] [4칸 여백 + »(with_action)] [stretch]
        self._display = QWidget()
        dl = QHBoxLayout(self._display)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(0)
        self._lbl = _DblClickLabel("—")
        # 평문으로 렌더 — 값에 &, ', < 등이 있어도 그대로 보이게(HTML 엔티티 오표기 방지)
        self._lbl.setTextFormat(Qt.TextFormat.PlainText)
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self._lbl.setToolTip("더블클릭하여 편집")
        self._lbl.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self._lbl.double_clicked.connect(self._enter_edit)
        dl.addWidget(self._lbl)
        self._action_btn: QPushButton | None = None
        if with_action:
            dl.addSpacing(28)   # 값 오른쪽 ~4칸 여백
            self._action_btn = QPushButton("»")
            self._action_btn.setFlat(True)
            self._action_btn.setFixedSize(22, 20)
            self._action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._action_btn.setToolTip(action_tip or "같은 정보의 영상 보기")
            self._action_btn.clicked.connect(self.action_clicked.emit)
            self._action_btn.setVisible(False)
            dl.addWidget(self._action_btn)
        dl.addStretch()
        self.addWidget(self._display)

        self._edit = QLineEdit()
        self._edit.editingFinished.connect(self._commit)
        self.addWidget(self._edit)
        self.setCurrentWidget(self._display)
        self._apply_theme()

    @property
    def value(self) -> str:
        return self._value

    def set_editable(self, editable: bool) -> None:
        self._editable = editable
        self._lbl.setToolTip("더블클릭하여 편집" if editable else "")

    def set_value(self, value: str) -> None:
        self._value = value or ""
        self._render()
        if self._action_btn is not None:
            self._action_btn.setVisible(bool(self._value))
        self.setCurrentWidget(self._display)

    def _render(self) -> None:
        tok = _t()
        # PlainText 라벨이므로 escape 없이 원문 그대로 설정 (' 등이 &#x27;로 보이던 문제 해결)
        if self._value:
            self._lbl.setText(self._value)
            self._lbl.setStyleSheet(f"color:{tok.text_primary};")
        else:
            self._lbl.setText(self._placeholder)
            self._lbl.setStyleSheet(f"color:{tok.text_muted}; font-style:italic;")

    def _enter_edit(self) -> None:
        if not self._editable:
            return
        self._edit.setText(self._value)
        self.setCurrentWidget(self._edit)
        self._edit.setFocus()
        self._edit.selectAll()

    def _commit(self) -> None:
        if self.currentWidget() is not self._edit:
            return
        new_val = self._edit.text().strip()
        self.setCurrentWidget(self._display)
        if new_val != self._value:
            self._value = new_val
            self._render()
            if self._action_btn is not None:
                self._action_btn.setVisible(bool(self._value))
            self.edited.emit(new_val)

    def _apply_theme(self) -> None:
        self._render()

class _SpinRefreshButton(QPushButton):
    """새로고침(reload) 아이콘 버튼 — 갱신 중에는 아이콘이 빙글빙글 회전한다.

    QStyle 표준 새로고침 아이콘(SP_BrowserReload)을 쓰고, `start_spin()` 동안
    QTimer로 아이콘을 회전시켜 진행 중임을 직관적으로 보여준다.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._angle = 0
        self._spinning = False
        self._base_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        self._base_pixmap = self._base_icon.pixmap(QSize(18, 18))
        self.setIconSize(QSize(18, 18))
        self.setIcon(self._base_icon)
        self._timer = QTimer(self)
        self._timer.setInterval(55)
        self._timer.timeout.connect(self._tick)

    def _tick(self) -> None:
        self._angle = (self._angle + 30) % 360
        rotated = self._base_pixmap.transformed(
            QTransform().rotate(self._angle), Qt.TransformationMode.SmoothTransformation
        )
        self.setIcon(QIcon(rotated))

    def start_spin(self) -> None:
        if not self._spinning:
            self._spinning = True
            self._timer.start()

    def stop_spin(self) -> None:
        if self._spinning:
            self._spinning = False
            self._timer.stop()
        self._angle = 0
        self.setIcon(self._base_icon)

class _LockedNotice(QWidget):
    """아직 라이브러리에 없는 영상에서 '왜 못 쓰는지 + 어떻게 푸는지'를 보여주는 판.

    요약·가사는 영상별로 DB에 저장되므로 **안정적인 로컬 video_id가 있어야** 한다
    (스트리밍/추천 영상에는 없다). 예전에는 그래서 두 탭을 통째로 비활성화했는데,
    비활성 탭은 클릭조차 되지 않아 사용자가 '왜 안 되는지'를 알 방법이 없었다.
    이제 탭은 열리되 이 안내판이 뜨고, 버튼 한 번으로 카테고리에 담아 잠금을 푼다.
    """

    action_clicked = pyqtSignal()

    def __init__(
        self, text: str, button_text: str = "카테고리에 담기",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(24, 24, 24, 24)
        col.setSpacing(12)
        col.addStretch(1)
        self._lbl = QLabel(text)
        self._lbl.setWordWrap(True)
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(self._lbl)
        self._btn = QPushButton(button_text)
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.clicked.connect(self.action_clicked.emit)
        col.addWidget(self._btn, 0, Qt.AlignmentFlag.AlignHCenter)
        col.addStretch(1)
        self._apply_theme(ThemeManager.instance().current())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)

    def _apply_theme(self, tokens) -> None:
        self._lbl.setStyleSheet(f"color:{tokens.text_secondary}; font-size:10pt;")
        self._btn.setStyleSheet(
            f"QPushButton {{ color:{tokens.text_primary}; background:{tokens.bg_elevated};"
            f" border:1px solid {tokens.border}; border-radius:4px; padding:6px 18px; }}"
            f" QPushButton:hover {{ background:{tokens.bg_surface}; }}"
        )

def _bold_font(size: int) -> QFont:
    f = QFont()
    f.setPointSize(size)
    f.setBold(True)
    return f

def _hline() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setFrameShadow(QFrame.Shadow.Sunken)
    return sep

def _wrap(widget: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(widget)
    area.setFrameShape(QFrame.Shape.NoFrame)
    return area

def _clear_layout(layout) -> None:
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())

def _open_folder(file_path: str) -> None:
    p = Path(file_path)
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(p)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(p)])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.parent)))

def _open_file(file_path: str) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(file_path))
