"""InputMixin — 마우스 활동에 따른 컨트롤바 표시/숨김, 키보드 단축키, 휠.

    InlinePlayer에 섞여 들어가는 mixin이라 위젯 상태를 그대로 쓴다
    (런타임 클래스는 하나다 — 조립은 `gui/widgets/video_player.py`).
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QCursor, QKeyEvent
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtWidgets import QApplication

logger = logging.getLogger(__name__)


class InputMixin:
    """컨트롤바 자동 숨김(이벤트 필터·커서 폴링) + YouTube 호환 단축키 + Ctrl(+Shift)+휠."""

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
            dur = self._effective_duration()
            if dur > 0:
                self._seek_to(dur * pct // 100)
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
