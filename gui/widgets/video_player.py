"""Reusable inline video-player widget (InlinePlayer).

Layout: 16:9 video area that overlays the control bar at the bottom.
Qt 6.6+ multimedia renders via QRhi (not a native HWND), so a child QWidget
with raise_() correctly appears on top of QVideoWidget.

Fullscreen creates a separate top-level window on the same monitor as the
player, redirects QMediaPlayer output there, and restores on exit.
"""
from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import (
    QEvent,
    QPoint,
    QPointF,
    QRectF,
    QSizeF,
    QThread,
    QTimer,
    QUrl,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QBrush, QColor, QCursor, QKeyEvent, QPainter
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QGraphicsVideoItem
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizeGrip,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from application.library.dtos import DownloadInfoDTO
from domain.download.value_objects import DownloadSettings, MediaFormat, Quality
from gui.themes.manager import ThemeManager

logger = logging.getLogger(__name__)


# ── Background worker: resolve yt-dlp stream URL ──────────────────

class _StreamWorker(QThread):
    # (path_or_url, quality_label e.g. "720p", is_local) — is_local=True면 임시 병합 파일
    stream_ready = pyqtSignal(str, str, bool)
    progress     = pyqtSignal(int)   # 병합 다운로드 진행률(0-100)
    failed       = pyqtSignal(str)

    def __init__(
        self,
        url: str,
        quality_fmt: str = "best[ext=mp4]/best",
        merge: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._url = url
        self._quality_fmt = quality_fmt
        self._merge = merge           # True면 영상+오디오를 ffmpeg로 병합해 임시 파일 재생

    def run(self) -> None:
        try:
            import yt_dlp  # noqa: PLC0415
            if self._merge:
                self._run_merge(yt_dlp)
            else:
                self._run_stream(yt_dlp)
        except Exception as exc:
            self.failed.emit(str(exc))

    # ── 즉시 스트리밍: 단일 muxed URL을 그대로 QMediaPlayer에 전달 ──
    def _run_stream(self, yt_dlp) -> None:
        opts = {"quiet": True, "no_warnings": True,
                "format": self._quality_fmt, "noplaylist": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(self._url, download=False) or {}
        stream: str = info.get("url", "")
        fmt_info: dict = {}
        if not stream:
            for f in reversed(info.get("formats") or []):
                if f.get("url") and f.get("ext") == "mp4" and f.get("acodec") not in (None, "none"):
                    stream, fmt_info = f["url"], f
                    break
        if not stream:
            for f in reversed(info.get("formats") or []):
                if f.get("url"):
                    stream, fmt_info = f["url"], f
                    break
        h = fmt_info.get("height") or info.get("height")
        label = f"{h}p" if h else ""
        if stream:
            self.stream_ready.emit(stream, label, False)
        else:
            self.failed.emit("스트림 URL을 가져올 수 없습니다.")

    # ── 고화질: 분리된 영상+오디오를 ffmpeg로 임시 mp4에 병합해 로컬 재생 ──
    def _run_merge(self, yt_dlp) -> None:
        import os  # noqa: PLC0415
        import tempfile  # noqa: PLC0415
        try:
            from utils.resources import get_ffmpeg_path  # noqa: PLC0415
            ffmpeg = get_ffmpeg_path()
        except (FileNotFoundError, Exception):  # noqa: BLE001
            ffmpeg = None
        if not ffmpeg:
            # ffmpeg 없으면 병합 불가 → 즉시 스트리밍으로 폴백(보통 360p)
            self._run_stream(yt_dlp)
            return

        tmpdir = tempfile.mkdtemp(prefix="ovc_stream_")
        opts = {
            "quiet": True, "no_warnings": True, "noplaylist": True,
            "format": self._quality_fmt,
            "merge_output_format": "mp4",
            "outtmpl": os.path.join(tmpdir, "stream.%(ext)s"),
            "ffmpeg_location": ffmpeg,
            "progress_hooks": [self._merge_hook],
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(self._url, download=True) or {}
        rd = (info.get("requested_downloads") or [{}])[0]
        path = rd.get("filepath") or info.get("filepath") or ydl.prepare_filename(info)
        if not path or not os.path.exists(path):
            # 병합 산출물을 못 찾으면 디렉터리에서 첫 파일을 집는다
            files = [os.path.join(tmpdir, f) for f in os.listdir(tmpdir)]
            path = files[0] if files else ""
        h = rd.get("height") or info.get("height")
        label = f"{h}p" if h else ""
        if path and os.path.exists(path):
            self.stream_ready.emit(path, label, True)
        else:
            self.failed.emit("고화질 병합에 실패했습니다.")

    def _merge_hook(self, d: dict) -> None:
        if d.get("status") != "downloading":
            return
        try:
            pct = str(d.get("_percent_str") or "0").strip().rstrip("%")
            self.progress.emit(int(float(pct or 0)))
        except (ValueError, TypeError):
            pass


# ── Control bar (overlaid at the bottom of the video area) ────────

def _bar_style() -> str:
    """현재 테마 토큰을 반영한 컨트롤바 QSS를 반환한다."""
    tok = ThemeManager.instance().current()
    return f"""
QWidget#ctrlbar {{
    background: rgba(0,0,0,115);
}}
QToolButton {{
    color: {tok.text_primary};
    background: transparent;
    border: none;
    font-size: 13px;
    padding: 2px 4px;
    min-width: 24px;
    min-height: 24px;
}}
QToolButton:hover {{ color: {tok.accent_hover}; background: rgba(255,255,255,15); border-radius: 3px; }}
QLabel {{ color: {tok.text_secondary}; background: transparent; font-size: 9pt; }}
/* 슬라이더(_TrackSlider)는 QPainter로 직접 그린다 — 영상 오버레이 위에서
   QSlider::groove/add-page 서브컨트롤이 검게 렌더되는 문제를 회피하기 위함. */
"""


def _quality_badge_style() -> str:
    tok = ThemeManager.instance().current()
    return (
        f"color:{tok.text_primary}; background:{tok.badge_bg}; "
        "font-size:8pt; padding:1px 5px; border-radius:3px;"
    )

# YouTube 고화질(>360p)은 영상+오디오가 분리돼 ffmpeg 병합이 필요하다.
# Windows Media Foundation 호환을 위해 avc1(H.264)+m4a(AAC)를 우선 선택한다.
def _merge_fmt(h: int) -> str:
    return (
        f"bestvideo[height<={h}][vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
        f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/"
        f"best[height<={h}][ext=mp4]/best[height<={h}]/best"
    )


# (메뉴 라벨, yt-dlp 포맷, 버튼 단축 라벨, merge: 병합 필요 여부)
_QUALITY_OPTIONS = [
    ("자동 (빠른 재생)", "best[ext=mp4]/best", "자동",  False),
    ("1080p",           _merge_fmt(1080),     "1080p", True),
    ("720p",            _merge_fmt(720),      "720p",  True),
    ("480p",            _merge_fmt(480),      "480p",  True),
    ("360p",            "best[height<=360][ext=mp4]/best[height<=360]/best", "360p", False),
    ("240p",            "best[height<=240][ext=mp4]/best[height<=240]/best", "240p", False),
]
_DEFAULT_QUALITY_FMT = _QUALITY_OPTIONS[0][1]
_DEFAULT_QUALITY_MERGE = _QUALITY_OPTIONS[0][3]


class _TrackSlider(QSlider):
    """트랙·핸들을 QPainter로 직접 그리는 QSlider.

    QGraphicsVideoItem(영상) 위에 컨트롤바가 겹쳐진 상황에서는 Qt 스타일시트의
    `QSlider::groove`/`::add-page` 서브컨트롤이 색을 무시하고 검게 렌더되는 문제가
    있다(영상 오버레이 위 서브컨트롤 렌더 제약). 반면 위젯 배경·sub-page 같은
    직접 채움은 정상 렌더되므로, 트랙 전체를 `paintEvent`에서 QPainter로 직접
    그린다. 직접 채움은 반투명 알파도 영상 위에 정상 합성되므로, 미채움 트랙은
    **반투명 화이트**로 그려 영상이 비쳐 보이게 한다(사용자 요구 = 반투명).
    """

    _TRACK_H = 4
    _HANDLE_R = 6
    # 미채움 트랙 — 반투명 화이트(영상이 비쳐 보이는 옅은 반투명)
    _TRACK_ALPHA = 115

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 시그니처)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        tok = ThemeManager.instance().current()
        rect = self.rect()
        cy = rect.height() / 2
        pad = self._HANDLE_R + 1
        x0 = float(pad)
        span = max(1.0, rect.width() - 2 * pad)
        mn, mx = self.minimum(), self.maximum()
        frac = 0.0 if mx <= mn else (self.value() - mn) / (mx - mn)
        frac = min(1.0, max(0.0, frac))
        hx = x0 + span * frac
        th = self._TRACK_H
        r = th / 2

        painter.setPen(Qt.PenStyle.NoPen)
        # 미채움 트랙(전체) — 반투명 화이트로 영상이 비침
        painter.setBrush(QColor(255, 255, 255, self._TRACK_ALPHA))
        painter.drawRoundedRect(QRectF(x0, cy - th / 2, span, th), r, r)
        # 채움(핸들 왼쪽) — 불투명 progress_fg로 진행분을 또렷하게
        painter.setBrush(QColor(tok.progress_fg))
        painter.drawRoundedRect(QRectF(x0, cy - th / 2, hx - x0, th), r, r)
        # 핸들
        hr = self._HANDLE_R
        painter.setBrush(QColor(tok.text_primary))
        painter.drawEllipse(QPointF(hx, cy), float(hr), float(hr))
        painter.end()


class _ControlBar(QWidget):
    play_toggled       = pyqtSignal()
    seek_relative      = pyqtSignal(int)   # delta in seconds
    seek_to_ms         = pyqtSignal(int)   # absolute ms
    volume_changed     = pyqtSignal(int)   # 0-100
    mute_toggled       = pyqtSignal()
    fullscreen_toggled = pyqtSignal()
    pip_toggled        = pyqtSignal()         # 화면 속 화면(PiP) 토글
    download_requested = pyqtSignal(object)   # DownloadSettings
    quality_changed    = pyqtSignal(str, str, bool) # (fmt_string, short_label, merge)

    _HEIGHT = 72

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ctrlbar")
        self.setStyleSheet(_bar_style())
        self.setFixedHeight(self._HEIGHT)
        ThemeManager.instance().theme_changed.connect(
            lambda _: self.setStyleSheet(_bar_style())
        )
        # Allow the bar to receive mouse events (needed for clicks on controls)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._dragging = False
        self._setup()

    def _setup(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 6)
        outer.setSpacing(4)

        # Progress slider (full width)
        self._progress = _TrackSlider(Qt.Orientation.Horizontal)
        self._progress.setRange(0, 0)
        self._progress.setToolTip("재생 위치")
        self._progress.sliderPressed.connect(lambda: setattr(self, "_dragging", True))
        self._progress.sliderReleased.connect(self._on_seek_released)
        outer.addWidget(self._progress)

        # Button row
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)

        def btn(text: str, tip: str, slot) -> QToolButton:
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            return b

        self._btn_play = btn("▶", "재생/일시정지  (Space / K)", self.play_toggled.emit)
        self._btn_back = btn("⏪", "10초 뒤로  (J)", lambda: self.seek_relative.emit(-10))
        self._btn_fwd  = btn("⏩", "10초 앞으로  (L)", lambda: self.seek_relative.emit(10))
        self._btn_mute = btn("🔊", "음소거  (M)", self.mute_toggled.emit)

        self._vol = _TrackSlider(Qt.Orientation.Horizontal)
        self._vol.setRange(0, 100)
        self._vol.setValue(100)
        self._vol.setFixedWidth(68)
        self._vol.setToolTip("볼륨  (↑/↓)")
        self._vol.valueChanged.connect(self.volume_changed.emit)

        self._time_lbl = QLabel("0:00 / 0:00")

        self._quality_lbl = QLabel("")
        self._quality_lbl.setStyleSheet(_quality_badge_style())
        self._quality_lbl.hide()

        self._btn_quality = QToolButton()
        self._btn_quality.setText("자동")
        self._btn_quality.setToolTip("재생 품질")
        self._btn_quality.setStyleSheet(
            "QToolButton{font-size:8pt;padding:1px 5px;border-radius:3px;"
            "background:rgba(255,255,255,20);color:#ddd;}"
            "QToolButton:hover{background:rgba(255,255,255,40);}"
        )
        self._btn_quality.clicked.connect(self._show_quality_menu)

        self._btn_dl = btn("⬇", "다운로드", self._show_download_menu)
        self._btn_pip = btn("⧉", "화면 속 화면  (P)", self.pip_toggled.emit)
        self._btn_fs = btn("⛶", "전체화면  (F)", self.fullscreen_toggled.emit)

        for w in (self._btn_play, self._btn_back, self._btn_fwd,
                  self._btn_mute, self._vol, self._time_lbl):
            row.addWidget(w)
        row.addStretch()
        row.addWidget(self._quality_lbl)
        row.addWidget(self._btn_quality)
        row.addWidget(self._btn_dl)
        row.addWidget(self._btn_pip)
        row.addWidget(self._btn_fs)
        outer.addLayout(row)

    # ── State helpers ──────────────────────────────────────────────

    def update_position(self, pos_ms: int, dur_ms: int) -> None:
        if not self._dragging:
            self._progress.setRange(0, dur_ms)
            self._progress.setValue(pos_ms)
        self._time_lbl.setText(f"{self._fmt(pos_ms)} / {self._fmt(dur_ms)}")

    def update_duration(self, dur_ms: int) -> None:
        if not self._dragging:
            self._progress.setRange(0, dur_ms)

    def set_playing(self, playing: bool) -> None:
        self._btn_play.setText("⏸" if playing else "▶")

    def set_muted(self, muted: bool) -> None:
        self._btn_mute.setText("🔇" if muted else "🔊")

    def set_volume(self, vol: int) -> None:
        self._vol.blockSignals(True)
        self._vol.setValue(vol)
        self._vol.blockSignals(False)

    def set_quality(self, label: str) -> None:
        self._quality_lbl.setText(label)
        self._quality_lbl.setVisible(bool(label))

    def _on_seek_released(self) -> None:
        self._dragging = False
        self.seek_to_ms.emit(self._progress.value())

    def _show_quality_menu(self) -> None:
        menu = QMenu(self)
        tok = ThemeManager.instance().current()
        menu.setStyleSheet(
            f"QMenu{{background:{tok.bg_elevated};color:{tok.text_primary};border:1px solid {tok.border_muted};}}"
            f"QMenu::item:selected{{background:{tok.bg_overlay};}}"
        )
        for menu_label, fmt, short, merge in _QUALITY_OPTIONS:
            act = menu.addAction(menu_label)
            act.triggered.connect(
                lambda _c, f=fmt, s=short, m=merge: self._on_quality_item(f, s, m)
            )
        btn_pos = self._btn_quality.mapToGlobal(QPoint(0, 0))
        hint = menu.sizeHint()
        menu.exec(QPoint(btn_pos.x(), btn_pos.y() - hint.height()))

    def _on_quality_item(self, fmt: str, short: str, merge: bool) -> None:
        self._btn_quality.setText(short)
        self.quality_changed.emit(fmt, short, merge)

    def _show_download_menu(self) -> None:
        menu = QMenu(self)
        tok = ThemeManager.instance().current()
        menu.setStyleSheet(
            f"QMenu{{background:{tok.bg_elevated};color:{tok.text_primary};border:1px solid {tok.border_muted};}}"
            f"QMenu::item:selected{{background:{tok.bg_overlay};}}"
        )

        vm = menu.addMenu("🎬  동영상")
        for quality, label in [
            (Quality.BEST,  "최고 화질"),
            (Quality.P2160, "2160p  (4K)"),
            (Quality.P1080, "1080p  (HD)"),
            (Quality.P720,  "720p"),
            (Quality.P480,  "480p"),
            (Quality.P360,  "360p"),
        ]:
            act = vm.addAction(label)
            act.triggered.connect(
                lambda _c, q=quality: self.download_requested.emit(
                    DownloadSettings(quality=q, fmt=MediaFormat.MP4)
                )
            )

        am = menu.addMenu("🎵  오디오")
        for fmt, label in [(MediaFormat.MP3, "MP3"), (MediaFormat.M4A, "M4A")]:
            act = am.addAction(label)
            act.triggered.connect(
                lambda _c, f=fmt: self.download_requested.emit(
                    DownloadSettings(quality=Quality.AUDIO, fmt=f)
                )
            )

        btn_pos = self._btn_dl.mapToGlobal(QPoint(0, 0))
        hint    = menu.sizeHint()
        menu.exec(QPoint(btn_pos.x(), btn_pos.y() - hint.height()))

    @staticmethod
    def _fmt(ms: int) -> str:
        s = ms // 1000
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ── 16:9 video area with overlaid control bar ─────────────────────

class _VideoArea(QWidget):
    """Enforces 16:9 aspect ratio; hosts the visual stack and overlays
    the control bar at the bottom (QRhi backend ensures correct z-order)."""

    _BAR_H = _ControlBar._HEIGHT

    def __init__(self, stack: QStackedWidget, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background:#000;")
        self.setMouseTracking(True)
        self._stack = stack
        self._bar: QWidget | None = None
        stack.setParent(self)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_overlay_bar(self, bar: QWidget) -> None:
        self._bar = bar
        bar.setParent(self)
        self._layout_children()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, w: int) -> int:
        return max(w * 9 // 16, 90)

    def resizeEvent(self, event) -> None:
        self.setFixedHeight(self.heightForWidth(self.width()))
        self._layout_children()
        super().resizeEvent(event)

    def _layout_children(self) -> None:
        # self.height() 대신 heightForWidth 를 직접 계산:
        # resizeEvent 안에서 setFixedHeight() 직후에는 self.height()가 이전 값을 반환하므로
        # 컨트롤바 Y 좌표가 위젯 바깥으로 밀리는 버그가 발생함.
        h = self.heightForWidth(self.width())
        self._stack.setGeometry(0, 0, self.width(), h)
        if self._bar is not None:
            self._bar.setGeometry(0, h - self._BAR_H, self.width(), self._BAR_H)
            self._bar.raise_()


# ── Video view (QGraphicsView + QGraphicsVideoItem) ───────────────
# QVideoWidget은 Windows에서 네이티브 D3D HWND를 생성하며
# 이 D3D 렌더링이 Qt 위젯을 덮어써 컨트롤바 오버레이가 불가능함.
# QGraphicsVideoItem은 Qt 텍스처 시스템으로 렌더링하므로 오버레이가 정상 동작.

class _VideoView(QGraphicsView):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background: #000; border: none;")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.setInteractive(False)

        scene = QGraphicsScene(self)
        scene.setBackgroundBrush(QBrush(QColor("#000000")))
        self.setScene(scene)

        self._item = QGraphicsVideoItem()
        scene.addItem(self._item)
        self._item.nativeSizeChanged.connect(lambda _: self._fit())

    @property
    def video_item(self) -> QGraphicsVideoItem:
        return self._item

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.setSceneRect(0, 0, self.width(), self.height())
        self._fit()

    def _fit(self) -> None:
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        native = self._item.nativeSize()
        if native.isValid() and native.width() > 0 and native.height() > 0:
            scale = min(w / native.width(), h / native.height())
            vw, vh = native.width() * scale, native.height() * scale
            self._item.setPos(QPointF((w - vw) / 2, (h - vh) / 2))
            self._item.setSize(QSizeF(vw, vh))
        else:
            self._item.setPos(QPointF(0, 0))
            self._item.setSize(QSizeF(w, h))


# ── Dedicated fullscreen window ───────────────────────────────────

class _PipWindow(QWidget):
    """화면 속 화면(PiP) — 항상 위에 뜨는 작은 플로팅 재생 창.

    `_FullscreenWindow`와 동일하게 공유 `QMediaPlayer`의 출력을 자체 `_VideoView`로
    리다이렉트한다(재생 위치·볼륨·상태는 그대로 유지). `_FullscreenWindow`와 마찬가지로
    **컨트롤바(`bar`) 신호는 외부(InlinePlayer)에서 반드시 배선**해야 버튼이 동작한다.

    프레임리스·항상 위이며, 영상 영역 드래그로 이동하고 우하단 `QSizeGrip`으로
    크기를 조절한다. 닫기(창 X/Esc/PiP 버튼/더블클릭)는 `exit_requested`로 알린다.
    """

    exit_requested = pyqtSignal()

    _DEFAULT_W = 480
    _DEFAULT_H = 270

    def __init__(self, player: QMediaPlayer, audio: QAudioOutput, key_handler=None) -> None:
        super().__init__(
            None,
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setStyleSheet("background:#000;")
        self.setWindowTitle("화면 속 화면")
        self._player = player
        self._key_handler = key_handler
        self._drag_offset: QPoint | None = None

        self._vw = _VideoView(self)
        # 영상 영역은 마우스 이벤트를 투명 처리 → 창 드래그가 영상 위에서도 동작
        self._vw.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._vw.viewport().setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.bar = _ControlBar(self)
        # PiP 창에서는 전체화면 버튼 숨기고, PiP 버튼은 '인라인 복귀' 용도
        self.bar._btn_fs.hide()
        self.bar._btn_pip.setToolTip("인라인으로 복귀")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._vw)

        player.setVideoOutput(self._vw.video_item)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._grip = QSizeGrip(self)
        self.resize(self._DEFAULT_W, self._DEFAULT_H)
        QTimer.singleShot(0, self._layout_children)

    def _layout_children(self) -> None:
        bh = _ControlBar._HEIGHT
        self.bar.setGeometry(0, self.height() - bh, self.width(), bh)
        self.bar.raise_()
        self.bar.show()
        gs = 16
        self._grip.setGeometry(self.width() - gs, self.height() - gs, gs, gs)
        self._grip.raise_()

    def resizeEvent(self, event) -> None:
        self._layout_children()
        super().resizeEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._key_handler:
            self._key_handler(event)
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None

    def mouseDoubleClickEvent(self, event) -> None:
        self.exit_requested.emit()

    def closeEvent(self, event) -> None:
        self.exit_requested.emit()
        event.ignore()


class _FullscreenWindow(QWidget):
    """Top-level fullscreen window on the target screen.

    Holds its own QVideoWidget; QMediaPlayer output is redirected here.
    All key events are forwarded to the provided key_handler so that the
    InlinePlayer's full shortcut set (Space, J, L, F, Esc, …) works.

    `_PipWindow`와 동일하게 **컨트롤바(`bar`) 신호는 외부(InlinePlayer)에서 반드시
    배선**해야 버튼이 동작한다(재생/탐색/볼륨/음소거/다운로드/화질/전체화면·PiP 전환).
    """

    exit_requested = pyqtSignal()

    def __init__(
        self,
        player: QMediaPlayer,
        audio: QAudioOutput,
        key_handler=None,
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint,
        )
        self.setStyleSheet("background:#000;")
        self._player = player
        self._key_handler = key_handler

        self._vw = _VideoView(self)
        self.bar = _ControlBar(self)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._vw)

        player.setVideoOutput(self._vw.video_item)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        QTimer.singleShot(0, self._position_bar)

    def _position_bar(self) -> None:
        bh = _ControlBar._HEIGHT
        self.bar.setGeometry(0, self.height() - bh, self.width(), bh)
        self.bar.raise_()
        self.bar.show()

    def resizeEvent(self, event) -> None:
        bh = _ControlBar._HEIGHT
        self.bar.setGeometry(0, self.height() - bh, self.width(), bh)
        self.bar.raise_()
        super().resizeEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        # Forward every key to InlinePlayer so all shortcuts work in fullscreen
        if self._key_handler:
            self._key_handler(event)
        else:
            if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_F):
                self.exit_requested.emit()
            else:
                super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        self.exit_requested.emit()

    def closeEvent(self, event) -> None:
        self.exit_requested.emit()
        event.ignore()


# ── Public widget ─────────────────────────────────────────────────

class InlinePlayer(QWidget):
    """Inline player: 16:9 video area with overlaid auto-hide control bar.

    Control bar overlays the bottom of the video, auto-hides after 3 s of
    mouse inactivity while playing, reappears on mouse movement over the area.

    YouTube-compatible keyboard shortcuts (Space/K, J, L, ←/→, ↑/↓, M, F, 0-9).
    """

    playback_failed    = pyqtSignal(str)
    download_requested = pyqtSignal(str, str, object)  # (url, title, DownloadSettings)

    _HIDE_MS = 2_000   # 2초 비활성 후 숨김
    _SHOW_MS = 1_000   # 마우스 감지 1초 후 표시
    _last_quality_fmt: str = _DEFAULT_QUALITY_FMT  # 세션 내 품질 선택 공유
    _last_quality_merge: bool = _DEFAULT_QUALITY_MERGE
    _last_quality_short: str = _QUALITY_OPTIONS[0][2]  # "자동"
    # 재생 품질 단축 라벨 → 다운로드 품질 문자열 매핑
    # DownloadInfoDTO.quality는 Quality Enum 값("1080p" 등) 또는 파일명 레이블("FHD" 등)
    _SHORT_TO_QUALITIES: dict[str, set[str]] = {
        "1080p": {"1080p", "FHD"},
        "720p":  {"720p",  "HD"},
        "480p":  {"480p",  "SD"},
        "360p":  {"360p",  "LD"},
        "240p":  {"240p"},
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._downloads: list[DownloadInfoDTO] = []
        self._video_url: str    = ""
        self._video_title: str  = ""
        self._worker: _StreamWorker | None  = None
        self._fs_win: _FullscreenWindow | None = None
        self._pip_win: _PipWindow | None = None
        self._volume    = 100
        self._is_muted  = False
        self._filter_on = False
        self._current_quality_fmt = InlinePlayer._last_quality_fmt
        self._current_merge: bool = InlinePlayer._last_quality_merge
        self._current_quality_short: str = InlinePlayer._last_quality_short
        self._resume_ms: int = 0
        self._stream_quality_label: str = ""  # yt-dlp 보고 품질 레이블
        self._temp_stream_path: str = ""      # 고화질 병합 임시 파일(재생 후 정리)
        self._setup()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(self._HIDE_MS)
        self._hide_timer.timeout.connect(self._auto_hide_bar)

        # 마우스 감지 후 1초 딜레이로 컨트롤바 표시
        self._show_timer = QTimer(self)
        self._show_timer.setSingleShot(True)
        self._show_timer.setInterval(self._SHOW_MS)
        self._show_timer.timeout.connect(self._do_show_bar_delayed)

        # 100ms마다 커서 위치를 확인해 컨트롤바 표시/raise
        self._cursor_poll = QTimer(self)
        self._cursor_poll.setInterval(100)
        self._cursor_poll.timeout.connect(self._poll_cursor)

    def _setup(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._player = QMediaPlayer(self)
        self._audio  = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._audio.setVolume(1.0)

        self._video_view = _VideoView()
        self._player.setVideoOutput(self._video_view.video_item)

        self._thumb_label = QLabel()
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_label.setStyleSheet("background:#1a1a1a;")

        self._visual_stack = QStackedWidget()
        self._visual_stack.setMouseTracking(True)
        self._visual_stack.addWidget(self._thumb_label)   # index 0
        self._visual_stack.addWidget(self._video_view)    # index 1

        # Control bar is an overlay inside _video_area
        # _VideoView renders via Qt texture system (no native D3D HWND),
        # so the control bar overlay is composited correctly by Qt.
        self._bar = _ControlBar()
        self._video_area = _VideoArea(self._visual_stack)
        self._video_area.set_overlay_bar(self._bar)
        outer.addWidget(self._video_area)

        # Status label (below video area, shown only while fetching stream)
        self._status_lbl = QLabel("")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setStyleSheet("color:#aaa;font-size:8pt;background:#111;")
        self._status_lbl.setFixedHeight(18)
        self._status_lbl.hide()
        outer.addWidget(self._status_lbl)

        # Wire control bar signals → player
        self._bar.play_toggled.connect(self._toggle_play)
        self._bar.seek_relative.connect(self._seek_relative)
        self._bar.seek_to_ms.connect(self._player.setPosition)
        self._bar.volume_changed.connect(self._on_volume_changed)
        self._bar.mute_toggled.connect(self._toggle_mute)
        self._bar.fullscreen_toggled.connect(self._toggle_fullscreen)
        self._bar.pip_toggled.connect(self._toggle_pip)
        self._bar.download_requested.connect(self._on_download_requested)
        self._bar.quality_changed.connect(self._on_quality_changed)

        # Wire player signals → control bar
        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._bar.update_duration)
        self._player.playbackStateChanged.connect(self._on_playback_state)
        self._player.errorOccurred.connect(self._on_error)
        self._player.metaDataChanged.connect(self._on_metadata_changed)
        self._player.mediaStatusChanged.connect(self._on_media_status)

        # 개별 위젯에도 이벤트 필터 설치 (앱 레벨 필터 보완)
        self._video_area.installEventFilter(self)
        self._visual_stack.installEventFilter(self)
        self._video_view.installEventFilter(self)

    # ── Mouse-activity tracking ────────────────────────────────────

    def showEvent(self, event) -> None:
        if not self._filter_on:
            app = QApplication.instance()
            if app:
                app.installEventFilter(self)
                self._filter_on = True
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._remove_filter()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        if self._pip_win:
            self._exit_pip()
        if self._fs_win:
            self._exit_fullscreen()
        self._remove_filter()
        super().closeEvent(event)

    def _remove_filter(self) -> None:
        if self._filter_on:
            app = QApplication.instance()
            if app:
                try:
                    app.removeEventFilter(self)
                except RuntimeError:
                    pass
            self._filter_on = False
        for w in (self._video_area, self._visual_stack, self._video_view):
            try:
                w.removeEventFilter(self)
            except RuntimeError:
                pass

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.MouseMove:
            try:
                gpos = event.globalPosition().toPoint()
            except AttributeError:
                gpos = event.globalPos()  # type: ignore[attr-defined]
            # Show bar whenever mouse is anywhere inside the video area
            va_local = self._video_area.mapFromGlobal(gpos)
            if self._video_area.rect().contains(va_local):
                self._on_mouse_activity()
        return False

    def _on_mouse_activity(self) -> None:
        playing = self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        if self._bar.isVisible():
            # 이미 표시 중: z-order 유지 + 숨김 타이머 리셋
            self._bar.raise_()
            if playing:
                self._hide_timer.start()
        else:
            # 숨겨진 상태: 1초 딜레이 후 표시
            if not self._show_timer.isActive():
                self._show_timer.start()

    def _do_show_bar_delayed(self) -> None:
        """_show_timer 만료 시 컨트롤바 표시."""
        self._bar.show()
        self._bar.raise_()
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._hide_timer.start()

    def _auto_hide_bar(self) -> None:
        if self._player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            return
        # 커서가 비디오 영역 안에 있으면 숨기지 않고 타이머를 재시작
        gpos = QCursor.pos()
        va_local = self._video_area.mapFromGlobal(gpos)
        if self._video_area.rect().contains(va_local):
            self._hide_timer.start()
        else:
            self._bar.hide()
            self._show_timer.stop()

    def _poll_cursor(self) -> None:
        if self._player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            return
        gpos = QCursor.pos()
        va_local = self._video_area.mapFromGlobal(gpos)
        if self._video_area.rect().contains(va_local):
            if self._bar.isVisible():
                self._bar.raise_()
            else:
                if not self._show_timer.isActive():
                    self._show_timer.start()
        else:
            self._show_timer.stop()

    # ── Public API ─────────────────────────────────────────────────

    @property
    def position_ms(self) -> int:
        """현재 재생 위치(ms). 재생 전이면 0."""
        return self._player.position()

    def seek_to_ms(self, ms: int) -> None:
        """절대 위치(ms)로 재생 위치를 이동한다. 설명 타임스탬프 클릭 등에서 사용."""
        self._player.setPosition(max(0, int(ms)))

    def load(
        self,
        video_url: str,
        downloads: list[DownloadInfoDTO],
        thumbnail_pixmap=None,
        title: str = "",
        resume_ms: int = 0,
    ) -> None:
        self.stop()
        self._video_url   = video_url
        self._video_title = title
        self._downloads   = downloads
        self._resume_ms   = resume_ms
        self._current_quality_fmt   = InlinePlayer._last_quality_fmt
        self._current_merge         = InlinePlayer._last_quality_merge
        self._current_quality_short = InlinePlayer._last_quality_short
        self._stream_quality_label = ""
        self._visual_stack.setCurrentIndex(0)
        if thumbnail_pixmap and not thumbnail_pixmap.isNull():
            self._thumb_label.setPixmap(thumbnail_pixmap)
        else:
            self._thumb_label.clear()
            self._thumb_label.setText("미리보기 없음" if not video_url else "")
        self._status_lbl.hide()
        self._bar.set_quality("")
        self._bar.show()
        self._bar.raise_()
        self._hide_timer.stop()

    def _find_local_for_quality(self, short: str) -> str | None:
        """선택 품질과 일치하는 다운로드 파일 경로 반환.
        "자동"이면 품질 무관 첫 번째 파일, 없으면 None."""
        target = InlinePlayer._SHORT_TO_QUALITIES.get(short)  # None → 자동
        for dl in reversed(self._downloads):
            if not (dl.file_path and Path(dl.file_path).exists()):
                continue
            if target is None or dl.quality in target:
                return dl.file_path
        return None

    def play(self) -> None:
        local = self._find_local_for_quality(self._current_quality_short)
        if local:
            self._start_local(local)
            return
        self._fetch_stream()

    def stop(self) -> None:
        # 분리 재생 창(PiP/전체화면)이 열려 있으면 출력을 인라인으로 복귀 후 정리
        if self._pip_win:
            self._exit_pip()
        if self._fs_win:
            self._exit_fullscreen()
        self._player.stop()
        self._player.setSource(QUrl())   # 파일 핸들 해제 후 임시 파일 삭제 가능
        self._cleanup_temp()
        self._hide_timer.stop()
        if self._worker:
            # 시그널 먼저 해제 — 스레드가 늦게 결과를 내보내도 무시
            try:
                self._worker.stream_ready.disconnect()
                self._worker.progress.disconnect()
                self._worker.failed.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._worker.quit()
            # 즉시 참조를 버리지 않고 Qt에 위임 — 스레드 종료 후 안전하게 삭제
            self._worker.deleteLater()
            self._worker = None
        self._visual_stack.setCurrentIndex(0)
        self._status_lbl.hide()
        self._bar.show()
        self._bar.raise_()
        self._bar.set_playing(False)

    def _cleanup_temp(self) -> None:
        """고화질 병합 임시 파일/디렉터리를 삭제한다."""
        path = self._temp_stream_path
        self._temp_stream_path = ""
        if not path:
            return
        try:
            import os  # noqa: PLC0415
            import shutil  # noqa: PLC0415
            d = os.path.dirname(path)
            if os.path.isfile(path):
                os.remove(path)
            if d and os.path.basename(d).startswith("ovc_stream_") and os.path.isdir(d):
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            logger.debug("임시 스트림 파일 정리 실패", exc_info=True)

    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    # ── YouTube keyboard shortcuts ─────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Space, Qt.Key.Key_K):
            self._toggle_play()
        elif key == Qt.Key.Key_J:
            self._seek_relative(-10)
        elif key == Qt.Key.Key_L:
            self._seek_relative(10)
        elif key == Qt.Key.Key_Left:
            self._seek_relative(-5)
        elif key == Qt.Key.Key_Right:
            self._seek_relative(5)
        elif key == Qt.Key.Key_Up:
            self._change_volume(5)
        elif key == Qt.Key.Key_Down:
            self._change_volume(-5)
        elif key == Qt.Key.Key_M:
            self._toggle_mute()
        elif key == Qt.Key.Key_P:
            self._toggle_pip()
        elif key in (Qt.Key.Key_F, Qt.Key.Key_Escape):
            # F toggles; Escape only exits (never enters) PiP/fullscreen
            if key == Qt.Key.Key_Escape:
                if self._pip_win and self._pip_win.isVisible():
                    self._exit_pip()
                elif self._fs_win and self._fs_win.isVisible():
                    self._exit_fullscreen()
            else:
                self._toggle_fullscreen()
        elif Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            pct = (key - Qt.Key.Key_0) * 10
            dur = self._player.duration()
            if dur > 0:
                self._player.setPosition(dur * pct // 100)
        else:
            super().keyPressEvent(event)

    # ── Internals ──────────────────────────────────────────────────

    def _toggle_play(self) -> None:
        state = self._player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self._player.play()
        else:
            self.play()

    def _seek_relative(self, delta_sec: int) -> None:
        pos = self._player.position()
        dur = self._player.duration()
        if dur > 0:
            self._player.setPosition(max(0, min(pos + delta_sec * 1000, dur)))

    def _change_volume(self, delta: int) -> None:
        vol = max(0, min(self._volume + delta, 100))
        self._volume = vol
        self._audio.setVolume(vol / 100.0)
        self._bar.set_volume(vol)
        if self._fs_win:
            self._fs_win.bar.set_volume(vol)
        if self._pip_win:
            self._pip_win.bar.set_volume(vol)

    def _toggle_mute(self) -> None:
        self._is_muted = not self._is_muted
        self._audio.setMuted(self._is_muted)
        self._bar.set_muted(self._is_muted)
        if self._fs_win:
            self._fs_win.bar.set_muted(self._is_muted)
        if self._pip_win:
            self._pip_win.bar.set_muted(self._is_muted)

    def _toggle_fullscreen(self) -> None:
        if self._fs_win and self._fs_win.isVisible():
            self._exit_fullscreen()
        else:
            self._enter_fullscreen()

    def _enter_fullscreen(self) -> None:
        # PiP와 동시 분리는 하지 않는다.
        if self._pip_win and self._pip_win.isVisible():
            self._exit_pip()

        center = self.mapToGlobal(QPoint(self.width() // 2, self.height() // 2))
        screen = QApplication.screenAt(center) or QApplication.primaryScreen()

        self._fs_win = _FullscreenWindow(
            self._player, self._audio, key_handler=self.keyPressEvent
        )
        bar = self._fs_win.bar
        # 전체화면 바 → 플레이어 (인라인 바와 동일한 핸들러 재사용)
        bar.play_toggled.connect(self._toggle_play)
        bar.seek_relative.connect(self._seek_relative)
        bar.seek_to_ms.connect(self._player.setPosition)
        bar.volume_changed.connect(self._on_volume_changed)
        bar.mute_toggled.connect(self._toggle_mute)
        bar.download_requested.connect(self._on_download_requested)
        bar.quality_changed.connect(self._on_quality_changed)
        bar.fullscreen_toggled.connect(self._toggle_fullscreen)
        bar.pip_toggled.connect(self._toggle_pip)
        # 플레이어 → 전체화면 바 (재생시간). 위치/재생상태는 _on_position/_on_playback_state가 fan-out.
        self._player.durationChanged.connect(bar.update_duration)
        # 현재 상태를 전체화면 바에 1회 반영
        dur = self._player.duration()
        bar.update_duration(dur)
        bar.update_position(self._player.position(), dur)
        bar.set_playing(self.is_playing())
        bar.set_volume(self._volume)
        bar.set_muted(self._is_muted)
        bar.set_quality(
            "" if self._current_quality_short == "자동" else self._current_quality_short
        )

        self._fs_win.exit_requested.connect(self._exit_fullscreen)

        geo = screen.geometry()
        self._fs_win.setGeometry(geo)
        self._fs_win.showFullScreen()
        self._fs_win.setFocus()

    def _exit_fullscreen(self) -> None:
        self._player.setVideoOutput(self._video_view.video_item)
        if self._fs_win:
            try:
                self._player.durationChanged.disconnect(self._fs_win.bar.update_duration)
            except (TypeError, RuntimeError):
                pass
            try:
                self._fs_win.exit_requested.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._fs_win.close()
            self._fs_win.deleteLater()
            self._fs_win = None
        self.setFocus()

    # ── Picture-in-Picture (화면 속 화면) ───────────────────────────

    def _toggle_pip(self) -> None:
        if self._pip_win and self._pip_win.isVisible():
            self._exit_pip()
        else:
            self._enter_pip()

    def _enter_pip(self) -> None:
        # 전체화면과 동시 분리는 하지 않는다.
        if self._fs_win and self._fs_win.isVisible():
            self._exit_fullscreen()

        self._pip_win = _PipWindow(
            self._player, self._audio, key_handler=self.keyPressEvent
        )
        bar = self._pip_win.bar
        # PiP 바 → 플레이어 (인라인 바와 동일한 핸들러 재사용)
        bar.play_toggled.connect(self._toggle_play)
        bar.seek_relative.connect(self._seek_relative)
        bar.seek_to_ms.connect(self._player.setPosition)
        bar.volume_changed.connect(self._on_volume_changed)
        bar.mute_toggled.connect(self._toggle_mute)
        bar.download_requested.connect(self._on_download_requested)
        bar.quality_changed.connect(self._on_quality_changed)
        bar.pip_toggled.connect(self._exit_pip)
        # 플레이어 → PiP 바 (재생시간). 위치/재생상태는 _on_position/_on_playback_state가 fan-out.
        self._player.durationChanged.connect(bar.update_duration)
        # 현재 상태를 PiP 바에 1회 반영
        dur = self._player.duration()
        bar.update_duration(dur)
        bar.update_position(self._player.position(), dur)
        bar.set_playing(self.is_playing())
        bar.set_volume(self._volume)
        bar.set_muted(self._is_muted)
        bar.set_quality(
            "" if self._current_quality_short == "자동" else self._current_quality_short
        )

        self._pip_win.exit_requested.connect(self._exit_pip)
        self._show_pip_placeholder(True)

        # 화면 우하단에 배치
        center = self.mapToGlobal(QPoint(self.width() // 2, self.height() // 2))
        screen = QApplication.screenAt(center) or QApplication.primaryScreen()
        geo = screen.availableGeometry()
        w, h = _PipWindow._DEFAULT_W, _PipWindow._DEFAULT_H
        self._pip_win.setGeometry(geo.right() - w - 24, geo.bottom() - h - 24, w, h)
        self._pip_win.show()
        self._pip_win.raise_()
        self._pip_win.setFocus()

    def _exit_pip(self) -> None:
        # 출력 복귀 먼저, 그다음 창 정리
        self._player.setVideoOutput(self._video_view.video_item)
        if self._pip_win:
            try:
                self._player.durationChanged.disconnect(self._pip_win.bar.update_duration)
            except (TypeError, RuntimeError):
                pass
            try:
                self._pip_win.exit_requested.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._pip_win.close()
            self._pip_win.deleteLater()
            self._pip_win = None
        self._show_pip_placeholder(False)
        self.setFocus()

    def _show_pip_placeholder(self, on: bool) -> None:
        """PiP 활성 시 인라인 영역에 안내(썸네일/문구)를 표시한다."""
        if on:
            pm = self._thumb_label.pixmap()
            if pm is None or pm.isNull():
                self._thumb_label.setText("화면 속 화면으로 재생 중")
            self._visual_stack.setCurrentIndex(0)
        elif self._player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self._visual_stack.setCurrentIndex(1)

    def _on_volume_changed(self, vol: int) -> None:
        self._volume = vol
        self._audio.setVolume(vol / 100.0)
        muted = vol == 0
        if muted != self._is_muted:
            self._is_muted = muted
            self._audio.setMuted(muted)
            self._bar.set_muted(muted)

    def _on_position(self, pos: int) -> None:
        dur = self._player.duration()
        self._bar.update_position(pos, dur)
        if self._fs_win:
            self._fs_win.bar.update_position(pos, dur)
        if self._pip_win:
            self._pip_win.bar.update_position(pos, dur)

    def _on_playback_state(self, state: QMediaPlayer.PlaybackState) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self._bar.set_playing(playing)
        if self._fs_win:
            self._fs_win.bar.set_playing(playing)
        if self._pip_win:
            self._pip_win.bar.set_playing(playing)
        if playing:
            self._bar.show()
            self._bar.raise_()
            self._hide_timer.start()
            self._cursor_poll.start()
        else:
            self._hide_timer.stop()
            self._show_timer.stop()
            self._cursor_poll.stop()
            self._bar.show()
            self._bar.raise_()
        if state == QMediaPlayer.PlaybackState.StoppedState:
            self._visual_stack.setCurrentIndex(0)

    def _do_play_start(self) -> None:
        """재생 시작. 이어보기(resume_ms) seek은 미디어가 탐색 가능해지는
        시점(_on_media_status)에서 견고하게 처리한다."""
        self._player.play()

    def _on_media_status(self, status) -> None:
        """미디어가 로드/버퍼되어 탐색 가능해지면 이어보기 위치로 이동한다.
        고정 지연(seek-after-80ms)은 네트워크 스트림에서 불안정하므로 사용하지 않는다."""
        if self._resume_ms <= 0:
            return
        if status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ) and self._player.isSeekable():
            self._player.setPosition(self._resume_ms)
            self._resume_ms = 0

    def _start_local(self, path: str) -> None:
        self._player.setSource(QUrl.fromLocalFile(path))
        self._visual_stack.setCurrentIndex(1)
        self._bar.show()
        self._bar.raise_()
        QTimer.singleShot(50, self._do_play_start)

    def _fetch_stream(self) -> None:
        if not self._video_url:
            self.playback_failed.emit("재생할 URL이 없습니다.")
            return
        # 이전 소스/임시 파일 해제 (특히 품질 전환 시)
        self._player.setSource(QUrl())
        self._cleanup_temp()
        self._status_lbl.setText(
            "고화질 준비 중…" if self._current_merge else "스트림 URL 가져오는 중…"
        )
        self._status_lbl.show()
        # 이전 워커가 살아 있으면 늦게 도착하는 신호를 무시한다
        if self._worker is not None:
            try:
                self._worker.stream_ready.disconnect()
                self._worker.progress.disconnect()
                self._worker.failed.disconnect()
            except (TypeError, RuntimeError):
                pass
        self._worker = _StreamWorker(
            self._video_url, self._current_quality_fmt, self._current_merge, self
        )
        self._worker.stream_ready.connect(self._on_stream_ready)
        self._worker.progress.connect(self._on_merge_progress)
        self._worker.failed.connect(self._on_stream_failed)
        self._worker.start()

    def _on_merge_progress(self, pct: int) -> None:
        self._status_lbl.setText(f"고화질 준비 중…  {pct}%")
        self._status_lbl.show()

    def _on_stream_ready(self, src: str, quality: str, is_local: bool) -> None:
        self._status_lbl.hide()
        self._temp_stream_path = src if is_local else ""
        self._player.setSource(QUrl.fromLocalFile(src) if is_local else QUrl(src))
        self._visual_stack.setCurrentIndex(1)
        self._bar.show()
        self._bar.raise_()
        self._stream_quality_label = quality  # metadata 업데이트 기준으로 사용
        self._bar.set_quality(quality or "")
        QTimer.singleShot(50, self._do_play_start)

    def _on_stream_failed(self, err: str) -> None:
        self._status_lbl.hide()
        self.playback_failed.emit(err)

    def _on_error(self, error, error_string: str) -> None:
        if error != QMediaPlayer.Error.NoError:
            self.stop()
            self.playback_failed.emit(error_string)

    def _on_quality_changed(self, fmt: str, short: str, merge: bool) -> None:
        self._current_quality_fmt   = fmt
        self._current_merge         = merge
        self._current_quality_short = short
        InlinePlayer._last_quality_fmt   = fmt
        InlinePlayer._last_quality_merge = merge
        InlinePlayer._last_quality_short = short
        state = self._player.playbackState()
        if state != QMediaPlayer.PlaybackState.StoppedState:
            # 현재 재생 위치를 저장해 새 화질에서 이어서 재생
            self._resume_ms = self._player.position()
            self._player.stop()
            self._visual_stack.setCurrentIndex(0)
            local = self._find_local_for_quality(short)
            if local:
                self._bar.set_quality(short)
                self._start_local(local)
            else:
                self._bar.set_quality("전환 중…")
                self._fetch_stream()

    def _on_metadata_changed(self) -> None:
        """yt-dlp 보고 품질이 없을 때만 Qt 메타데이터 해상도로 뱃지를 보완한다."""
        if self._stream_quality_label:
            return
        try:
            from PyQt6.QtMultimedia import QMediaMetaData  # noqa: PLC0415
            meta = self._player.metaData()
            res = meta.value(QMediaMetaData.Key.Resolution)
            if res is not None and hasattr(res, "height"):
                h = res.height()
                if h > 0:
                    self._bar.set_quality(f"{h}p")
        except Exception:
            logger.exception("Qt 메타데이터 해상도 뱃지 보완 실패")

    def _on_download_requested(self, settings: DownloadSettings) -> None:
        self.download_requested.emit(self._video_url, self._video_title, settings)
