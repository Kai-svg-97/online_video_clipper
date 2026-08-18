"""마우스 ‹/› 히스토리 — 라이브러리 어느 화면에서든 동작하는지 고정한다.

예전에는 영상 목록 뷰·앨범 위젯에만 이벤트 필터를 걸어, 좌측 트리·피드 카드·태그
패널·빈 공간처럼 필터가 없는 곳에서는 마우스 뒤로가기가 **조용히 죽었다**(위젯을 새로
추가할 때마다 배선을 잊으면 또 죽는다). 지금은 화면이 보이는 동안 앱 전역 필터가 받고
"같은 창 안의 클릭인가"로만 판단한다.

그래서 이 파일이 지키는 것은 두 가지다.
* 어느 자식 위젯에서 눌러도 히스토리가 움직인다(범위가 넓어졌다).
* 그렇다고 아무거나 삼키지는 않는다 — 모달 대화상자, 다른 창, 다른 마우스 버튼,
  그리고 **Ctrl+휠 뷰 전환은 목록 위에서만**(전역 필터라 범위를 좁히지 않으면 트리·
  플레이어의 Ctrl+휠까지 뷰를 바꾼다).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent, QWheelEvent
from PyQt6.QtWidgets import QApplication, QDialog, QLabel

from gui.panels.library_panel import LibraryPanel


@pytest.fixture
def album_vm():
    vm = MagicMock()
    for sig in ("albums_changed", "detail_ready", "track_filled", "fill_finished",
                "unknown_resolved", "error_occurred", "add_progress", "tracks_added"):
        getattr(vm, sig).connect = MagicMock()
    vm.detail = None
    return vm


@pytest.fixture
def panel(qtbot, library_vm, download_vm, clip_vm, album_vm, monkeypatch):
    import config.settings as settings
    monkeypatch.setattr(settings, "save_setting", lambda *a, **k: None)
    monkeypatch.setattr(library_vm, "load", lambda *a, **k: None)
    p = LibraryPanel(vm=library_vm, clip_vm=clip_vm, download_vm=download_vm,
                     album_vm=album_vm)
    qtbot.addWidget(p)
    p.show()
    qtbot.waitExposed(p)
    yield p
    for worker in list(library_vm._list_workers):
        worker.wait(3000)
    library_vm.shutdown()


def _press(widget, button) -> None:
    """실제 마우스 누름 이벤트를 그 위젯으로 보낸다(앱 필터를 거친다)."""
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPointF(4, 4), QPointF(4, 4),
        button, button, Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget, event)


def _spy(panel, monkeypatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(panel, "_go_back", lambda: calls.append("back"))
    monkeypatch.setattr(panel, "_go_forward", lambda: calls.append("forward"))
    return calls


class TestEveryScreen:
    """필터가 걸린 위젯 목록이 아니라 '같은 창'이 기준이다."""

    def _surfaces(self, panel) -> dict:
        return {
            "좌측 트리": panel._playlist_panel,
            "영상 그리드": panel._icon_view.viewport(),
            "피드 그리드": panel._feed_grid,
            "앨범 그리드": panel._album_grid,
            "앨범 상세": panel._album_detail,
            "추천 스트립": panel._recommend_strip,
            "패널 빈 공간": panel,
        }

    def test_어느_화면에서_눌러도_뒤로_간다(self, panel, monkeypatch):
        calls = _spy(panel, monkeypatch)

        for name, widget in self._surfaces(panel).items():
            calls.clear()
            _press(widget, Qt.MouseButton.BackButton)
            assert calls == ["back"], name

    def test_어느_화면에서_눌러도_앞으로_간다(self, panel, monkeypatch):
        calls = _spy(panel, monkeypatch)

        for name, widget in self._surfaces(panel).items():
            calls.clear()
            _press(widget, Qt.MouseButton.ForwardButton)
            assert calls == ["forward"], name

    def test_영상_상세에서는_상세_전용_경로로_간다(self, panel, monkeypatch):
        """재생목록으로 들어온 상세는 재생 이력을 먼저 되짚어야 한다 — 그래서 상세
        위에서의 ‹는 `_go_back`이 아니라 상세 경로로 보낸다.

        상세 위젯도 자체 앱 필터로 같은 곳(back_requested)에 보내므로 어느 쪽이 먼저
        돌든 결과는 같아야 한다. 여기서는 이 패널의 라우팅 규칙만 직접 확인한다."""
        calls: list[str] = []
        monkeypatch.setattr(panel, "_go_back", lambda: calls.append("back"))
        monkeypatch.setattr(
            panel, "_on_detail_back_requested", lambda: calls.append("detail_back")
        )
        panel._nav_stack.setCurrentIndex(1)
        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress, QPointF(4, 4), QPointF(4, 4),
            Qt.MouseButton.BackButton, Qt.MouseButton.BackButton,
            Qt.KeyboardModifier.NoModifier,
        )

        assert panel._handle_history_mouse(panel, event) is True
        assert calls == ["detail_back"]

    def test_상세에서도_앞으로가기가_동작한다(self, panel, monkeypatch):
        """상세 위젯의 자체 필터는 ‹만 처리한다 — ›는 여기서 받아야 한다."""
        calls = _spy(panel, monkeypatch)
        panel._nav_stack.setCurrentIndex(1)

        _press(panel._detail_widget, Qt.MouseButton.ForwardButton)

        assert calls == ["forward"]


class TestScope:
    def test_보통_클릭은_그대로_흘려_보낸다(self, panel, monkeypatch):
        calls = _spy(panel, monkeypatch)

        _press(panel._icon_view.viewport(), Qt.MouseButton.LeftButton)

        assert calls == []

    def test_모달_대화상자가_떠_있으면_넘기지_않는다(self, panel, qtbot, monkeypatch):
        """정리·빠른 이동 같은 대화상자 위에서의 ‹는 그 창의 몫이다."""
        calls = _spy(panel, monkeypatch)
        dlg = QDialog(panel)
        qtbot.addWidget(dlg)
        dlg.setModal(True)
        dlg.show()
        qtbot.waitExposed(dlg)

        _press(panel._icon_view.viewport(), Qt.MouseButton.BackButton)

        assert calls == []
        dlg.close()

    def test_다른_창의_클릭은_무시한다(self, panel, qtbot, monkeypatch):
        calls = _spy(panel, monkeypatch)
        other = QLabel("다른 창")
        qtbot.addWidget(other)
        other.show()
        qtbot.waitExposed(other)

        _press(other, Qt.MouseButton.BackButton)

        assert calls == []

    def test_화면이_가려지면_필터를_뗀다(self, panel, monkeypatch):
        """다른 페이지(다운로드·설정)의 클릭까지 가로채면 안 된다.

        목록 뷰에는 Ctrl+휠용 자체 필터가 그대로 남으므로, 전역 필터로만 받던
        곳(좌측 트리)으로 확인한다."""
        calls = _spy(panel, monkeypatch)
        panel.hide()
        assert panel._app_filter_on is False

        _press(panel._playlist_panel, Qt.MouseButton.BackButton)

        assert calls == []


class TestCtrlWheelScope:
    """전역 필터가 되면서 Ctrl+휠의 적용 범위가 문제가 됐다."""

    def _wheel(self, widget) -> None:
        event = QWheelEvent(
            QPointF(4, 4), QPointF(4, 4), QPoint(0, 0), QPoint(0, 120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier,
            Qt.ScrollPhase.NoScrollPhase, False,
        )
        QApplication.sendEvent(widget, event)

    def test_목록_위에서는_뷰가_바뀐다(self, panel, monkeypatch):
        calls: list[int] = []
        monkeypatch.setattr(panel, "_cycle_view", calls.append)

        self._wheel(panel._icon_view.viewport())

        assert calls == [1]

    def test_트리_위에서는_바뀌지_않는다(self, panel, monkeypatch):
        """트리·플레이어의 Ctrl+휠은 각자 쓰임이 있다(자막 크기 등)."""
        calls: list[int] = []
        monkeypatch.setattr(panel, "_cycle_view", calls.append)

        self._wheel(panel._playlist_panel)

        assert calls == []


class TestAlbumLeavesOnCategory:
    """앨범을 보다가 카테고리를 고르면 그 카테고리의 영상 목록으로 나온다."""

    def _music(self, panel, library_vm):
        music = SimpleNamespace(id=uuid4(), name="Music", parent_id=None,
                                video_count=0, color="")
        other = SimpleNamespace(id=uuid4(), name="IT", parent_id=None,
                                video_count=0, color="")
        library_vm._categories = [music, other]
        panel._current_cat_id = music.id
        panel._update_view_options()
        return music, other

    def test_다른_카테고리를_고르면_앨범에서_나온다(self, panel, library_vm):
        _music, other = self._music(panel, library_vm)
        panel._btn_album.click()
        assert panel._album_mode is True

        panel._on_cat_filter_changed(other.id)

        assert panel._album_mode is False
        assert panel._current_cat_id == other.id

    def test_같은_음악_계열_카테고리를_골라도_나온다(self, panel, library_vm):
        """앨범 버튼이 계속 보이는 카테고리라도 마찬가지다 — 트리 클릭은
        '이 카테고리를 보겠다'는 뜻이지 '앨범 보기를 유지하겠다'가 아니다."""
        music, _other = self._music(panel, library_vm)
        panel._btn_album.click()

        panel._on_cat_filter_changed(music.id)

        assert panel._album_mode is False
        assert not panel._btn_album.isHidden()      # 다시 들어갈 길은 남아 있다

    def test_앨범_상세를_보던_중에도_나온다(self, panel, library_vm):
        _music, other = self._music(panel, library_vm)
        panel._btn_album.click()
        panel._on_album_clicked("iu\x1fpalette")
        assert panel._nav_stack.currentIndex() == 2

        panel._on_cat_filter_changed(other.id)

        assert panel._nav_stack.currentIndex() == 0
        assert panel._album_mode is False

    def test_뒤로가면_보던_앨범_화면으로_돌아온다(self, panel, library_vm):
        """나가는 것과 잃는 것은 다르다 — 히스토리에는 남아야 한다."""
        _music, other = self._music(panel, library_vm)
        panel._btn_album.click()

        panel._on_cat_filter_changed(other.id)
        panel._go_back()

        assert panel._album_mode is True

    def test_복원_중에는_앨범_모드를_건드리지_않는다(self, panel, library_vm):
        """복원은 스냅샷이 결정한다 — 여기서 나가 버리면 되살릴 화면이 사라진다."""
        music, _other = self._music(panel, library_vm)
        panel._btn_album.click()
        panel._is_restoring = True

        panel._on_cat_filter_changed(music.id)

        assert panel._album_mode is True
        panel._is_restoring = False
