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

from typing import TYPE_CHECKING, ClassVar

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from gui.themes.tokens import DEFAULT_PRESET, PRESETS, ThemeTokens
from gui.themes.stylesheet import build_qss

if TYPE_CHECKING:
    pass


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
        """테마를 즉시 전환하고 설정 파일에 저장한다."""
        if preset_name not in PRESETS:
            return
        self._apply_tokens(PRESETS[preset_name], save=True)

    def current(self) -> ThemeTokens:
        """현재 적용된 ThemeTokens를 반환한다."""
        return self._current

    # ------------------------------------------------------------------
    # 내부 구현
    # ------------------------------------------------------------------

    def _apply_tokens(self, tokens: ThemeTokens, *, save: bool) -> None:
        self._current = tokens
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_qss(tokens))
        if save:
            self._save(tokens.name)
        self.theme_changed.emit(tokens)

    @staticmethod
    def _save(name: str) -> None:
        """테마 이름을 config.yaml에 저장한다."""
        try:
            from config import settings as _s
            _s.save_theme(name)
        except Exception:
            pass  # 저장 실패 시 무시 (비필수 기능)
