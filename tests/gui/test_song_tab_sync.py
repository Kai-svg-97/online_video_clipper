"""노래 탭의 싱크 UI 검증 — ⏱ 버튼 노출 조건, 현재 줄 하이라이트, 클릭 seek.

행 컨테이너(_LyricRow)로 통일했기 때문에 하이라이트·클릭 대상이 명확해졌다.
이 테스트가 그 구조를 고정한다.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from application.song.dtos import LyricsLineDTO, SongInfoDTO
from gui.panels.video_detail_panel import _LyricRow, _SongTab


@pytest.fixture
def tab(qapp_instance):
    w = _SongTab()
    w.resize(400, 600)
    return w


def _dto(lines) -> SongInfoDTO:
    return SongInfoDTO(
        video_id=uuid4(), is_song=True, artist="가수", song_title="제목",
        lyrics_lines=tuple(lines),
    )


def _synced_dto() -> SongInfoDTO:
    return _dto(
        [
            LyricsLineDTO(original="one", translation="하나", start_ms=1000),
            LyricsLineDTO(original="two", translation="둘", start_ms=5000),
        ]
    )


def _plain_dto() -> SongInfoDTO:
    return _dto([LyricsLineDTO(original="a"), LyricsLineDTO(original="b")])


def _gapped_dto() -> SongInfoDTO:
    """절 사이에 빈 줄(간주)이 낀 가사 — _render_lyrics가 spacer로 대체하고 _rows에서
    제외하므로, _rows의 위치와 lyrics_lines의 인덱스가 어긋난다(실제 LRC에 흔한 형태)."""
    return _dto(
        [
            LyricsLineDTO(original="one", start_ms=1000),
            LyricsLineDTO(original="", start_ms=3000),
            LyricsLineDTO(original="two", start_ms=5000),
        ]
    )


def _rows(tab) -> list:
    layout = tab._lyrics_layout
    return [
        layout.itemAt(i).widget()
        for i in range(layout.count())
        if isinstance(layout.itemAt(i).widget(), _LyricRow)
    ]


class TestRowContainers:
    def test_줄마다_행_위젯이_생긴다(self, tab):
        tab.set_info(_plain_dto())
        assert len(_rows(tab)) == 2

    def test_번역_병행_모드에서도_행_수는_같다(self, tab):
        tab.set_info(_synced_dto())
        assert len(_rows(tab)) == 2

    def test_오른쪽_배치_전환_후에도_행_수가_같다(self, tab):
        tab.set_info(_synced_dto())
        tab._toggle_lyrics_layout()
        assert len(_rows(tab)) == 2

    def test_가사_내용이_같으면_행_위젯을_재사용한다(self, tab):
        """헤더(가수 등)만 바뀌고 가사(원문·번역·타이밍)가 그대로면 _LyricRow를
        다시 만들지 않는다 — 위젯 재생성 생략이 이 최적화의 목적이다."""
        tab.set_info(_synced_dto())
        before = _rows(tab)
        same_lines_diff_artist = SongInfoDTO(
            video_id=uuid4(), is_song=True, artist="다른 가수", song_title="제목",
            lyrics_lines=_synced_dto().lyrics_lines,
        )
        tab.set_info(same_lines_diff_artist)
        assert _rows(tab) == before


class TestSyncedButton:
    def test_싱크_가사가_없으면_노출된다(self, tab):
        tab.set_info(_plain_dto())
        assert tab._synced_btn.isVisibleTo(tab) is True

    def test_싱크_가사가_있으면_숨긴다(self, tab):
        tab.set_info(_synced_dto())
        assert tab._synced_btn.isVisibleTo(tab) is False

    def test_클릭하면_신호가_나간다(self, tab):
        seen = []
        tab.synced_requested.connect(lambda: seen.append(True))
        tab.set_info(_plain_dto())
        tab._synced_btn.click()
        assert seen == [True]

    def test_스트리밍은_비활성(self, tab):
        tab.set_editable(False)
        tab.set_info(_plain_dto())
        assert tab._synced_btn.isEnabled() is False


class TestHighlight:
    def test_현재_줄만_강조된다(self, tab):
        tab.set_info(_synced_dto())
        tab.set_current_line(1)
        rows = _rows(tab)
        assert rows[0].is_current is False
        assert rows[1].is_current is True

    def test_None이면_강조를_해제한다(self, tab):
        tab.set_info(_synced_dto())
        tab.set_current_line(0)
        tab.set_current_line(None)
        assert all(not r.is_current for r in _rows(tab))

    def test_범위_밖_인덱스는_무시된다(self, tab):
        tab.set_info(_synced_dto())
        tab.set_current_line(99)   # 예외 없이 아무것도 강조하지 않는다
        assert all(not r.is_current for r in _rows(tab))

    def test_같은_가사로_다시_설정해도_강조가_유지된다(self, tab):
        """가사 내용(원문·번역·타이밍)이 그대로면 위젯을 다시 만들지 않으므로
        강조도 풀리지 않는다 — 재생 중 필드 편집을 저장해도(song_info_changed 재방출)
        강조가 사라지면 안 된다는 요구사항의 회귀 방지."""
        tab.set_info(_synced_dto())
        tab.set_current_line(0)
        tab.set_info(_synced_dto())
        rows = _rows(tab)
        assert rows[0].is_current is True

    def test_다른_가사로_바뀌면_강조가_초기화된다(self, tab):
        tab.set_info(_synced_dto())
        tab.set_current_line(0)
        other = _dto(
            [
                LyricsLineDTO(original="different", translation="다름", start_ms=2000),
                LyricsLineDTO(original="lines", translation="가사", start_ms=6000),
            ]
        )
        tab.set_info(other)
        assert all(not r.is_current for r in _rows(tab))

    def test_빈_줄이_있어도_line_index로_올바른_행을_강조한다(self, tab):
        """빈 줄(간주)은 spacer가 되어 _rows에 들어가지 않으므로 _rows[index] 같은
        위치 인덱싱으로 퇴행하면 엉뚱한 행(또는 범위 밖)이 강조된다. line_index
        조회라면 lyrics_lines 인덱스 2("two")가 _rows의 두 번째(위치 1) 행이다."""
        tab.set_info(_gapped_dto())
        rows = _rows(tab)
        assert len(rows) == 2  # 빈 줄은 행이 되지 않는다
        tab.set_current_line(2)
        assert rows[0].is_current is False
        assert rows[1].is_current is True
        assert rows[1].line_index == 2


class TestClickSeek:
    def test_시간_정보가_있는_줄은_클릭하면_seek_신호(self, tab):
        seen: list[int] = []
        tab.lyrics_seek_requested.connect(seen.append)
        tab.set_info(_synced_dto())
        _rows(tab)[1].clicked.emit()
        assert seen == [5000]

    def test_시간_정보가_없는_줄은_클릭해도_신호가_없다(self, tab):
        seen: list[int] = []
        tab.lyrics_seek_requested.connect(seen.append)
        tab.set_info(_plain_dto())
        _rows(tab)[0].clicked.emit()
        assert seen == []


class TestAutoScrollSuppression:
    def test_사용자_스크롤_중에는_자동_스크롤을_멈춘다(self, tab):
        tab.set_info(_synced_dto())
        tab._on_user_scroll()
        assert tab._autoscroll_suppressed() is True

    def test_기본값은_자동_스크롤_허용(self, tab):
        assert tab._autoscroll_suppressed() is False


class TestOffsetControl:
    """노래 탭 자체에서 가사 시작 시각(오프셋)을 조정하는 입력 필드.

    ⏱(싱크 가사 찾기)와 상호 배타적으로 노출된다 — 시간 정보가 없으면 조정할
    대상이 없으므로 검색 버튼을, 있으면 오프셋 컨트롤을 보여준다.
    """

    def _dto_with_offset(self, ms: int) -> SongInfoDTO:
        return SongInfoDTO(
            video_id=uuid4(), is_song=True,
            lyrics_lines=(
                LyricsLineDTO(original="one", start_ms=1000),
                LyricsLineDTO(original="two", start_ms=5000),
            ),
            lyrics_offset_ms=ms,
        )

    def test_싱크_가사가_없으면_숨긴다(self, tab):
        tab.set_info(_plain_dto())
        assert tab._offset_spin.isVisibleTo(tab) is False

    def test_싱크_가사가_있으면_노출된다(self, tab):
        tab.set_info(_synced_dto())
        assert tab._offset_spin.isVisibleTo(tab) is True

    def test_기존_오프셋_값이_초_단위로_표시된다(self, tab):
        tab.set_info(self._dto_with_offset(1500))
        assert tab._offset_spin.value() == pytest.approx(1.5)

    def test_음수_오프셋도_표시된다(self, tab):
        tab.set_info(self._dto_with_offset(-750))
        assert tab._offset_spin.value() == pytest.approx(-0.75)

    def test_값을_바꾸면_ms_단위로_신호가_나간다(self, tab):
        tab.set_info(self._dto_with_offset(0))
        seen: list[int] = []
        tab.offset_changed.connect(seen.append)
        tab._offset_spin.setValue(0.5)
        assert seen == [500]

    def test_set_offset_ms로_갱신하면_신호가_다시_나가지_않는다(self, tab):
        """플레이어 쪽에서 바뀐 값을 반영할 때 되돌아오는 신호로 루프가 생기면 안 된다."""
        tab.set_info(self._dto_with_offset(0))
        seen: list[int] = []
        tab.offset_changed.connect(seen.append)
        tab.set_offset_ms(1000)
        assert seen == []
        assert tab._offset_spin.value() == pytest.approx(1.0)

    def test_스트리밍은_비활성(self, tab):
        tab.set_editable(False)
        tab.set_info(self._dto_with_offset(0))
        assert tab._offset_spin.isEnabled() is False
