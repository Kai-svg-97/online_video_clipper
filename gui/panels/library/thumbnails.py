"""썸네일 로딩·캐시 — 저사양 PC 메모리 규칙(LRU + 표시 크기로만 보관)을 지키는 곳.

전역 캐시 인스턴스(`_thumb_cache`)가 여기 있으므로, 화면 부품들은 이 모듈을 통해서만
썸네일을 얻는다. 원본 QImage를 들고 있지 않고 **표시 크기로 축소한 QPixmap**만 캐시한다.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from pathlib import Path

from PyQt6.QtCore import (
    QThread,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QImage, QPixmap,
)

from config.settings import LRU_THUMBNAIL_MAX, THUMBNAIL_DIR

from gui.panels.library.constants import _THUMB_RENDER_SIZE_KINDS
from gui.panels.library.formatting import _t

logger = logging.getLogger(__name__)


class _ThumbnailCache:
    def __init__(self, maxsize: int = LRU_THUMBNAIL_MAX) -> None:
        self._cache: OrderedDict[str, QPixmap] = OrderedDict()
        self._maxsize = maxsize

    def get(self, key: str) -> QPixmap | None:
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put(self, key: str, pixmap: QPixmap) -> None:
        self._cache[key] = pixmap
        self._cache.move_to_end(key)
        if len(self._cache) > self._maxsize:
            self._cache.popitem(last=False)


_thumb_cache = _ThumbnailCache(LRU_THUMBNAIL_MAX * _THUMB_RENDER_SIZE_KINDS)


def _load_thumb(thumbnail_path: str, w: int, h: int) -> QPixmap:
    """Load thumbnail scaled to (w, h); cached by path+size."""
    key = f"{thumbnail_path}@{w}x{h}" if thumbnail_path else f"__ph__{w}x{h}"
    cached = _thumb_cache.get(key)
    if cached is not None:
        return cached

    if thumbnail_path:
        full = Path(THUMBNAIL_DIR) / thumbnail_path
        if full.exists():
            src = QPixmap(str(full))
            if not src.isNull():
                scaled = src.scaled(
                    w, h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                _thumb_cache.put(key, scaled)
                return scaled

    pm = QPixmap(w, h)
    pm.fill(QColor(_t().bg_overlay))
    _thumb_cache.put(key, pm)
    return pm


def _load_thumb_async(thumbnail_path: str, w: int, h: int) -> QPixmap:
    """캐시 히트 시 즉시 반환, 미스 시 플레이스홀더 반환 (파일 I/O 없음).
    _ThumbBgLoader가 백그라운드에서 파일을 읽어 캐시를 채운 뒤 dataChanged로 재그리기 요청한다."""
    key = f"{thumbnail_path}@{w}x{h}" if thumbnail_path else f"__ph__{w}x{h}"
    cached = _thumb_cache.get(key)
    if cached is not None:
        return cached
    pm = QPixmap(w, h)
    pm.fill(QColor(_t().bg_overlay))
    return pm


class _ThumbBgLoader(QThread):
    """백그라운드에서 QImage를 로드하고 배치 단위로 메인 스레드로 전달한다.

    QImage는 비-GUI 스레드에서 안전하게 생성 가능(Qt 명세).
    QPixmap 변환은 수신 슬롯(_on_thumb_batch) — main thread 에서만 수행한다.
    """
    batch_ready = pyqtSignal(list)  # list[(path: str, w: int, h: int, img: QImage)]

    _IO_SEMA = threading.Semaphore(4)  # 동시 파일 읽기 4개 제한

    def __init__(self, items: list[tuple[str, int, int]], parent=None) -> None:
        super().__init__(parent)
        self._items = items
        self._cancelled = False

    def cancel(self) -> None:
        """남은 항목의 디코딩을 중단한다(협조적 취소).

        검색어를 입력하면 결과 목록이 연달아 바뀌는데, 이전 결과의 썸네일 50장을
        계속 디코딩하면 CPU·GIL을 잡아 메인 스레드 입력이 밀린다.
        """
        self._cancelled = True

    def run(self) -> None:
        batch: list = []
        for path, w, h in self._items:
            if self._cancelled:
                return
            key = f"{path}@{w}x{h}"
            if _thumb_cache.get(key) is not None:
                continue  # 이미 캐시에 있으면 스킵 (읽기만이므로 스레드 안전)
            full = Path(THUMBNAIL_DIR) / path
            if not full.exists():
                continue
            with self._IO_SEMA:
                img = QImage(str(full))
            if img.isNull():
                continue
            scaled = img.scaled(
                w, h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            batch.append((path, w, h, scaled))
            if len(batch) >= 8:
                self.batch_ready.emit(list(batch))
                batch.clear()
        if batch:
            self.batch_ready.emit(batch)
