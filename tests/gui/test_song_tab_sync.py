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

    def test_가사_재렌더_후_강조가_초기화된다(self, tab):
        tab.set_info(_synced_dto())
        tab.set_current_line(0)
        tab.set_info(_synced_dto())
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
