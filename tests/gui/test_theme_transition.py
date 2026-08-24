"""테마 전환 크로스페이드 — 전체 QSS가 한 프레임에 뒤바뀌지 않는다는 계약을 고정한다.

`ThemeManager.apply()`는 전환 직전 화면을 창별로 캡처해 새 테마 위에 스냅샷으로
덮어 두고, 그 스냅샷의 옵아시티만 낮춰 사라지게 한다(아래에서 새 테마가 서서히
드러난다). 반면 `initialize()`(앱 시작)는 화면이 아직 뜨기 전이라 애니메이션이
필요 없으므로 스냅샷을 만들지 않는다.

영상 표시면(QGraphicsView)이 **지금 보이는** 창에는 스냅샷을 덮지 않는다 —
정지 프레임이 잠깐 얹히면 재생 중인 영상이 깜빡이거나 검게 비칠 수 있기 때문이다.
다만 그 QGraphicsView가 QStackedWidget 등에 감춰진 페이지에 있을 뿐이라면(라이브러리
상세화면의 InlinePlayer처럼 화면이 바뀌어도 계속 살아 있는 위젯) 그 창은 정상적으로
크로스페이드 대상이 되어야 한다 — "존재만으로" 판정하면 메인 윈도우는 영원히
크로스페이드가 걸리지 않는다.

**싱글턴이 아니라 `ThemeManager()`를 직접 생성해 쓴다.** `ThemeManager.instance()`는
프로세스 전역이라 다른 테스트 파일이 만든 위젯들이 그 `theme_changed`에 계속 연결돼
있다(예: 여러 패널이 앱 수명 동안 살아있다고 가정하고 연결한 뒤 해제하지 않는 기존
코드) — 그 신호를 실제로 emit하면 이미 죽은 다른 테스트의 위젯을 건드려 이 테스트와
무관한 실패가 섞여 들어온다. 크로스페이드 로직 자체는 인스턴스 메서드라 새
`ThemeManager()`로도 완전히 동일하게 검증되고, 그 인스턴스의 `theme_changed`는
아무도 구독하지 않은 깨끗한 신호라 다른 테스트의 위젯과 무관하다.
"""
from __future__ import annotations

from unittest.mock import patch

from PyQt6.QtWidgets import QGraphicsView, QLabel, QStackedWidget, QVBoxLayout, QWidget

from gui.themes.manager import ThemeManager
from gui.themes.tokens import PRESETS


def _preset_names() -> list[str]:
    names = list(PRESETS.keys())
    assert len(names) >= 2
    return names[:2]


def _isolated_manager() -> ThemeManager:
    """싱글턴과 무관한 새 인스턴스 — theme_changed에 아무도 연결돼 있지 않다."""
    return ThemeManager()


class TestCrossfadeOnApply:
    def test_보이는_창에_스냅샷이_얹히고_사라진다(self, qtbot):
        win = QWidget()
        win.resize(240, 160)
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)

        before = len(win.findChildren(QLabel))
        name_a, _ = _preset_names()
        with patch("gui.themes.manager.ThemeManager._save"):
            _isolated_manager().apply(name_a)

        after = len(win.findChildren(QLabel))
        assert after == before + 1   # 스냅샷 오버레이 1개가 얹혔다

        qtbot.waitUntil(
            lambda: len(win.findChildren(QLabel)) == before, timeout=2000
        )

    def test_숨은_창에는_스냅샷을_얹지_않는다(self, qtbot):
        win = QWidget()
        win.resize(240, 160)
        qtbot.addWidget(win)
        # show() 하지 않음 — isVisible() == False

        before = len(win.findChildren(QLabel))
        name_a, _ = _preset_names()
        with patch("gui.themes.manager.ThemeManager._save"):
            _isolated_manager().apply(name_a)

        assert len(win.findChildren(QLabel)) == before


class TestVideoSurfaceSkip:
    def test_보이는_영상_표시면이_있는_창은_건너뛴다(self, qtbot):
        win = QWidget()
        win.resize(240, 160)
        layout = QVBoxLayout(win)
        view = QGraphicsView()
        layout.addWidget(view)
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)

        before = len(win.findChildren(QLabel))
        name_a, _ = _preset_names()
        with patch("gui.themes.manager.ThemeManager._save"):
            _isolated_manager().apply(name_a)

        assert len(win.findChildren(QLabel)) == before   # 스냅샷 없이 즉시 전환

    def test_감춰진_페이지의_영상_표시면은_창을_막지_않는다(self, qtbot):
        """QStackedWidget이 감춘 페이지의 QGraphicsView는 `isVisible()`이 False다.

        라이브러리 상세화면의 InlinePlayer처럼, 화면이 목록으로 바뀌어도 위젯
        자체는 스택 안에 계속 존재한다. "존재만으로" 영상 표시면을 판정하면 이런
        창은 앱이 뜬 뒤로 영원히 크로스페이드가 걸리지 않는다.
        """
        win = QStackedWidget()
        win.resize(240, 160)
        page_list = QLabel("목록")
        page_video = QWidget()
        QVBoxLayout(page_video).addWidget(QGraphicsView())
        win.addWidget(page_list)
        win.addWidget(page_video)
        win.setCurrentIndex(0)   # 영상 페이지는 감춰짐
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)

        before = len(win.findChildren(QLabel))
        name_a, _ = _preset_names()
        with patch("gui.themes.manager.ThemeManager._save"):
            _isolated_manager().apply(name_a)

        after = len(win.findChildren(QLabel))
        assert after == before + 1   # 감춰진 영상 페이지와 무관하게 스냅샷이 얹힌다

        qtbot.waitUntil(
            lambda: len(win.findChildren(QLabel)) == before, timeout=2000
        )


class TestInitializeDoesNotAnimate:
    def test_시작_초기화는_스냅샷을_만들지_않는다(self, qtbot) -> None:
        mgr = _isolated_manager()
        with patch.object(mgr, "_snapshot_windows", wraps=mgr._snapshot_windows) as spy:
            mgr.initialize()
            spy.assert_not_called()


class TestSingletonStillSaves:
    def test_apply는_여전히_설정_파일에_저장을_시도한다(self, qtbot) -> None:
        """싱글턴 경로에서는 `_save`가 실제로 불린다(설정 저장 계약 유지) — 이
        테스트만 격리된 인스턴스가 아니라 `_save` 호출 자체를 스파이한다."""
        name_a, _ = _preset_names()
        with patch("gui.themes.manager.ThemeManager._save") as spy:
            _isolated_manager().apply(name_a)
            spy.assert_called_once_with(name_a)
