"""앨범 보기 위젯 — 자켓 그리드 + 앨범 상세(자켓·설명·수록곡).

앨범은 저장 단위가 아니라 노래 정보에서 파생되는 묶음이므로, 이 위젯들은 상태를 갖지
않고 DTO를 받아 그리기만 한다(조회·매핑은 application 레이어).

수록곡 행에는 **출처 배지**가 반드시 붙는다 — 내가 등록한 영상인지, 앱이 자동으로 찾아
붙인 영상인지, 아직 못 찾았는지를 구분하지 못하면 "내 라이브러리"라는 감각이 무너진다.
"""

from __future__ import annotations

import hashlib
import logging

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from application.song.album_dtos import (
    TRACK_ORIGIN_AUTO,
    TRACK_ORIGIN_LIBRARY,
    TRACK_ORIGIN_MISSING,
    AlbumCardDTO,
    AlbumDetailDTO,
    AlbumTrackDTO,
)
from config.settings import THUMBNAIL_DIR
from gui.themes.manager import ThemeManager

logger = logging.getLogger(__name__)

# 수록곡 출처 배지 문구 — 화면 문구는 GUI만 갖는다(DTO는 식별자만 싣는다).
ORIGIN_LABELS = {
    TRACK_ORIGIN_LIBRARY: "내 등록",
    TRACK_ORIGIN_AUTO: "자동 매핑",
    TRACK_ORIGIN_MISSING: "없음",
}


def _t():
    return ThemeManager.instance().current()


def _album_thumb_id(album_key: str) -> str:
    """앨범 키를 파일명으로 쓸 수 있는 짧은 id로 바꾼다(키에 제어문자가 들어 있다)."""
    return hashlib.sha1(album_key.encode("utf-8")).hexdigest()[:16]   # noqa: S324


def _fmt_dur(sec: int | None) -> str:
    if not sec:
        return ""
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


class _JacketLabel(QLabel):
    """정사각 앨범 자켓 — 둥근 모서리로 그린다."""

    def __init__(self, size: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._size = size
        self.setFixedSize(size, size)
        self._pix: QPixmap | None = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_image(self, image: QImage | QPixmap | None) -> None:
        if image is None:
            self._pix = None
        else:
            pix = QPixmap.fromImage(image) if isinstance(image, QImage) else image
            self._pix = pix.scaled(
                self._size, self._size,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0.0, 0.0, float(self._size), float(self._size), 8.0, 8.0)
        tokens = _t()
        if self._pix is None:
            # 자켓이 없을 때의 자리 표시 — 색은 테마 토큰에서 온다(색상 규칙).
            painter.fillPath(path, QColor(tokens.bg_elevated))
            painter.setPen(QColor(tokens.text_muted))
            font = painter.font()
            font.setPointSize(max(10, self._size // 4))
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "♪")
        else:
            painter.setClipPath(path)
            x = (self._size - self._pix.width()) // 2
            y = (self._size - self._pix.height()) // 2
            painter.drawPixmap(x, y, self._pix)
        painter.end()


class _AlbumCard(QFrame):
    """앨범 자켓 카드 — 자켓 + 앨범명 + 가수 + 보유 곡 수."""

    clicked = pyqtSignal(str)   # album_key

    JACKET = 160
    _W = JACKET + 16

    def __init__(self, dto: AlbumCardDTO, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dto = dto
        self._loader = None
        self.setFixedWidth(self._W)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._build()
        self._apply_theme(ThemeManager.instance().current())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)

    def _build(self) -> None:
        col = QVBoxLayout(self)
        col.setContentsMargins(8, 8, 8, 8)
        col.setSpacing(4)
        self._jacket = _JacketLabel(self.JACKET)
        col.addWidget(self._jacket, 0, Qt.AlignmentFlag.AlignHCenter)

        self._title_lbl = QLabel(self._dto.album_title)
        self._title_lbl.setWordWrap(True)
        f = QFont()
        f.setPointSize(9)
        f.setWeight(QFont.Weight.DemiBold)
        self._title_lbl.setFont(f)
        col.addWidget(self._title_lbl)

        sub = self._dto.artist or ""
        counts = f"{self._dto.library_count}곡"
        if self._dto.track_count and self._dto.track_count != self._dto.library_count:
            counts = f"{self._dto.library_count}/{self._dto.track_count}곡"
        self._sub_lbl = QLabel("  ·  ".join(p for p in (sub, counts) if p))
        fs = QFont()
        fs.setPointSize(8)
        self._sub_lbl.setFont(fs)
        col.addWidget(self._sub_lbl)

        self._load_art()

    def _apply_theme(self, tokens) -> None:
        self.setStyleSheet(
            f"QFrame {{ background: {tokens.bg_surface}; border-radius: 10px; }}"
            f" QFrame:hover {{ background: {tokens.bg_elevated}; }}"
        )
        self._title_lbl.setStyleSheet(f"color:{tokens.text_primary}; background: transparent;")
        self._sub_lbl.setStyleSheet(f"color:{tokens.text_secondary}; background: transparent;")

    def _load_art(self) -> None:
        """자켓을 띄운다 — 내려받은 파일 > 원격 URL > 대표 영상 썸네일 순."""
        local = self._dto.artwork_path or self._dto.fallback_thumb_path
        if local:
            path = THUMBNAIL_DIR / local
            if path.exists():
                img = QImage(str(path))
                if not img.isNull():
                    self._jacket.set_image(img)
                    if not self._dto.artwork_url:
                        return
        if not self._dto.artwork_url:
            return
        from gui.panels.feed_panel import start_thumb_loader  # noqa: PLC0415

        # 카드는 목록을 다시 채울 때마다 지워진다 — 부모로 매달면 실행 중인 로더가
        # 함께 파괴돼 앱이 종료된다(gui/workers.py 참고). 슬롯도 바운드 메서드로 준다.
        self._loader = start_thumb_loader(
            self._dto.artwork_url,
            _album_thumb_id(self._dto.key or self._dto.album_title),
            self._on_art_loaded,
            prefix="album",
            size=(self.JACKET * 2, self.JACKET * 2),
        )

    def _on_art_loaded(self, _id: str, img: QImage) -> None:
        self._jacket.set_image(img)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._dto.key)
        super().mouseReleaseEvent(event)


class AlbumGrid(QScrollArea):
    """앨범 자켓 그리드 — 창 폭에 맞춰 열 수를 다시 계산한다."""

    album_clicked = pyqtSignal(str)   # album_key

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._inner = _AlbumGridInner()
        self._inner.album_clicked.connect(self.album_clicked)
        self.setWidget(self._inner)

    def set_albums(self, albums: list[AlbumCardDTO]) -> None:
        self._inner.set_albums(albums)

    def set_status(self, text: str) -> None:
        self._inner.set_status(text)

    def count(self) -> int:
        return len(self._inner.cards)


class _AlbumGridInner(QWidget):
    album_clicked = pyqtSignal(str)

    _CARD_W = _AlbumCard._W + 16

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._status = QLabel("")
        self._status.setContentsMargins(16, 12, 16, 0)
        self._status.hide()
        root.addWidget(self._status)
        holder = QWidget()
        self._grid = QGridLayout(holder)
        self._grid.setContentsMargins(12, 12, 12, 12)
        self._grid.setSpacing(12)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        root.addWidget(holder)
        root.addStretch(1)
        self.cards: list[_AlbumCard] = []
        self._cols = 0

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        # 고정폭 카드가 스크롤 영역의 축소를 막지 않도록 한 칸까지 줄어들 수 있게 한다.
        return QSize(self._CARD_W + 24, 0)

    def set_status(self, text: str) -> None:
        self._status.setText(text)
        self._status.setVisible(bool(text))
        self._status.setStyleSheet(f"color:{_t().text_secondary}; font-size:9pt;")

    def set_albums(self, albums: list[AlbumCardDTO]) -> None:
        for card in self.cards:
            card.setParent(None)
            card.deleteLater()
        self.cards.clear()
        self._cols = self._calc_cols()
        for i, dto in enumerate(albums):
            card = _AlbumCard(dto)
            card.clicked.connect(self.album_clicked)
            self._grid.addWidget(card, i // self._cols, i % self._cols)
            self.cards.append(card)

    def _calc_cols(self) -> int:
        return max(1, (self.width() - 24) // self._CARD_W)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        cols = self._calc_cols()
        if self.cards and cols != self._cols:
            self._cols = cols
            for i, card in enumerate(self.cards):
                self._grid.addWidget(card, i // cols, i % cols)


class _TrackRow(QFrame):
    """수록곡 1행 — 번호 · 제목 · 가수 · 길이 · 출처 배지 (+ 재생 가능하면 클릭).

    2장짜리 앨범은 디스크마다 1번부터 다시 매겨지므로, 그런 앨범에서는 번호를
    "1-3"(디스크-트랙)으로 보여 준다 — 안 그러면 같은 번호가 두 번 나와 목록이
    잘못된 것처럼 보인다.
    """

    clicked = pyqtSignal(object)   # AlbumTrackDTO

    def __init__(
        self, track: AlbumTrackDTO, show_disc: bool = False, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._track = track
        self._show_disc = show_disc
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        if track.playable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build()
        self._apply_theme(ThemeManager.instance().current())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)

    def _build(self) -> None:
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(8)
        self._no_lbl = QLabel(
            f"{self._track.disc_no}-{self._track.track_no}" if self._show_disc
            else str(self._track.track_no)
        )
        self._no_lbl.setFixedWidth(36 if self._show_disc else 24)
        self._no_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._no_lbl)

        self._title_lbl = QLabel(self._track.title)
        self._title_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        row.addWidget(self._title_lbl, 1)

        self._artist_lbl = QLabel(self._track.artist or "")
        row.addWidget(self._artist_lbl)

        self._dur_lbl = QLabel(_fmt_dur(self._track.duration_sec))
        self._dur_lbl.setFixedWidth(48)
        self._dur_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._dur_lbl)

        self._badge = QLabel(ORIGIN_LABELS.get(self._track.origin, ""))
        self._badge.setFixedWidth(64)
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self._badge)

    def _apply_theme(self, tokens) -> None:
        from gui.themes.colors import sem  # noqa: PLC0415

        missing = self._track.origin == TRACK_ORIGIN_MISSING
        body = tokens.text_secondary if missing else tokens.text_primary
        self.setStyleSheet(
            f"QFrame {{ border-radius:6px; }}"
            f" QFrame:hover {{ background:{tokens.bg_elevated if not missing else 'transparent'}; }}"
        )
        self._no_lbl.setStyleSheet(f"color:{tokens.text_secondary}; background:transparent;")
        self._title_lbl.setStyleSheet(f"color:{body}; background:transparent;")
        self._artist_lbl.setStyleSheet(
            f"color:{tokens.text_secondary}; font-size:8pt; background:transparent;"
        )
        self._dur_lbl.setStyleSheet(
            f"color:{tokens.text_secondary}; font-size:8pt; background:transparent;"
        )
        badge_color = {
            TRACK_ORIGIN_LIBRARY: sem("success"),
            TRACK_ORIGIN_AUTO: tokens.accent,
            TRACK_ORIGIN_MISSING: tokens.text_muted,
        }.get(self._track.origin, tokens.text_muted)
        self._badge.setStyleSheet(
            f"color:{badge_color}; font-size:8pt; border:1px solid {badge_color};"
            " border-radius:8px; padding:1px 4px; background:transparent;"
        )

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._track.playable:
            self.clicked.emit(self._track)
        super().mouseReleaseEvent(event)


class AlbumDetailPanel(QWidget):
    """앨범 상세 — 좌: 자켓·설명·재생 버튼 / 우: 수록곡 목록."""

    back_requested = pyqtSignal()
    play_album_requested = pyqtSignal(object)   # AlbumDetailDTO
    track_clicked = pyqtSignal(object)          # AlbumTrackDTO
    refresh_requested = pyqtSignal(str)         # album_key — 앨범 정보 다시 받기
    fill_requested = pyqtSignal(str)            # album_key — 빠진 곡 다시 찾기

    JACKET = 220

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._detail: AlbumDetailDTO | None = None
        self._loader = None
        self._rows: list[_TrackRow] = []
        self._build()
        self._apply_theme(ThemeManager.instance().current())
        ThemeManager.instance().theme_changed.connect(self._apply_theme)

    # ── 구성 ────────────────────────────────────────────────────────
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        top = QHBoxLayout()
        self._btn_back = QPushButton("‹")
        self._btn_back.setFixedSize(28, 28)
        self._btn_back.setToolTip("앨범 목록으로")
        self._btn_back.clicked.connect(self.back_requested.emit)
        top.addWidget(self._btn_back)
        self._crumb = QLabel("")
        top.addWidget(self._crumb)
        top.addStretch(1)
        self._status_lbl = QLabel("")
        top.addWidget(self._status_lbl)
        root.addLayout(top)

        body = QHBoxLayout()
        body.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(8)
        self._jacket = _JacketLabel(self.JACKET)
        left.addWidget(self._jacket, 0, Qt.AlignmentFlag.AlignHCenter)
        self._title_lbl = QLabel("")
        self._title_lbl.setWordWrap(True)
        tf = QFont()
        tf.setPointSize(13)
        tf.setWeight(QFont.Weight.Bold)
        self._title_lbl.setFont(tf)
        left.addWidget(self._title_lbl)
        self._artist_lbl = QLabel("")
        left.addWidget(self._artist_lbl)
        self._desc_lbl = QLabel("")
        self._desc_lbl.setWordWrap(True)
        left.addWidget(self._desc_lbl)

        self._btn_play = QPushButton("▶  앨범 재생")
        self._btn_play.clicked.connect(self._on_play)
        left.addWidget(self._btn_play)

        btn_row = QHBoxLayout()
        self._btn_fill = QPushButton("빠진 곡 찾기")
        self._btn_fill.setToolTip("라이브러리에 없는 수록곡의 공식 음원 영상을 찾아 붙인다")
        self._btn_fill.clicked.connect(
            lambda: self.fill_requested.emit(self._detail.key if self._detail else "")
        )
        btn_row.addWidget(self._btn_fill)
        self._btn_refresh = QPushButton("⟳")
        self._btn_refresh.setFixedWidth(32)
        self._btn_refresh.setToolTip("앨범 정보 다시 받기")
        self._btn_refresh.clicked.connect(
            lambda: self.refresh_requested.emit(self._detail.key if self._detail else "")
        )
        btn_row.addWidget(self._btn_refresh)
        left.addLayout(btn_row)
        left.addStretch(1)

        left_holder = QWidget()
        left_holder.setLayout(left)
        left_holder.setFixedWidth(self.JACKET + 24)
        body.addWidget(left_holder)

        right = QVBoxLayout()
        right.setSpacing(4)
        self._tracks_header = QLabel("수록곡")
        hf = QFont()
        hf.setPointSize(10)
        hf.setWeight(QFont.Weight.Bold)
        self._tracks_header.setFont(hf)
        right.addWidget(self._tracks_header)
        self._tracks_scroll = QScrollArea()
        self._tracks_scroll.setWidgetResizable(True)
        self._tracks_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._tracks_holder = QWidget()
        self._tracks_layout = QVBoxLayout(self._tracks_holder)
        self._tracks_layout.setContentsMargins(0, 0, 0, 0)
        self._tracks_layout.setSpacing(2)
        self._tracks_layout.addStretch(1)
        self._tracks_scroll.setWidget(self._tracks_holder)
        right.addWidget(self._tracks_scroll, 1)
        right_holder = QWidget()
        right_holder.setLayout(right)
        body.addWidget(right_holder, 1)

        root.addLayout(body, 1)

    def _apply_theme(self, tokens) -> None:
        self._crumb.setStyleSheet(f"color:{tokens.text_secondary}; font-size:9pt;")
        self._status_lbl.setStyleSheet(f"color:{tokens.text_secondary}; font-size:9pt;")
        self._title_lbl.setStyleSheet(f"color:{tokens.text_primary};")
        self._artist_lbl.setStyleSheet(f"color:{tokens.text_secondary}; font-size:9pt;")
        self._desc_lbl.setStyleSheet(f"color:{tokens.text_secondary}; font-size:9pt;")
        self._tracks_header.setStyleSheet(f"color:{tokens.text_primary};")

    # ── 채우기 ──────────────────────────────────────────────────────
    def set_detail(self, detail: AlbumDetailDTO | None, crumb: str = "") -> None:
        self._detail = detail
        self._crumb.setText(crumb)
        if detail is None:
            self._title_lbl.setText("앨범을 찾을 수 없습니다.")
            self._artist_lbl.setText("")
            self._desc_lbl.setText("")
            self._render_tracks([])
            return
        self._title_lbl.setText(detail.album_title)
        self._artist_lbl.setText(detail.artist)
        self._desc_lbl.setText(detail.description)
        self._btn_play.setEnabled(any(t.playable for t in detail.tracks))
        self._load_art(detail)
        self._render_tracks(detail.tracks)
        self.set_status(
            f"내 등록 {detail.library_count}곡  ·  자동 {detail.auto_count}곡"
            + (f"  ·  없음 {detail.missing_count}곡" if detail.missing_count else "")
        )

    def set_status(self, text: str) -> None:
        self._status_lbl.setText(text)

    def status_text(self) -> str:
        """현재 상태 문구 — 호출부가 뒤에 진행 상황을 덧붙일 때 읽는다."""
        return self._status_lbl.text()

    def set_busy(self, busy: bool) -> None:
        self._btn_fill.setEnabled(not busy)
        self._btn_refresh.setEnabled(not busy)

    def apply_filled_track(self, track: AlbumTrackDTO) -> None:
        """자동 매핑이 끝난 곡 하나를 제자리에서 갱신한다(전체 재조회 없이)."""
        if self._detail is None:
            return
        # **(디스크, 트랙)으로 찾는다** — 번호만 비교하면 2장짜리 앨범에서 disc1·disc2의
        # 같은 번호 행이 **둘 다** 같은 곡으로 덮어써진다(실제로 그 증상이 나왔다).
        tracks = [track if t.slot == track.slot else t for t in self._detail.tracks]
        self._detail = AlbumDetailDTO(
            key=self._detail.key,
            album_title=self._detail.album_title,
            artist=self._detail.artist,
            artwork_url=self._detail.artwork_url,
            artwork_path=self._detail.artwork_path,
            fallback_thumb_path=self._detail.fallback_thumb_path,
            description=self._detail.description,
            release_date=self._detail.release_date,
            genre=self._detail.genre,
            source_name=self._detail.source_name,
            source_url=self._detail.source_url,
            tracks=tracks,
        )
        self._render_tracks(tracks)
        self._btn_play.setEnabled(any(t.playable for t in tracks))
        self.set_status(
            f"내 등록 {self._detail.library_count}곡  ·  자동 {self._detail.auto_count}곡"
            + (f"  ·  없음 {self._detail.missing_count}곡"
               if self._detail.missing_count else "")
        )

    # ── 내부 ───────────────────────────────────────────────────────
    def _render_tracks(self, tracks: list[AlbumTrackDTO]) -> None:
        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()
        multi_disc = len({t.disc_no for t in tracks}) > 1
        for i, track in enumerate(tracks):
            row = _TrackRow(track, show_disc=multi_disc)
            row.clicked.connect(self.track_clicked)
            self._tracks_layout.insertWidget(i, row)
            self._rows.append(row)

    def _load_art(self, detail: AlbumDetailDTO) -> None:
        local = detail.artwork_path or detail.fallback_thumb_path
        shown = False
        if local:
            path = THUMBNAIL_DIR / local
            if path.exists():
                img = QImage(str(path))
                if not img.isNull():
                    self._jacket.set_image(img)
                    shown = True
        if not detail.artwork_url:
            if not shown:
                self._jacket.set_image(None)
            return
        from gui.panels.feed_panel import start_thumb_loader  # noqa: PLC0415

        self._loader = start_thumb_loader(
            detail.artwork_url,
            _album_thumb_id(detail.key or detail.album_title),
            self._on_art_loaded,
            prefix="album",
            size=(self.JACKET * 2, self.JACKET * 2),
        )

    def _on_art_loaded(self, _id: str, img: QImage) -> None:
        self._jacket.set_image(img)

    def _on_play(self) -> None:
        if self._detail is not None:
            self.play_album_requested.emit(self._detail)
