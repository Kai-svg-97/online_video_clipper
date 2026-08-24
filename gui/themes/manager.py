"""ThemeManager — 테마 전환 싱글턴.

사용 예:
    # 앱 시작 시 초기화
    ThemeManager.instance().initialize(app)

    # 테마 변경
    ThemeManager.instance().apply("zinc")

    # 현재 토큰 읽기
    tok = ThemeManager.instance().current()

    # 변경 감지 (커스텀 위젯용)
    ThemeManager.instance().theme_changed.connect(self._on_theme_changed)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, ClassVar

from PyQt6.QtCore import QEasingCurve, QObject, QPropertyAnimation, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QGraphicsOpacityEffect, QGraphicsView, QLabel, QWidget

from gui.themes.tokens import DEFAULT_PRESET, PRESETS, ThemeTokens
from gui.themes.stylesheet import build_qss

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    pass

# 사용자가 직접 고른 전환(설정 화면 테마 카드 클릭)에서만 크로스페이드를 건다 —
# 시작 시 초기화(initialize)는 화면이 아직 뜨기 전이라 애니메이션이 보일 일이 없다.
_CROSSFADE_MS = 220


def _has_visible_video_surface(widget: QWidget) -> bool:
    """이 창에 **지금 보이는** 영상 표시면(QGraphicsView)이 있는지.

    라이브러리 상세화면의 InlinePlayer는 화면이 목록으로 바뀌어도 QStackedWidget
    안에 계속 살아 있다(미니바 재생 유지 설계) — 따라서 존재 여부만 보면 메인
    윈도우는 앱 구동 후 영원히 "영상 있는 창"으로 잘못 판정돼 크로스페이드가 다시는
    걸리지 않는다. `isVisible()`은 QStackedWidget이 감춘 페이지에는 False를
    돌려주므로, 지금 화면에 실제로 떠 있는 것만 걸러낸다(gui/anim.py와 같은 이유 —
    영상 서피스 위에 정지 스냅샷을 잠깐 얹으면 깜빡이거나 검게 비칠 수 있다).
    """
    if isinstance(widget, QGraphicsView):
        return widget.isVisible()
    return any(v.isVisible() for v in widget.findChildren(QGraphicsView))


class ThemeManager(QObject):
    """싱글턴 테마 관리자.

    QApplication.setStyleSheet()를 통해 전역 QSS를 교체하고
    theme_changed 시그널로 커스텀 위젯에 알린다.
    """

    theme_changed = pyqtSignal(object)  # ThemeTokens 전달

    _instance: ClassVar[ThemeManager | None] = None

    def __init__(self) -> None:
        super().__init__()
        self._current: ThemeTokens = PRESETS[DEFAULT_PRESET]

    # ------------------------------------------------------------------
    # 싱글턴 접근자
    # ------------------------------------------------------------------

    @classmethod
    def instance(cls) -> "ThemeManager":
        """프로세스 전역 ThemeManager 인스턴스를 반환한다."""
        if cls._instance is None:
            cls._instance = ThemeManager()
        return cls._instance

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def initialize(self, preset_name: str | None = None) -> None:
        """앱 시작 시 저장된 테마를 로드해 적용한다.

        preset_name 이 주어지면 해당 테마를 강제 적용한다.
        """
        name = preset_name if preset_name in PRESETS else DEFAULT_PRESET
        self._apply_tokens(PRESETS[name], save=False)

    def apply(self, preset_name: str) -> None:
        """테마를 크로스페이드로 전환하고 설정 파일에 저장한다.

        전체 QSS가 한 프레임에 통째로 뒤바뀌면 눈이 아프므로, 전환 직전 화면을
        창별로 캡처해 새 테마 위에 살짝 덮어 두고 그 스냅샷만 옵아시티를 낮춰
        사라지게 한다(아래에서 새 테마가 서서히 드러난다).
        """
        if preset_name not in PRESETS:
            return
        self._apply_tokens(PRESETS[preset_name], save=True, animate=True)

    def current(self) -> ThemeTokens:
        """현재 적용된 ThemeTokens를 반환한다."""
        return self._current

    # ------------------------------------------------------------------
    # 내부 구현
    # ------------------------------------------------------------------

    def _apply_tokens(self, tokens: ThemeTokens, *, save: bool, animate: bool = False) -> None:
        overlays = self._snapshot_windows() if animate else []
        self._current = tokens
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_qss(tokens))
        if save:
            self._save(tokens.name)
        self.theme_changed.emit(tokens)
        if overlays:
            self._fade_out_snapshots(overlays)

    def _snapshot_windows(self) -> list[QLabel]:
        """전환 직전 모든 창의 스냅샷을 떠 그 창 맨 위에 덮는다.

        위젯을 다시 그리는 게 아니라 정적 이미지 한 장을 얹는 것이라 비용이 적고,
        아래의 실제 위젯은 새 QSS로 즉시 갈아 끼워져도 화면상으로는 스냅샷이
        걷히면서 자연스럽게 드러난다.
        """
        app = QApplication.instance()
        if app is None:
            return []
        overlays: list[QLabel] = []
        for win in app.topLevelWidgets():
            if not win.isVisible() or win.isMinimized():
                continue
            if _has_visible_video_surface(win):
                continue
            try:
                pixmap = win.grab()
            except RuntimeError:
                continue
            if pixmap.isNull():
                continue
            overlay = QLabel(win)
            overlay.setPixmap(pixmap)
            overlay.setGeometry(win.rect())
            # 클릭은 곧바로 아래(새 테마로 갈아 끼워진 실제 위젯)에 전달한다 —
            # 220ms짜리 스냅샷 때문에 그 잠깐 동안 입력이 막히면 안 된다.
            overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            overlay.show()
            overlay.raise_()
            overlays.append(overlay)
        return overlays

    @staticmethod
    def _fade_out_snapshots(overlays: list[QLabel]) -> None:
        for overlay in overlays:
            effect = QGraphicsOpacityEffect(overlay)
            overlay.setGraphicsEffect(effect)
            anim = QPropertyAnimation(effect, b"opacity", overlay)
            anim.setDuration(_CROSSFADE_MS)
            anim.setStartValue(1.0)
            anim.setEndValue(0.0)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)

            def _cleanup(_overlay: QLabel = overlay) -> None:
                try:
                    _overlay.setGraphicsEffect(None)
                    _overlay.deleteLater()
                except RuntimeError:
                    logger.debug("테마 전환 스냅샷이 이미 정리됨 — 무시")

            anim.finished.connect(_cleanup)
            anim.start()
            overlay._theme_fade_anim = anim  # GC 방지(중간에 사라지면 반투명으로 굳는다)

    @staticmethod
    def _save(name: str) -> None:
        """테마 이름을 config.yaml에 저장한다."""
        try:
            from config import settings as _s
            _s.save_theme(name)
        except Exception:
            logger.debug("테마 저장 실패 (비필수 기능)", exc_info=True)  # 저장 실패 시 무시
