"""컨트롤 바와 슬라이더 — 영상 위에 겹쳐 그리는 재생 조작 UI.

슬라이더는 스타일시트가 아니라 `paintEvent`에서 직접 그린다: 영상 위에 얹힌
QSlider는 groove/add-page 서브컨트롤이 스타일 색을 무시하고 검게 렌더되는 Qt 제약이
있다. 색을 바꿀 땐 `_bar_style`이 아니라 `_TrackSlider`를 고쳐야 한다.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import (
    QPoint,
    QPointF,
    QRectF,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QActionGroup, QColor, QPainter
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from domain.download.value_objects import DownloadSettings, MediaFormat, Quality
from gui.themes.manager import ThemeManager

from gui.widgets.player.constants import _QUALITY_HEIGHTS, _QUALITY_OPTIONS

logger = logging.getLogger(__name__)


# 재생 컨트롤 아이콘(글리프) 크기 — 예전 13px/24px 상자는 큰 화면에서 알아보기
# 어려울 만큼 작았다. 두 배로 키우고 바 높이도 그만큼 늘린다(높이를 그대로 두면
# 진행 슬라이더와 버튼 행이 서로를 밀어낸다).
_ICON_PX = 26
_ICON_BOX = 48


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
    font-size: {_ICON_PX}px;
    padding: 2px 6px;
    min-width: {_ICON_BOX}px;
    min-height: {_ICON_BOX}px;
}}
QToolButton:hover {{ color: {tok.accent_hover}; background: rgba(255,255,255,15); border-radius: 3px; }}
QLabel {{ color: {tok.text_secondary}; background: transparent; font-size: 11pt; }}
/* 슬라이더(_TrackSlider)는 QPainter로 직접 그린다 — 영상 오버레이 위에서
   QSlider::groove/add-page 서브컨트롤이 검게 렌더되는 문제를 회피하기 위함. */
"""

def _quality_badge_style() -> str:
    tok = ThemeManager.instance().current()
    return (
        f"color:{tok.text_primary}; background:{tok.badge_bg}; "
        "font-size:10pt; padding:2px 7px; border-radius:4px;"
    )

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
    # ⬇ 클릭 — 플레이어가 사용 가능한 화질을 확인한 뒤 open_download_menu()를 부른다
    download_menu_requested = pyqtSignal()
    # 자막(가사) — 좌클릭 토글, 우클릭 메뉴에서 싱크 조정
    subtitle_toggled       = pyqtSignal(bool)
    subtitle_offset_nudged = pyqtSignal(int)   # ±ms
    subtitle_sync_here     = pyqtSignal()      # 현재 재생 위치를 현재 줄에 맞춤
    subtitle_offset_reset  = pyqtSignal()
    subtitle_prefs_reset   = pyqtSignal()      # 자막 크기·위치를 기본값으로 초기화
    # 영상 자막(YouTube 캡션) — 두 칸(0·1)을 각각 고른다. key가 ""이면 그 칸은 끄기.
    video_subtitle_selected  = pyqtSignal(int, str)   # (slot, track_key)
    video_subtitle_translate = pyqtSignal(int, str)   # (slot, 대상 언어 코드, ""=원본)

    # 진행 슬라이더 + 버튼 행(_ICON_BOX) + 여백. 아이콘을 키우면 함께 커져야 한다.
    _HEIGHT = 96

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ctrlbar")
        self.setStyleSheet(_bar_style())
        self.setFixedHeight(self._HEIGHT)
        self._heights: list[int] | None = None   # 이 영상이 제공하는 화질(미확인이면 None)
        self._has_subtitle = False
        # 영상 자막 상태: 목록과 두 칸의 선택(트랙 key + 번역 대상)
        self._video_tracks: list = []
        self._vsub_keys: list[str] = ["", ""]
        self._vsub_langs: list[str] = ["", ""]
        self._subtitle_on = True
        self._subtitle_offset_ms = 0
        self._subtitle_prefs_dirty = False
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
            "QToolButton{font-size:10pt;padding:3px 9px;border-radius:4px;"
            "background:rgba(255,255,255,20);color:#ddd;}"
            "QToolButton:hover{background:rgba(255,255,255,40);}"
        )
        self._btn_quality.clicked.connect(self._show_quality_menu)

        self._btn_cc = btn("💬", "가사 자막  (C)", self._on_cc_clicked)
        self._btn_cc.setEnabled(False)
        self._btn_cc.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._btn_cc.customContextMenuRequested.connect(
            lambda _pos: self._show_subtitle_menu()
        )

        # 영상 자막(CC) — 가사 자막(💬)과 다른 기능이라 버튼을 따로 둔다.
        self._btn_vsub = btn("CC", "영상 자막 — 언어 선택·자동 번역",
                             self._show_video_subtitle_menu)
        self._btn_vsub.setEnabled(False)

        self._btn_dl = btn("⬇", "다운로드", self.download_menu_requested.emit)
        self._btn_pip = btn("⧉", "화면 속 화면  (P)", self.pip_toggled.emit)
        self._btn_fs = btn("⛶", "전체화면  (F)", self.fullscreen_toggled.emit)

        for w in (self._btn_play, self._btn_back, self._btn_fwd,
                  self._btn_mute, self._vol, self._time_lbl):
            row.addWidget(w)
        row.addStretch()
        row.addWidget(self._quality_lbl)
        row.addWidget(self._btn_quality)
        row.addWidget(self._btn_cc)
        row.addWidget(self._btn_vsub)
        row.addWidget(self._btn_dl)
        row.addWidget(self._btn_pip)
        row.addWidget(self._btn_fs)
        outer.addLayout(row)

        # 초기 글리프를 상태와 맞춘다 — 가사가 붙기 전(비활성)에는 빈 말풍선이어야 한다.
        self._update_cc_look()

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

    # ── 자막(가사) ─────────────────────────────────────────────────
    def set_has_subtitle(self, has: bool) -> None:
        """싱크 가사 유무 — 없으면 버튼을 비활성하고 이유를 툴팁으로 알린다."""
        self._has_subtitle = has
        self._refresh_cc_enabled()
        self._update_cc_look()

    def set_subtitle_prefs_dirty(self, dirty: bool) -> None:
        """자막 크기·위치가 기본값에서 벗어나 있는지.

        조절 단축키(Ctrl+휠/방향키)에는 가사 유무 조건이 없어서 **아무 영상에서나**
        값을 바꿀 수 있는데, 초기화 메뉴는 💬 버튼에 달려 있고 그 버튼은 싱크 가사가
        있을 때만 활성이었다. 그래서 비(非)노래 영상에서 키운 값을 되돌릴 방법이
        없었다. 값이 기본값이 아니면 가사가 없어도 버튼을 열어 둔다(초기화 항목만).
        """
        dirty = bool(dirty)
        if dirty == self._subtitle_prefs_dirty:
            return
        self._subtitle_prefs_dirty = dirty
        self._refresh_cc_enabled()

    def _refresh_cc_enabled(self) -> None:
        enabled = self._has_subtitle or self._subtitle_prefs_dirty
        self._btn_cc.setEnabled(enabled)
        if self._has_subtitle:
            tip = "가사 자막  (C)"
        elif enabled:
            tip = "시간 정보가 있는 가사가 없습니다 — 우클릭: 자막 크기·위치 초기화"
        else:
            tip = "시간 정보가 있는 가사가 없습니다"
        self._btn_cc.setToolTip(tip)

    def set_subtitle_on(self, on: bool) -> None:
        self._subtitle_on = on
        self._update_cc_look()

    def set_subtitle_offset_ms(self, ms: int) -> None:
        self._subtitle_offset_ms = int(ms)

    def _update_cc_look(self) -> None:
        # 자막이 실제로 나오는 상태(가사 있음 + 켜짐)면 말풍선을 채우고, 그 밖에는
        # 빈 말풍선으로 바꾼다 — 아이콘 하나로 on/off를 구분한다.
        self._btn_cc.setText("💬" if (self._subtitle_on and self._has_subtitle) else "🗨")

    def _on_cc_clicked(self) -> None:
        if not self._has_subtitle:
            return
        self._subtitle_on = not self._subtitle_on
        self._update_cc_look()
        self.subtitle_toggled.emit(self._subtitle_on)

    # ── 영상 자막(CC) ──────────────────────────────────────────────
    # 두 칸을 각각 고르게 하는 이유는 **동시에 두 언어를 보기 위해서**다(원어 + 모국어).
    # 이 바는 트랙을 해석하지 않는다 — 목록을 받아 그리고 고른 key만 돌려보낸다.
    # 번역 조합(트랙 × 대상 언어)은 경우의 수가 많아 메뉴로 펼치면 감당이 안 되므로,
    # '언어'와 '자동 번역'을 각각 고르게 하고 조합은 플레이어가 만든다.

    def set_video_subtitle_tracks(self, tracks: list) -> None:
        """고를 수 있는 자막 트랙 목록(`.key`/`.label`을 가진 객체)."""
        self._video_tracks = list(tracks or [])
        self._btn_vsub.setEnabled(bool(self._video_tracks))
        self._btn_vsub.setToolTip(
            "영상 자막 — 언어 선택·자동 번역" if self._video_tracks
            else "이 영상에는 자막이 없습니다"
        )
        self._update_vsub_look()

    def set_video_subtitle_selection(self, slot: int, key: str, translate_to: str = "") -> None:
        if slot not in (0, 1):
            return
        self._vsub_keys[slot] = key or ""
        self._vsub_langs[slot] = translate_to or ""
        self._update_vsub_look()

    def _update_vsub_look(self) -> None:
        """켜져 있으면 글자를 강조해 상태가 보이게 한다."""
        on = any(self._vsub_keys)
        self._btn_vsub.setText("CC" if on else "cc")

    def _show_video_subtitle_menu(self) -> None:
        if not self._video_tracks:
            return
        menu = QMenu(self)
        for slot in (0, 1):
            sub = menu.addMenu(f"자막 {slot + 1}" + ("" if slot == 0 else " (동시 표시)"))
            group = QActionGroup(sub)
            group.setExclusive(True)
            off = sub.addAction("끄기")
            off.setCheckable(True)
            off.setChecked(not self._vsub_keys[slot])
            off.triggered.connect(
                lambda _c=False, s=slot: self.video_subtitle_selected.emit(s, "")
            )
            group.addAction(off)
            sub.addSeparator()
            for track in self._video_tracks:
                act = sub.addAction(track.label)
                act.setCheckable(True)
                act.setChecked(self._vsub_keys[slot] == track.key)
                act.triggered.connect(
                    lambda _c=False, s=slot, k=track.key:
                    self.video_subtitle_selected.emit(s, k)
                )
                group.addAction(act)
            sub.addSeparator()
            trans = sub.addMenu("자동 번역")
            tgroup = QActionGroup(trans)
            tgroup.setExclusive(True)
            none_act = trans.addAction("번역 안 함")
            none_act.setCheckable(True)
            none_act.setChecked(not self._vsub_langs[slot])
            none_act.triggered.connect(
                lambda _c=False, s=slot: self.video_subtitle_translate.emit(s, "")
            )
            tgroup.addAction(none_act)
            for code, label in self._translate_targets():
                act = trans.addAction(label)
                act.setCheckable(True)
                act.setChecked(self._vsub_langs[slot] == code)
                act.triggered.connect(
                    lambda _c=False, s=slot, c=code:
                    self.video_subtitle_translate.emit(s, c)
                )
                tgroup.addAction(act)
        menu.exec(self._btn_vsub.mapToGlobal(self._btn_vsub.rect().bottomLeft()))

    @staticmethod
    def _translate_targets() -> tuple:
        from infrastructure.subtitle.youtube_subtitles import (  # noqa: PLC0415
            TRANSLATE_TARGETS,
        )
        return TRANSLATE_TARGETS

    def _build_subtitle_menu(self) -> "QMenu | None":
        """💬 우클릭 메뉴를 만든다. 열 이유가 없으면 None.

        싱크 오프셋 항목들은 트랙이 있어야 의미가 있으므로 가사가 있을 때만 넣고,
        크기·위치 초기화는 값이 기본값에서 벗어나 있으면 가사가 없어도 넣는다.
        (``exec``와 분리해 둔 것은 모달 루프 없이 구성만 테스트하기 위해서다.)
        """
        if not self._has_subtitle and not self._subtitle_prefs_dirty:
            return None
        menu = QMenu(self)
        if self._has_subtitle:
            sec = self._subtitle_offset_ms / 1000.0
            menu.addAction(f"싱크: {sec:+.2f}초").setEnabled(False)
            menu.addSeparator()
            menu.addAction("−0.25초  ( [ / , )", lambda: self.subtitle_offset_nudged.emit(-250))
            menu.addAction("+0.25초  ( ] / . )", lambda: self.subtitle_offset_nudged.emit(250))
            menu.addAction("현재 위치를 이 줄에 맞춤  ( \\ )", self.subtitle_sync_here.emit)
            menu.addSeparator()
            menu.addAction("초기화", self.subtitle_offset_reset.emit)
        menu.addAction("자막 크기·위치 초기화", self.subtitle_prefs_reset.emit)
        return menu

    def _show_subtitle_menu(self) -> None:
        menu = self._build_subtitle_menu()
        if menu is None:
            return
        menu.exec(self._btn_cc.mapToGlobal(self._btn_cc.rect().bottomLeft()))

    def _on_seek_released(self) -> None:
        self._dragging = False
        self.seek_to_ms.emit(self._progress.value())

    # ── 사용 가능한 화질 ───────────────────────────────────────────
    def set_available_heights(self, heights: "list[int] | None") -> None:
        """이 영상이 실제로 제공하는 세로 해상도 목록. None이면 '알 수 없음'."""
        self._heights = list(heights) if heights else None

    def set_download_busy(self, busy: bool) -> None:
        """화질 확인 중에는 ⬇ 버튼을 잠근다(중복 조회 방지)."""
        self._btn_dl.setEnabled(not busy)
        self._btn_dl.setToolTip("화질 확인 중…" if busy else "다운로드")

    def _max_height(self) -> "int | None":
        return max(self._heights) if self._heights else None

    def _height_offered(self, height: "int | None") -> bool:
        """해당 화질이 의미 있는 선택지인지.

        포맷 문자열이 `height<=N` 이라 최대치를 넘는 항목은 같은 결과를 주므로 뺀다.
        (세로 영상은 높이가 1920처럼 크게 잡히니 '정확히 존재하는 값'이 아니라
        최대치 이하인지로 판정한다.)
        """
        top = self._max_height()
        return height is None or top is None or height <= top

    def _show_quality_menu(self) -> None:
        menu = QMenu(self)
        tok = ThemeManager.instance().current()
        menu.setStyleSheet(
            f"QMenu{{background:{tok.bg_elevated};color:{tok.text_primary};border:1px solid {tok.border_muted};}}"
            f"QMenu::item:selected{{background:{tok.bg_overlay};}}"
        )
        for menu_label, fmt, short, merge in _QUALITY_OPTIONS:
            if not self._height_offered(_QUALITY_HEIGHTS.get(short)):
                continue
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

    def open_download_menu(self) -> None:
        """다운로드 메뉴를 연다 — 이 영상이 실제로 제공하는 화질만 나열한다."""
        menu = QMenu(self)
        tok = ThemeManager.instance().current()
        menu.setStyleSheet(
            f"QMenu{{background:{tok.bg_elevated};color:{tok.text_primary};border:1px solid {tok.border_muted};}}"
            f"QMenu::item:selected{{background:{tok.bg_overlay};}}"
        )

        vm = menu.addMenu("🎬  동영상")
        top = self._max_height()
        best_label = f"최고 화질  ({top}p)" if top else "최고 화질"
        for quality, height, label in [
            (Quality.BEST,  None, best_label),
            (Quality.P2160, 2160, "2160p  (4K)"),
            (Quality.P1080, 1080, "1080p  (HD)"),
            (Quality.P720,   720, "720p"),
            (Quality.P480,   480, "480p"),
            (Quality.P360,   360, "360p"),
        ]:
            if not self._height_offered(height):
                continue
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
