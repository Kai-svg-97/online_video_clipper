from __future__ import annotations

import logging
import re
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
    QTimer,
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
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QPushButton,
    QStackedWidget,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

_PAGE_LIST   = 0
_PAGE_DETAIL = 1

from application.download.dtos import DownloadJobDTO
from gui.themes.manager import ThemeManager
from gui.workers import retire_thread, track_thread
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
# 연관 영상 RelatedItem 생성 헬퍼 (라이브러리 VideoDTO → RelatedItem)
# ──────────────────────────────────────────────────────────────────
def _make_related_item(v):
    """VideoDTO를 RelatedItem으로 변환."""
    from gui.panels.video_detail_panel import RelatedItem  # noqa: PLC0415
    meta: list[str] = []
    if v.view_count:
        meta.append(f"조회수 {v.view_count:,}회")
    if v.published_at:
        meta.append(str(v.published_at))
    yt_vid_id = ""
    thumb_url = ""
    if v.url:
        m = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", v.url)
        if not m:
            m = re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", v.url)
        if m:
            yt_vid_id = m.group(1)
            thumb_url = f"https://i.ytimg.com/vi/{yt_vid_id}/hqdefault.jpg"
    return RelatedItem(
        key=str(v.id),
        title=v.title,
        channel=v.channel_name,
        duration_sec=v.duration_sec,
        meta_text="  ·  ".join(meta),
        payload=v.id,
        thumb_path=v.thumbnail_path or "",
        thumb_url=thumb_url,
        yt_video_id=yt_vid_id,
    )


# ──────────────────────────────────────────────────────────────────
# DownloadPanel — 단일 화면 (카드 그리드 ↔ 영상 상세 스택)
# ──────────────────────────────────────────────────────────────────
class DownloadPanel(QWidget):
    retry_requested                 = pyqtSignal(object)  # failed 카드 클릭 → DownloadJobDTO
    navigate_to_category_requested  = pyqtSignal(object)  # (category_id: UUID)

    def __init__(
        self,
        vm: DownloadViewModel,
        thumb_provider: Callable[[str], str | None] | None = None,
        title_provider: Callable[[str], str | None] | None = None,
        library_vm=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._vm = vm
        self._thumb_provider = thumb_provider
        self._title_provider = title_provider
        self._library_vm = library_vm
        self._worker: _ThumbWorker | None = None
        self._setup_ui()

        vm.queue_changed.connect(self._on_queue_changed)
        vm.history_changed.connect(self.refresh)

        QTimer.singleShot(0, self.refresh)

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._page_stack = QStackedWidget()
        outer.addWidget(self._page_stack)

        # ── 페이지 0: 카드 그리드 목록 ───────────────────────────────
        list_page = QWidget()
        list_layout = QVBoxLayout(list_page)
        list_layout.setContentsMargins(4, 4, 4, 4)
        list_layout.setSpacing(4)

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
        list_layout.addLayout(header_row)

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
        list_layout.addWidget(self._list)
        self._page_stack.addWidget(list_page)

        # ── 페이지 1: 영상 상세 (VideoDetailWidget 임베드) ────────────
        from gui.panels.video_detail_panel import VideoDetailWidget  # noqa: PLC0415
        detail_page = QWidget()
        detail_layout = QVBoxLayout(detail_page)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(0)

        self._detail_widget = VideoDetailWidget(download_vm=self._vm)
        self._detail_widget.back_requested.connect(self._on_detail_back)
        self._detail_widget.item_selected.connect(self._on_related_item_selected)
        self._detail_widget.download_requested.connect(
            lambda url, title, settings: self._vm.start_download(url, title, settings)
        )
        self._detail_widget.notes_saved.connect(self._on_notes_saved)
        self._detail_widget.category_path_clicked.connect(
            self.navigate_to_category_requested.emit
        )
        detail_layout.addWidget(self._detail_widget, 1)
        self._page_stack.addWidget(detail_page)

    # ── 상세화면 오픈 ────────────────────────────────────────────────

    def open_video_detail(self, video_id: UUID) -> None:
        """라이브러리 영상 상세화면을 패널 내에서 연다."""
        if self._library_vm is None:
            return
        detail = self._library_vm.get_video_detail(video_id)
        if detail is None:
            return

        cat_path = (self._library_vm.get_category_path_with_ids(detail.category_id)
                    if detail.category_id else [])

        # 연관 영상 (같은 카테고리 영상들)
        related: list = []
        if detail.category_id:
            cat_videos = self._library_vm.get_category_videos(detail.category_id, limit=30)
            related = [_make_related_item(v) for v in cat_videos if v.id != video_id]

        tag_ids = {t.name: t.id for t in self._library_vm.tags}
        self._detail_widget.load(detail, tag_ids, related=related,
                                 category_path=cat_path or None)
        self._page_stack.setCurrentIndex(_PAGE_DETAIL)

    def _on_detail_back(self) -> None:
        self._page_stack.setCurrentIndex(_PAGE_LIST)

    def _on_notes_saved(self, video_id, notes: str) -> None:
        if self._library_vm is not None:
            self._library_vm.save_notes(video_id, notes)

    def _on_related_item_selected(self, payload: object) -> None:
        if isinstance(payload, UUID):
            self.open_video_detail(payload)

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
            # 신호만 끊고 끝날 때까지 레지스트리가 붙든다 — quit()은 이벤트 루프만
            # 끝내므로 디코딩 중인 run()은 계속 돌고, 그 상태로 삭제되면 앱이 죽는다.
            retire_thread(self._worker, self._worker.batch_ready)
        paths = self._model.thumb_paths()
        if not paths:
            return
        # 부모로 매달지 않는다 — 패널이 사라지는 순간 실행 중이면 앱이 죽는다.
        self._worker = track_thread(_ThumbWorker(paths))
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
            # URL → video_id 조회 후 패널 내 상세 오픈
            if self._library_vm is not None:
                video_id = self._library_vm.find_video_id_by_url(job.url)
                if video_id is not None:
                    self.open_video_detail(video_id)
                    return
            # 라이브러리에 없으면 외부 핸들러로 fallback (이전 동작)
            # (연결된 슬롯 없으므로 무시됨)
