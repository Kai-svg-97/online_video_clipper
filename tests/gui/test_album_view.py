"""앨범 보기 GUI — 정렬 항목 노출 조건, 그리드/상세 렌더, 재생 배선을 고정한다.

특히 중요한 것:
* '앨범' 보기 버튼은 **음악 카테고리에서만** 뜬다(다른 카테고리에서는 뜻이 없다).
* '앨범'은 정렬이 아니라 보기 유형이다 — 정렬 콤보에 섞이면 SQL 정렬로 새어 나간다.
* 수록곡 행에는 출처 배지(내 등록/자동 매핑/없음)가 반드시 붙는다.
* 앨범 재생은 기존 재생목록 컨텍스트(_playlist_ctx)를 그대로 쓴다.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from application.song.album_dtos import (
    TRACK_ORIGIN_AUTO,
    TRACK_ORIGIN_LIBRARY,
    TRACK_ORIGIN_MISSING,
    AlbumCardDTO,
    AlbumDetailDTO,
    AlbumTrackDTO,
)
from gui.panels.album_panel import ORIGIN_LABELS, AlbumDetailPanel, AlbumGrid, _TrackRow
from gui.panels.library_panel import _VIEW_ALBUMS, _VIEW_DETAIL, _VIEW_LIST, LibraryPanel


def _cat(name, cat_id=None, parent_id=None):
    return SimpleNamespace(
        id=cat_id or uuid4(), name=name, parent_id=parent_id, video_count=0, color=""
    )


def _card(title="Palette", key="iu\x1fpalette"):
    return AlbumCardDTO(key=key, album_title=title, artist="IU", library_count=2, track_count=3)


def _detail(tracks=None):
    return AlbumDetailDTO(
        key="iu\x1fpalette",
        album_title="Palette",
        artist="IU",
        description="IU  ·  K-Pop  ·  2017-04-21 발매",
        tracks=tracks if tracks is not None else [
            AlbumTrackDTO(track_no=1, title="Palette", origin=TRACK_ORIGIN_LIBRARY,
                          video_id=uuid4()),
            AlbumTrackDTO(track_no=2, title="밤편지", origin=TRACK_ORIGIN_AUTO,
                          stream_url="https://youtu.be/auto1", stream_yt_id="auto1"),
            AlbumTrackDTO(track_no=3, title="이런 엔딩", origin=TRACK_ORIGIN_MISSING),
        ],
    )


class TestAlbumGrid:
    def test_카드를_그린다(self, qtbot):
        grid = AlbumGrid()
        qtbot.addWidget(grid)

        grid.set_albums([_card(), _card("Chat-Shire", "iu\x1fchatshire")])

        assert grid.count() == 2

    def test_카드_클릭이_앨범_키를_보낸다(self, qtbot):
        grid = AlbumGrid()
        qtbot.addWidget(grid)
        grid.set_albums([_card()])
        got: list[str] = []
        grid.album_clicked.connect(got.append)

        grid._inner.cards[0].clicked.emit("iu\x1fpalette")

        assert got == ["iu\x1fpalette"]


class TestAlbumDetailPanel:
    def test_수록곡마다_출처_배지가_붙는다(self, qtbot):
        panel = AlbumDetailPanel()
        qtbot.addWidget(panel)

        panel.set_detail(_detail())

        badges = [row._badge.text() for row in panel._rows]
        assert badges == [
            ORIGIN_LABELS[TRACK_ORIGIN_LIBRARY],
            ORIGIN_LABELS[TRACK_ORIGIN_AUTO],
            ORIGIN_LABELS[TRACK_ORIGIN_MISSING],
        ]

    def test_없는_곡은_클릭해도_재생을_요청하지_않는다(self, qtbot):
        panel = AlbumDetailPanel()
        qtbot.addWidget(panel)
        panel.set_detail(_detail())
        got: list = []
        panel.track_clicked.connect(got.append)

        missing_row = panel._rows[2]
        missing_row.clicked.emit(missing_row._track)   # 직접 쏘면 나가지만
        assert missing_row._track.playable is False    # 행 자체가 클릭을 막는다
        got.clear()

        playable_row = panel._rows[0]
        playable_row.clicked.emit(playable_row._track)
        assert got and got[0].origin == TRACK_ORIGIN_LIBRARY

    def test_상태에_보유_자동_없음_수가_나온다(self, qtbot):
        panel = AlbumDetailPanel()
        qtbot.addWidget(panel)

        panel.set_detail(_detail())

        text = panel.status_text()
        assert "내 등록 1곡" in text and "자동 1곡" in text and "없음 1곡" in text

    def test_자동_매핑_결과가_행에_반영된다(self, qtbot):
        panel = AlbumDetailPanel()
        qtbot.addWidget(panel)
        panel.set_detail(_detail())

        panel.apply_filled_track(AlbumTrackDTO(
            track_no=3, title="이런 엔딩", origin=TRACK_ORIGIN_AUTO,
            stream_url="https://youtu.be/auto3", stream_yt_id="auto3",
        ))

        assert panel._rows[2]._badge.text() == ORIGIN_LABELS[TRACK_ORIGIN_AUTO]
        assert "없음" not in panel.status_text()

    def test_앨범_재생_버튼이_DTO를_보낸다(self, qtbot):
        panel = AlbumDetailPanel()
        qtbot.addWidget(panel)
        detail = _detail()
        panel.set_detail(detail)
        got: list = []
        panel.play_album_requested.connect(got.append)

        panel._btn_play.click()

        assert got == [detail]


class TestTrackRowMissing:
    def test_없는_곡은_playable이_아니다(self, qtbot):
        row = _TrackRow(AlbumTrackDTO(track_no=1, title="x", origin=TRACK_ORIGIN_MISSING))
        qtbot.addWidget(row)
        assert row._track.playable is False


@pytest.fixture
def album_vm():
    vm = MagicMock()
    for sig in ("albums_changed", "detail_ready", "track_filled", "fill_finished",
                "unknown_resolved", "error_occurred"):
        getattr(vm, sig).connect = MagicMock()
    vm.detail = None
    return vm


@pytest.fixture
def panel(qtbot, library_vm, download_vm, clip_vm, album_vm, monkeypatch):
    import config.settings as settings
    monkeypatch.setattr(settings, "save_setting", lambda *a, **k: None)
    monkeypatch.setattr(library_vm, "load", lambda *a, **k: None)
    p = LibraryPanel(
        vm=library_vm, clip_vm=clip_vm, download_vm=download_vm, album_vm=album_vm
    )
    qtbot.addWidget(p)
    yield p
    for worker in list(library_vm._list_workers):
        worker.wait(3000)
    library_vm.shutdown()


class TestAlbumButtonVisibility:
    def _music_tree(self, library_vm):
        music = _cat("Music")
        sub = _cat("K-Pop", parent_id=music.id)
        other = _cat("IT")
        library_vm._categories = [music, sub, other]
        return music, sub, other

    def test_음악_카테고리에서만_앨범_버튼이_뜬다(self, panel, library_vm):
        music, sub, other = self._music_tree(library_vm)

        panel._current_cat_id = other.id
        panel._update_view_options()
        assert panel._btn_album.isHidden()

        panel._current_cat_id = music.id
        panel._update_view_options()
        assert not panel._btn_album.isHidden()

    def test_하위_카테고리도_최상위가_음악이면_뜬다(self, panel, library_vm):
        _music, sub, _other = self._music_tree(library_vm)

        panel._current_cat_id = sub.id
        panel._update_view_options()

        assert not panel._btn_album.isHidden()

    def test_뮤직_song_이름도_음악으로_본다(self, panel, library_vm):
        for name in ("뮤직", "Song", "노래", "음악"):
            cat = _cat(name)
            library_vm._categories = [cat]
            panel._current_cat_id = cat.id
            panel._update_view_options()
            assert not panel._btn_album.isHidden(), name
            # 다음 반복을 위해 원상복구
            library_vm._categories = []
            panel._current_cat_id = None
            panel._update_view_options()

    def test_음악이_아닌_곳으로_옮기면_항목이_사라진다(self, panel, library_vm):
        music, _sub, other = self._music_tree(library_vm)
        panel._current_cat_id = music.id
        panel._update_view_options()

        panel._current_cat_id = other.id
        panel._update_view_options()

        assert panel._btn_album.isHidden()


class TestAlbumMode:
    def test_앨범_보기는_정렬을_건드리지_않는다(self, panel, library_vm, monkeypatch):
        # 앨범은 보기 유형이다 — 정렬 조회가 함께 나가면 목록이 헛돈다.
        sorts: list = []
        monkeypatch.setattr(library_vm, "set_sort", lambda *a: sorts.append(a))
        library_vm._categories = [_cat("Music", cat_id=uuid4())]
        panel._current_cat_id = library_vm._categories[0].id
        panel._update_view_options()

        panel._btn_album.click()

        assert sorts == []
        assert panel._album_mode is True
        assert panel._view_stack.currentIndex() == _VIEW_ALBUMS

    def test_다른_보기_버튼을_누르면_앨범_모드가_풀린다(self, panel, library_vm, album_vm):
        library_vm._categories = [_cat("Music", cat_id=uuid4())]
        panel._current_cat_id = library_vm._categories[0].id
        panel._update_view_options()
        panel._btn_album.click()

        panel._btn_list.click()

        assert panel._album_mode is False
        assert panel._view_stack.currentIndex() == _VIEW_LIST

    def test_앨범에서_나오면_직전_목록_뷰로_돌아간다(self, panel, library_vm):
        # 보기 그룹에 앨범 버튼이 함께 있어 checkedId()로 되돌리면 다시 앨범이 된다.
        library_vm._categories = [_cat("Music", cat_id=uuid4())]
        panel._current_cat_id = library_vm._categories[0].id
        panel._update_view_options()
        panel._btn_table.click()          # 표 뷰를 보고 있다가
        panel._btn_album.click()          # 앨범으로 갔다가

        panel._exit_album_mode()          # 카테고리 이동 등으로 앨범이 풀리면

        assert panel._view_stack.currentIndex() == _VIEW_DETAIL   # 표 뷰로 복귀

    def test_음악이_아닌_카테고리로_옮기면_앨범_모드가_풀린다(self, panel, library_vm):
        music = _cat("Music")
        other = _cat("IT")
        library_vm._categories = [music, other]
        panel._current_cat_id = music.id
        panel._update_view_options()
        panel._btn_album.click()

        panel._current_cat_id = other.id
        panel._update_view_options()

        assert panel._btn_album.isHidden()
        assert panel._album_mode is False
        assert panel._view_stack.currentIndex() != _VIEW_ALBUMS

    def test_앨범_카드_클릭이_상세_조회를_요청한다(self, panel, album_vm):
        panel._album_mode = True

        panel._on_album_clicked("iu\x1fpalette")

        album_vm.load_detail.assert_called_once()
        assert panel._nav_stack.currentIndex() == 2      # 앨범 상세 페이지

    def test_빠진_곡이_있으면_열자마자_자동으로_찾는다(self, panel, album_vm):
        panel._album_mode = True

        panel._on_album_detail_ready(_detail())

        album_vm.fill_missing_tracks.assert_called_once()

    def test_빠진_곡이_없으면_찾지_않는다(self, panel, album_vm):
        panel._album_mode = True
        full = _detail([
            AlbumTrackDTO(track_no=1, title="a", origin=TRACK_ORIGIN_LIBRARY, video_id=uuid4()),
        ])

        panel._on_album_detail_ready(full)

        album_vm.fill_missing_tracks.assert_not_called()


class TestAlbumPlayback:
    def test_앨범_재생이_재생목록_컨텍스트를_세운다(self, panel, album_vm, monkeypatch):
        opened: list = []
        monkeypatch.setattr(panel, "_open_playlist_payload",
                            lambda payload, autoplay: opened.append((payload, autoplay)))
        detail = _detail()

        panel._on_play_album(detail)

        assert panel._playlist_ctx is not None
        assert panel._playlist_ctx["header"] == "앨범: Palette"
        # 재생 가능한 곡만 재생목록에 들어간다(없음 트랙 제외)
        assert len(panel._playlist_ctx["items"]) == 2
        assert opened and opened[0][1] is True

    def test_수록곡_클릭은_그_곡부터_재생한다(self, panel, album_vm, monkeypatch):
        detail = _detail()
        album_vm.detail = detail
        opened: list = []
        monkeypatch.setattr(panel, "_open_playlist_payload",
                            lambda payload, autoplay: opened.append(payload))

        panel._on_album_track_clicked(detail.tracks[1])   # 자동 매핑된 2번 곡

        assert opened and getattr(opened[0], "url", "") == "https://youtu.be/auto1"


class TestAlbumNavHistory:
    """앨범 그리드·상세도 화면 히스토리(뒤로/앞으로)에 편입된다.

    앨범 보기는 같은 카테고리 위의 '다른 화면'이라 스냅샷의 kind만으로는 구분되지
    않는다 — 모드(album_mode)와 열려 있던 앨범 키를 따로 싣지 않으면, 뒤로 갔을 때
    앨범 그리드 대신 일반 목록이 뜨거나 앨범 상세가 되살아나지 않는다.
    """

    def _music_category(self, panel, library_vm):
        music = _cat("Music")
        library_vm._categories = [music]
        panel._current_cat_id = music.id
        panel._update_view_options()
        return music

    def _enter_album_mode(self, panel, library_vm):
        self._music_category(panel, library_vm)
        panel._btn_album.click()

    def test_스냅샷이_앨범_상태를_담는다(self, panel, library_vm):
        self._enter_album_mode(panel, library_vm)
        panel._on_album_clicked("iu\x1fpalette")

        snap = panel._capture_screen()

        assert snap["album_mode"] is True
        assert snap["album_key"] == "iu\x1fpalette"
        assert snap["nav_idx"] == 2

    def test_앨범_그리드_진입이_히스토리에_쌓인다(self, panel, library_vm):
        self._music_category(panel, library_vm)
        before = len(panel._nav_history)

        panel._btn_album.click()

        assert len(panel._nav_history) == before + 1
        assert panel._nav_history[-1]["album_mode"] is False   # 진입 직전은 일반 목록

    def test_그리드에서_뒤로가면_일반_목록으로_돌아간다(self, panel, library_vm):
        self._enter_album_mode(panel, library_vm)

        panel._go_back()

        assert panel._album_mode is False
        assert panel._view_stack.currentIndex() != _VIEW_ALBUMS

    def test_앨범_상세에서_뒤로가면_그리드로_돌아온다(self, panel, library_vm):
        self._enter_album_mode(panel, library_vm)
        panel._on_album_clicked("iu\x1fpalette")
        assert panel._nav_stack.currentIndex() == 2

        panel._go_back()

        assert panel._nav_stack.currentIndex() == 0
        assert panel._album_mode is True
        assert panel._view_stack.currentIndex() == _VIEW_ALBUMS

    def test_앞으로가기로_앨범_상세가_다시_열린다(self, panel, library_vm, album_vm):
        self._enter_album_mode(panel, library_vm)
        panel._on_album_clicked("iu\x1fpalette")
        panel._go_back()
        album_vm.load_detail.reset_mock()

        panel._go_forward()

        assert panel._nav_stack.currentIndex() == 2
        assert album_vm.load_detail.call_args.args[0] == "iu\x1fpalette"

    def test_복원_중에는_히스토리를_다시_쌓지_않는다(self, panel, library_vm):
        self._enter_album_mode(panel, library_vm)
        panel._on_album_clicked("iu\x1fpalette")
        depth = len(panel._nav_history)

        panel._go_back()

        # 뒤로가기는 스택에서 하나를 꺼내 쓸 뿐 새로 쌓지 않는다.
        assert len(panel._nav_history) == depth - 1

    def test_앨범_상세_뒤로가기_버튼도_히스토리를_되짚는다(self, panel, library_vm):
        self._enter_album_mode(panel, library_vm)
        panel._on_album_clicked("iu\x1fpalette")

        panel._album_detail.back_requested.emit()

        assert panel._nav_stack.currentIndex() == 0
        assert panel._album_mode is True

    def test_마우스_뒤로가기가_앨범_화면에서도_동작한다(self, panel, library_vm, monkeypatch):
        """이벤트 필터가 앨범 위젯에 걸려 있지 않으면 마우스 ‹가 조용히 죽는다."""
        from PyQt6.QtCore import QPointF, Qt
        from PyQt6.QtGui import QMouseEvent
        from PyQt6.QtWidgets import QApplication

        calls: list = []
        monkeypatch.setattr(panel, "_go_back", lambda: calls.append(1))

        for widget in (panel._album_grid, panel._album_detail):
            calls.clear()
            event = QMouseEvent(
                QMouseEvent.Type.MouseButtonPress, QPointF(5, 5), QPointF(5, 5),
                Qt.MouseButton.BackButton, Qt.MouseButton.BackButton,
                Qt.KeyboardModifier.NoModifier,
            )
            QApplication.sendEvent(widget, event)
            assert calls == [1], widget

    def test_앨범_재생_후_뒤로가면_앨범_상세로_돌아온다(self, panel, library_vm, album_vm,
                                                    monkeypatch):
        """재생목록 진입은 push_nav=False라, 앨범 상세를 따로 쌓아 두지 않으면
        재생 이력을 다 되짚은 뒤 뒤로가기가 앨범 그리드로 건너뛴다."""
        monkeypatch.setattr(panel, "_open_playlist_payload", lambda payload, autoplay: None)
        self._enter_album_mode(panel, library_vm)
        panel._on_album_clicked("iu\x1fpalette")
        detail = _detail()
        album_vm.detail = detail

        panel._on_play_album(detail)
        panel._playlist_ctx = None          # 재생 이력을 모두 되짚은 상태
        panel._go_back()

        assert panel._nav_stack.currentIndex() == 2      # 앨범 상세로 복귀
        assert panel._album_mode is True
