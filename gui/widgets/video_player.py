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
    QTimer,
    QUrl,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QCursor, QKeyEvent
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from application.library.dtos import DownloadInfoDTO
from config import settings
from domain.download.value_objects import DownloadSettings
from gui.workers import retire_thread, track_thread
from gui.widgets.lyrics_overlay import LyricsCue, LyricsOverlay, LyricsTrack


# ── 분할된 부품 (gui/widgets/player/*) ─────────────────────────────
# 이 파일에는 화면 조립·흐름 제어만 남기고 부품은 패키지로 옮겼다.
# 아래 재수출은 기존 임포트 경로를 유지하기 위한 것이다.
from gui.widgets.player.stream import (  # noqa: F401
    _HEIGHT_CACHE,
    _FormatProbeWorker,
    _StreamWorker,
    _cache_heights,
    _is_youtube,
    _pick_stream_url,
    _stream_playable,
)
from gui.widgets.player.controls import (  # noqa: F401
    _ControlBar,
    _TrackSlider,
    _bar_style,
    _quality_badge_style,
)
from gui.widgets.player.surfaces import (  # noqa: F401
    _FullscreenWindow,
    _PipWindow,
    _VideoArea,
    _VideoView,
)


# ── 분할된 부품 (gui/widgets/player/*) ─────────────────────────────
# 이 파일에는 화면 조립·흐름 제어만 남기고 부품은 패키지로 옮겼다.
# 아래 재수출은 기존 임포트 경로를 유지하기 위한 것이다.
from gui.widgets.player.constants import (  # noqa: F401
    _merge_fmt,
    _DEFAULT_QUALITY_FMT,
    _DEFAULT_QUALITY_MERGE,
    _MAX_STREAM_RETRIES,
    _PROBE_RANGE,
    _PROBE_TIMEOUT,
    _PROBE_UA,
    _QUALITY_HEIGHTS,
    _QUALITY_OPTIONS,
    _STREAM_CLIENTS,
)

logger = logging.getLogger(__name__)


# ── 스트림 URL 획득 보조 (순수 함수 — 네트워크 없이 테스트 가능) ──────────











# ── Background worker: resolve yt-dlp stream URL ──────────────────



# ── Control bar (overlaid at the bottom of the video area) ────────





# URL → 사용 가능한 높이 목록 (세션 캐시, 상한 있음)













# ── 16:9 video area with overlaid control bar ─────────────────────



# ── Video view (QGraphicsView + QGraphicsVideoItem) ───────────────
# QVideoWidget은 Windows에서 네이티브 D3D HWND를 생성하며
# 이 D3D 렌더링이 Qt 위젯을 덮어써 컨트롤바 오버레이가 불가능함.
# QGraphicsVideoItem은 Qt 텍스처 시스템으로 렌더링하므로 오버레이가 정상 동작.



# ── Dedicated fullscreen window ───────────────────────────────────





# ── Public widget ─────────────────────────────────────────────────

class InlinePlayer(QWidget):
    """Inline player: 16:9 video area with overlaid auto-hide control bar.

    Control bar overlays the bottom of the video, auto-hides after 3 s of
    mouse inactivity while playing, reappears on mouse movement over the area.

    YouTube-compatible keyboard shortcuts (Space/K, J, L, ←/→, ↑/↓, M, F, 0-9,
    C, [, ], \\).
    """

    playback_failed    = pyqtSignal(str)
    download_requested = pyqtSignal(str, str, object)  # (url, title, DownloadSettings)
    playback_finished  = pyqtSignal()   # 미디어 끝까지 재생됨(EndOfMedia) — 재생목록 자동 다음곡용
    subtitle_offset_changed = pyqtSignal(int)   # 사용자가 싱크를 바꿈 → 저장 요청
    current_line_changed    = pyqtSignal(int)   # 원본 가사 줄 인덱스(없으면 -1)

    _HIDE_MS = 2_000   # 2초 비활성 후 숨김
    _SHOW_MS = 1_000   # 마우스 감지 1초 후 표시
    _OFFSET_STEP_MS = 250   # [ / ] 한 번에 움직이는 폭
    _FONT_SCALE_STEP = 0.1      # Ctrl + 휠/방향키 한 번에 움직이는 배율
    _BOTTOM_RATIO_STEP = 0.02   # Ctrl+Shift + 휠/방향키 한 번에 움직이는 위치 비율
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
        self._probe: _FormatProbeWorker | None = None
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
        self._playing_local: bool = False     # 로컬 파일 재생 중인지(재시도 판단용)
        self._stream_retries: int = 0         # 재생 오류 후 스트림 재획득 횟수
        self._track: LyricsTrack | None = None
        self._subtitle_on = True
        # 자막 표시 설정은 전역이라 생성 시 설정값을 읽어 시작한다.
        self._subtitle_font_scale: float = settings.SUBTITLE_FONT_SCALE
        self._subtitle_bottom_ratio: float = settings.SUBTITLE_BOTTOM_RATIO
        self._current_line_index = -1
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
        self._subtitle = LyricsOverlay()
        self._video_area = _VideoArea(self._visual_stack)
        self._video_area.set_overlay_subtitle(self._subtitle)
        self._video_area.set_overlay_bar(self._bar)
        outer.addWidget(self._video_area)

        # Status label (below video area, shown only while fetching stream)
        self._status_lbl = QLabel("")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setStyleSheet("color:#aaa;font-size:8pt;background:#111;")
        self._status_lbl.setFixedHeight(18)
        self._status_lbl.hide()
        outer.addWidget(self._status_lbl)

        self._transient_timer = QTimer(self)
        self._transient_timer.setSingleShot(True)
        self._transient_timer.timeout.connect(self._clear_transient)
        self._transient_text = ""
        # 임시 문구가 덮어쓴 직전 상태(문구, 표시 여부) — 만료 후 되돌린다.
        self._status_before_transient: tuple[str, bool] = ("", False)

        # 휠은 이벤트가 연속으로 쏟아지므로 자막 오프셋과 같은 500ms 디바운스로
        # 마지막 값만 한 번 기록한다.
        self._prefs_save_timer = QTimer(self)
        self._prefs_save_timer.setSingleShot(True)
        self._prefs_save_timer.setInterval(500)
        self._prefs_save_timer.timeout.connect(self._flush_subtitle_prefs)

        # Wire control bar signals → player
        self._bar.play_toggled.connect(self._toggle_play)
        self._bar.seek_relative.connect(self._seek_relative)
        self._bar.seek_to_ms.connect(self._player.setPosition)
        self._bar.volume_changed.connect(self._on_volume_changed)
        self._bar.mute_toggled.connect(self._toggle_mute)
        self._bar.fullscreen_toggled.connect(self._toggle_fullscreen)
        self._bar.pip_toggled.connect(self._toggle_pip)
        self._bar.download_requested.connect(self._on_download_requested)
        self._bar.download_menu_requested.connect(self._on_download_menu_requested)
        self._bar.quality_changed.connect(self._on_quality_changed)
        self._bar.subtitle_toggled.connect(self.set_subtitle_enabled)
        self._bar.subtitle_offset_nudged.connect(self._nudge_subtitle_offset)
        self._bar.subtitle_sync_here.connect(
            lambda: self._sync_subtitle_here(self._player.position())
        )
        self._bar.subtitle_offset_reset.connect(self._reset_subtitle_offset)
        self._bar.subtitle_prefs_reset.connect(self._reset_subtitle_prefs)

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
        # _video_view.viewport()에는 별도로 installEventFilter를 걸지 않는다 —
        # showEvent()가 앱 전역 필터(app.installEventFilter(self))를 이미 설치하고,
        # 전역 필터는 애플리케이션의 모든 객체로 가는 이벤트를 개별 설치보다 먼저
        # 받으므로 eventFilter()의 Wheel 분기가 그 경로로도 정상 도달한다(실측
        # 확인 — per-object 설치를 빼고도 동작함). 왜 Wheel 분기가 필요한지는
        # eventFilter() 주석 참조.

        # 저장된 크기·위치를 오버레이에 실제로 밀어 넣는다. 생성자가 설정값을 필드에
        # 담기만 하고 여기서 반영하지 않으면, config 에 2.0 이 저장돼 있어도 화면
        # 자막은 1.0 크기로 뜨고 첫 Ctrl+휠에서 1.0 → 2.1 로 튄다.
        self._apply_subtitle_prefs()

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
        if self._prefs_save_timer.isActive():
            self._prefs_save_timer.stop()
            self._flush_subtitle_prefs()
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
        elif event.type() == QEvent.Type.Wheel:
            # _VideoView(QGraphicsView)의 실제 입력 수신부는 viewport()다. 이 viewport로
            # 온 Wheel 이벤트는 QAbstractScrollArea가 내부적으로 viewportEvent()를 거쳐
            # wheelEvent()로 바로 넘기는데, 이 경로는 QApplication::notify()의 "무시된
            # 이벤트는 부모 위젯으로 전파한다" 처리를 거치지 않는다 — _VideoView.wheelEvent
            # 의 event.ignore()가 상위(InlinePlayer/_FullscreenWindow)까지 자동으로
            # 전달되지 않는다는 뜻이다(가시성과는 무관 — 재생 중이라 뷰가 화면에 보이는
            # 상태에서도 동일하게 막힌다). 그래서 _VideoView를 담고 있는 **세 창 모두**
            # viewport를 직접 가로채 InlinePlayer.wheelEvent로 넘긴다: 인라인
            # self._video_view.viewport(), 전체화면 self._fs_win._vw.viewport(),
            # PiP self._pip_win._vw.viewport(). PiP는 드래그용
            # WA_TransparentForMouseEvents 덕분에 히트테스트가 viewport를 건너뛰어
            # 지금까지 '우연히' 동작했지만, viewport로 직접 온 휠에는 폴백이 없어
            # 드래그 구현을 바꾸면 전체화면과 같은 방식으로 조용히 죽는다.
            fs_viewport = self._fs_win._vw.viewport() if self._fs_win else None
            pip_viewport = self._pip_win._vw.viewport() if self._pip_win else None
            if (
                obj is self._video_view.viewport()
                or (fs_viewport is not None and obj is fs_viewport)
                or (pip_viewport is not None and obj is pip_viewport)
            ):
                self.wheelEvent(event)
                return event.isAccepted()
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

    # ── 가사 자막 ──────────────────────────────────────────────────
    def set_lyrics(self, track: LyricsTrack | None) -> None:
        """표시할 싱크 가사를 설정한다. None/빈 트랙이면 자막 UI를 비활성한다."""
        self._track = track if (track is not None and not track.is_empty) else None
        has = self._track is not None
        # -1이 아니라 강제 갱신 센티넬(-2)로 둔다 — 새 트랙의 현재 줄이 마침 '없음'(-1)이어도
        # 이전 줄을 강조하던 소비자가 해제 신호(current_line_changed(-1))를 받아야 한다.
        self._current_line_index = -2
        for bar in self._all_bars():
            bar.set_has_subtitle(has)
            bar.set_subtitle_on(self._subtitle_on)
            bar.set_subtitle_offset_ms(self._track.offset_ms if has else 0)
        for overlay in self._all_subtitles():
            overlay.set_cue(None)
            overlay.set_text_visible(self._subtitle_on)
        if has:
            self._apply_subtitle_position(self._player.position())

    def set_subtitle_enabled(self, on: bool) -> None:
        self._subtitle_on = bool(on)
        for bar in self._all_bars():
            bar.set_subtitle_on(self._subtitle_on)
        for overlay in self._all_subtitles():
            overlay.set_text_visible(self._subtitle_on)

    def subtitle_offset_ms(self) -> int:
        return self._track.offset_ms if self._track else 0

    def set_subtitle_offset_ms(self, ms: int) -> None:
        """외부(상세화면 노래 탭 등)에서 절대 오프셋 값을 지정한다.

        `[`/`]` 단축키·우클릭 메뉴가 쓰는 내부 조정과 동일한 경로를 타므로 바·오버레이
        갱신과 `subtitle_offset_changed` 발행(→디바운스 저장)이 그대로 따라온다.
        """
        self._set_subtitle_offset(int(ms))

    def _all_bars(self) -> list:
        """인라인 + 분리 창의 컨트롤바 — 상태를 팬아웃할 대상."""
        bars = [self._bar]
        if self._fs_win:
            bars.append(self._fs_win.bar)
        if self._pip_win:
            bars.append(self._pip_win.bar)
        return bars

    def _all_subtitles(self) -> list:
        overlays = [self._subtitle]
        if self._fs_win:
            overlays.append(self._fs_win.subtitle)
        if self._pip_win:
            overlays.append(self._pip_win.subtitle)
        return overlays

    def _subtitle_prefs_dirty(self) -> bool:
        """크기·위치가 기본값에서 벗어나 있는지(초기화 메뉴 노출 조건)."""
        return (
            self._subtitle_font_scale != LyricsOverlay.FONT_SCALE_DEFAULT
            or self._subtitle_bottom_ratio != LyricsOverlay.BOTTOM_RATIO_DEFAULT
        )

    def _apply_subtitle_prefs(self) -> None:
        """현재 크기·위치를 3창 오버레이 전부에 반영한다."""
        for overlay in self._all_subtitles():
            overlay.set_font_scale(self._subtitle_font_scale)
            overlay.set_bottom_ratio(self._subtitle_bottom_ratio)
        # 값이 기본값이 아니면 가사가 없어도 💬 우클릭으로 초기화에 닿을 수 있어야 한다.
        dirty = self._subtitle_prefs_dirty()
        for bar in self._all_bars():
            bar.set_subtitle_prefs_dirty(dirty)

    def _show_transient(self, text: str, ms: int = 1000) -> None:
        """조절 중 현재 값을 잠깐 보여준다.

        가사 줄이 안 나오는 구간에서 조절하면 화면에 아무 변화가 없어 먹었는지
        알 수 없다. 그래서 값 표시는 있으나 마나 한 장식이 아니라 필수다.

        상태 라벨(`_status_lbl`)은 **인라인 위젯의 자식**이라 전체화면에서는 가려지고
        PiP 는 아예 다른 창이다. 그래서 같은 문구를 3창 오버레이에도 그린다 —
        오버레이는 세 창이 모두 갖고 있고 이미 영상 위에 얹혀 있다.
        """
        if not self._transient_text:
            # 진행 중이던 안내(예: "스트림 URL 가져오는 중…")를 덮어쓰므로 되돌릴 수
            # 있게 보관한다. 이미 임시 문구 중이면 처음 보관한 원본을 유지한다.
            self._status_before_transient = (
                self._status_lbl.text(), not self._status_lbl.isHidden()
            )
        self._transient_text = text
        self._status_lbl.setText(text)
        self._status_lbl.show()
        for overlay in self._all_subtitles():
            overlay.set_notice(text)
        self._transient_timer.start(ms)

    def _clear_transient(self) -> None:
        # 그 사이 스트림 안내 문구로 바뀌었다면 건드리지 않는다.
        if self._status_lbl.text() == self._transient_text:
            prev_text, prev_visible = self._status_before_transient
            self._status_lbl.setText(prev_text)
            self._status_lbl.setVisible(prev_visible)
        self._transient_text = ""
        self._status_before_transient = ("", False)
        for overlay in self._all_subtitles():
            overlay.set_notice("")

    def _nudge_subtitle_scale(self, delta: float) -> None:
        ov = self._subtitle
        # 0.1 씩 더하면 부동소수 찌꺼기(1.9700000000000002)가 쌓여 그대로 저장된다.
        # 스텝이 소수 둘째 자리까지라 매번 반올림해 누적 자체를 막는다.
        ov.set_font_scale(round(self._subtitle_font_scale + delta, 2))
        self._subtitle_font_scale = round(ov.font_scale, 2)   # clamp 된 실제 값을 되받는다
        self._apply_subtitle_prefs()
        self._show_transient(f"자막 크기 {round(self._subtitle_font_scale * 100)}%")
        self._queue_subtitle_prefs_save()

    def _nudge_subtitle_bottom(self, delta: float) -> None:
        ov = self._subtitle
        ov.set_bottom_ratio(round(self._subtitle_bottom_ratio + delta, 2))
        self._subtitle_bottom_ratio = round(ov.bottom_ratio, 2)
        self._apply_subtitle_prefs()
        self._show_transient(f"자막 위치 {round(self._subtitle_bottom_ratio * 100)}%")
        self._queue_subtitle_prefs_save()

    def _queue_subtitle_prefs_save(self) -> None:
        self._prefs_save_timer.start()

    def _flush_subtitle_prefs(self) -> None:
        try:
            # 설정 파일에 1.9700000000000002 같은 값이 박히지 않게 저장 직전에도 자른다
            # (설정 파일을 손으로 고쳐 들어온 값에도 적용된다).
            settings.save_setting("subtitle_font_scale", round(self._subtitle_font_scale, 2))
            settings.save_setting("subtitle_bottom_ratio", round(self._subtitle_bottom_ratio, 2))
        except OSError:
            logger.exception("자막 표시 설정 저장 실패")

    def _reset_subtitle_prefs(self) -> None:
        self._subtitle_font_scale = LyricsOverlay.FONT_SCALE_DEFAULT
        self._subtitle_bottom_ratio = LyricsOverlay.BOTTOM_RATIO_DEFAULT
        self._apply_subtitle_prefs()
        self._show_transient("자막 크기·위치 초기화")
        self._queue_subtitle_prefs_save()

    def _apply_subtitle_position(self, pos_ms: int) -> None:
        """재생 위치에 맞춰 자막을 갱신한다. **줄이 바뀔 때만** 다시 그린다."""
        if self._track is None:
            return
        idx = self._track.index_at(pos_ms)
        line_index = self._track.cue(idx).line_index if idx is not None else -1
        if line_index == self._current_line_index:
            return
        self._current_line_index = line_index
        cue: LyricsCue | None = self._track.cue(idx) if idx is not None else None
        for overlay in self._all_subtitles():
            overlay.set_cue(cue)
        self.current_line_changed.emit(line_index)

    def _set_subtitle_offset(self, ms: int) -> None:
        if self._track is None:
            return
        self._track.offset_ms = ms
        for bar in self._all_bars():
            bar.set_subtitle_offset_ms(self._track.offset_ms)
        # 오프셋이 바뀌면 현재 줄 판정이 달라지므로 강제로 다시 계산한다.
        # -2는 "다음 계산을 반드시 반영하라"는 센티넬 — -1(자막 없음)과 구분해야
        # 오프셋을 늘려 자막이 사라지는 전이(-1로의 변화)도 반영된다.
        self._current_line_index = -2
        self._apply_subtitle_position(self._player.position())
        self.subtitle_offset_changed.emit(self._track.offset_ms)

    def _nudge_subtitle_offset(self, delta_ms: int) -> None:
        if self._track is None:
            return
        self._set_subtitle_offset(self._track.offset_ms + int(delta_ms))

    def _sync_subtitle_here(self, pos_ms: int) -> None:
        """현재 재생 위치가 '지금 표시 중인 줄'의 시작이 되도록 오프셋을 맞춘다."""
        if self._track is None:
            return
        idx = self._track.index_at(pos_ms)
        if idx is None:
            return
        cue = self._track.cue(idx)
        self._set_subtitle_offset(pos_ms - cue.start_ms)

    def _reset_subtitle_offset(self) -> None:
        self._set_subtitle_offset(0)

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
        self._stream_retries = 0   # 영상이 바뀌면 재시도 예산도 새로 준다
        self._playing_local  = False
        self._current_quality_fmt   = InlinePlayer._last_quality_fmt
        self._current_merge         = InlinePlayer._last_quality_merge
        self._current_quality_short = InlinePlayer._last_quality_short
        self._stream_quality_label = ""
        self.set_lyrics(None)   # 이전 영상의 자막이 남지 않게 초기화
        self._visual_stack.setCurrentIndex(0)
        if thumbnail_pixmap and not thumbnail_pixmap.isNull():
            self._thumb_label.setPixmap(thumbnail_pixmap)
        else:
            self._thumb_label.clear()
            self._thumb_label.setText("미리보기 없음" if not video_url else "")
        self._status_lbl.hide()
        self._bar.set_quality("")
        # 화질 목록은 영상마다 다르다 — 캐시가 있으면 즉시, 없으면 ⬇ 클릭 시 조회한다.
        self._bar.set_available_heights(_HEIGHT_CACHE.get(video_url))
        self._bar.set_download_busy(False)
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
            # 시그널을 먼저 끊고(늦게 오는 결과 무시) 스레드가 끝날 때까지 붙든다.
            # 예전엔 quit()+deleteLater()였는데, quit()은 이벤트 루프만 끝내므로
            # yt-dlp를 도는 run()은 계속 실행되고, 그 상태로 삭제되면 Qt가 프로세스를
            # 죽였다(스트림을 받는 도중 뒤로가기 → 앱 종료).
            retire_thread(self._worker, "stream_ready", "progress", "failed")
            self._worker = None
        if self._probe:
            # 화질 조회 결과가 늦게 와도 이미 다른 영상으로 넘어갔을 수 있다.
            # 스트림 워커와 같은 이유로 quit()+deleteLater()는 쓰지 않는다 —
            # yt-dlp를 도는 run()은 quit()으로 멈추지 않는다.
            retire_thread(self._probe, "heights_ready", "failed")
            self._probe = None
        self._bar.set_download_busy(False)
        self._visual_stack.setCurrentIndex(0)
        self._status_lbl.hide()
        self._bar.show()
        self._bar.raise_()
        self._bar.set_playing(False)
        # 정지는 '같은 영상을 멈춘' 경우도 있으므로 트랙은 유지하고 현재 줄만 지운다.
        # (다른 영상으로 넘어가는 초기화는 load()가 set_lyrics(None)으로 처리한다.)
        self._current_line_index = -1
        for overlay in self._all_subtitles():
            overlay.set_cue(None)

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
        mods = event.modifiers()
        if (
            mods & Qt.KeyboardModifier.ControlModifier
            and key in (Qt.Key.Key_Up, Qt.Key.Key_Down)
        ):
            sign = 1 if key == Qt.Key.Key_Up else -1
            # Ctrl+Shift 도 Ctrl 비트가 켜져 있으므로 Shift 를 먼저 판정한다.
            if mods & Qt.KeyboardModifier.ShiftModifier:
                self._nudge_subtitle_bottom(sign * self._BOTTOM_RATIO_STEP)
            else:
                self._nudge_subtitle_scale(sign * self._FONT_SCALE_STEP)
            return
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
        elif key == Qt.Key.Key_C:
            if self._track is not None:
                self.set_subtitle_enabled(not self._subtitle_on)
        elif key in (Qt.Key.Key_BracketLeft, Qt.Key.Key_Comma):
            self._nudge_subtitle_offset(-self._OFFSET_STEP_MS)
        elif key in (Qt.Key.Key_BracketRight, Qt.Key.Key_Period):
            self._nudge_subtitle_offset(self._OFFSET_STEP_MS)
        elif key == Qt.Key.Key_Backslash:
            self._sync_subtitle_here(self._player.position())
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

    def wheelEvent(self, event) -> None:
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            # angleDelta().y() > 0 이면 위로 굴린 것 — 값이 커진다.
            sign = 1 if event.angleDelta().y() > 0 else -1
            if mods & Qt.KeyboardModifier.ShiftModifier:
                self._nudge_subtitle_bottom(sign * self._BOTTOM_RATIO_STEP)
            else:
                self._nudge_subtitle_scale(sign * self._FONT_SCALE_STEP)
            event.accept()
            return
        # 수정키 없는 휠은 건드리지 않는다(기존 동작 유지).
        super().wheelEvent(event)

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
            self._player,
            self._audio,
            key_handler=self.keyPressEvent,
            wheel_handler=self.wheelEvent,
        )
        bar = self._fs_win.bar
        # 전체화면 바 → 플레이어 (인라인 바와 동일한 핸들러 재사용)
        bar.play_toggled.connect(self._toggle_play)
        bar.seek_relative.connect(self._seek_relative)
        bar.seek_to_ms.connect(self._player.setPosition)
        bar.volume_changed.connect(self._on_volume_changed)
        bar.mute_toggled.connect(self._toggle_mute)
        bar.download_requested.connect(self._on_download_requested)
        bar.download_menu_requested.connect(self._on_download_menu_requested)
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
        bar.set_available_heights(_HEIGHT_CACHE.get(self._video_url))
        has = self._track is not None
        bar.set_has_subtitle(has)
        self._apply_subtitle_prefs()
        bar.set_subtitle_on(self._subtitle_on)
        bar.set_subtitle_offset_ms(self._track.offset_ms if has else 0)
        bar.subtitle_toggled.connect(self.set_subtitle_enabled)
        bar.subtitle_offset_nudged.connect(self._nudge_subtitle_offset)
        bar.subtitle_sync_here.connect(
            lambda: self._sync_subtitle_here(self._player.position())
        )
        bar.subtitle_offset_reset.connect(self._reset_subtitle_offset)
        bar.subtitle_prefs_reset.connect(self._reset_subtitle_prefs)
        self._fs_win.subtitle.set_text_visible(self._subtitle_on)
        # 현재 줄을 새 창에도 1회 반영
        self._current_line_index = -2
        self._apply_subtitle_position(self._player.position())

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
        # 창이 사라졌으니 인라인 오버레이가 현재 줄을 다시 갖도록 강제 갱신한다.
        self._current_line_index = -2
        self._apply_subtitle_position(self._player.position())
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
            self._player,
            self._audio,
            key_handler=self.keyPressEvent,
            wheel_handler=self.wheelEvent,
        )
        bar = self._pip_win.bar
        # PiP 바 → 플레이어 (인라인 바와 동일한 핸들러 재사용)
        bar.play_toggled.connect(self._toggle_play)
        bar.seek_relative.connect(self._seek_relative)
        bar.seek_to_ms.connect(self._player.setPosition)
        bar.volume_changed.connect(self._on_volume_changed)
        bar.mute_toggled.connect(self._toggle_mute)
        bar.download_requested.connect(self._on_download_requested)
        bar.download_menu_requested.connect(self._on_download_menu_requested)
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
        bar.set_available_heights(_HEIGHT_CACHE.get(self._video_url))
        has = self._track is not None
        bar.set_has_subtitle(has)
        self._apply_subtitle_prefs()
        bar.set_subtitle_on(self._subtitle_on)
        bar.set_subtitle_offset_ms(self._track.offset_ms if has else 0)
        bar.subtitle_toggled.connect(self.set_subtitle_enabled)
        bar.subtitle_offset_nudged.connect(self._nudge_subtitle_offset)
        bar.subtitle_sync_here.connect(
            lambda: self._sync_subtitle_here(self._player.position())
        )
        bar.subtitle_offset_reset.connect(self._reset_subtitle_offset)
        bar.subtitle_prefs_reset.connect(self._reset_subtitle_prefs)
        self._pip_win.subtitle.set_text_visible(self._subtitle_on)
        # 현재 줄을 새 창에도 1회 반영
        self._current_line_index = -2
        self._apply_subtitle_position(self._player.position())

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
        # 창이 사라졌으니 인라인 오버레이가 현재 줄을 다시 갖도록 강제 갱신한다.
        self._current_line_index = -2
        self._apply_subtitle_position(self._player.position())
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
        self._apply_subtitle_position(pos)

    def _on_playback_state(self, state: QMediaPlayer.PlaybackState) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self._bar.set_playing(playing)
        if self._fs_win:
            self._fs_win.bar.set_playing(playing)
        if self._pip_win:
            self._pip_win.bar.set_playing(playing)
        if playing:
            # 실제로 재생이 시작됐으면 재시도 예산을 되돌린다. 여기서 초기화하지 않고
            # 스트림을 받을 때마다 초기화하면 오류→재시도가 무한히 반복될 수 있다.
            self._stream_retries = 0
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
        # 끝까지 재생되면(수동 stop과 구분되는 유일한 지표) 재생목록 다음곡 신호를 낸다.
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.playback_finished.emit()
            return
        if self._resume_ms <= 0:
            return
        if status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ) and self._player.isSeekable():
            self._player.setPosition(self._resume_ms)
            self._resume_ms = 0

    def _start_local(self, path: str) -> None:
        self._playing_local = True
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
        # 이전 워커가 살아 있으면 늦게 도착하는 신호를 무시한다.
        # 참조만 버리면 실행 중인 QThread가 파괴돼 프로세스가 죽는다 — retire_thread가
        # 신호를 끊고 끝날 때까지 대신 붙들어 준다(gui/workers.py).
        retire_thread(self._worker, "stream_ready", "progress", "failed")
        # 부모를 주지 않는다 — 플레이어가 사라져도 스레드가 함께 파괴되지 않게.
        self._worker = track_thread(_StreamWorker(
            self._video_url, self._current_quality_fmt, self._current_merge
        ))
        # 끝나면 참조를 놓는다 — 끝난 워커를 계속 들고 있으면 뒤늦은 정리에서 헷갈린다.
        self._worker.finished.connect(lambda w=self._worker: self._forget_stream_worker(w))
        self._worker.stream_ready.connect(self._on_stream_ready)
        self._worker.progress.connect(self._on_merge_progress)
        self._worker.failed.connect(self._on_stream_failed)
        self._worker.start()

    def _forget_stream_worker(self, worker) -> None:
        """스트림 워커가 끝나면 참조를 놓는다(다음 정리에서 죽은 객체를 만지지 않게)."""
        if self._worker is worker:
            self._worker = None

    def _on_merge_progress(self, pct: int) -> None:
        self._status_lbl.setText(f"고화질 준비 중…  {pct}%")
        self._status_lbl.show()

    def _on_stream_ready(self, src: str, quality: str, is_local: bool) -> None:
        self._status_lbl.hide()
        self._playing_local = is_local
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
        if error == QMediaPlayer.Error.NoError:
            return
        # 스트리밍 재생 오류는 URL 만료·일시적 거부가 대부분이라, 새 URL을 받아 한 번은
        # 조용히 다시 시도한다(사용자에게는 잠깐 버퍼링한 것처럼 보인다). 로컬 파일
        # 재생 오류는 다시 받아도 같은 파일이라 재시도하지 않는다.
        if (
            self._video_url
            and not self._playing_local
            and self._stream_retries < _MAX_STREAM_RETRIES
        ):
            self._stream_retries += 1
            logger.warning(
                "재생 오류 — 스트림을 다시 받아 재시도(%d/%d): %s",
                self._stream_retries, _MAX_STREAM_RETRIES, error_string,
            )
            self._player.stop()
            self._player.setSource(QUrl())
            self._fetch_stream()
            return
        logger.warning("재생 오류(재시도 소진): %s / url=%s", error_string, self._video_url)
        self.stop()
        self.playback_failed.emit(error_string)

    def show_playback_error(self, message: str) -> None:
        """재생 실패를 영상 자리에 표시한다.

        예전에는 실패하면 곧바로 기본 브라우저를 열었다. 사용자는 **앱에서 보려고**
        누른 것이므로 창이 튀는 것 자체가 불편하고, 원인도 알 수 없었다. 이제는 이유를
        보여주고, 브라우저로 갈지는 상단 🌐 버튼으로 직접 고르게 한다.
        """
        self._visual_stack.setCurrentIndex(0)
        text = message.strip().replace("\n", " ")
        if len(text) > 110:
            text = text[:110] + "…"
        self._status_lbl.setText(f"재생 실패: {text} — 🌐 버튼으로 브라우저에서 열 수 있습니다.")
        self._status_lbl.show()

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

    def _on_download_menu_requested(self) -> None:
        """⬇ 클릭 — 사용 가능한 화질을 확인한 뒤 메뉴를 연다.

        고정 목록을 그대로 띄우면 최대 1080p인 영상에도 4K가 나열돼 혼란스럽다.
        조회는 네트워크 작업이라 워커에서 하고, 끝나면 그 바의 메뉴를 대신 연다.
        실패하면 예전처럼 전체 목록을 보여준다(다운로드 자체는 막지 않는다).
        """
        bar = self.sender() if isinstance(self.sender(), _ControlBar) else self._bar
        url = self._video_url
        cached = _HEIGHT_CACHE.get(url)
        if not url or cached is not None:
            bar.set_available_heights(cached)
            bar.open_download_menu()
            return

        bar.set_download_busy(True)

        def _ready(u: str, heights: list, b=bar) -> None:
            _cache_heights(u, heights)
            b.set_download_busy(False)
            b.set_available_heights(heights)
            b.open_download_menu()

        def _failed(_msg: str, b=bar) -> None:
            b.set_download_busy(False)
            b.set_available_heights(None)   # 알 수 없으면 전체 목록으로
            b.open_download_menu()

        # 조회 중 화면을 벗어나도 스레드가 파괴되지 않도록 부모 없이 만들어 등록한다.
        self._probe = track_thread(_FormatProbeWorker(url))
        self._probe.heights_ready.connect(_ready)
        self._probe.failed.connect(_failed)
        self._probe.start()
