"""상세화면 '카테고리 지정'(📁)과 라이브러리 밖 영상의 잠금 안내를 검증한다.

핵심은 두 가지다.
1. 스트리밍(추천·피드) 영상에서도 요약·노래 탭이 **열려 있어야** 한다 — 예전처럼 탭을
   비활성화하면 클릭조차 되지 않아 "왜 못 쓰는지"를 알릴 방법이 없다. 대신 탭 안에
   안내판이 뜨고, 그 버튼으로 카테고리에 담아 잠금을 푼다.
2. 담기 요청은 위젯이 직접 처리하지 않고 payload(로컬=UUID / 스트리밍=FeedVideoDTO)를
   실어 상위로 올린다 — 등록·카테고리 이동은 LibraryPanel/ViewModel의 일이다.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from application.library.dtos import FeedVideoDTO
from gui.panels.library_panel import LibraryPanel
from gui.panels.video_detail_panel import VideoDetailWidget


def _feed(vid="strm0000001", title="스트리밍 영상"):
    return FeedVideoDTO(
        url=f"https://www.youtube.com/watch?v={vid}",
        title=title,
        channel_name="채널",
        channel_id="UC0",
        thumbnail_url="",
        thumbnail_path="",
        published_at="",
        view_count=None,
        duration_sec=100,
        in_library=False,
        yt_video_id=vid,
    )


def _detail_dto(video_id):
    """VideoDetailDTO 대용 — load()가 읽는 속성만 갖춘 가벼운 스텁."""
    return SimpleNamespace(
        id=video_id,
        url="https://youtu.be/local000001",
        title="로컬 영상",
        channel_name="채널",
        duration_sec=100,
        published_at="",
        view_count=None,
        favorite=False,
        watched=False,
        description="",
        notes="",
        tags=(),
        downloads=[],
        failed_downloads=[],
        gemini_summary="",
        summary_status="",
        category_id=None,
        thumbnail_path="",
    )


class TestStreamingLockNotice:
    def test_요약_노래_탭이_열려_있고_안내판이_뜬다(self, qtbot):
        w = VideoDetailWidget()
        qtbot.addWidget(w)

        w.load_stream(_feed())

        # 탭 자체는 활성 — 눌러서 안내를 읽을 수 있어야 한다.
        assert w._tabs.isTabEnabled(w._TAB_SUMMARY)
        assert w._tabs.isTabEnabled(w._TAB_SONG)
        # 내용은 잠금 안내판
        assert w._summary_stack.currentIndex() == w._SUMMARY_LOCKED
        assert w._song_tab._lyrics_stack.currentIndex() == w._song_tab._STACK_LOCKED

    def test_로컬_영상으로_로드하면_잠금이_풀린다(self, qtbot):
        w = VideoDetailWidget()
        qtbot.addWidget(w)
        w.load_stream(_feed())

        w.load(_detail_dto(uuid4()), tag_ids={})

        assert w._summary_stack.currentIndex() == w._SUMMARY_VIEW
        assert w._song_tab._lyrics_stack.currentIndex() == w._song_tab._STACK_VIEW

    def test_노래정보_갱신이_안내판을_지우지_않는다(self, qtbot):
        # set_info(None)이 표시 화면으로 되돌리면 안내 문구가 사라져 버린다.
        w = VideoDetailWidget()
        qtbot.addWidget(w)
        w.load_stream(_feed())

        w._song_tab.set_info(None)

        assert w._song_tab._lyrics_stack.currentIndex() == w._song_tab._STACK_LOCKED


class TestAssignRequestPayload:
    def test_스트리밍은_피드DTO를_실어_보낸다(self, qtbot):
        w = VideoDetailWidget()
        qtbot.addWidget(w)
        dto = _feed()
        w.load_stream(dto)
        got: list = []
        w.category_assign_requested.connect(got.append)

        w._btn_category.click()

        assert got == [dto]

    def test_로컬은_video_id를_실어_보낸다(self, qtbot):
        w = VideoDetailWidget()
        qtbot.addWidget(w)
        vid = uuid4()
        w.load(_detail_dto(vid), tag_ids={})
        got: list = []
        w.category_assign_requested.connect(got.append)

        w._btn_category.click()

        assert got == [vid]

    def test_안내판_버튼도_같은_요청을_낸다(self, qtbot):
        w = VideoDetailWidget()
        qtbot.addWidget(w)
        dto = _feed()
        w.load_stream(dto)
        got: list = []
        w.category_assign_requested.connect(got.append)

        w._song_tab._locked._btn.click()
        w._summary_locked._btn.click()

        assert got == [dto, dto]


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


class TestPanelWiring:
    """LibraryPanel이 payload 종류에 맞는 동작(이동 vs 등록)을 고른다."""

    def test_로컬_영상은_카테고리만_옮긴다(self, panel, library_vm, monkeypatch):
        cat_id = uuid4()
        video_id = uuid4()
        monkeypatch.setattr(panel, "_pick_category", lambda: (True, cat_id))
        moved: list = []
        monkeypatch.setattr(library_vm, "assign_category",
                            lambda vid, cid: moved.append((vid, cid)))
        monkeypatch.setattr(panel, "_reload_detail_in_place", lambda vid: None)

        panel._on_detail_category_requested(video_id)

        assert moved == [(video_id, cat_id)]

    def test_스트리밍_영상은_그_카테고리로_등록한다(self, panel, library_vm, monkeypatch):
        cat_id = uuid4()
        dto = _feed()
        monkeypatch.setattr(panel, "_pick_category", lambda: (True, cat_id))
        added: list = []
        monkeypatch.setattr(library_vm, "add_video",
                            lambda url, cid=None: added.append((url, cid)))
        monkeypatch.setattr(library_vm, "get_video_id_by_url", lambda url: None)

        panel._on_detail_category_requested(dto)

        assert added == [(dto.url, cat_id)]
        assert panel._pending_category_url == dto.url

    def test_취소하면_아무것도_하지_않는다(self, panel, library_vm, monkeypatch):
        monkeypatch.setattr(panel, "_pick_category", lambda: (False, None))
        added: list = []
        monkeypatch.setattr(library_vm, "add_video",
                            lambda url, cid=None: added.append((url, cid)))

        panel._on_detail_category_requested(_feed())

        assert added == []
        assert panel._pending_category_url == ""

    def test_등록이_끝나면_로컬_상세로_갈아탄다(self, panel, library_vm, monkeypatch):
        dto = _feed()
        video_id = uuid4()
        panel._pending_category_url = dto.url
        panel._nav_stack.setCurrentIndex(1)          # 상세 화면을 보고 있다
        monkeypatch.setattr(library_vm, "get_video_id_by_url", lambda url: video_id)
        opened: list = []
        monkeypatch.setattr(panel, "_open_detail",
                            lambda vid, **kw: opened.append((vid, kw)))

        panel._on_video_added_for_detail(dto.url)

        assert opened and opened[0][0] == video_id
        assert opened[0][1]["push_nav"] is False     # 화면 히스토리를 늘리지 않는다
        assert panel._pending_category_url == ""

    def test_다른_영상_등록에는_반응하지_않는다(self, panel, library_vm, monkeypatch):
        panel._pending_category_url = "https://youtu.be/mine"
        opened: list = []
        monkeypatch.setattr(panel, "_open_detail",
                            lambda vid, **kw: opened.append(vid))

        panel._on_video_added_for_detail("https://youtu.be/other")

        assert opened == []
        assert panel._pending_category_url == "https://youtu.be/mine"

    def test_추천_카드_카테고리_추가가_id를_그대로_넘긴다(self, panel, library_vm, monkeypatch):
        # 예전엔 selected_id를 괄호 없이 써서 바운드 메서드가 카테고리 id로 넘어갔다.
        cat_id = uuid4()
        monkeypatch.setattr(panel, "_pick_category", lambda: (True, cat_id))
        added: list = []
        monkeypatch.setattr(library_vm, "add_video",
                            lambda url, cid=None: added.append((url, cid)))

        panel._on_recommend_to_category("https://youtu.be/rec1")

        assert added == [("https://youtu.be/rec1", cat_id)]
