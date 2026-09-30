"""DetachedWindowsMixin — 전체화면·화면 속 화면(PiP) 분리 재생 창.

    InlinePlayer에 섞여 들어가는 mixin이라 위젯 상태를 그대로 쓴다
    (런타임 클래스는 하나다 — 조립은 `gui/widgets/video_player.py`).
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QPoint
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtWidgets import QApplication

from gui.text import tr
from gui.text.labels import quality_badge_text
from gui.widgets.player.stream import _HEIGHT_CACHE
from gui.widgets.player.surfaces import _FullscreenWindow, _PipWindow

logger = logging.getLogger(__name__)


class DetachedWindowsMixin:
    """공유 QMediaPlayer의 출력만 분리 창으로 옮기고, 새 바를 인라인과 같은 핸들러에 배선한다."""

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
        bar.video_subtitle_selected.connect(self._select_video_subtitle)
        bar.video_subtitle_translate.connect(self._translate_video_subtitle)
        bar.seek_relative.connect(self._seek_relative)
        bar.seek_to_ms.connect(self._seek_to)
        bar.volume_changed.connect(self._on_volume_changed)
        bar.mute_toggled.connect(self._toggle_mute)
        bar.download_requested.connect(self._on_download_requested)
        bar.download_menu_requested.connect(self._on_download_menu_requested)
        bar.quality_changed.connect(self._on_quality_changed)
        bar.fullscreen_toggled.connect(self._toggle_fullscreen)
        bar.pip_toggled.connect(self._toggle_pip)
        # 플레이어 → 전체화면 바 (재생시간). 위치/재생상태는 _on_position/_on_playback_state가 fan-out.
        # 현재 상태를 전체화면 바에 1회 반영. 재생기의 값이 아니라 실효 값을 쓴다 —
        # remux 스트림에서 재생기는 길이를 모르고 위치도 0부터 다시 센다.
        bar.update_duration(self._effective_duration())
        bar.update_position(self.position_ms, self._effective_duration())
        bar.set_playing(self.is_playing())
        bar.set_volume(self._volume)
        bar.set_muted(self._is_muted)
        bar.set_quality(quality_badge_text(self._current_quality_short))
        bar.set_available_heights(_HEIGHT_CACHE.get(self._video_url))
        has = self._track is not None
        bar.set_has_subtitle(has)
        self._apply_subtitle_prefs()
        bar.set_subtitle_on(self._subtitle_on)
        bar.set_subtitle_offset_ms(self._track.offset_ms if has else 0)
        # 영상 자막 목록·선택도 새 바에 그대로 실어야 분리 창에서 고를 수 있다.
        bar.set_translate_targets_source(self._translate_targets_source())
        bar.set_video_subtitle_tracks(self._vsub_available)
        for slot in (0, 1):
            bar.set_video_subtitle_selection(
                slot, self._vsub_keys[slot], self._vsub_langs[slot]
            )
        bar.subtitle_toggled.connect(self.set_subtitle_enabled)
        bar.subtitle_offset_nudged.connect(self._nudge_subtitle_offset)
        bar.subtitle_sync_here.connect(
            lambda: self._sync_subtitle_here(self._player.position())
        )
        bar.subtitle_offset_reset.connect(self._reset_subtitle_offset)
        bar.subtitle_prefs_reset.connect(self._reset_subtitle_prefs)
        self._fs_win.subtitle.set_text_visible(self._subtitle_on)
        self._fs_win.subtitle.set_subtitle_texts(*self._vsub_texts)
        # 현재 줄을 새 창에도 1회 반영
        self._current_line_index = -2
        self._apply_subtitle_position(self.position_ms)

        self._fs_win.exit_requested.connect(self._exit_fullscreen)

        geo = screen.geometry()
        self._fs_win.setGeometry(geo)
        self._fs_win.showFullScreen()
        self._fs_win.setFocus()

    def _exit_fullscreen(self) -> None:
        self._player.setVideoOutput(self._video_view.video_item)
        if self._fs_win:
            try:
                self._fs_win.exit_requested.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._fs_win.close()
            self._fs_win.deleteLater()
            self._fs_win = None
        # 창이 사라졌으니 인라인 오버레이가 현재 줄을 다시 갖도록 강제 갱신한다.
        self._current_line_index = -2
        self._apply_subtitle_position(self.position_ms)
        self.setFocus()

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
        bar.video_subtitle_selected.connect(self._select_video_subtitle)
        bar.video_subtitle_translate.connect(self._translate_video_subtitle)
        bar.seek_relative.connect(self._seek_relative)
        bar.seek_to_ms.connect(self._seek_to)
        bar.volume_changed.connect(self._on_volume_changed)
        bar.mute_toggled.connect(self._toggle_mute)
        bar.download_requested.connect(self._on_download_requested)
        bar.download_menu_requested.connect(self._on_download_menu_requested)
        bar.quality_changed.connect(self._on_quality_changed)
        bar.pip_toggled.connect(self._exit_pip)
        # 플레이어 → PiP 바 (재생시간). 위치/재생상태는 _on_position/_on_playback_state가 fan-out.
        # 현재 상태를 PiP 바에 1회 반영. 재생기의 값이 아니라 실효 값을 쓴다 —
        # remux 스트림에서 재생기는 길이를 모르고 위치도 0부터 다시 센다.
        bar.update_duration(self._effective_duration())
        bar.update_position(self.position_ms, self._effective_duration())
        bar.set_playing(self.is_playing())
        bar.set_volume(self._volume)
        bar.set_muted(self._is_muted)
        bar.set_quality(quality_badge_text(self._current_quality_short))
        bar.set_available_heights(_HEIGHT_CACHE.get(self._video_url))
        has = self._track is not None
        bar.set_has_subtitle(has)
        self._apply_subtitle_prefs()
        bar.set_subtitle_on(self._subtitle_on)
        bar.set_subtitle_offset_ms(self._track.offset_ms if has else 0)
        # 영상 자막 목록·선택도 새 바에 그대로 실어야 분리 창에서 고를 수 있다.
        bar.set_translate_targets_source(self._translate_targets_source())
        bar.set_video_subtitle_tracks(self._vsub_available)
        for slot in (0, 1):
            bar.set_video_subtitle_selection(
                slot, self._vsub_keys[slot], self._vsub_langs[slot]
            )
        bar.subtitle_toggled.connect(self.set_subtitle_enabled)
        bar.subtitle_offset_nudged.connect(self._nudge_subtitle_offset)
        bar.subtitle_sync_here.connect(
            lambda: self._sync_subtitle_here(self._player.position())
        )
        bar.subtitle_offset_reset.connect(self._reset_subtitle_offset)
        bar.subtitle_prefs_reset.connect(self._reset_subtitle_prefs)
        self._pip_win.subtitle.set_text_visible(self._subtitle_on)
        self._pip_win.subtitle.set_subtitle_texts(*self._vsub_texts)
        # 현재 줄을 새 창에도 1회 반영
        self._current_line_index = -2
        self._apply_subtitle_position(self.position_ms)

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
                self._pip_win.exit_requested.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._pip_win.close()
            self._pip_win.deleteLater()
            self._pip_win = None
        self._show_pip_placeholder(False)
        # 창이 사라졌으니 인라인 오버레이가 현재 줄을 다시 갖도록 강제 갱신한다.
        self._current_line_index = -2
        self._apply_subtitle_position(self.position_ms)
        self.setFocus()

    def _show_pip_placeholder(self, on: bool) -> None:
        """PiP 활성 시 인라인 영역에 안내(썸네일/문구)를 표시한다."""
        if on:
            pm = self._thumb_label.pixmap()
            if pm is None or pm.isNull():
                self._thumb_label.setText(tr("화면 속 화면으로 재생 중"))
            self._visual_stack.setCurrentIndex(0)
        elif self._player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self._visual_stack.setCurrentIndex(1)
