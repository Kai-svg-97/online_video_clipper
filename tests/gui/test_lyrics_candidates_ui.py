"""가사 후보 목록 UI 검증 — 조회중 표시, 도착 순서대로 채우기, 선택·적용 배선.

핵심 계약은 "느린 출처 하나 때문에 이미 확보한 후보를 못 보는 일이 없어야 한다"이다.
따라서 결과를 부분적으로 넣은 상태에서도 확보된 행은 선택·적용할 수 있어야 한다.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from PyQt6.QtCore import Qt

from application.song.dtos import LyricsCandidateDTO, SongInfoDTO
from gui.panels.video_detail_panel import _LyricsCandidateList, _SongTab


@pytest.fixture
def clist(qapp_instance):
    w = _LyricsCandidateList()
    w.resize(700, 300)
    return w


def _cand(source="LRCLIB", synced=True, artist="가수A") -> LyricsCandidateDTO:
    return LyricsCandidateDTO(
        source_name=source,
        artist=artist,
        title="제목A",
        first_line="첫 줄입니다",
        is_synced=synced,
        line_count=3,
        lines=("첫 줄입니다", "둘", "셋"),
        timings=(0, 1000, 2000) if synced else (),
        language="ko",
    )


def _col_text(w, row, col) -> str:
    item = w._table.item(row, col)
    return item.text() if item is not None else ""


class TestPendingRows:
    def test_출처마다_조회중_행을_먼저_만든다(self, clist):
        clist.begin(["LRCLIB", "지니", "벅스"])
        assert clist._table.rowCount() == 3
        assert _col_text(clist, 0, clist._COL_SOURCE) == "LRCLIB"
        assert _col_text(clist, 1, clist._COL_FIRST) == "조회중…"
        assert "0/3" in clist._status_lbl.text()

    def test_조회중_행은_선택할_수_없다(self, clist):
        clist.begin(["LRCLIB"])
        item = clist._table.item(0, clist._COL_SOURCE)
        assert not (item.flags() & Qt.ItemFlag.ItemIsSelectable)
        assert clist._apply_btn.isEnabled() is False

    def test_출처가_없으면_안내_문구를_띄운다(self, clist):
        clist.begin([])
        assert clist._table.rowCount() == 0
        assert "출처가 없습니다" in clist._status_lbl.text()


class TestIncrementalResults:
    def test_도착한_행만_채우고_나머지는_조회중으로_남는다(self, clist):
        clist.begin(["LRCLIB", "지니"])
        clist.add_result("LRCLIB", _cand())

        assert _col_text(clist, 0, clist._COL_ARTIST) == "가수A"
        assert _col_text(clist, 0, clist._COL_TITLE) == "제목A"
        assert "첫 줄입니다" in _col_text(clist, 0, clist._COL_FIRST)
        assert _col_text(clist, 0, clist._COL_SYNC) == "싱크"
        # 아직 조회 중인 출처는 그대로 남는다.
        assert _col_text(clist, 1, clist._COL_FIRST) == "조회중…"

    def test_한_출처의_여러_후보를_모두_행으로_보여준다(self, clist):
        """같은 제목·다른 가수 — 출처당 1행으로 접히면 고를 수가 없다."""
        clist.begin(["LRCLIB", "지니"])
        for name in ("가수1", "가수2", "가수3"):
            clist.add_result("LRCLIB", _cand(artist=name))

        assert clist._table.rowCount() == 4   # LRCLIB 3행 + 지니 조회중 1행
        assert [_col_text(clist, r, clist._COL_ARTIST) for r in range(3)] == [
            "가수1", "가수2", "가수3"
        ]
        # 행이 늘어도 출처 표기는 유지되고 순서가 섞이지 않는다.
        assert [_col_text(clist, r, clist._COL_SOURCE) for r in range(4)] == [
            "LRCLIB", "LRCLIB", "LRCLIB", "지니"
        ]

    def test_나중_출처_결과가_와도_고른_행이_유지된다(self, clist):
        clist.begin(["LRCLIB", "지니"])
        clist.add_result("LRCLIB", _cand(artist="가수1"))
        clist.add_result("LRCLIB", _cand(artist="가수2"))
        clist._table.selectRow(1)
        assert clist.selected_candidate().artist == "가수2"

        clist.add_result("지니", _cand(source="지니", artist="가수9"))
        assert clist.selected_candidate().artist == "가수2"

    def test_첫_유효_후보를_자동_선택해_바로_적용할_수_있다(self, clist):
        clist.begin(["LRCLIB", "지니"])
        clist.add_result("LRCLIB", _cand())
        assert clist.selected_candidate() is not None
        assert clist._apply_btn.isEnabled() is True

    def test_결과_없이_끝난_출처는_선택_불가로_남는다(self, clist):
        clist.begin(["LRCLIB", "지니"])
        clist.source_done("지니", 0)
        assert _col_text(clist, 1, clist._COL_FIRST) == "결과 없음"
        item = clist._table.item(1, clist._COL_SOURCE)
        assert not (item.flags() & Qt.ItemFlag.ItemIsSelectable)

    def test_정렬_근거를_툴팁에_담는다(self, clist):
        """열은 다섯 개로 유지하되, 왜 이 순서인지는 확인할 수 있어야 한다."""
        clist.begin(["Genius"])
        clist.add_result(
            "Genius",
            LyricsCandidateDTO(
                source_name="Genius", artist="가수A", title="제목A", first_line="첫 줄",
                line_count=3, popularity=1234567, duration_sec=213, lines=("첫 줄",),
            ),
        )
        tip = clist._table.item(0, clist._COL_TITLE).toolTip()
        assert "조회수 1,234,567" in tip
        assert "길이 3:33" in tip

    def test_싱크_없는_후보는_대시로_표기한다(self, clist):
        clist.begin(["지니"])
        clist.add_result("지니", _cand(source="지니", synced=False))
        assert _col_text(clist, 0, clist._COL_SYNC) == "—"

    def test_모르는_출처_결과는_무시한다(self, clist):
        """검색이 취소된 뒤 늦게 도착한 결과가 목록을 망가뜨리지 않아야 한다."""
        clist.begin(["LRCLIB"])
        clist.add_result("옛날 검색 출처", _cand())
        assert clist._table.rowCount() == 1
        assert _col_text(clist, 0, clist._COL_FIRST) == "조회중…"


class TestFinish:
    def test_끝나면_남은_조회중_행을_정리한다(self, clist):
        clist.begin(["LRCLIB", "지니"])
        clist.add_result("LRCLIB", _cand())
        clist.finish(1)   # 지니는 결과 통지 없이 끝남(취소·오류)
        assert _col_text(clist, 1, clist._COL_FIRST) == "결과 없음"
        assert "후보 1건" in clist._status_lbl.text()

    def test_후보가_없으면_다시_검색을_안내한다(self, clist):
        clist.begin(["LRCLIB"])
        clist.source_done("LRCLIB", 0)
        clist.finish(0)
        assert "찾지 못했습니다" in clist._status_lbl.text()


class TestChoose:
    def test_적용_버튼이_선택한_후보를_방출한다(self, clist):
        seen = []
        clist.chosen.connect(seen.append)
        clist.begin(["LRCLIB"])
        clist.add_result("LRCLIB", _cand())
        clist._apply_btn.click()
        assert len(seen) == 1
        assert seen[0].source_name == "LRCLIB"


class TestSongTabIntegration:
    """검색 버튼 → 후보 목록 전환 → 선택 방출까지 탭 수준 배선."""

    @pytest.fixture
    def tab(self, qapp_instance):
        w = _SongTab()
        w.resize(600, 500)
        return w

    def test_가사_검색_버튼은_후보_검색을_요청한다(self, tab):
        seen = []
        tab.candidates_requested.connect(lambda: seen.append(True))
        tab.set_info(
            SongInfoDTO(video_id=uuid4(), is_song=True, artist="가수", song_title="제목")
        )
        tab._lyrics_refresh_btn.click()
        assert seen == [True]

    def test_검색을_시작하면_후보_목록으로_전환한다(self, tab):
        tab.begin_candidates(["LRCLIB", "지니"])
        assert tab._lyrics_stack.currentIndex() == tab._STACK_CANDIDATES

    def test_검색_중_노래정보_갱신이_목록을_닫지_않는다(self, tab):
        """검색 도중 다른 저장(필드 편집 등)이 song_info_changed를 쏘아도 유지된다."""
        tab.begin_candidates(["LRCLIB"])
        tab.set_info(SongInfoDTO(video_id=uuid4(), is_song=True, artist="가수"))
        assert tab._lyrics_stack.currentIndex() == tab._STACK_CANDIDATES

    def test_후보를_고르면_목록을_닫고_신호를_올린다(self, tab):
        seen = []
        tab.candidate_chosen.connect(seen.append)
        tab.begin_candidates(["LRCLIB"])
        tab.add_candidate_result("LRCLIB", _cand())
        tab._candidates._apply_btn.click()

        assert len(seen) == 1
        assert seen[0].source_name == "LRCLIB"
        assert tab._lyrics_stack.currentIndex() == tab._STACK_VIEW

    def test_닫기_버튼은_가사_표시로_돌아간다(self, tab):
        tab.begin_candidates(["LRCLIB"])
        tab.close_candidates()
        assert tab._lyrics_stack.currentIndex() == tab._STACK_VIEW


class TestViewModelToWidgetChain:
    """SongViewModel(실제 QThread) → VideoDetailWidget → 노래 탭 표까지 전 구간.

    위젯 단위 테스트는 슬롯을 직접 부르므로, 신호 이름이 어긋나거나 워커 스레드에서
    온 결과가 표에 닿지 않는 실패를 잡지 못한다. LibraryPanel과 **같은 방식**으로
    연결해 실제로 행이 채워지는지 본다.
    """

    def _vm_and_widget(self, qapp_instance, video_id):
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        from application.song.commands import SearchLyricsCandidatesHandler
        from domain.song.ports import LyricsResult
        from gui.panels.video_detail_panel import VideoDetailWidget
        from gui.view_models.song_vm import SongViewModel

        class _P:
            """같은 제목의 두 가수 곡을 돌려주는 제공자."""

            key = "p"

            def search(self, artist, title, duration_sec=None, limit=10):
                return [
                    LyricsResult(
                        lines=["첫 줄", "둘째"], timings=[0, 2000], language="ko",
                        source_url="http://x", artist="가수A", title="제목A",
                    ),
                    LyricsResult(
                        lines=["다른 첫 줄"], language="ko",
                        source_url="http://y", artist="가수B", title="제목A",
                    ),
                ]

        song_repo = MagicMock()
        song_repo.list_lyrics_sources.return_value = [
            SimpleNamespace(provider_key="p", enabled=True, name="LRCLIB"),
            SimpleNamespace(provider_key="없음", enabled=True, name="비활성"),
        ]
        song_repo.get.return_value = None
        video_repo = MagicMock()
        video_repo.get_by_id.return_value = SimpleNamespace(
            video=SimpleNamespace(
                title="가수A - 제목A",
                channel=SimpleNamespace(name="Chan"),
                duration=SimpleNamespace(seconds=180),
            )
        )
        vm = SongViewModel(
            get_song_info=MagicMock(**{"handle.return_value": None}),
            fetch_song=MagicMock(),
            search_candidates=SearchLyricsCandidatesHandler(
                song_repo, video_repo, lyrics_providers={"p": _P()}
            ),
            apply_candidate=MagicMock(),
            set_flag=MagicMock(),
            update_field=MagicMock(),
            update_lyrics=MagicMock(),
            translate_lyrics=MagicMock(),
            set_lyrics_offset=MagicMock(),
            list_sources=MagicMock(**{"handle.return_value": []}),
            add_source=MagicMock(),
            update_source=MagicMock(),
            delete_source=MagicMock(),
            reorder_sources=MagicMock(),
        )
        widget = VideoDetailWidget()
        widget._detail = SimpleNamespace(id=video_id)
        # LibraryPanel과 동일한 배선
        widget.song_candidates_requested.connect(vm.search_lyrics_candidates)
        vm.candidates_started.connect(widget.song_candidates_started)
        vm.candidate_ready.connect(widget.song_candidate_ready)
        vm.candidate_source_done.connect(widget.song_candidate_source_done)
        vm.candidates_finished.connect(widget.song_candidates_finished)
        return vm, widget

    def test_검색_요청부터_표_채우기까지_이어진다(self, qapp_instance):
        import time

        video_id = uuid4()
        vm, widget = self._vm_and_widget(qapp_instance, video_id)
        done = []
        vm.candidates_finished.connect(lambda *_a: done.append(True))

        widget._song_tab._lyrics_refresh_btn.click()

        # 제공자 구현이 없는 출처는 목록에서 빠지므로 행은 1개다(조회중 잔류 방지).
        table = widget._song_tab._candidates._table
        assert table.rowCount() == 1
        assert table.item(0, 0).text() == "LRCLIB"

        deadline = time.monotonic() + 5
        while not done and time.monotonic() < deadline:
            qapp_instance.processEvents()
            time.sleep(0.01)
        qapp_instance.processEvents()

        assert done, "후보 검색이 끝나지 않았다"
        # 같은 제목의 두 가수 곡이 각각 한 행으로 올라온다.
        assert table.rowCount() == 2
        assert [table.item(r, 1).text() for r in range(2)] == ["가수A", "가수B"]
        assert table.item(0, 2).text() == "제목A"
        assert "첫 줄" in table.item(0, 3).text()
        assert table.item(0, 4).text() == "싱크"
        assert table.item(1, 4).text() == "—"
        vm.shutdown()
        widget.deleteLater()

    def test_다른_영상_상세로_넘어가면_결과를_버린다(self, qapp_instance):
        video_id = uuid4()
        vm, widget = self._vm_and_widget(qapp_instance, video_id)
        widget._song_tab.begin_candidates(["LRCLIB"])
        # 상세가 다른 영상으로 바뀐 뒤 늦게 도착한 결과
        widget._detail = type(widget._detail)(id=uuid4())
        widget.song_candidate_ready(video_id, "LRCLIB", _cand())

        table = widget._song_tab._candidates._table
        assert table.item(0, 3).text() == "조회중…"
        vm.shutdown()
        widget.deleteLater()
