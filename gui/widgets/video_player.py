"""Reusable inline video-player widget (InlinePlayer).

Layout: 16:9 video area that overlays the control bar at the bottom.
Qt 6.6+ multimedia renders via QRhi (not a native HWND), so a child QWidget
with raise_() correctly appears on top of QVideoWidget.

Fullscreen creates a separate top-level window on the same monitor as the
player, redirects QMediaPlayer output there, and restores on exit.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QEvent, QPoint, QThread, QTimer, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from application.library.dtos import DownloadInfoDTO
from domain.download.value_objects import DownloadSettings, MediaFormat, Quality


# ── Background worker: resolve yt-dlp stream URL ──────────────────

class _StreamWorker(QThread):
    stream_ready = pyqtSignal(str, str)   # (stream_url, quality_label e.g. "720p")
    failed       = pyqtSignal(str)

    def __init__(self, url: str, quality_fmt: str = "best[ext=mp4]/best", parent=None) -> None:
        super().__init__(parent)
        self._url = url
        self._quality_fmt = quality_fmt

    def run(self) -> None:
        try:
            import yt_dlp  # noqa: PLC0415
            opts = {"quiet": True, "format": self._quality_fmt, "noplaylist": True}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self._url, download=False) or {}
                stream: str = info.get("url", "")
                fmt_info: dict = {}
                if not stream:
                    for f in reversed(info.get("formats") or []):
                        if f.get("url") and f.get("ext") == "mp4":
                            stream = f["url"]
                            fmt_info = f
                            break
                if not stream:
                    for f in reversed(info.get("formats") or []):
                        if f.get("url"):
                            stream = f["url"]
                            fmt_info = f
                            break

                quality_label = ""
                h = fmt_info.get("height") or info.get("height")
                if h:
                    quality_label = f"{h}p"

                if stream:
                    self.stream_ready.emit(stream, quality_label)
                else:
                    self.failed.emit("스트림 URL을 가져올 수 없습니다.")
        except Exception as exc:
            self.failed.emit(str(exc))


# ── Control bar (overlaid at the bottom of the video area) ────────

_BAR_STYLE = """
QWidget#ctrlbar {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 rgba(0,0,0,0), stop:1 rgba(0,0,0,200));
}
QToolButton {
    color: #e0e0e0;
    background: transparent;
    border: none;
    font-size: 13px;
    padding: 2px 4px;
    min-width: 24px;
    min-height: 24px;
}
QToolButton:hover { color: #fff; background: rgba(255,255,255,15); border-radius: 3px; }
QLabel { color: #ccc; background: transparent; font-size: 9pt; }
QSlider::groove:horizontal {
    height: 4px; background: rgba(255,255,255,60); border-radius: 2px;
}
QSlider::sub-page:horizontal {
    height: 4px; background: #f00; border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 12px; height: 12px;
    margin: -4px 0;
    background: #ddd; border-radius: 6px;
}
"""

_QUALITY_BADGE = (
    "color:#fff; background:rgba(0,0,0,0.7); "
    "font-size:8pt; padding:1px 5px; border-radius:3px;"
)

# (label shown in menu, format string for yt-dlp, short label for button)
_QUALITY_OPTIONS = [
    ("자동 (최고 화질)", "best[ext=mp4]/best",                              "자동"),
    ("1080p",           "best[height<=1080][ext=mp4]/best[height<=1080]/best", "1080p"),
    ("720p",            "best[height<=720][ext=mp4]/best[height<=720]/best",   "720p"),
    ("480p",            "best[height<=480][ext=mp4]/best[height<=480]/best",   "480p"),
    ("360p",            "best[height<=360][ext=mp4]/best[height<=360]/best",   "360p"),
    ("240p",            "best[height<=240][ext=mp4]/best[height<=240]/best",   "240p"),
]
_DEFAULT_QUALITY_FMT = _QUALITY_OPTIONS[0][1]


class _ControlBar(QWidget):
    play_toggled       = pyqtSignal()
    seek_relative      = pyqtSignal(int)   # delta in seconds
    seek_to_ms         = pyqtSignal(int)   # absolute ms
    volume_changed     = pyqtSignal(int)   # 0-100
    mute_toggled       = pyqtSignal()
    fullscreen_toggled = pyqtSignal()
    download_requested = pyqtSignal(object)   # DownloadSettings
    quality_changed    = pyqtSignal(str, str) # (fmt_string, short_label)

    _HEIGHT = 72

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ctrlbar")
        self.setStyleSheet(_BAR_STYLE)
        self.setFixedHeight(self._HEIGHT)
        # Allow the bar to receive mouse events (needed for clicks on controls)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._dragging = False
        self._setup()

    def _setup(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 6)
        outer.setSpacing(4)

        # Progress slider (full width)
        self._progress = QSlider(Qt.Orientation.Horizontal)
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

        self._vol = QSlider(Qt.Orientation.Horizontal)
        self._vol.setRange(0, 100)
        self._vol.setValue(100)
        self._vol.setFixedWidth(68)
        self._vol.setToolTip("볼륨  (↑/↓)")
        self._vol.valueChanged.connect(self.volume_changed.emit)

        self._time_lbl = QLabel("0:00 / 0:00")

        self._quality_lbl = QLabel("")
        self._quality_lbl.setStyleSheet(_QUALITY_BADGE)
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
        self._btn_fs = btn("⛶", "전체화면  (F)", self.fullscreen_toggled.emit)

        for w in (self._btn_play, self._btn_back, self._btn_fwd,
                  self._btn_mute, self._vol, self._time_lbl):
            row.addWidget(w)
        row.addStretch()
        row.addWidget(self._quality_lbl)
        row.addWidget(self._btn_quality)
        row.addWidget(self._btn_dl)
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
        menu.setStyleSheet(
            "QMenu{background:#1e1e1e;color:#e0e0e0;border:1px solid #444;}"
            "QMenu::item:selected{background:#333;}"
        )
        for menu_label, fmt, short in _QUALITY_OPTIONS:
            act = menu.addAction(menu_label)
            act.triggered.connect(
                lambda _c, f=fmt, s=short: self._on_quality_item(f, s)
            )
        btn_pos = self._btn_quality.mapToGlobal(QPoint(0, 0))
        hint = menu.sizeHint()
        menu.exec(QPoint(btn_pos.x(), btn_pos.y() - hint.height()))

    def _on_quality_item(self, fmt: str, short: str) -> None:
        self._btn_quality.setText(short)
        self.quality_changed.emit(fmt, short)

    def _show_download_menu(self) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#1e1e1e;color:#e0e0e0;border:1px solid #444;}"
            "QMenu::item:selected{background:#333;}"
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
        self._stack.setGeometry(self.rect())
        if self._bar is not None:
            self._bar.setGeometry(0, self.height() - self._BAR_H, self.width(), self._BAR_H)
            self._bar.raise_()


# ── Dedicated fullscreen window ───────────────────────────────────

class _FullscreenWindow(QWidget):
    """Top-level fullscreen window on the target screen.

    Holds its own QVideoWidget; QMediaPlayer output is redirected here.
    All key events are forwarded to the provided key_handler so that the
    InlinePlayer's full shortcut set (Space, J, L, F, Esc, …) works.
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

        self._vw = QVideoWidget(self)
        self._fs_bar = _ControlBar(self)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._vw)

        player.setVideoOutput(self._vw)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        QTimer.singleShot(0, self._position_bar)

    def _position_bar(self) -> None:
        bh = _ControlBar._HEIGHT
        self._fs_bar.setGeometry(0, self.height() - bh, self.width(), bh)
        self._fs_bar.raise_()
        self._fs_bar.show()

    def resizeEvent(self, event) -> None:
        bh = _ControlBar._HEIGHT
        self._fs_bar.setGeometry(0, self.height() - bh, self.width(), bh)
        self._fs_bar.raise_()
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

    _HIDE_MS = 3_000

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._downloads: list[DownloadInfoDTO] = []
        self._video_url: str    = ""
        self._video_title: str  = ""
        self._worker: _StreamWorker | None  = None
        self._fs_win: _FullscreenWindow | None = None
        self._volume    = 100
        self._is_muted  = False
        self._filter_on = False
        self._current_quality_fmt = _DEFAULT_QUALITY_FMT
        self._setup()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(self._HIDE_MS)
        self._hide_timer.timeout.connect(self._auto_hide_bar)

    def _setup(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._player = QMediaPlayer(self)
        self._audio  = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._audio.setVolume(1.0)

        self._video_widget = QVideoWidget()
        self._player.setVideoOutput(self._video_widget)

        self._thumb_label = QLabel()
        self._thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb_label.setStyleSheet("background:#1a1a1a;")

        self._visual_stack = QStackedWidget()
        self._visual_stack.addWidget(self._thumb_label)   # index 0
        self._visual_stack.addWidget(self._video_widget)  # index 1

        # Control bar is an overlay inside _video_area
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
        self._bar.download_requested.connect(self._on_download_requested)
        self._bar.quality_changed.connect(self._on_quality_changed)

        # Wire player signals → control bar
        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._bar.update_duration)
        self._player.playbackStateChanged.connect(self._on_playback_state)
        self._player.errorOccurred.connect(self._on_error)
        self._player.metaDataChanged.connect(self._on_metadata_changed)

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
        self._bar.show()
        self._bar.raise_()
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._hide_timer.start()

    def _auto_hide_bar(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._bar.hide()

    # ── Public API ─────────────────────────────────────────────────

    def load(
        self,
        video_url: str,
        downloads: list[DownloadInfoDTO],
        thumbnail_pixmap=None,
        title: str = "",
    ) -> None:
        self.stop()
        self._video_url   = video_url
        self._video_title = title
        self._downloads   = downloads
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

    def play(self) -> None:
        for dl in reversed(self._downloads):
            if dl.file_path and Path(dl.file_path).exists():
                self._start_local(dl.file_path)
                return
        self._fetch_stream()

    def stop(self) -> None:
        self._player.stop()
        self._hide_timer.stop()
        if self._worker:
            self._worker.quit()
            self._worker = None
        self._visual_stack.setCurrentIndex(0)
        self._status_lbl.hide()
        self._bar.show()
        self._bar.raise_()
        self._bar.set_playing(False)

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
        elif key in (Qt.Key.Key_F, Qt.Key.Key_Escape):
            # F toggles; Escape only exits (never enters) fullscreen
            if key == Qt.Key.Key_Escape:
                if self._fs_win and self._fs_win.isVisible():
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

    def _toggle_mute(self) -> None:
        self._is_muted = not self._is_muted
        self._audio.setMuted(self._is_muted)
        self._bar.set_muted(self._is_muted)

    def _toggle_fullscreen(self) -> None:
        if self._fs_win and self._fs_win.isVisible():
            self._exit_fullscreen()
        else:
            self._enter_fullscreen()

    def _enter_fullscreen(self) -> None:
        center = self.mapToGlobal(QPoint(self.width() // 2, self.height() // 2))
        screen = QApplication.screenAt(center) or QApplication.primaryScreen()

        self._fs_win = _FullscreenWindow(
            self._player, self._audio, key_handler=self.keyPressEvent
        )
        self._fs_win.exit_requested.connect(self._exit_fullscreen)

        geo = screen.geometry()
        self._fs_win.setGeometry(geo)
        self._fs_win.showFullScreen()
        self._fs_win.setFocus()

    def _exit_fullscreen(self) -> None:
        self._player.setVideoOutput(self._video_widget)
        if self._fs_win:
            self._fs_win.exit_requested.disconnect()
            self._fs_win.close()
            self._fs_win.deleteLater()
            self._fs_win = None
        self.setFocus()

    def _on_volume_changed(self, vol: int) -> None:
        self._volume = vol
        self._audio.setVolume(vol / 100.0)
        muted = vol == 0
        if muted != self._is_muted:
            self._is_muted = muted
            self._audio.setMuted(muted)
            self._bar.set_muted(muted)

    def _on_position(self, pos: int) -> None:
        self._bar.update_position(pos, self._player.duration())

    def _on_playback_state(self, state: QMediaPlayer.PlaybackState) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self._bar.set_playing(playing)
        if playing:
            self._bar.show()
            self._bar.raise_()
            self._hide_timer.start()
        else:
            self._hide_timer.stop()
            self._bar.show()
            self._bar.raise_()
        if state == QMediaPlayer.PlaybackState.StoppedState:
            self._visual_stack.setCurrentIndex(0)

    def _start_local(self, path: str) -> None:
        self._player.setSource(QUrl.fromLocalFile(path))
        self._visual_stack.setCurrentIndex(1)
        self._bar.show()
        self._bar.raise_()
        QTimer.singleShot(50, self._player.play)

    def _fetch_stream(self) -> None:
        if not self._video_url:
            self.playback_failed.emit("재생할 URL이 없습니다.")
            return
        self._status_lbl.setText("스트림 URL 가져오는 중…")
        self._status_lbl.show()
        self._worker = _StreamWorker(self._video_url, self._current_quality_fmt, self)
        self._worker.stream_ready.connect(self._on_stream_ready)
        self._worker.failed.connect(self._on_stream_failed)
        self._worker.start()

    def _on_stream_ready(self, stream_url: str, quality: str) -> None:
        self._status_lbl.hide()
        self._player.setSource(QUrl(stream_url))
        self._visual_stack.setCurrentIndex(1)
        self._bar.show()
        self._bar.raise_()
        if quality:
            self._bar.set_quality(quality)
        QTimer.singleShot(50, self._player.play)

    def _on_stream_failed(self, err: str) -> None:
        self._status_lbl.hide()
        self.playback_failed.emit(err)

    def _on_error(self, error, error_string: str) -> None:
        if error != QMediaPlayer.Error.NoError:
            self.stop()
            self.playback_failed.emit(error_string)

    def _on_quality_changed(self, fmt: str, _label: str) -> None:
        self._current_quality_fmt = fmt
        state = self._player.playbackState()
        if state != QMediaPlayer.PlaybackState.StoppedState:
            self._player.stop()
            self._visual_stack.setCurrentIndex(0)
            self._fetch_stream()

    def _on_metadata_changed(self) -> None:
        """Update quality badge with actual video resolution once media loads."""
        try:
            from PyQt6.QtMultimedia import QMediaMetaData  # noqa: PLC0415
            meta = self._player.metaData()
            res = meta.value(QMediaMetaData.Key.Resolution)
            if res is not None and hasattr(res, "height"):
                h = res.height()
                if h > 0:
                    self._bar.set_quality(f"{h}p")
        except Exception:
            pass

    def _on_download_requested(self, settings: DownloadSettings) -> None:
        self.download_requested.emit(self._video_url, self._video_title, settings)
