from __future__ import annotations

import logging
from collections import OrderedDict
from pathlib import Path
from uuid import UUID

from PyQt6.QtCore import (
    QAbstractListModel,
    QModelIndex,
    QRect,
    QSize,
    Qt,
    QThread,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListView,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStyledItemDelegate,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from application.download.dtos import DownloadJobDTO
from gui.themes.manager import ThemeManager
from gui.view_models.download_vm import DownloadViewModel

logger = logging.getLogger(__name__)

_VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".m4a", ".mp3", ".opus"}
_THUMB_EXTS = (".jpg", ".webp", ".png")

CARD_W  = 200
THUMB_H = 112   # 16:9 비율
TEXT_H  = 48
CARD_H  = THUMB_H + TEXT_H
CARD_PAD = 6


def _t():
    return ThemeManager.instance().current()


def _is_listable_history(job: DownloadJobDTO) -> bool:
    """완료 이력에 표시할 항목인지 판정.

    file_path가 있으면 영상 확장자만 표시(썸네일 .jpg/.webp·중단 파일 .part 등 제외).
    file_path가 없는 실패 작업은 '실패' 카드로 그대로 보여준다.
    """
    if not job.file_path:
        return bool(job.error_msg)
    suffix = Path(job.file_path).suffix.lower()
    if suffix == ".part":
        return False
    return suffix in _VIDEO_EXTS


def _fmt_size(b: int | None) -> str:
    if b is None:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"


def _resolve_thumb(job: DownloadJobDTO) -> str | None:
    """yt-dlp가 영상 옆에 생성하는 동행 썸네일 파일 경로를 반환한다."""
    if not job.file_path:
        return None
    p = Path(job.file_path)
    for ext in _THUMB_EXTS:
        t = p.with_suffix(ext)
        if t.exists():
            return str(t)
    return None


# ──────────────────────────────────────────────────────────────────
# 썸네일 LRU 캐시 (다운로드 패널 전용, 최대 60개)
# ──────────────────────────────────────────────────────────────────
class _ThumbCache:
    def __init__(self, maxsize: int = 60) -> None:
        self._cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._maxsize = maxsize

    def get(self, key: str) -> QPixmap | None:
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put(self, key: str, pm: QPixmap) -> None:
        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            if len(self._cache) >= self._maxsize:
                self._cache.popitem(last=False)
            self._cache[key] = pm


_dl_thumb_cache = _ThumbCache(60)


def _thumb_key(path: str) -> str:
    return f"{path}@{CARD_W}x{THUMB_H}"


# ──────────────────────────────────────────────────────────────────
# 백그라운드 썸네일 워커
# QImage는 비-GUI 스레드에서 안전하게 생성 가능(Qt 명세).
# QPixmap 변환은 수신 슬롯(notify_thumbs_loaded) — main thread에서만 수행.
# ──────────────────────────────────────────────────────────────────
class _ThumbWorker(QThread):
    batch_ready = pyqtSignal(list)  # list[tuple[str, QImage]]

    def __init__(self, paths: list[str], parent=None) -> None:
        super().__init__(parent)
        self._paths = paths

    def run(self) -> None:
        results: list[tuple[str, QImage]] = []
        for path in self._paths:
            if _dl_thumb_cache.get(_thumb_key(path)) is not None:
                continue
            try:
                img = QImage(path)
                if img.isNull():
                    continue
                scaled = img.scaled(
                    CARD_W, THUMB_H,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                results.append((path, scaled))
            except Exception:
                logger.debug("썸네일 로드 실패: %s", path)
        if results:
            self.batch_ready.emit(results)


# ──────────────────────────────────────────────────────────────────
# 이력 모델
# ──────────────────────────────────────────────────────────────────
class _HistoryModel(QAbstractListModel):
    StatusRole = Qt.ItemDataRole.UserRole + 1
    ErrorRole  = Qt.ItemDataRole.UserRole + 2
    ThumbRole  = Qt.ItemDataRole.UserRole + 3
    JobRole    = Qt.ItemDataRole.UserRole + 4

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._jobs: list[DownloadJobDTO] = []
        self._thumbs: dict[str, str] = {}  # str(job.id) → thumb path

    def set_jobs(self, jobs: list[DownloadJobDTO]) -> None:
        self.beginResetModel()
        self._jobs = jobs
        self._thumbs = {}
        for j in jobs:
            p = _resolve_thumb(j)
            if p:
                self._thumbs[str(j.id)] = p
        self.endResetModel()

    def thumb_paths(self) -> list[str]:
        return list(self._thumbs.values())

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._jobs)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self._jobs):
            return None
        job = self._jobs[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return job.title or job.url
        if role == self.StatusRole:
            return job.status
        if role == self.ErrorRole:
            return job.error_msg
        if role == self.ThumbRole:
            return self._thumbs.get(str(job.id))
        if role == self.JobRole:
            return job
        return None

    def notify_thumbs_loaded(self, results: list) -> None:
        """백그라운드 워커에서 받은 QImage를 QPixmap으로 변환해 캐시에 저장하고 재그리기 요청."""
        loaded_paths: set[str] = set()
        for path, img in results:
            pm = QPixmap.fromImage(img)
            _dl_thumb_cache.put(_thumb_key(path), pm)
            loaded_paths.add(path)

        for row, job in enumerate(self._jobs):
            p = self._thumbs.get(str(job.id))
            if p and p in loaded_paths:
                idx = self.index(row, 0)
                self.dataChanged.emit(idx, idx, [self.ThumbRole])


# ──────────────────────────────────────────────────────────────────
# 이력 카드 델리게이트
# ──────────────────────────────────────────────────────────────────
class _HistoryCardDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index) -> QSize:
        return QSize(CARD_W + CARD_PAD * 2, CARD_H + CARD_PAD * 2)

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        from PyQt6.QtWidgets import QApplication, QStyle  # noqa: PLC0415
        QApplication.style().drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, option.widget
        )

        tok = _t()
        rect = option.rect
        tx = rect.left() + CARD_PAD
        ty = rect.top() + CARD_PAD

        title: str = index.data(Qt.ItemDataRole.DisplayRole) or ""
        thumb_path: str | None = index.data(_HistoryModel.ThumbRole)
        job: DownloadJobDTO | None = index.data(_HistoryModel.JobRole)
        status: str = job.status if job else "?"

        # ── 썸네일 (둥근 모서리) ────────────────────────────────────
        pm: QPixmap | None = _dl_thumb_cache.get(_thumb_key(thumb_path)) if thumb_path else None

        clip_path = QPainterPath()
        clip_path.addRoundedRect(float(tx), float(ty), float(CARD_W), float(THUMB_H), 6.0, 6.0)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipPath(clip_path)
        if pm and not pm.isNull():
            painter.drawPixmap(tx, ty, pm)
        else:
            painter.fillPath(clip_path, QColor(tok.bg_overlay))
            painter.setFont(QFont("", 22))
            painter.setPen(QColor(tok.text_muted))
            painter.drawText(
                QRect(tx, ty, CARD_W, THUMB_H),
                Qt.AlignmentFlag.AlignCenter,
                (title[:1] or "?").upper(),
            )
        painter.restore()

        # ── 상태 배지 (우상단 작은 원형 아이콘) ────────────────────
        if status == "completed":
            badge_bg = QColor("#4caf50")
            badge_ch = "✓"
        elif status == "failed":
            badge_bg = QColor("#f44336")
            badge_ch = "✗"
        else:
            badge_bg = QColor("#888888")
            badge_ch = "–"

        bx, by, br = tx + CARD_W - 22, ty + 4, 9  # 18×18 원
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(badge_bg)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(bx, by, br * 2, br * 2)
        painter.setFont(QFont("", 8, QFont.Weight.Bold))
        painter.setPen(QColor("white"))
        painter.drawText(QRect(bx, by, br * 2, br * 2), Qt.AlignmentFlag.AlignCenter, badge_ch)
        painter.restore()

        # ── 제목 텍스트 (썸네일 아래) ──────────────────────────────
        painter.save()
        painter.setFont(QFont("", 9))
        painter.setPen(QColor(tok.text_primary))
        painter.drawText(
            QRect(tx, ty + THUMB_H + 4, CARD_W, TEXT_H - 4),
            Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignTop,
            title,
        )
        painter.restore()

        # ── 선택 / 호버 테두리 ─────────────────────────────────────
        is_sel = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hov = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if is_sel or is_hov:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            border = QPainterPath()
            border.addRoundedRect(float(tx), float(ty), float(CARD_W), float(THUMB_H), 6.0, 6.0)
            pen = QPen(QColor(tok.selected_border if is_sel else tok.text_secondary))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(border)
            painter.restore()


# ──────────────────────────────────────────────────────────────────
# 진행 중인 다운로드 행 (변경 없음)
# ──────────────────────────────────────────────────────────────────
class _JobRow(QWidget):
    """진행 중인 다운로드 행."""

    def __init__(self, job: DownloadJobDTO, on_cancel, parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        self._title = QLabel(job.title)
        self._title.setMaximumWidth(300)
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setTextVisible(False)
        self._bar.setValue(int(job.progress.percent))
        self._speed = QLabel(job.progress.speed_formatted())
        cancel_btn = QPushButton("✕")
        cancel_btn.setFixedWidth(28)
        cancel_btn.clicked.connect(lambda: on_cancel(job.id))

        layout.addWidget(self._title)
        layout.addWidget(self._bar, 1)
        layout.addWidget(self._speed)
        layout.addWidget(cancel_btn)

    def update_job(self, job: DownloadJobDTO) -> None:
        self._bar.setValue(int(job.progress.percent))
        self._speed.setText(job.progress.speed_formatted())


# ──────────────────────────────────────────────────────────────────
# 진행 중 탭 (변경 없음)
# ──────────────────────────────────────────────────────────────────
class _QueueTab(QWidget):
    """진행 중인 다운로드 탭."""

    def __init__(self, vm: DownloadViewModel, parent=None) -> None:
        super().__init__(parent)
        self._vm = vm
        self._rows: dict[UUID, _JobRow] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.addStretch()
        scroll.setWidget(self._container)
        outer.addWidget(scroll)

        vm.queue_changed.connect(self.refresh)

    def refresh(self) -> None:
        jobs = self._vm.queue
        current_ids = {j.id for j in jobs}

        for job_id in list(self._rows):
            if job_id not in current_ids:
                row = self._rows.pop(job_id)
                self._container_layout.removeWidget(row)
                row.deleteLater()

        for job in jobs:
            if job.id in self._rows:
                self._rows[job.id].update_job(job)
            else:
                row = _JobRow(job, self._vm.cancel_download, self._container)
                self._rows[job.id] = row
                self._container_layout.insertWidget(
                    self._container_layout.count() - 1, row
                )


# ──────────────────────────────────────────────────────────────────
# 완료/실패 이력 탭 (카드 그리드)
# ──────────────────────────────────────────────────────────────────
class _HistoryTab(QWidget):
    video_open_requested = pyqtSignal(str)  # URL

    def __init__(self, vm: DownloadViewModel, parent=None) -> None:
        super().__init__(parent)
        self._vm = vm
        self._worker: _ThumbWorker | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(6, 4, 6, 4)
        refresh_btn = QPushButton("새로고침")
        refresh_btn.setFixedHeight(24)
        refresh_btn.clicked.connect(self.refresh)
        header_row.addStretch()
        header_row.addWidget(refresh_btn)
        outer.addLayout(header_row)

        self._model = _HistoryModel()
        self._delegate = _HistoryCardDelegate()

        self._list = QListView()
        self._list.setModel(self._model)
        self._list.setItemDelegate(self._delegate)
        self._list.setViewMode(QListView.ViewMode.IconMode)
        self._list.setResizeMode(QListView.ResizeMode.Adjust)
        self._list.setSpacing(8)
        self._list.setUniformItemSizes(True)
        self._list.setMovement(QListView.Movement.Static)
        self._list.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self._list.setMouseTracking(True)
        self._list.clicked.connect(self._on_card_clicked)
        outer.addWidget(self._list)

        vm.history_changed.connect(self.refresh)

    def refresh(self) -> None:
        all_jobs = self._vm.load_history()
        jobs = [j for j in all_jobs if _is_listable_history(j)]
        self._model.set_jobs(jobs)
        self._start_thumb_worker()

    def _start_thumb_worker(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.batch_ready.disconnect()
            self._worker.quit()
        paths = self._model.thumb_paths()
        if not paths:
            return
        self._worker = _ThumbWorker(paths, self)
        self._worker.batch_ready.connect(self._model.notify_thumbs_loaded)
        self._worker.start()

    def _on_card_clicked(self, index: QModelIndex) -> None:
        job: DownloadJobDTO | None = index.data(_HistoryModel.JobRole)
        if job and job.url:
            self.video_open_requested.emit(job.url)


# ──────────────────────────────────────────────────────────────────
# DownloadPanel
# ──────────────────────────────────────────────────────────────────
class DownloadPanel(QWidget):
    video_open_requested = pyqtSignal(str)  # URL — 카드 클릭 시 라이브러리 상세화면으로 이동

    def __init__(self, vm: DownloadViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vm = vm
        self._setup_ui()

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        header = QLabel("다운로드")
        header.setAlignment(Qt.AlignmentFlag.AlignLeft)
        outer.addWidget(header)

        tabs = QTabWidget()
        self._queue_tab = _QueueTab(self._vm)
        self._history_tab = _HistoryTab(self._vm)
        self._history_tab.video_open_requested.connect(self.video_open_requested)
        tabs.addTab(self._queue_tab, "진행 중")
        tabs.addTab(self._history_tab, "완료 이력")
        tabs.currentChanged.connect(self._on_tab_changed)
        outer.addWidget(tabs)

    def _on_tab_changed(self, index: int) -> None:
        if index == 1:
            self._history_tab.refresh()
