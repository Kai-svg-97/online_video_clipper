"""우측 목록(연관 영상 + 추천 영상) — 행 위젯과 두 구역 스크롤 목록.

연관 영상은 재생목록으로도 쓰이므로(자동 다음곡) payload 순서가 곧 재생 순서다.
추천 구역은 그 재생목록에 포함되지 않는다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from PyQt6.QtCore import (
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QFont,
    QFontMetrics,
    QImage,
)
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


from gui.themes.manager import ThemeManager

from gui.panels.detail.widgets import _clear_layout, _t

from gui.anim import fade_in

logger = logging.getLogger(__name__)


@dataclass
class RelatedItem:
    """상세화면 우측 연관 영상 1건.

    payload: 클릭 시 재진입에 사용 — 로컬 영상이면 VideoDTO.id(UUID),
    스트리밍(피드/채널) 영상이면 FeedVideoDTO.
    """
    key: str
    title: str
    channel: str
    duration_sec: int | None
    meta_text: str
    payload: object
    thumb_path: str = ""   # 로컬 썸네일 경로
    thumb_url: str = ""    # 원격 썸네일 URL
    yt_video_id: str = ""  # 스트리밍 항목 — 피드 그리드와 썸네일 캐시(feed_*) 공유용

def _fmt_dur(sec: int | None) -> str:
    if sec is None:
        return "—"
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def _fmt_pub(value: str | None) -> str:
    """업로드일 표기. yt-dlp의 YYYYMMDD 또는 ISO 문자열 모두 처리."""
    if not value:
        return ""
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}.{value[4:6]}.{value[6:]}"
    return value

def _payload_key(payload: object) -> str:
    """재생목록 payload를 RelatedItem.key와 같은 키로 변환(현재 항목 매칭용).

    로컬 영상 payload=UUID → str(UUID); 스트리밍 payload=FeedVideoDTO → yt_video_id/url.
    """
    if isinstance(payload, UUID):
        return str(payload)
    return getattr(payload, "yt_video_id", "") or getattr(payload, "url", "") or ""

class _RelatedRow(QFrame):
    """연관 영상 1행 — 작은 썸네일 + 제목 2줄 + 채널/메타. 단일 클릭으로 선택."""

    clicked = pyqtSignal(object)   # payload
    _TW, _TH = 168, 94

    def __init__(
        self, item: RelatedItem, is_current: bool = False, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._item = item
        self._is_current = is_current
        self._loader = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFrameShape(QFrame.Shape.NoFrame)
        # 행이 자연 높이(썸네일 기준 ~102px)를 초과해 세로로 늘어나지 않도록 고정
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._build_ui(item)
        self._apply_theme(ThemeManager.instance().current())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)

    def _build_ui(self, item: RelatedItem) -> None:
        from gui.panels.feed_panel import _RoundedThumbLabel  # noqa: PLC0415

        row = QHBoxLayout(self)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(8)

        self._thumb = _RoundedThumbLabel(self._TW, self._TH)
        if item.duration_sec:
            self._thumb.set_duration(_fmt_dur(item.duration_sec))
        row.addWidget(self._thumb, 0, Qt.AlignmentFlag.AlignTop)

        self._cache_key = ""
        self._load_thumb(item)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)
        self._title_lbl = QLabel(("▶ " + item.title) if self._is_current else item.title)
        self._title_lbl.setWordWrap(True)
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
        tf = QFont()
        tf.setPointSize(9)
        tf.setWeight(QFont.Weight.Bold if self._is_current else QFont.Weight.Medium)
        self._title_lbl.setFont(tf)
        # 제목은 최대 3줄까지 표시 — 채널명이 제목을 가리지 않도록 높이를 넉넉히 확보
        self._title_lbl.setMaximumHeight(QFontMetrics(tf).lineSpacing() * 3 + 4)
        text_col.addWidget(self._title_lbl)

        # 제목과 채널/메타 사이 여백 — 채널·조회수·등록시기를 행 아래쪽에 배치해
        # 제목 표시를 덜 방해하도록 한다.
        text_col.addStretch()

        cf = QFont()
        cf.setPointSize(7)   # 채널/조회수/등록시기는 제목보다 1pt 작게
        self._chan_lbl = QLabel(item.channel)
        self._chan_lbl.setFont(cf)
        text_col.addWidget(self._chan_lbl)

        self._meta_lbl = QLabel(item.meta_text)
        self._meta_lbl.setFont(cf)
        text_col.addWidget(self._meta_lbl)
        row.addLayout(text_col, 1)

    def _load_thumb(self, item: RelatedItem) -> None:
        """썸네일 로드 — 로컬 경로 우선, 없으면 피드 그리드와 동일한 캐시를 공유.

        스트리밍 항목은 ``yt_video_id`` 기준으로 피드 그리드(_FeedCard)가 쓰는
        인메모리 ``_feed_thumb_cache``·디스크 ``feed_{id}.{ext}``를 그대로 재사용해
        중복 다운로드(prefix 불일치로 인한 재다운로드·스레드 경쟁)를 막는다.
        """
        from config.settings import THUMBNAIL_DIR  # noqa: PLC0415
        from gui.panels.feed_panel import (  # noqa: PLC0415
            _feed_thumb_cache,
            start_thumb_loader,
        )

        # 1) 로컬 영상 — 저장된 썸네일 경로 우선
        if item.thumb_path and Path(item.thumb_path).exists():
            img = QImage(item.thumb_path)
            if not img.isNull():
                self._thumb.set_image(img)
            return

        # 2) 스트리밍 — 피드 그리드와 캐시/디스크(prefix "feed") 공유
        vid_id = item.yt_video_id
        if vid_id:
            self._cache_key = f"{vid_id}@{self._TW}x{self._TH}"
            cached_px = _feed_thumb_cache.get(self._cache_key)
            if cached_px is not None:
                self._thumb._pixmap = cached_px
                self._thumb.update()
                return
            for ext in ("jpg", "jpeg", "webp", "png"):
                cached = THUMBNAIL_DIR / f"feed_{vid_id}.{ext}"
                if cached.exists():
                    img = QImage(str(cached))
                    if not img.isNull():
                        self._thumb.set_image(img)
                        if self._cache_key:
                            _feed_thumb_cache.put(self._cache_key, self._thumb._pixmap)
                        return

        if not item.thumb_url:
            return
        # 목록을 다시 채우면 행이 지워지는데, 실행 중인 로더가 그때 파괴되면 Qt가
        # 프로세스를 죽인다 — 시작 헬퍼가 부모 없이 띄우고 끝날 때까지 붙든다.
        self._loader = start_thumb_loader(
            item.thumb_url, vid_id or item.key, self._on_remote_thumb,
            prefix="feed", size=(self._TW * 2, self._TH * 2),
        )

    def _on_remote_thumb(self, _id: str, im: QImage) -> None:
        fade_in(self._thumb)
        from gui.panels.feed_panel import _feed_thumb_cache  # noqa: PLC0415
        try:
            self._thumb.set_image(im)
            if self._cache_key:
                _feed_thumb_cache.put(self._cache_key, self._thumb._pixmap)
        except RuntimeError:
            pass  # 행 소멸 후 콜백 도달 시 무시

    def mouseReleaseEvent(self, event) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            self.clicked.emit(self._item.payload)

    def _apply_theme(self, tok) -> None:
        if self._is_current:
            # 현재 재생 중 행 — 배경 강조로 재생목록 내 위치를 표시
            self.setStyleSheet(
                f"QFrame{{background:{tok.bg_overlay};border-radius:6px;"
                f"border-left:3px solid {tok.accent};}}"
            )
        else:
            self.setStyleSheet(
                f"QFrame{{background:transparent;border-radius:6px;}}"
                f"QFrame:hover{{background:{tok.bg_overlay};}}"
            )
        self._title_lbl.setStyleSheet(f"color:{tok.text_primary};")
        self._chan_lbl.setStyleSheet(f"color:{tok.text_secondary};")
        self._meta_lbl.setStyleSheet(f"color:{tok.text_muted};")

class _RelatedList(QScrollArea):
    """우측 세로 목록 — 위: 연관 영상(재생목록), 아래: 추천 영상.

    두 구역을 **같은 스크롤 안에** 세로로 쌓는다. 추천 영상은 라이브러리 목록 기반
    후보라 연관 영상과 성격이 달라 헤더로 구분하고, **재생목록에는 넣지 않는다**
    (자동 다음곡이 라이브러리 밖 영상으로 새어나가지 않게 하려는 의도적 분리 —
    ``VideoDetailWidget.set_related``만 ``_playlist``를 채운다).

    구역마다 전용 컨테이너(``_rel_box``/``_rec_box``)를 두는 이유는, 예전처럼 한
    레이아웃에 헤더·행·스트레치를 늘어놓고 인덱스로 지우면 구역이 둘이 되는 순간
    삽입/삭제 위치가 어긋나기 때문이다.
    """

    item_selected = pyqtSignal(object)   # payload

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumWidth(360)
        self._inner = QWidget()
        self._layout = QVBoxLayout(self._inner)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(4)

        hf = QFont()
        hf.setPointSize(10)
        hf.setWeight(QFont.Weight.Bold)

        self._header = QLabel("연관 영상")
        self._header.setFont(hf)
        self._layout.addWidget(self._header)

        self._rel_box = QWidget()
        self._rel_layout = QVBoxLayout(self._rel_box)
        self._rel_layout.setContentsMargins(0, 0, 0, 0)
        self._rel_layout.setSpacing(4)
        self._layout.addWidget(self._rel_box)

        self._rec_header = QLabel("추천 영상")
        self._rec_header.setFont(hf)
        self._rec_header.setContentsMargins(0, 10, 0, 0)
        self._rec_header.hide()
        self._layout.addWidget(self._rec_header)

        self._rec_box = QWidget()
        self._rec_layout = QVBoxLayout(self._rec_box)
        self._rec_layout.setContentsMargins(0, 0, 0, 0)
        self._rec_layout.setSpacing(4)
        self._rec_box.hide()
        self._layout.addWidget(self._rec_box)

        self._layout.addStretch()
        self.setWidget(self._inner)

    def set_header(self, text: str) -> None:
        self._header.setText(text or "연관 영상")

    def set_items(self, items: list[RelatedItem], current_key: str | None = None) -> None:
        _clear_layout(self._rel_layout)
        if not items:
            empty = QLabel("표시할 영상이 없습니다.")
            empty.setStyleSheet(f"color:{_t().text_secondary};padding:8px;")
            self._rel_layout.addWidget(empty)
            return
        self._fill(self._rel_layout, items, current_key)

    def set_recommendations(self, items: list[RelatedItem]) -> None:
        """연관 영상 아래에 추천 영상을 나열한다(없으면 헤더째 감춘다)."""
        _clear_layout(self._rec_layout)
        self._rec_header.setVisible(bool(items))
        self._rec_box.setVisible(bool(items))
        if items:
            self._fill(self._rec_layout, items, None)

    def _fill(
        self, layout, items: list[RelatedItem], current_key: str | None
    ) -> None:
        for it in items:
            row = _RelatedRow(it, is_current=(current_key is not None and it.key == current_key))
            row.clicked.connect(self.item_selected.emit)
            layout.addWidget(row)
