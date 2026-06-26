from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Callable
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
    QPushButton,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from application.download.dtos import DownloadJobDTO
from gui.themes.manager import ThemeManager
from gui.view_models.download_vm import DownloadViewModel

logger = logging.getLogger(__name__)

_VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".m4a", ".mp3", ".opus"}
_THUMB_EXTS = (".jpg", ".webp", ".png")

CARD_W   = 200
THUMB_H  = 112  # 16:9 비율
TEXT_H   = 48
CARD_H   = THUMB_H + TEXT_H
CARD_PAD = 6


def _t():
    return ThemeManager.instance().current()


def _is_listable_history(job: DownloadJobDTO) -> bool:
    """완료 이력에 표시할 항목 판정.

    file_path가 있으면 영상 확장자만 표시(.part 제외).
    file_path가 없는 실패 작업은 '실패' 카드로 표시.
    """
    if not job.file_path:
        return bool(job.error_msg)
    suffix = Path(job.file_path).suffix.lower()
    if suffix == ".part":
        return False
    return suffix in _VIDEO_EXTS


def _dedupe_by_url(jobs: list[DownloadJobDTO]) -> list[DownloadJobDTO]:
    """동일 URL을 하나의 카드로 합침. jobs는 created_at DESC 정렬 가정."""
    import dataclasses  # noqa: PLC0415
    seen: dict[str, DownloadJobDTO] = {}
    for job in jobs:
        url = job.url
        if url not in seen:
            seen[url] = job
        else:
            existing = seen[url]
            if (not existing.title or existing.title == existing.url) and \
               job.title and job.title != job.url:
                seen[url] = dataclasses.replace(existing, title=job.title)
    return list(seen.values())


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
# 썸네일 LRU 캐시 (컬러 + 그레이스케일, 각 60개)
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
_dl_gray_cache  = _ThumbCache(60)


def _thumb_key(path: str) -> str:
    return f"{path}@{CARD_W}x{THUMB_H}"


def _thumb_gray_key(path: str) -> str:
    return f"{path}@gray{CARD_W}x{THUMB_H}"


# ──────────────────────────────────────────────────────────────────
# 백그라운드 썸네일 워커
# QImage는 비-GUI 스레드에서 안전하게 생성 가능(Qt 명세).
# QPixmap 변환은 main thread에서만 수행(notify_thumbs_loaded).
# 컬러 + 그레이스케일 두 버전 동시 생성.
# ──────────────────────────────────────────────────────────────────
class _ThumbWorker(QThread):
    # list[tuple[path, color_QImage, gray_QImage]]
    batch_ready = pyqtSignal(list)

    def __init__(self, paths: list[str], parent=None) -> None:
        super().__init__(parent)
        self._paths = paths

    def run(self) -> None:
        results: list[tuple[str, QImage, QImage]] = []
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
                gray = scaled.convertToFormat(QImage.Format.Format_Grayscale8)
                results.append((path, scaled, gray))
            except Exception:
                logger.debug("썸네일 로드 실패: %s", path)
        if results:
            self.batch_ready.emit(results)


# ──────────────────────────────────────────────────────────────────
# 이력 모델
# ──────────────────────────────────────────────────────────────────
class _HistoryModel(QAbstractListModel):
    StatusRole   = Qt.ItemDataRole.UserRole + 1
    ErrorRole    = Qt.ItemDataRole.UserRole + 2
    ThumbRole    = Qt.ItemDataRole.UserRole + 3
    JobRole      = Qt.ItemDataRole.UserRole + 4
    IsActiveRole = Qt.ItemDataRole.UserRole + 5

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._jobs: list[DownloadJobDTO] = []
        self._thumbs: dict[str, str] = {}   # str(job.id) → thumb path
        self._active_ids: set[UUID] = set()

    def set_all(
        self,
        active: list[DownloadJobDTO],
        history: list[DownloadJobDTO],
        thumb_provider: Callable[[str], str | None] | None = None,
        title_provider: Callable[[str], str | None] | None = None,
    ) -> None:
        import dataclasses  # noqa: PLC0415

        def _fix_title(job: DownloadJobDTO) -> DownloadJobDTO:
            if (not job.title or job.title == job.url) and title_provider:
                t = title_provider(job.url)
                if t:
                    return dataclasses.replace(job, title=t)
            return job

        self.beginResetModel()

        resolved_active = [_fix_title(j) for j in active]
        active_urls = {j.url for j in active}

        # 이력에서 활성 URL 제외(중복 방지) 후 병합
        unique_history = [j for j in _dedupe_by_url(history) if j.url not in active_urls]
        resolved_history = [_fix_title(j) for j in unique_history]

        self._jobs = resolved_active + resolved_history
        self._active_ids = {j.id for j in active}

        self._thumbs = {}
        for j in self._jobs:
            p = _resolve_thumb(j)
            if p is None and thumb_provider and j.url:
                try:
                    p = thumb_provider(j.url)
                except Exception:
                    p = None
            if p:
                self._thumbs[str(j.id)] = p

        self.endResetModel()

    def update_active_progress(self, active_jobs: list[DownloadJobDTO]) -> bool:
        """진행 중 항목의 progress만 in-place 갱신. 구조 변경이면 False 반환."""
        if len(active_jobs) != len(self._active_ids):
            return False

        active_by_id = {j.id: j for j in active_jobs}
        for row, job in enumerate(self._jobs):
            if job.id not in self._active_ids:
                continue
            new_job = active_by_id.get(job.id)
            if new_job and new_job.progress.percent != job.progress.percent:
                self._jobs[row] = new_job
                idx = self.index(row, 0)
                self.dataChanged.emit(idx, idx, [self.JobRole])
        return True

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
        if role == self.IsActiveRole:
            return job.id in self._active_ids
        return None

    def notify_thumbs_loaded(self, results: list) -> None:
        """백그라운드 워커에서 받은 QImage 쌍을 QPixmap으로 변환해 캐시에 저장."""
        loaded_paths: set[str] = set()
        for path, img, gray_img in results:
            _dl_thumb_cache.put(_thumb_key(path), QPixmap.fromImage(img))
            _dl_gray_cache.put(_thumb_gray_key(path), QPixmap.fromImage(gray_img))
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
        is_active: bool = bool(index.data(_HistoryModel.IsActiveRole))
        status: str = job.status if job else "?"
        pct: float = job.progress.percent if job else 0.0

        color_pm: QPixmap | None = (
            _dl_thumb_cache.get(_thumb_key(thumb_path)) if thumb_path else None
        )
        gray_pm: QPixmap | None = (
            _dl_gray_cache.get(_thumb_gray_key(thumb_path)) if thumb_path else None
        )

        clip_path = QPainterPath()
        clip_path.addRoundedRect(
            float(tx), float(ty), float(CARD_W), float(THUMB_H), 6.0, 6.0
        )

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if is_active:
            # ── 진행 중: 그레이스케일 배경 + 진행도만큼 컬러 reveal ────
            split_x = int(CARD_W * min(pct, 100.0) / 100.0)

            if color_pm and not color_pm.isNull():
                if gray_pm and not gray_pm.isNull():
                    painter.setClipPath(clip_path)
                    painter.drawPixmap(tx, ty, gray_pm)
                    if split_x > 0:
                        left_part = QPainterPath()
                        left_part.addRect(
                            float(tx), float(ty), float(split_x), float(THUMB_H)
                        )
                        painter.setClipPath(clip_path.intersected(left_part))
                        painter.drawPixmap(tx, ty, color_pm)
                else:
                    # 그레이스케일 미로드 시 폴백: 컬러 + 어두운 오버레이
                    painter.setClipPath(clip_path)
                    painter.drawPixmap(tx, ty, color_pm)
                    if split_x < CARD_W:
                        painter.fillRect(
                            QRect(tx + split_x, ty, CARD_W - split_x, THUMB_H),
                            QColor(0, 0, 0, 160),
                        )
            else:
                painter.setClipPath(clip_path)
                painter.fillPath(clip_path, QColor(tok.bg_overlay))
                painter.setFont(QFont("", 22))
                painter.setPen(QColor(tok.text_muted))
                painter.drawText(
                    QRect(tx, ty, CARD_W, THUMB_H),
                    Qt.AlignmentFlag.AlignCenter,
                    (title[:1] or "?").upper(),
                )
        else:
            # ── 완료/실패 카드: 컬러 썸네일 ─────────────────────────────
            painter.setClipPath(clip_path)
            if color_pm and not color_pm.isNull():
                painter.drawPixmap(tx, ty, color_pm)
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

        # ── 진행 중 퍼센트 텍스트 오버레이 ─────────────────────────────
        if is_active:
            pct_text = f"{int(pct)}%"
            mid_y = ty + THUMB_H // 2 - 14
            painter.save()
            painter.fillRect(QRect(tx, mid_y, CARD_W, 28), QColor(0, 0, 0, 120))
            painter.setFont(QFont("", 14, QFont.Weight.Bold))
            painter.setPen(QColor("white"))
            painter.drawText(
                QRect(tx, mid_y, CARD_W, 28),
                Qt.AlignmentFlag.AlignCenter,
                pct_text,
            )
            painter.restore()

        # ── 상태 배지 (진행 중은 퍼센트로 대체) ─────────────────────────
        if not is_active:
            if status == "completed":
                badge_bg = QColor("#4caf50")
                badge_ch = "✓"
            elif status == "failed":
                badge_bg = QColor("#ff9800")   # 주황 = 재시도 가능
                badge_ch = "↺"
            else:
                badge_bg = QColor("#888888")
                badge_ch = "–"

            bx, by, br = tx + CARD_W - 22, ty + 4, 9
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(badge_bg)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(bx, by, br * 2, br * 2)
            painter.setFont(QFont("", 8, QFont.Weight.Bold))
            painter.setPen(QColor("white"))
            painter.drawText(
                QRect(bx, by, br * 2, br * 2),
                Qt.AlignmentFlag.AlignCenter,
                badge_ch,
            )
            painter.restore()

        # ── 제목 텍스트 ───────────────────────────────────────────────
        painter.save()
        painter.setFont(QFont("", 9))
        painter.setPen(QColor(tok.text_primary))
        painter.drawText(
            QRect(tx, ty + THUMB_H + 4, CARD_W, TEXT_H - 4),
            Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignTop,
            title,
        )
        painter.restore()

        # ── 선택/호버 테두리 ─────────────────────────────────────────
        is_sel = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hov = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if is_sel or is_hov:
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            border = QPainterPath()
            border.addRoundedRect(
                float(tx), float(ty), float(CARD_W), float(THUMB_H), 6.0, 6.0
            )
            pen = QPen(QColor(tok.selected_border if is_sel else tok.text_secondary))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(border)
            painter.restore()


# ──────────────────────────────────────────────────────────────────
# DownloadPanel — 단일 카드 그리드 화면 (탭 없음)
# ──────────────────────────────────────────────────────────────────
class DownloadPanel(QWidget):
    video_open_requested = pyqtSignal(str)    # completed 카드 클릭 → URL
    retry_requested      = pyqtSignal(object) # failed 카드 클릭 → DownloadJobDTO

    def __init__(
        self,
        vm: DownloadViewModel,
        thumb_provider: Callable[[str], str | None] | None = None,
        title_provider: Callable[[str], str | None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._vm = vm
        self._thumb_provider = thumb_provider
        self._title_provider = title_provider
        self._worker: _ThumbWorker | None = None
        self._setup_ui()

        vm.queue_changed.connect(self._on_queue_changed)
        vm.history_changed.connect(self.refresh)

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(2, 0, 2, 0)
        hdr = QLabel("다운로드")
        hdr.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        refresh_btn = QPushButton("새로고침")
        refresh_btn.setFixedHeight(24)
        refresh_btn.clicked.connect(self.refresh)
        header_row.addWidget(hdr)
        header_row.addStretch()
        header_row.addWidget(refresh_btn)
        outer.addLayout(header_row)

        self._model    = _HistoryModel()
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

    # ── 데이터 갱신 ─────────────────────────────────────────────────

    def refresh(self) -> None:
        """완전 갱신: 활성 다운로드 + 이력 병합."""
        active  = self._vm.queue
        history = self._vm.load_history()
        filtered = [j for j in history if _is_listable_history(j)]
        self._model.set_all(active, filtered, self._thumb_provider, self._title_provider)
        self._start_thumb_worker()

    def _on_queue_changed(self) -> None:
        """progress 경량 갱신. 구조 변경(새 다운로드 시작·종료) 시에만 full refresh."""
        active = self._vm.queue
        if not self._model.update_active_progress(active):
            self.refresh()

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

    # ── 클릭 핸들러 ─────────────────────────────────────────────────

    def _on_card_clicked(self, index: QModelIndex) -> None:
        job: DownloadJobDTO | None = index.data(_HistoryModel.JobRole)
        if not job:
            return
        if bool(index.data(_HistoryModel.IsActiveRole)):
            return  # 진행 중 카드 클릭 무시
        if job.status == "failed":
            self.retry_requested.emit(job)
        elif job.url:
            self.video_open_requested.emit(job.url)
