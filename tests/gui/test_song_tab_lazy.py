"""노래 탭 지연 렌더 — 보이지 않는 가사 행을 만들지 않는다(성능 배치 7, A9).

회귀 배경: 상세를 열 때마다 `set_info`가 가사 63줄의 행 위젯(최대 190개)을 즉시
만들어 131ms를 썼다 — 사용자가 노래 탭을 열지 않아도 치르는 비용이었다. 또
`load()`가 `set_info(None)`로 렌더 키를 지워, 같은 영상을 다시 열면 같은 가사를
전부 다시 만들었다.

지연 판단은 `_SongTab`이 아니라 **`VideoDetailWidget`**(현재 탭이 노래 탭인가)에 둔다.
`_SongTab` 단독 위젯은 `isVisible()`이 거짓이라, 거기서 미루면
`test_song_tab_sync.py`의 계약이 깨진다.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from PyQt6.QtWidgets import QApplication, QLabel

from application.library.dtos import VideoDetailDTO
from application.song.dtos import LyricsLineDTO, SongInfoDTO
from gui.panels.video_detail_panel import VideoDetailWidget


def _detail() -> VideoDetailDTO:
    return VideoDetailDTO(
        id=uuid4(),
        url="https://www.youtube.com/watch?v=lazysong001",
        title="노래",
        channel_name="채널",
        channel_url="",
        thumbnail_path="",
        duration_sec=200,
        published_at=None,
        view_count=None,
        favorite=False,
        watched=False,
        category_id=None,
        notes="",
        description="",
    )


def _song(prefix: str = "line", n: int = 63) -> SongInfoDTO:
    return SongInfoDTO(
        video_id=uuid4(),
        is_song=True,
        artist="가수",
        song_title="제목",
        lyrics_lines=tuple(
            LyricsLineDTO(original=f"{prefix} {i}", translation=f"번역 {i}", start_ms=i * 1000)
            for i in range(n)
        ),
    )


def _flush() -> None:
    QApplication.processEvents()


@pytest.fixture
def w(qtbot):
    widget = VideoDetailWidget()
    qtbot.addWidget(widget)
    widget.resize(900, 700)
    return widget


def _open_song_tab(w: VideoDetailWidget) -> None:
    w._tabs.setCurrentIndex(w._TAB_SONG)
    _flush()


class TestLazyRender:
    def test_노래_탭이_아니면_가사_행을_만들지_않는다(self, w):
        assert w._tabs.currentIndex() != w._TAB_SONG

        w.load(_detail(), {})
        w.set_song_info(_song())
        _flush()

        assert len(w._song_tab._rows) == 0, "보이지 않는 탭에서 가사 행을 만들었다"

    def test_탭을_열면_그때_만든다(self, qtbot, w):
        w.load(_detail(), {})
        w.set_song_info(_song())

        _open_song_tab(w)

        qtbot.waitUntil(lambda: len(w._song_tab._rows) == 63, timeout=2000)

    def test_정보가_없으면_탭을_열어도_빈_상태_라벨이_보이고_예외가_없다(self, qtbot, w):
        w.load(_detail(), {})
        w.set_song_info(None)

        _open_song_tab(w)

        layout = w._song_tab._lyrics_layout
        labels = [
            layout.itemAt(i).widget()
            for i in range(layout.count())
            if isinstance(layout.itemAt(i).widget(), QLabel)
        ]
        assert len(w._song_tab._rows) == 0
        assert any(lbl.text().strip() for lbl in labels), "빈 상태 안내 라벨이 없다"

    def test_숨은_동안_글자_배율을_바꿔도_행을_억지로_만들지_않는다(self, w):
        w.load(_detail(), {})
        w.set_song_info(_song())

        w._set_text_scale(1.2)
        _flush()

        assert len(w._song_tab._rows) == 0


class TestRowReuse:
    def test_같은_영상을_다시_열면_행_위젯을_재사용한다(self, qtbot, w):
        _open_song_tab(w)
        detail, dto = _detail(), _song()
        w.load(detail, {})
        w.set_song_info(dto)
        qtbot.waitUntil(lambda: len(w._song_tab._rows) == 63, timeout=2000)
        ids = [id(r) for r in w._song_tab._rows]

        w.load(detail, {})
        w.set_song_info(dto)
        _flush()

        assert [id(r) for r in w._song_tab._rows] == ids, (
            "load()의 set_info(None)이 렌더 키를 지워 가사 행을 전부 다시 만들었다"
        )

    def test_다른_가사면_다시_만든다(self, qtbot, w):
        _open_song_tab(w)
        detail = _detail()
        w.load(detail, {})
        w.set_song_info(_song("가"))
        qtbot.waitUntil(lambda: len(w._song_tab._rows) == 63, timeout=2000)
        old_rows = list(w._song_tab._rows)   # 참조를 쥐어 id가 재사용되지 않게 한다

        w.load(detail, {})
        w.set_song_info(_song("나"))
        _flush()

        assert len(w._song_tab._rows) == 63
        assert all(new is not old for new in w._song_tab._rows for old in old_rows)


class TestDeferredHighlight:
    def test_지연_중_강조_요청은_안전하고_탭을_열면_그_줄이_강조된다(self, qtbot, w):
        w.load(_detail(), {})
        w.set_song_info(_song())
        assert len(w._song_tab._rows) == 0

        w._song_tab.set_current_line(10)   # 행이 없어도 예외가 없어야 한다

        _open_song_tab(w)

        qtbot.waitUntil(lambda: len(w._song_tab._rows) == 63, timeout=2000)
        current = w._song_tab._current_row
        assert current is not None, "탭을 열었는데 강조가 없다 — 재생 줄이 유실됐다"
        assert current.line_index == 10
