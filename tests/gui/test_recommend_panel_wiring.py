"""라이브러리 패널 ↔ 추천 스트립 배선을 검증한다.

추천은 목록이 바뀔 때마다 자동으로 돌기 때문에, 잘못 배선되면 (1) 접혀 있는데도
네트워크 조회가 돌거나 (2) 키 입력마다 검색이 폭주하거나 (3) 카드 그리드 화면에서
엉뚱한 씨앗으로 조회한다. 세 경우 모두 화면만 봐서는 알아채기 어렵다.
"""
from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from application.library.dtos import FeedVideoDTO, VideoDTO
from gui.panels.library_panel import (
    _QWIDGET_MAX_H,
    _RECOMMEND_DEBOUNCE_MS,
    _RECOMMEND_REVEAL_MS,
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


def _feed_dto(title="추천 영상", vid="rec00000001"):
    return FeedVideoDTO(
        url=f"https://www.youtube.com/watch?v={vid}",
        title=title,
        channel_name="채널",
        channel_id="UC0",
        thumbnail_url="",          # 네트워크 로더가 뜨지 않게 빈 값
        thumbnail_path="",
        published_at="",
        view_count=None,
        duration_sec=100,
        in_library=False,
        yt_video_id=vid,
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
    # 실사용 설정을 **읽지도 않는다** — 사용자가 스트립을 접어 두면(저장된 값이 False)
    # 지연 노출 테스트가 그 기계에서만 깨진다. 시작 상태를 기본값으로 고정한다.
    monkeypatch.setattr(settings, "RECOMMEND_STRIP_EXPANDED", True, raising=False)
    monkeypatch.setattr(settings, "RECOMMEND_STRIP_HEIGHT", 250, raising=False)
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
    """추천 목록이 다 준비되기 전에는 빈 띠가 자리를 차지하지 않아야 한다."""

    def test_hidden_until_results_arrive(self, panel):
        assert not panel._recommend_strip.isVisibleTo(panel)

        panel._on_recommend_items([_feed_dto()])

        assert panel._recommend_strip.isVisibleTo(panel)

    def test_partial_results_do_not_reveal(self, panel):
        # 부분 결과는 채워만 두고 노출하지 않는다(조회 중 상태가 보이지 않게).
        panel._on_recommend_partial([_feed_dto()])

        assert not panel._recommend_strip.isVisibleTo(panel)

    def test_empty_result_reveals_header_so_retry_stays_reachable(self, panel):
        # 결과가 없어도 완전히 숨기면 ⟳(다시 받기)에 닿을 수 없다.
        panel._on_recommend_items([])

        assert panel._recommend_strip.isVisibleTo(panel)

    def test_새_조회가_시작되면_다시_감춘다(self, panel, qtbot, library_vm, recommend_vm):
        # 카테고리를 바꾸면 씨앗이 통째로 달라져, 걸려 있던 카드는 새 목록과 무관하다.
        panel._on_recommend_items([_feed_dto()])
        assert panel._recommend_strip.isVisibleTo(panel)

        library_vm._videos = [_dto()]
        panel._refresh_recommendations()

        recommend_vm.load.assert_called_once()
        assert panel._recommend_ready is False
        qtbot.wait(_RECOMMEND_REVEAL_MS + 300)
        assert not panel._recommend_strip.isVisibleTo(panel)

        # 새 결과가 도착하면 다시 올라온다.
        panel._on_recommend_items([_feed_dto("추천2")])
        assert panel._recommend_strip.isVisibleTo(panel)

    def test_hidden_on_card_grid_view_and_restored_after(self, panel):
        panel._on_recommend_items([_feed_dto()])

        panel._view_stack.setCurrentIndex(_VIEW_FEED)
        assert not panel._recommend_strip.isVisibleTo(panel)

        panel._view_stack.setCurrentIndex(_VIEW_ICON)
        assert panel._recommend_strip.isVisibleTo(panel)


class TestRevealAnimation:
    """숨어 있던 스트립이 0에서 목표 높이까지 자라며 올라온다."""

    def test_준비되면_높이가_0에서_목표까지_자란다(self, panel, qtbot):
        panel.resize(1280, 800)
        panel.show()
        qtbot.waitExposed(panel)

        panel._on_recommend_items([_feed_dto()])

        # 시작 프레임 — 아직 목표 높이에 한참 못 미친다(= 아래에서 올라오는 중)
        assert panel._recommend_anim is not None
        assert panel._recommend_strip.maximumHeight() < panel._recommend_height

        qtbot.wait(_RECOMMEND_REVEAL_MS + 300)

        assert panel._recommend_anim is None
        assert panel._centre_splitter.sizes()[1] == panel._recommend_height
        # 끝난 뒤엔 사용자가 스플리터 핸들로 다시 늘릴 수 있어야 한다.
        assert panel._recommend_strip.maximumHeight() == _QWIDGET_MAX_H

    def test_새_조회는_아래로_접었다가_다시_올린다(self, panel, qtbot, library_vm):
        panel.resize(1280, 800)
        panel.show()
        qtbot.waitExposed(panel)
        panel._on_recommend_items([_feed_dto()])
        qtbot.wait(_RECOMMEND_REVEAL_MS + 300)
        height_before = panel._centre_splitter.sizes()[1]

        library_vm._videos = [_dto()]
        panel._refresh_recommendations()          # 카테고리 전환에 해당
        qtbot.wait(_RECOMMEND_REVEAL_MS + 300)

        assert panel._recommend_strip.isHidden()

        panel._on_recommend_items([_feed_dto("추천2")])
        qtbot.wait(_RECOMMEND_REVEAL_MS + 300)

        assert not panel._recommend_strip.isHidden()
        # 접기 전에 쓰던 높이를 그대로 복원한다.
        assert panel._centre_splitter.sizes()[1] == height_before


class TestDetailRecommendations:
    """상세화면 우측 '연관 영상' 아래에 같은 추천 결과를 재사용한다."""

    def test_추천_결과를_우측_목록_항목으로_변환한다(self, panel, recommend_vm):
        dto = _feed_dto("추천1")
        recommend_vm.items = [dto]

        items = panel._recommend_related_items()

        assert [i.title for i in items] == ["추천1"]
        assert items[0].payload is dto      # 클릭 시 스트리밍 상세로 재진입

    def test_상세가_열려_있으면_새_추천을_밀어넣는다(self, panel, recommend_vm, monkeypatch):
        recommend_vm.items = [_feed_dto("추천1")]
        pushed: list[list] = []
        monkeypatch.setattr(
            panel._detail_widget, "set_recommendations", lambda items: pushed.append(items)
        )
        panel._nav_stack.setCurrentIndex(1)      # 상세 화면

        panel._on_recommend_items([_feed_dto("추천1")])

        assert [i.title for i in pushed[0]] == ["추천1"]


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
