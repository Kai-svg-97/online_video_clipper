"""상세화면 자막 탭 — 왜 비었는지 말하고, 줄을 누르면 그 시점으로 간다.

빈 목록을 그냥 보여 주면 "자막이 없는 영상"인지 "아직 안 받아온 영상"인지 "검색어가
안 맞은 것"인지 구분할 수 없다. 세 경우가 각각 다른 안내를 띄우는지 고정한다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from gui.panels.detail.subtitle_tab import SubtitleTab


def _line(start_ms, text):
    return SimpleNamespace(start_ms=start_ms, end_ms=start_ms + 1000, text=text)


@pytest.fixture
def tab(qtbot):
    w = SubtitleTab()
    qtbot.addWidget(w)
    return w


class TestEmptyStates:
    def test_색인_전에는_가져오기_버튼이_뜬다(self, tab):
        tab.set_lines([], indexed=False)
        assert tab._stack.currentIndex() == tab._PAGE_EMPTY
        assert tab._index_btn.isVisibleTo(tab)
        assert "아직 가져오지" in tab._empty_lbl.text()

    def test_검색_결과가_없으면_가져오기를_권하지_않는다(self, tab):
        """색인은 있는데 검색어가 안 맞은 것이다 — 가져오기는 엉뚱한 해결책이다."""
        tab.set_lines([], indexed=True)
        assert tab._stack.currentIndex() == tab._PAGE_EMPTY
        assert not tab._index_btn.isVisibleTo(tab)
        assert "자막 줄이 없습니다" in tab._empty_lbl.text()

    def test_자막이_아예_없는_영상은_그렇게_알린다(self, tab):
        tab.show_no_subtitle()
        assert "가져올 수 있는 자막이 없습니다" in tab._empty_lbl.text()

    def test_스트리밍_영상은_버튼을_숨기고_방법을_알린다(self, tab):
        """눌러도 아무 일이 없는 버튼을 남기면 고장처럼 보인다."""
        tab.show_streaming_notice()
        assert not tab._index_btn.isVisibleTo(tab)
        assert "카테고리에 담으면" in tab._empty_lbl.text()

    def test_가져오는_중에는_버튼이_잠긴다(self, tab):
        tab.set_busy(True)
        assert not tab._index_btn.isEnabled()
        assert "가져오는 중" in tab._empty_lbl.text()
        tab.set_busy(False)
        assert tab._index_btn.isEnabled()


class TestList:
    def test_줄과_타임코드를_보여준다(self, tab):
        tab.set_lines([_line(0, "첫 줄"), _line(65_000, "둘째 줄")], indexed=True)
        assert tab._stack.currentIndex() == tab._PAGE_LIST
        assert tab._list.item(0).text().startswith("0:00")
        assert "1:05" in tab._list.item(1).text()

    def test_한_시간이_넘으면_시_단위로_적는다(self, tab):
        tab.set_lines([_line(3_725_000, "늦은 줄")], indexed=True)
        assert tab._list.item(0).text().startswith("1:02:05")

    def test_줄_수를_표시한다(self, tab):
        tab.set_lines([_line(0, "a"), _line(1000, "b")], indexed=True)
        assert tab._count_lbl.text() == "2줄"

    def test_너무_많으면_잘라서_보여주고_전체_수를_알린다(self, tab):
        """색인 전체를 쏟으면 스크롤만 길어지고 못 찾는다."""
        from gui.panels.detail.subtitle_tab import _MAX_ROWS

        tab.set_lines([_line(i * 100, f"줄{i}") for i in range(_MAX_ROWS + 10)], indexed=True)
        assert tab._list.count() == _MAX_ROWS
        assert tab._count_lbl.text() == f"{_MAX_ROWS}/{_MAX_ROWS + 10}줄"

    def test_다시_채우면_이전_줄이_남지_않는다(self, tab):
        tab.set_lines([_line(0, "옛날")], indexed=True)
        tab.set_lines([_line(0, "새것")], indexed=True)
        assert [tab._list.item(i).text() for i in range(tab._list.count())][0].endswith("새것")


class TestInteraction:
    def test_줄을_누르면_그_시점을_요청한다(self, tab):
        tab.set_lines([_line(0, "첫"), _line(90_000, "찾던 말")], indexed=True)
        got: list[int] = []
        tab.seek_requested.connect(got.append)

        tab._on_row(tab._list.item(1))

        assert got == [90_000]

    def test_검색어_입력이_신호로_나간다(self, tab):
        got: list[str] = []
        tab.search_changed.connect(got.append)
        tab._search.setText("코끼리")
        assert got[-1] == "코끼리"

    def test_검색어_비우기는_신호를_내지_않는다(self, tab):
        """영상을 바꿀 때 쓰는 초기화라, 신호가 나가면 이전 영상 기준 재조회가 돈다."""
        got: list[str] = []
        tab._search.setText("코끼리")
        tab.search_changed.connect(got.append)
        tab.clear_search()
        assert got == []
        assert tab.search_text == ""

    def test_가져오기_버튼이_요청을_낸다(self, tab):
        got: list[int] = []
        tab.index_requested.connect(lambda: got.append(1))
        tab._index_btn.click()
        assert got == [1]


class TestTranscribeButton:
    """음성 인식은 **대안**이다 — 쓸 수 있을 때만, 쓸모 있는 자리에만 보인다."""

    def test_기본은_숨어_있다(self, tab):
        """받아 둔 파일이 있어야 소리를 읽을 수 있다."""
        tab.set_lines([], indexed=False)
        assert not tab._asr_btn.isVisibleTo(tab)

    def test_쓸_수_있으면_색인_전_화면에_뜬다(self, tab):
        tab.set_transcribe_available(True)
        tab.set_lines([], indexed=False)
        assert tab._asr_btn.isHidden() is False

    def test_자막이_아예_없는_영상에서_가장_쓸모있다(self, tab):
        tab.set_transcribe_available(True)
        tab.show_no_subtitle()
        assert tab._asr_btn.isHidden() is False

    def test_검색_결과가_없을_때는_숨는다(self, tab):
        """색인은 있다 — 음성 인식은 엉뚱한 해결책이다."""
        tab.set_transcribe_available(True)
        tab.set_lines([], indexed=True)
        assert tab._asr_btn.isHidden() is True

    def test_스트리밍_영상에서는_숨는다(self, tab):
        tab.set_transcribe_available(True)
        tab.show_streaming_notice()
        assert tab._asr_btn.isHidden() is True

    def test_버튼이_요청을_낸다(self, tab):
        got: list[int] = []
        tab.transcribe_requested.connect(lambda: got.append(1))
        tab._asr_btn.click()
        assert got == [1]

    def test_진행_문구를_보여준다(self, tab):
        tab.show_transcribing("소리를 듣는 중… 42%")
        assert "42%" in tab._empty_lbl.text()
        assert tab._asr_btn.isHidden() is True     # 도는 동안 다시 누를 수 없다
