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
    QSize,
    QThread,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QImage, QImageReader, QPixmap,
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

    def peek(self, key: str) -> QPixmap | None:
        """최근 사용 순서를 바꾸지 않고 확인만 한다.

        워커 스레드는 ``get``(``move_to_end``)을 부르면 안 된다 — 메인 스레드의
        ``put``과 OrderedDict를 동시에 변경하게 된다. 읽기만 하는 ``peek``을 쓴다.
        """
        return self._cache.get(key)

    def put(self, key: str, pixmap: QPixmap) -> None:
        self._cache[key] = pixmap
        self._cache.move_to_end(key)
        if len(self._cache) > self._maxsize:
            self._cache.popitem(last=False)


_thumb_cache = _ThumbnailCache(LRU_THUMBNAIL_MAX * _THUMB_RENDER_SIZE_KINDS)


def _decode_scaled(path_str: str, w: int, h: int) -> QImage | None:
    """파일을 (w, h)에 맞춰(KeepAspectRatio) 디코드한다. 실패하면 None.

    원본을 전부 디코드한 뒤 ``scaled()``로 줄이면 장당 약 3.4ms, 디코드 시점에
    줄이면(``setScaledSize``) 약 1ms다. 다만 ``setScaledSize`` 단독은 비정수배 축소에서
    Fast 변환이라 계단이 생긴다(213x120 실측 MSE 19, SmoothTransformation 대비).
    그래서 원본이 목표의 **정확한 2의 거듭제곱 배**(1280→320 등, 디코더가 DCT 축소로
    정확히 처리해 계단이 없다)면 목표로 바로 디코드하고(320x180 MSE 0.3, 장당 약 1.2ms),
    그렇지 않으면 **목표의 2배 크기로 디코드한 뒤 Smooth로 줄인다**(213x120 MSE 1.1~1.7,
    장당 약 1.5~1.9ms). 원본이 이미 목표 크기면 변환 없이 그대로 쓴다.
    예외를 내지 않는다 — 워커 스레드와 그리기 경로 양쪽에서 부른다.
    """
    try:
        reader = QImageReader(path_str)
        src = reader.size()
        if not src.isValid() or src.isEmpty():
            img = QImage(path_str)
            if img.isNull():
                return None
            return img.scaled(
                w, h,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        target = src.scaled(QSize(w, h), Qt.AspectRatioMode.KeepAspectRatio)
        ratio = src.width() / max(target.width(), 1)
        if ratio > 1.0 and abs(ratio - round(ratio)) < 0.02 and round(ratio) in (2, 4, 8):
            reader.setScaledSize(target)   # 디코더 DCT 축소가 정확히 맞는 경우
        else:
            double = QSize(target.width() * 2, target.height() * 2)
            if double.width() < src.width():
                reader.setScaledSize(double)   # 실제로 줄어드는 경우만 디코더에 맡긴다
        img = reader.read()
        if img.isNull():
            return None
        if img.size() == target:
            return img
        return img.scaled(
            target,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    except Exception:
        logger.exception("썸네일 디코드 실패: %s", path_str)
        return None


def _load_thumb(thumbnail_path: str, w: int, h: int) -> QPixmap:
    """Load thumbnail scaled to (w, h); cached by path+size."""
    key = f"{thumbnail_path}@{w}x{h}" if thumbnail_path else f"__ph__{w}x{h}"
    cached = _thumb_cache.get(key)
    if cached is not None:
        return cached

    if thumbnail_path:
        full = Path(THUMBNAIL_DIR) / thumbnail_path
        if full.exists():
            img = _decode_scaled(str(full), w, h)
            if img is not None:
                scaled = QPixmap.fromImage(img)
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
            # peek: 순서를 바꾸는 get은 메인 스레드 put과 경합한다(C1).
            if _thumb_cache.peek(key) is not None:
                continue
            full = Path(THUMBNAIL_DIR) / path
            if not full.exists():
                continue
            with self._IO_SEMA:
                scaled = _decode_scaled(str(full), w, h)
            if scaled is None:
                continue
            batch.append((path, w, h, scaled))
            if len(batch) >= 8:
                self.batch_ready.emit(list(batch))
                batch.clear()
        if batch:
            self.batch_ready.emit(batch)
