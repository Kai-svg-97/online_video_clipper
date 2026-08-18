"""영상 표시면과 분리 창 — 인라인 영역, 화면 속 화면(PiP), 전체화면.

세 창은 하나의 QMediaPlayer 출력 대상만 바꿔 쓰므로 위치·볼륨·상태가 유지된다.
`_VideoView`는 NoFocus다 — 포커스를 쥐면 방향키를 스크롤로 삼켜 단축키가 죽는다.
"""

from __future__ import annotations

import logging

from PyQt6.QtCore import (
    QPoint,
    QPointF,
    QSizeF,
    QTimer,
    Qt,
    pyqtSignal,
)
from PyQt6.QtGui import QBrush, QColor, QKeyEvent
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtMultimediaWidgets import QGraphicsVideoItem
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsScene,
    QGraphicsView,
    QSizeGrip,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gui.widgets.lyrics_overlay import LyricsOverlay

from gui.widgets.player.controls import _ControlBar

logger = logging.getLogger(__name__)


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
        self._subtitle: QWidget | None = None
        stack.setParent(self)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def set_overlay_bar(self, bar: QWidget) -> None:
        self._bar = bar
        bar.setParent(self)
        self._layout_children()

    def set_overlay_subtitle(self, widget: QWidget) -> None:
        self._subtitle = widget
        widget.setParent(self)
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
        if self._subtitle is not None:
            # 영역 전체를 덮는다 — 글자를 키우거나 위치를 올려도 잘리지 않는다.
            # 컨트롤바를 나중에 raise_() 하므로 바가 계속 자막 위에 온다.
            self._subtitle.setGeometry(0, 0, self.width(), h)
            self._subtitle.raise_()
        if self._bar is not None:
            self._bar.setGeometry(0, h - self._BAR_H, self.width(), self._BAR_H)
            self._bar.raise_()

class _VideoView(QGraphicsView):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet("background: #000; border: none;")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.setInteractive(False)
        # QGraphicsView는 기본적으로 포커스를 잡고 방향키(↑/↓/←/→)를 스크롤용으로
        # 소비한다. 전체화면·PiP 창에서 이 뷰가 포커스를 쥐면 창의 keyPressEvent가
        # 방향키를 못 받아 볼륨(↑/↓)·탐색(←/→) 단축키가 먹통이 된다. 포커스를 아예
        # 잡지 않게 해 상위 창이 모든 키를 처리하도록 한다.
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        scene = QGraphicsScene(self)
        scene.setBackgroundBrush(QBrush(QColor("#000000")))
        self.setScene(scene)

        self._item = QGraphicsVideoItem()
        scene.addItem(self._item)
        self._item.nativeSizeChanged.connect(lambda _: self._fit())

    @property
    def video_item(self) -> QGraphicsVideoItem:
        return self._item

    def wheelEvent(self, event) -> None:
        # QGraphicsView 는 휠을 스크롤로 소비한다. 스크롤바를 꺼 둔 뷰라 쓸모가 없고,
        # 삼키면 상위 플레이어의 자막 크기·위치 단축키가 조용히 죽는다.
        event.ignore()

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

class _PipWindow(QWidget):
    """화면 속 화면(PiP) — 항상 위에 뜨는 작은 플로팅 재생 창.

    `_FullscreenWindow`와 동일하게 공유 `QMediaPlayer`의 출력을 자체 `_VideoView`로
    리다이렉트한다(재생 위치·볼륨·상태는 그대로 유지). `_FullscreenWindow`와 마찬가지로
    **컨트롤바(`bar`) 신호는 외부(InlinePlayer)에서 반드시 배선**해야 버튼이 동작한다.
    **자막 오버레이(`subtitle`)도 `bar`와 마찬가지로 외부(InlinePlayer)가 내용을 채워야
    한다.**

    프레임리스·항상 위이며, 영상 영역 드래그로 이동하고 우하단 `QSizeGrip`으로
    크기를 조절한다. 닫기(창 X/Esc/PiP 버튼/더블클릭)는 `exit_requested`로 알린다.
    """

    exit_requested = pyqtSignal()

    _DEFAULT_W = 480
    _DEFAULT_H = 270

    def __init__(
        self,
        player: QMediaPlayer,
        audio: QAudioOutput,
        key_handler=None,
        wheel_handler=None,
    ) -> None:
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
        self._wheel_handler = wheel_handler
        self._drag_offset: QPoint | None = None

        self._vw = _VideoView(self)
        # 영상 영역은 마우스 이벤트를 투명 처리 → 창 드래그가 영상 위에서도 동작.
        # 부수효과로 휠 이벤트의 히트테스트가 _vw(viewport)를 건너뛰고 이 창으로
        # 떨어져 wheelEvent()가 호출되지만, **거기에 의존하지는 않는다** —
        # InlinePlayer.eventFilter 의 Wheel 분기가 이 창의 viewport 도 명시적으로
        # 가로채므로(전체화면과 동일) 이 속성을 빼도 Ctrl+휠은 살아 있다.
        self._vw.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._vw.viewport().setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.subtitle = LyricsOverlay(self)
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
        self.subtitle.setGeometry(0, 0, self.width(), self.height())
        self.subtitle.raise_()
        self.subtitle.show()
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

    def wheelEvent(self, event) -> None:
        # 자막 크기·위치 조절이 분리 창에서도 동작하도록 InlinePlayer 로 넘긴다.
        if self._wheel_handler:
            self._wheel_handler(event)
        else:
            super().wheelEvent(event)

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
    **자막 오버레이(`subtitle`)도 `bar`와 마찬가지로 외부(InlinePlayer)가 내용을 채워야
    한다.**
    """

    exit_requested = pyqtSignal()

    def __init__(
        self,
        player: QMediaPlayer,
        audio: QAudioOutput,
        key_handler=None,
        wheel_handler=None,
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint,
        )
        self.setStyleSheet("background:#000;")
        self._player = player
        self._key_handler = key_handler
        self._wheel_handler = wheel_handler

        self._vw = _VideoView(self)
        self.subtitle = LyricsOverlay(self)
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
        self.subtitle.setGeometry(0, 0, self.width(), self.height())
        self.subtitle.raise_()
        self.subtitle.show()
        self.bar.setGeometry(0, self.height() - bh, self.width(), bh)
        self.bar.raise_()
        self.bar.show()

    def resizeEvent(self, event) -> None:
        bh = _ControlBar._HEIGHT
        self.subtitle.setGeometry(0, 0, self.width(), self.height())
        self.subtitle.raise_()
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

    def wheelEvent(self, event) -> None:
        # 자막 크기·위치 조절이 분리 창에서도 동작하도록 InlinePlayer 로 넘긴다.
        if self._wheel_handler:
            self._wheel_handler(event)
        else:
            super().wheelEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        self.exit_requested.emit()

    def closeEvent(self, event) -> None:
        self.exit_requested.emit()
        event.ignore()
