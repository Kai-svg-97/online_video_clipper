"""Reusable inline video-player widget (InlinePlayer).

Layout: 16:9 video area that overlays the control bar at the bottom.
Qt 6.6+ multimedia renders via QRhi (not a native HWND), so a child QWidget
with raise_() correctly appears on top of QVideoWidget.

Fullscreen creates a separate top-level window on the same monitor as the
player, redirects QMediaPlayer output there, and restores on exit.
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from application.library.dtos import DownloadInfoDTO
from config import settings
from gui.themes.colors import tok
from gui.widgets.lyrics_overlay import LyricsOverlay, LyricsTrack

# ── 동작 묶음 (gui/widgets/player/mixins/*) ────────────────────────
# 이 파일은 **조립부**다 — 상태 필드·자식 위젯·신호 배선만 둔다. 동작은 주제별
# mixin으로 나눴을 뿐 런타임 클래스는 `InlinePlayer` 하나라 상태 공유 방식은 같다.
from gui.widgets.player.mixins.detached import DetachedWindowsMixin
from gui.widgets.player.mixins.input import InputMixin
from gui.widgets.player.mixins.lyrics import LyricsSubtitleMixin
from gui.widgets.player.mixins.playback import PlaybackMixin
from gui.widgets.player.mixins.stream_source import StreamSourceMixin
from gui.widgets.player.mixins.timeline import TimelineMixin
from gui.widgets.player.mixins.video_subtitles import VideoSubtitleMixin

# ── 분할된 부품 (gui/widgets/player/*) ─────────────────────────────
# 부품은 패키지로 옮겼다. 아래 재수출은 기존 임포트 경로를 유지하기 위한 것이다
# (`monkeypatch`는 재수출이 아니라 **쓰는 쪽 모듈**을 패치해야 한다).
from gui.widgets.subtitle_track import SubtitleTrack  # noqa: F401
from gui.text.labels import quality_badge_text, sponsor_category_label  # noqa: F401
from gui.widgets.player.stream import (  # noqa: F401
    _SubtitleFetchWorker,
    _SubtitleListWorker,
    _VSUB_LIST_CACHE,
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


# ── Public widget ─────────────────────────────────────────────────

class InlinePlayer(
    InputMixin,
    TimelineMixin,
    PlaybackMixin,
    StreamSourceMixin,
    LyricsSubtitleMixin,
    VideoSubtitleMixin,
    DetachedWindowsMixin,
    QWidget,
):
    """Inline player: 16:9 video area with overlaid auto-hide control bar.

    Control bar overlays the bottom of the video, auto-hides after 3 s of
    mouse inactivity while playing, reappears on mouse movement over the area.

    YouTube-compatible keyboard shortcuts (Space/K, J, L, ←/→, ↑/↓, M, F, 0-9,
    C, [, ], \\).
    """

    playback_failed    = pyqtSignal(str)
    download_requested = pyqtSignal(str, str, object)  # (url, title, DownloadSettings)
    playback_finished  = pyqtSignal()   # 미디어 끝까지 재생됨(EndOfMedia) — 재생목록 자동 다음곡용
    playing_changed    = pyqtSignal(bool)  # 재생/일시정지 전환 — 이어보기 위치 보고 주기 제어
    subtitle_offset_changed = pyqtSignal(int)   # 사용자가 싱크를 바꿈 → 저장 요청
    current_line_changed    = pyqtSignal(int)   # 원본 가사 줄 인덱스(없으면 -1)
    segment_skipped         = pyqtSignal(str)   # SponsorBlock 구간을 건너뜀(표시 이름)
    # 자막 큐가 손에 들어왔다 — 색인에 공짜로 실어 보낸다(재차 받지 않는다).
    subtitle_cues_ready     = pyqtSignal(str, str, object)  # lang, label, cues

    _HIDE_MS = 2_000   # 2초 비활성 후 숨김
    _SHOW_MS = 1_000   # 마우스 감지 1초 후 표시
    _OFFSET_STEP_MS = 250   # [ / ] 한 번에 움직이는 폭
    _FONT_SCALE_STEP = 0.1      # Ctrl + 휠/방향키 한 번에 움직이는 배율
    _BOTTOM_RATIO_STEP = 0.02   # Ctrl+Shift + 휠/방향키 한 번에 움직이는 위치 비율
    _last_quality_fmt: str = _DEFAULT_QUALITY_FMT  # 세션 내 품질 선택 공유
    _last_quality_merge: bool = _DEFAULT_QUALITY_MERGE
    _last_quality_short: str = _QUALITY_OPTIONS[0][0]  # 화질 **키**("auto")
    # 재생 품질 단축 라벨 → 다운로드 품질 문자열 매핑
    # DownloadInfoDTO.quality는 Quality Enum 값("1080p" 등) 또는 파일명 레이블("FHD" 등)
    _SHORT_TO_QUALITIES: dict[str, set[str]] = {
        "1080p": {"1080p", "FHD"},
        "720p":  {"720p",  "HD"},
        "480p":  {"480p",  "SD"},
        "360p":  {"360p",  "LD"},
        "240p":  {"240p"},
    }

    def __init__(self, parent=None, *, stream_relay=None, subtitles=None) -> None:
        super().__init__(parent)
        # 조립 루트가 주는 인프라 기능(`gui/media_services.py`). 비어 있으면 그 기능만
        # 빠진다 — 중계가 없으면 고화질을 병합 방식으로, 자막 소스가 없으면 CC 목록 없이.
        self._stream_relay = stream_relay     # IStreamRelay | None
        self._subtitles = subtitles           # IVideoSubtitleSource | None
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
        # SponsorBlock — 건너뛸 구간과 "이미 건너뛴" 구간. 후자가 없으면 사용자가
        # 일부러 되감아 그 구간을 보려 할 때마다 다시 튕겨 나간다.
        self._skip_segments: list = []
        self._skipped_once: set = set()
        self._stream_quality_label: str = ""  # yt-dlp 보고 품질 레이블
        self._temp_stream_path: str = ""      # 고화질 병합 임시 파일(재생 후 정리)
        # 실시간 remux 스트림 — 재생기가 길이도 seek도 모르는 소스라 우리가 들고 있는다.
        self._remux_url: str = ""             # ?ss= 를 붙이기 전의 재생 URL
        self._stream_offset_ms: int = 0       # 지금 흐르는 스트림이 시작한 지점
        self._stream_duration_ms: int = 0     # yt-dlp가 알려준 영상 길이
        self._pending_seek_ms: int | None = None   # 아직 스트림에 반영되지 않은 seek
        self._last_truncation_ms: int = -1     # 스트림이 끊긴 마지막 지점(무한 재시도 차단)
        # 실시간 remux를 쓸지. 원본이 **먼 오프셋 요청을 거부**하는 일이 있어(실측:
        # 파일 중간 이후 바이트에 403) 그런 영상에서는 예전 방식으로 내려간다.
        self._prefer_remux: bool = True
        self._playing_local: bool = False     # 로컬 파일 재생 중인지(재시도 판단용)
        self._stream_retries: int = 0         # 재생 오류 후 스트림 재획득 횟수
        self._track: LyricsTrack | None = None
        self._subtitle_on = True
        # 영상 자막(YouTube 캡션) — 두 칸을 동시에 켤 수 있다(원어 + 모국어).
        self._vsub_available: list = []
        self._vsub_keys: list[str] = ["", ""]
        self._vsub_langs: list[str] = ["", ""]
        self._vsub_tracks: list = [None, None]
        self._vsub_texts: tuple[str, str] = ("", "")
        self._vsub_workers: list = [None, None]
        self._vsub_list_worker = None
        # 지난번에 고른 언어 — 영상이 바뀌어도 같은 언어가 있으면 이어서 켠다.
        self._vsub_pref_lang: list[str] = [
            getattr(settings, "VIDEO_SUBTITLE_LANG_1", "") or "",
            getattr(settings, "VIDEO_SUBTITLE_LANG_2", "") or "",
        ]
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

        # remux 스트림의 seek은 ffmpeg 재기동이라 비싸다. J/L 연타나 화살표 연속
        # 입력을 한 번으로 합친다 — 누를 때마다 새 프로세스를 띄우면 화면이 멎는다.
        self._seek_commit = QTimer(self)
        self._seek_commit.setSingleShot(True)
        self._seek_commit.setInterval(300)
        self._seek_commit.timeout.connect(self._commit_pending_seek)

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
        # 포스터 자리 — 재생 전 정지 화면이라 레터박스 검정이 아니라 테마 배경을
        # 따라 창과 이어 보이게 한다.
        self._thumb_label.setStyleSheet(f"background:{tok().bg_base};")

        self._visual_stack = QStackedWidget()
        self._visual_stack.setMouseTracking(True)
        self._visual_stack.addWidget(self._thumb_label)   # index 0
        self._visual_stack.addWidget(self._video_view)    # index 1

        # Control bar is an overlay inside _video_area
        # _VideoView renders via Qt texture system (no native D3D HWND),
        # so the control bar overlay is composited correctly by Qt.
        self._bar = _ControlBar()
        self._bar.set_translate_targets_source(self._translate_targets_source())
        self._subtitle = LyricsOverlay()
        self._video_area = _VideoArea(self._visual_stack)
        self._video_area.set_overlay_subtitle(self._subtitle)
        self._video_area.set_overlay_bar(self._bar)
        outer.addWidget(self._video_area)

        # Status label (below video area, shown only while fetching stream)
        self._status_lbl = QLabel("")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 이 라벨은 영상 영역 *아래*에 별도로 붙는 위젯이라 레터박스 검정 예외가
        # 적용되지 않는다 — 밝은 테마에서 창 하단에 검은 띠가 생기던 원인이었다.
        self._status_lbl.setStyleSheet(
            f"color:{tok().text_secondary};font-size:8pt;background:{tok().bg_surface};"
        )
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
        self._bar.seek_to_ms.connect(self._seek_to)
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
            lambda: self._sync_subtitle_here(self.position_ms)
        )
        self._bar.subtitle_offset_reset.connect(self._reset_subtitle_offset)
        self._bar.subtitle_prefs_reset.connect(self._reset_subtitle_prefs)
        self._bar.video_subtitle_selected.connect(self._select_video_subtitle)
        self._bar.video_subtitle_translate.connect(self._translate_video_subtitle)

        # Wire player signals → control bar
        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._publish_duration)
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
