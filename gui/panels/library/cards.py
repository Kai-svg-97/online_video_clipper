"""폴더·재생목록 카드 그리드 부품 — 폴더 안 내용을 카드로 보여 주는 화면."""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import (
    QRect,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QFont, QPainter, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config.settings import THUMBNAIL_DIR

from gui.panels.library.formatting import _fmt_elapsed, _t

logger = logging.getLogger(__name__)


class _PlaylistThumbLabel(QLabel):
    """재생목록 카드 썸네일 — 영상 개수 배지를 우하단에 오버레이."""

    _W, _H = 213, 120

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._thumb: QPixmap | None = None
        self._count: int = 0
        self.setFixedSize(self._W, self._H)

    def set_data(self, thumb_path: str, count: int) -> None:
        self._count = count
        self._thumb = None
        if thumb_path:
            p = Path(THUMBNAIL_DIR) / thumb_path
            if p.exists():
                pix = QPixmap(str(p))
                if not pix.isNull():
                    self._thumb = pix.scaled(
                        self._W, self._H,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        painter.fillRect(rect, QColor(30, 30, 30))
        if self._thumb:
            sw, sh = self._thumb.width(), self._thumb.height()
            sx = max(0, (sw - self._W) // 2)
            sy = max(0, (sh - self._H) // 2)
            painter.drawPixmap(rect, self._thumb, QRect(sx, sy, self._W, self._H))
        else:
            painter.setPen(QColor(90, 90, 90))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "No thumbnail")
        if self._count > 0:
            bw, bh = 46, 20
            bx = rect.right() - bw - 4
            by = rect.bottom() - bh - 4
            painter.fillRect(QRect(bx, by, bw, bh), QColor(0, 0, 0, 170))
            painter.setPen(QColor(255, 255, 255))
            f = QFont()
            f.setPointSize(8)
            f.setBold(True)
            painter.setFont(f)
            painter.drawText(QRect(bx, by, bw, bh), Qt.AlignmentFlag.AlignCenter, f"▶ {self._count}")
        painter.end()


class _BaseCard(QFrame):
    """hover 테두리 효과를 공통 제공하는 카드 기반 클래스."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._hovered = False

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._hovered:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            c = self.palette().highlight().color()
            c.setAlpha(120)
            painter.setPen(QPen(c, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.rect().adjusted(1, 1, -1, -1))
            painter.end()


class _FolderCard(_BaseCard):
    """섹션 루트 뷰의 폴더 디렉터리 카드."""

    clicked = pyqtSignal(object)   # folder UUID

    def __init__(self, folder, parent=None) -> None:
        super().__init__(parent)
        self._folder_id = folder.id
        self.setFixedWidth(221)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        icon_lbl = QLabel("📂")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("font-size:36pt;")
        layout.addWidget(icon_lbl)
        name_lbl = QLabel(folder.name)
        name_lbl.setWordWrap(True)
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setStyleSheet("font-size:9pt; font-weight:600;")
        layout.addWidget(name_lbl)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._folder_id)
        super().mousePressEvent(event)


class _UnfiledCard(_BaseCard):
    """섹션 루트 뷰의 '미분류' 디렉터리 카드."""

    clicked = pyqtSignal()

    def __init__(self, count: int, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(221)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        icon_lbl = QLabel("📂")
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("font-size:36pt;")
        layout.addWidget(icon_lbl)
        name_lbl = QLabel(f"미분류  ({count})" if count else "미분류")
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_lbl.setStyleSheet("font-size:9pt; font-weight:600; color:#aaa;")
        layout.addWidget(name_lbl)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _PlaylistCard(_BaseCard):
    """폴더 뷰의 재생목록 카드 한 장."""

    clicked = pyqtSignal(object)   # playlist UUID

    def __init__(self, pl, get_first_item, parent=None) -> None:
        super().__init__(parent)
        self._pl_id = pl.id
        self.setFixedWidth(221)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFrameShape(QFrame.Shape.StyledPanel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._thumb = _PlaylistThumbLabel()
        layout.addWidget(self._thumb)

        title_lbl = QLabel(pl.title)
        title_lbl.setWordWrap(True)
        title_lbl.setMaximumHeight(38)
        title_lbl.setStyleSheet("font-size:9pt; font-weight:600;")
        layout.addWidget(title_lbl)

        time_lbl = QLabel(_fmt_elapsed(pl.updated_at))
        time_lbl.setStyleSheet(f"font-size:8pt; color:{_t().text_secondary};")
        layout.addWidget(time_lbl)

        first = get_first_item(pl.id) if get_first_item else None
        self._thumb.set_data(first.thumbnail_path if first else "", pl.item_count)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._pl_id)
        super().mousePressEvent(event)


class _FolderContentsView(QScrollArea):
    """폴더/섹션 루트 선택 시 하위 폴더·미분류·재생목록을 카드 그리드로 표시한다."""

    playlist_selected = pyqtSignal(object)   # playlist UUID
    folder_selected   = pyqtSignal(object)   # folder UUID

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self._container = QWidget()
        self._grid = None   # QGridLayout — 카드 로드 시 생성
        self.setWidget(self._container)

    def load(
        self,
        playlists: list,
        get_first_item,
        folders: list | None = None,
        show_unfiled: bool = False,
        unfiled_count: int = 0,
    ) -> None:
        """폴더 카드(선택적) + 미분류 카드(선택적) + 재생목록 카드를 그리드로 표시한다."""
        # 이전 카드 전부 제거
        old_layout = self._container.layout()
        if old_layout is not None:
            while old_layout.count():
                item = old_layout.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()
            QWidget().setLayout(old_layout)

        from PyQt6.QtWidgets import QGridLayout  # noqa: PLC0415
        grid = QGridLayout(self._container)
        grid.setSpacing(12)
        grid.setContentsMargins(12, 12, 12, 12)
        cols = 3
        idx = 0

        # ── 폴더 카드 ──
        for f in (folders or []):
            card = _FolderCard(f, self._container)
            card.clicked.connect(self.folder_selected)
            grid.addWidget(card, idx // cols, idx % cols)
            idx += 1

        # ── 미분류 카드 ──
        if show_unfiled:
            card = _UnfiledCard(unfiled_count, self._container)
            card.clicked.connect(lambda: self.folder_selected.emit(None))
            grid.addWidget(card, idx // cols, idx % cols)
            idx += 1

        # ── 재생목록 카드 ──
        for pl in playlists:
            card = _PlaylistCard(pl, get_first_item, self._container)
            card.clicked.connect(self.playlist_selected)
            grid.addWidget(card, idx // cols, idx % cols)
            idx += 1

        if idx > 0:
            grid.setColumnStretch(cols, 1)
            grid.setRowStretch((idx - 1) // cols + 1, 1)
        self._grid = grid

        if idx == 0:
            lbl = QLabel("이 폴더에 재생목록이 없습니다.")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(f"color:{_t().text_secondary}; font-size:11pt;")
            grid.addWidget(lbl, 0, 0)
