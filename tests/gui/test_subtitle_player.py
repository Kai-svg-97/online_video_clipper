"""플레이어 자막 배선 검증 — 💬 버튼 활성 조건, 현재 줄 갱신, 오프셋 조작.

실제 미디어 없이 InlinePlayer의 자막 상태 API만 두드린다(재생은 하지 않는다).
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent

from gui.widgets.lyrics_overlay import LyricsCue, LyricsTrack
from gui.widgets.video_player import InlinePlayer


@pytest.fixture
def player(qapp_instance):
    p = InlinePlayer()
    p.resize(800, 450)
    yield p
    p.stop()
    p.deleteLater()


def _track() -> LyricsTrack:
    return LyricsTrack(
        [
            LyricsCue(start_ms=1000, original="one", translation="하나", line_index=0),
            LyricsCue(start_ms=5000, original="two", translation="둘", line_index=1),
        ]
    )


def _key(player, key: int) -> None:
    player.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


class TestSubtitleButtonEnablement:
    def test_가사가_없으면_비활성(self, player):
        assert player._bar._btn_cc.isEnabled() is False

    def test_싱크_가사를_주면_활성(self, player):
        player.set_lyrics(_track())
        assert player._bar._btn_cc.isEnabled() is True

    def test_빈_트랙은_비활성(self, player):
        player.set_lyrics(LyricsTrack([]))
        assert player._bar._btn_cc.isEnabled() is False

    def test_None을_주면_다시_비활성(self, player):
        player.set_lyrics(_track())
        player.set_lyrics(None)
        assert player._bar._btn_cc.isEnabled() is False


class TestCurrentLine:
    def test_재생_위치에_맞는_줄이_오버레이에_뜬다(self, player):
        player.set_lyrics(_track())
        player._apply_subtitle_position(1200)
        assert player._subtitle.current_text == ("one", "하나")
        player._apply_subtitle_position(6000)
        assert player._subtitle.current_text == ("two", "둘")

    def test_첫_줄_이전에는_비어_있다(self, player):
        player.set_lyrics(_track())
        player._apply_subtitle_position(500)
        assert player._subtitle.current_text == ("", "")

    def test_current_line_changed가_원본_줄_인덱스를_알린다(self, player):
        seen: list[int] = []
        player.current_line_changed.connect(seen.append)
        player.set_lyrics(_track())
        player._apply_subtitle_position(1200)
        player._apply_subtitle_position(6000)
        assert seen[-2:] == [0, 1]

    def test_같은_줄이면_신호를_반복하지_않는다(self, player):
        seen: list[int] = []
        player.set_lyrics(_track())
        player.current_line_changed.connect(seen.append)
        player._apply_subtitle_position(1200)
        player._apply_subtitle_position(1300)
        assert seen == [0]


class TestSubtitleToggle:
    def test_C_키로_자막을_끄고_켠다(self, player):
        player.set_lyrics(_track())
        player._apply_subtitle_position(1200)
        _key(player, Qt.Key.Key_C)
        assert player._subtitle_on is False
        _key(player, Qt.Key.Key_C)
        assert player._subtitle_on is True

    def test_가사가_없으면_C_키가_무시된다(self, player):
        _key(player, Qt.Key.Key_C)
        assert player._subtitle_on is True


class TestOffsetShortcuts:
    def test_대괄호_키로_오프셋을_조정한다(self, player):
        player.set_lyrics(_track())
        _key(player, Qt.Key.Key_BracketRight)
        assert player._track.offset_ms == 250
        _key(player, Qt.Key.Key_BracketLeft)
        _key(player, Qt.Key.Key_BracketLeft)
        assert player._track.offset_ms == -250

    def test_오프셋_변경이_신호로_나간다(self, player):
        seen: list[int] = []
        player.set_lyrics(_track())
        player.subtitle_offset_changed.connect(seen.append)
        _key(player, Qt.Key.Key_BracketRight)
        assert seen == [250]

    def test_가사가_없으면_오프셋_키가_무시된다(self, player):
        seen: list[int] = []
        player.subtitle_offset_changed.connect(seen.append)
        _key(player, Qt.Key.Key_BracketRight)
        assert seen == []

    def test_오프셋_조정이_표시_줄에_반영된다(self, player):
        player.set_lyrics(_track())
        player._apply_subtitle_position(1200)
        assert player._subtitle.current_text[0] == "one"
        player._nudge_subtitle_offset(2000)   # 자막을 2초 늦춤
        assert player._subtitle.current_text == ("", "")


class TestSyncHere:
    def test_현재_위치를_현재_줄에_맞춘다(self, player):
        player.set_lyrics(_track())
        # 재생 위치 3000ms에서 "지금 이 줄"을 맞추면 현재 줄(1000ms)이 3000ms로 이동
        player._sync_subtitle_here(3000)
        assert player._track.offset_ms == 2000

    def test_표시할_줄이_없으면_아무것도_하지_않는다(self, player):
        player.set_lyrics(_track())
        player._sync_subtitle_here(200)
        assert player._track.offset_ms == 0


class TestLoadResetsSubtitle:
    def test_load하면_자막이_초기화된다(self, player):
        player.set_lyrics(_track())
        player.load("https://youtu.be/other", [])
        assert player._track is None
        assert player._bar._btn_cc.isEnabled() is False
