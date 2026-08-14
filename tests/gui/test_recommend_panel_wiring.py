"""라이브러리 패널 ↔ 추천 스트립 배선을 검증한다.

추천은 목록이 바뀔 때마다 자동으로 돌기 때문에, 잘못 배선되면 (1) 접혀 있는데도
네트워크 조회가 돌거나 (2) 키 입력마다 검색이 폭주하거나 (3) 카드 그리드 화면에서
엉뚱한 씨앗으로 조회한다. 세 경우 모두 화면만 봐서는 알아채기 어렵다.
"""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from application.library.dtos import VideoDTO
from gui.panels.library_panel import (
    _RECOMMEND_DEBOUNCE_MS,
    _VIEW_FEED,
    _VIEW_ICON,
    LibraryPanel,
)


def _drain(library_vm) -> None:
    for worker in list(library_vm._list_workers):
        worker.wait(3000)
    library_vm.shutdown()


def _dto(title="파이썬 강의", channel="코딩채널", tags=("개발",)):
    return VideoDTO(
        id=uuid4(),
        url=f"https://youtu.be/{uuid4().hex[:11]}",
        title=title,
        channel_name=channel,
        thumbnail_path="",
        duration_sec=60,
        favorite=False,
        watched=False,
        category_id=None,
        tag_names=tags,
    )


@pytest.fixture
def recommend_vm():
    vm = MagicMock()
    # 시그널 연결 대상이므로 connect만 무해하게 받아 넘긴다.
    for sig in ("items_changed", "partial_ready", "loading_changed", "error_occurred"):
        getattr(vm, sig).connect = MagicMock()
    return vm


@pytest.fixture
def panel(qtbot, library_vm, download_vm, clip_vm, recommend_vm, monkeypatch):
    # 설정 파일에 접힘 상태를 쓰지 않는다(실사용 config.yaml 보호).
    import config.settings as settings
    monkeypatch.setattr(settings, "save_setting", lambda *a, **k: None)
    # 패널 생성 시 예약되는 초기 목록 로드를 막는다 — 그 워커가 끝나면서
    # videos_changed가 다시 나면서 테스트가 심어 둔 목록을 빈 목록으로 덮어쓴다.
    monkeypatch.setattr(library_vm, "load", lambda *a, **k: None)
    p = LibraryPanel(
        vm=library_vm,
        clip_vm=clip_vm,
        download_vm=download_vm,
        recommend_vm=recommend_vm,
    )
    qtbot.addWidget(p)
    yield p
    _drain(library_vm)


class TestAutoRefresh:
    def test_list_change_does_not_query_immediately(self, panel, library_vm, recommend_vm):
        panel._recommend_strip.set_expanded(True, notify=False)
        library_vm._videos = [_dto()]
        panel._on_videos_changed()

        recommend_vm.load.assert_not_called()      # 디바운스 대기 중
        assert panel._recommend_timer.isActive()

    def test_query_runs_after_debounce(self, panel, qtbot, library_vm, recommend_vm):
        panel._recommend_strip.set_expanded(True, notify=False)
        library_vm._videos = [_dto("파이썬 강의 1"), _dto("파이썬 강의 2")]
        panel._on_videos_changed()

        qtbot.wait(_RECOMMEND_DEBOUNCE_MS + 200)

        recommend_vm.load.assert_called_once()
        kwargs = recommend_vm.load.call_args.kwargs
        assert kwargs["seed_titles"] == ("파이썬 강의 1", "파이썬 강의 2")
        assert kwargs["seed_channels"] == ("코딩채널", "코딩채널")
        assert kwargs["seed_tags"] == ("개발", "개발")

    def test_collapsed_strip_never_queries(self, panel, qtbot, library_vm, recommend_vm):
        panel._recommend_strip.set_expanded(False, notify=False)
        library_vm._videos = [_dto()]
        panel._on_videos_changed()
        qtbot.wait(_RECOMMEND_DEBOUNCE_MS + 200)

        recommend_vm.load.assert_not_called()
        assert not panel._recommend_timer.isActive()

    def test_card_grid_views_are_skipped(self, panel, library_vm, recommend_vm):
        panel._recommend_strip.set_expanded(True, notify=False)
        panel._view_stack.setCurrentIndex(_VIEW_FEED)
        library_vm._videos = [_dto()]
        panel._on_videos_changed()

        assert not panel._recommend_timer.isActive()

    def test_empty_list_shows_reason_without_querying(self, panel, library_vm, recommend_vm):
        panel._recommend_strip.set_expanded(True, notify=False)
        library_vm._videos = []

        panel._refresh_recommendations()

        recommend_vm.load.assert_not_called()
        assert panel._recommend_strip.set_status
        assert panel._recommend_strip._status_lbl.text() != ""

    def test_manual_refresh_forces_requery(self, panel, library_vm, recommend_vm):
        panel._recommend_strip.set_expanded(True, notify=False)
        library_vm._videos = [_dto()]

        panel._recommend_strip.refresh_requested.emit()

        recommend_vm.load.assert_called_once()
        assert recommend_vm.load.call_args.kwargs["force"] is True


class TestStripVisibility:
    def test_hidden_on_card_grid_view_and_restored_after(self, panel):
        panel._view_stack.setCurrentIndex(_VIEW_FEED)
        assert not panel._recommend_strip.isVisibleTo(panel)

        panel._view_stack.setCurrentIndex(_VIEW_ICON)
        assert panel._recommend_strip.isVisibleTo(panel)


class TestDropWiring:
    def test_tree_url_drop_registers_video_in_that_category(self, panel, library_vm, monkeypatch):
        """추천 카드를 카테고리에 끌어다 놓으면 그 카테고리로 등록된다."""
        calls: list[tuple] = []
        monkeypatch.setattr(
            library_vm, "add_video", lambda url, cat=None: calls.append((url, cat))
        )
        cat_id = uuid4()

        panel._playlist_panel.url_dropped.emit("https://youtu.be/rec1", cat_id)

        assert calls == [("https://youtu.be/rec1", cat_id)]

    def test_root_drop_registers_without_category(self, panel, library_vm, monkeypatch):
        calls: list[tuple] = []
        monkeypatch.setattr(
            library_vm, "add_video", lambda url, cat=None: calls.append((url, cat))
        )

        panel._playlist_panel.url_dropped.emit("https://youtu.be/rec2", None)

        assert calls == [("https://youtu.be/rec2", None)]
