"""검색 입력 디바운스와 표(상세) 뷰 지연 갱신을 검증한다.

배경: 예전에는 `textChanged`가 곧바로 `set_search_text`를 불러 키 한 번마다
DB 조회 워커가 뜨고, 그 결과마다 표 뷰가 행별로 상세 조회를 돌려 메인 스레드가
막혔다. 한글 IME는 조합 중에도 `textChanged`를 방출해 체감이 더 나빴다.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from PyQt6.QtCore import Qt

from application.library.dtos import VideoDTO
from gui.panels.library_panel import _VIEW_DETAIL, _VIEW_ICON, LibraryPanel


def _drain(library_vm) -> None:
    """목록 워커가 끝나기를 기다린 뒤 정리한다.

    shutdown()은 실행 중인 워커를 terminate() 하므로, 곧바로 부르면 QThread가
    중간에 죽어 테스트 프로세스째 크래시할 수 있다.
    """
    for worker in list(library_vm._list_workers):
        worker.wait(3000)
    library_vm.shutdown()


@pytest.fixture
def panel(qtbot, library_vm, download_vm, clip_vm):
    p = LibraryPanel(vm=library_vm, clip_vm=clip_vm, download_vm=download_vm)
    qtbot.addWidget(p)
    yield p
    _drain(library_vm)


def _dto(title="제목"):
    return VideoDTO(
        id=uuid4(),
        url="https://youtu.be/abc",
        title=title,
        channel_name="채널",
        thumbnail_path="",
        duration_sec=60,
        favorite=False,
        watched=False,
        category_id=None,
    )


class TestSearchDebounce:
    """패널이 실제 조회를 언제 트리거하는지 — VM 호출을 가로채 관찰한다."""

    @pytest.fixture
    def calls(self, panel, library_vm, monkeypatch):
        recorded: list[str] = []
        monkeypatch.setattr(library_vm, "set_search_text", recorded.append)
        return recorded

    def test_typing_does_not_query_immediately(self, panel, qtbot, calls):
        # 한 글자씩 입력 = textChanged 3회 (IME 조합도 동일하게 여러 번 방출된다)
        for text in ("파", "파이", "파이썬"):
            panel._search_box.setText(text)

        assert calls == []
        assert panel._search_timer.isActive()

        qtbot.waitUntil(lambda: bool(calls), timeout=3000)
        assert calls == ["파이썬"]          # 입력이 멎은 뒤 한 번만 조회
        assert not panel._search_timer.isActive()

    def test_enter_applies_immediately(self, panel, qtbot, calls):
        panel._search_box.setText("레디스")
        assert calls == []

        qtbot.keyClick(panel._search_box, Qt.Key.Key_Return)
        assert calls == ["레디스"]
        assert not panel._search_timer.isActive()

    def test_clearing_applies_immediately(self, panel, calls):
        panel._search_box.setText("도커")
        panel._search_box.clear()

        assert calls == [""]               # 지우기는 기다리지 않는다
        assert not panel._search_timer.isActive()


class TestSearchTextGuard:
    """뷰모델은 실제로 바뀐 검색어에서만 재조회한다."""

    def test_unchanged_text_does_not_requery(self, library_vm):
        try:
            library_vm.set_search_text("가사")
            before = library_vm._list_gen

            library_vm.set_search_text("가사 ")   # strip 결과 동일 → 무시
            assert library_vm._list_gen == before

            library_vm.set_search_text("가사집")  # 실제 변경 → 재조회
            assert library_vm._list_gen > before
        finally:
            _drain(library_vm)


class TestTableLazyRefresh:
    def test_table_not_filled_while_hidden(self, panel, library_vm):
        panel._view_stack.setCurrentIndex(_VIEW_ICON)
        library_vm._videos = [_dto()]
        panel._on_videos_changed()

        assert panel._table.rowCount() == 0
        assert panel._table_dirty is True

    def test_table_filled_on_switch(self, panel, library_vm):
        panel._view_stack.setCurrentIndex(_VIEW_ICON)
        library_vm._videos = [_dto("보이는 제목")]
        panel._on_videos_changed()

        panel._switch_view(_VIEW_DETAIL)
        assert panel._table.rowCount() == 1
        assert panel._table.item(0, 0).text() == "보이는 제목"
        assert panel._table_dirty is False

    def test_table_refreshes_immediately_when_visible(self, panel, library_vm):
        panel._switch_view(_VIEW_DETAIL)
        library_vm._videos = [_dto("즉시 반영")]
        panel._on_videos_changed()

        assert panel._table.rowCount() == 1
        assert panel._table_dirty is False

    def test_no_per_row_detail_query(self, panel, library_vm):
        """행마다 get_video_detail 을 부르던 N+1 이 사라졌는지 고정한다."""
        panel._switch_view(_VIEW_DETAIL)
        library_vm._videos = [_dto(f"영상 {i}") for i in range(10)]
        library_vm._get_video_detail.handle.reset_mock()

        panel._on_videos_changed()

        assert library_vm._get_video_detail.handle.call_count == 0
