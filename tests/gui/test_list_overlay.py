"""목록 상태 안내판 — 조회 중·결과 없음을 화면이 말해 주는지 고정한다.

이전에는 목록이 아무 말도 하지 않았다: 카테고리를 눌러도 조회가 끝날 때까지 이전
목록이 그대로였고, 0건이면 그냥 빈 화면이라 '없는 건지 못 불러온 건지' 알 수 없었다.

깜빡임 방지도 계약이다 — 캐시 히트처럼 즉시 끝나는 조회에서 '불러오는 중'이 번쩍이면
오히려 더 산만하다(그래서 지연 후에만 띄운다).
"""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from application.library.dtos import VideoDTO
from gui.panels.library.mixins.video_list import _LOADING_HINT_DELAY_MS
from gui.panels.library_panel import LibraryPanel


def _dto(title="영상"):
    return VideoDTO(
        id=uuid4(), url=f"https://youtu.be/{uuid4().hex[:11]}", title=title,
        channel_name="채널", thumbnail_path="", duration_sec=60,
        favorite=False, watched=False, category_id=None, tag_names=(),
    )


@pytest.fixture
def panel(qtbot, library_vm, download_vm, clip_vm, monkeypatch):
    import config.settings as settings
    monkeypatch.setattr(settings, "save_setting", lambda *a, **k: None)
    monkeypatch.setattr(library_vm, "load", lambda *a, **k: None)
    p = LibraryPanel(vm=library_vm, clip_vm=clip_vm, download_vm=download_vm)
    qtbot.addWidget(p)
    yield p
    for worker in list(library_vm._list_workers):
        worker.wait(3000)
    library_vm.shutdown()


class TestEmptyState:
    def test_영상이_없으면_담는_방법을_알려준다(self, panel, library_vm):
        library_vm._videos = []

        panel._on_videos_changed()

        overlay = panel._list_overlay
        assert not overlay.isHidden()
        assert "아직 영상이 없습니다" in overlay.text()
        assert "끌어다" in overlay.text()          # 무엇을 하면 되는지까지 알려 준다

    def test_검색_결과가_없으면_검색_기준으로_안내한다(self, panel, library_vm):
        library_vm._videos = []
        panel._search_box.setText("없는검색어")

        panel._on_videos_changed()

        assert "검색 결과가 없습니다" in panel._list_overlay.text()

    def test_태그_필터_결과가_없으면_태그로_안내한다(self, panel, library_vm):
        library_vm._videos = []
        panel._active_tag_ids = {uuid4()}

        panel._on_videos_changed()

        assert "이 태그에" in panel._list_overlay.text()

    def test_영상이_있으면_안내판을_걷는다(self, panel, library_vm):
        library_vm._videos = []
        panel._on_videos_changed()
        assert not panel._list_overlay.isHidden()

        library_vm._videos = [_dto()]
        panel._on_videos_changed()

        assert panel._list_overlay.isHidden()


class TestLoadingHint:
    def test_조회가_길어지면_불러오는_중을_띄운다(self, panel, qtbot):
        panel._on_list_loading(True)

        qtbot.wait(_LOADING_HINT_DELAY_MS + 150)

        assert "불러오는 중" in panel._list_overlay.text()

    def test_짧은_조회에서는_깜빡이지_않는다(self, panel, library_vm, qtbot):
        """캐시 히트처럼 즉시 끝나는 조회 — 안내가 번쩍이면 더 산만하다."""
        library_vm._videos = [_dto()]

        panel._on_list_loading(True)
        panel._on_list_loading(False)      # 지연 시간 전에 끝났다
        qtbot.wait(_LOADING_HINT_DELAY_MS + 150)

        assert panel._list_overlay.isHidden()

    def test_조회가_끝나면_결과에_맞는_안내로_바뀐다(self, panel, library_vm, qtbot):
        library_vm._videos = []
        panel._on_list_loading(True)
        qtbot.wait(_LOADING_HINT_DELAY_MS + 150)
        assert "불러오는 중" in panel._list_overlay.text()

        panel._on_list_loading(False)

        assert "아직 영상이 없습니다" in panel._list_overlay.text()


class TestOverlayGeometry:
    def test_클릭을_통과시킨다(self, panel):
        """안내가 떠 있어도 아래 목록을 조작할 수 있어야 한다."""
        from PyQt6.QtCore import Qt

        panel._ensure_overlay()

        assert panel._list_overlay.testAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )

    def test_목록_영역_크기를_따라간다(self, panel, qtbot):
        panel.resize(1000, 700)
        panel.show()
        qtbot.waitExposed(panel)
        panel._ensure_overlay()

        panel._view_stack.resize(640, 480)
        qtbot.wait(50)

        assert panel._list_overlay.size() == panel._view_stack.size()


def test_뷰모델_없이도_안내판이_만들어진다(qtbot, library_vm, monkeypatch):
    """부품 단독 생성 — 패널이 다른 뷰모델 없이 떠도 안내가 동작해야 한다."""
    import config.settings as settings
    monkeypatch.setattr(settings, "save_setting", lambda *a, **k: None)
    monkeypatch.setattr(library_vm, "load", lambda *a, **k: None)
    p = LibraryPanel(vm=library_vm)
    qtbot.addWidget(p)

    assert p._ensure_overlay() is not None
    assert isinstance(p._loading_timer, MagicMock) is False
    for worker in list(library_vm._list_workers):
        worker.wait(3000)
    library_vm.shutdown()
