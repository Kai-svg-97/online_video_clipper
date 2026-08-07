"""플레이어 자막 배선 검증 — 💬 버튼 활성 조건, 현재 줄 갱신, 오프셋 조작.

실제 미디어 없이 InlinePlayer의 자막 상태 API만 두드린다(재생은 하지 않는다).
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget

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


def _fake_position(player, ms: int) -> None:
    """재생 위치를 고정한다.

    분리 창 진입/이탈 코드는 ``self._player.position()``을 읽는데, 미디어가 없으면 항상 0이라
    "첫 줄 이전"이 되어 자막 전달을 검증할 수 없다. 실제 재생과 같은 일관된 상태를 만들려고
    위치만 고정한다(재생은 하지 않는다).
    """
    player._player.position = lambda: ms


class TestSubtitleButtonEnablement:
    def test_가사가_없으면_비활성(self, player):
        assert player._bar._btn_cc.isEnabled() is False

    def test_가사가_붙기_전_글리프가_상태와_맞는다(self, player):
        # 버튼을 만들 때의 텍스트("💬")가 아니라 '비활성' 상태에 맞는 글리프여야 한다.
        assert player._bar._btn_cc.text() == "🗨"

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

    def test_새_가사의_현재_줄이_없으면_해제_신호가_나간다(self, player):
        # 이전 곡의 3번째 줄을 강조하던 소비자(노래 탭)가 해제 신호를 받아야 한다.
        # set_lyrics가 _current_line_index를 -1로 두면 새 판정도 -1이라 조용히 넘어간다.
        _fake_position(player, 1200)
        player.set_lyrics(_track())
        seen: list[int] = []
        player.current_line_changed.connect(seen.append)
        later = LyricsTrack([LyricsCue(start_ms=5000, original="late", line_index=0)])
        player.set_lyrics(later)
        assert seen == [-1]

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


class TestInlineOverlayVisible:
    def test_인라인_오버레이가_보인다(self, player):
        # 분리 창과 달리 인라인 오버레이만 명시적 show() 없이 _VideoArea 자식으로 얹힌다.
        assert player._subtitle.isVisibleTo(player) is True


# ── 분리 창(PiP·전체화면) ─────────────────────────────────────────
# CLAUDE.md 경고: 분리 창의 컨트롤바 신호는 외부(InlinePlayer)가 배선하지 않으면
# 버튼이 조용히 죽는다. 아래 테스트가 자막 4개 신호의 배선을 실제 동작으로 고정한다.
# 창 정리는 player 픽스처의 stop()이 _exit_pip/_exit_fullscreen을 호출해 처리하므로
# 도중에 실패해도 창이 다음 테스트로 새지 않는다.

class TestPipSubtitleWiring:
    def test_진입시_현재_줄과_상태가_반영된다(self, player):
        _fake_position(player, 1200)
        player.set_lyrics(_track())
        player._enter_pip()
        bar = player._pip_win.bar
        assert bar._btn_cc.isEnabled() is True
        assert bar._subtitle_on is True
        assert bar._subtitle_offset_ms == 0
        assert player._pip_win.subtitle.current_text == ("one", "하나")

    def test_진입시_오프셋이_그대로_전달된다(self, player):
        _fake_position(player, 1200)
        track = _track()
        track.offset_ms = 500
        player.set_lyrics(track)
        player._enter_pip()
        assert player._pip_win.bar._subtitle_offset_ms == 500

    def test_자막을_끈_채_진입하면_꺼진_상태로_열린다(self, player):
        player.set_lyrics(_track())
        player.set_subtitle_enabled(False)
        player._enter_pip()
        assert player._pip_win.bar._subtitle_on is False
        assert player._pip_win.bar._btn_cc.text() == "🗨"
        assert player._pip_win.subtitle._visible_text is False

    def test_바에서_토글하면_인라인까지_반영된다(self, player):
        player.set_lyrics(_track())
        player._enter_pip()
        player._pip_win.bar.subtitle_toggled.emit(False)
        assert player._subtitle_on is False
        assert player._bar._btn_cc.text() == "🗨"

    def test_바에서_오프셋을_조정할_수_있다(self, player):
        player.set_lyrics(_track())
        player._enter_pip()
        player._pip_win.bar.subtitle_offset_nudged.emit(250)
        assert player._track.offset_ms == 250

    def test_바에서_이_줄에_맞춤을_할_수_있다(self, player):
        _fake_position(player, 3000)
        player.set_lyrics(_track())
        player._enter_pip()
        player._pip_win.bar.subtitle_sync_here.emit()
        assert player._track.offset_ms == 2000

    def test_바에서_초기화할_수_있다(self, player):
        player.set_lyrics(_track())
        player._nudge_subtitle_offset(250)
        player._enter_pip()
        player._pip_win.bar.subtitle_offset_reset.emit()
        assert player._track.offset_ms == 0

    def test_열려_있는_동안_set_lyrics가_반영된다(self, player):
        player._enter_pip()
        assert player._pip_win.bar._btn_cc.isEnabled() is False
        player.set_lyrics(_track())
        assert player._pip_win.bar._btn_cc.isEnabled() is True

    def test_닫으면_인라인이_현재_줄을_되찾는다(self, player):
        _fake_position(player, 1200)
        player.set_lyrics(_track())
        player._enter_pip()
        player._exit_pip()
        assert player._pip_win is None
        assert player._subtitle.current_text == ("one", "하나")


class TestFullscreenSubtitleWiring:
    def test_진입시_현재_줄과_상태가_반영된다(self, player):
        _fake_position(player, 1200)
        player.set_lyrics(_track())
        player._enter_fullscreen()
        bar = player._fs_win.bar
        assert bar._btn_cc.isEnabled() is True
        assert bar._subtitle_on is True
        assert bar._subtitle_offset_ms == 0
        assert player._fs_win.subtitle.current_text == ("one", "하나")

    def test_진입시_오프셋이_그대로_전달된다(self, player):
        _fake_position(player, 1200)
        track = _track()
        track.offset_ms = 500
        player.set_lyrics(track)
        player._enter_fullscreen()
        assert player._fs_win.bar._subtitle_offset_ms == 500

    def test_자막을_끈_채_진입하면_꺼진_상태로_열린다(self, player):
        player.set_lyrics(_track())
        player.set_subtitle_enabled(False)
        player._enter_fullscreen()
        assert player._fs_win.bar._subtitle_on is False
        assert player._fs_win.bar._btn_cc.text() == "🗨"
        assert player._fs_win.subtitle._visible_text is False

    def test_바에서_토글하면_인라인까지_반영된다(self, player):
        player.set_lyrics(_track())
        player._enter_fullscreen()
        player._fs_win.bar.subtitle_toggled.emit(False)
        assert player._subtitle_on is False
        assert player._bar._btn_cc.text() == "🗨"

    def test_바에서_오프셋을_조정할_수_있다(self, player):
        player.set_lyrics(_track())
        player._enter_fullscreen()
        player._fs_win.bar.subtitle_offset_nudged.emit(-250)
        assert player._track.offset_ms == -250

    def test_바에서_이_줄에_맞춤을_할_수_있다(self, player):
        _fake_position(player, 3000)
        player.set_lyrics(_track())
        player._enter_fullscreen()
        player._fs_win.bar.subtitle_sync_here.emit()
        assert player._track.offset_ms == 2000

    def test_바에서_초기화할_수_있다(self, player):
        player.set_lyrics(_track())
        player._nudge_subtitle_offset(250)
        player._enter_fullscreen()
        player._fs_win.bar.subtitle_offset_reset.emit()
        assert player._track.offset_ms == 0

    def test_열려_있는_동안_set_lyrics가_반영된다(self, player):
        player._enter_fullscreen()
        assert player._fs_win.bar._btn_cc.isEnabled() is False
        player.set_lyrics(_track())
        assert player._fs_win.bar._btn_cc.isEnabled() is True

    def test_닫으면_인라인이_현재_줄을_되찾는다(self, player):
        _fake_position(player, 1200)
        player.set_lyrics(_track())
        player._enter_fullscreen()
        player._exit_fullscreen()
        assert player._fs_win is None
        assert player._subtitle.current_text == ("one", "하나")


class TestShortcutReachability:
    """단축키가 **실제 키 입력**으로 핸들러까지 도달하는지 본다.

    이 파일의 다른 테스트는 `player.keyPressEvent(...)`를 직접 호출하므로 "핸들러가
    올바른가"만 검증한다. 그것만으로는 포커스 배선이 끊겨도(=사용자가 아무리 눌러도
    안 먹어도) 통과한다. `_VideoView`와 컨트롤바는 일부러 포커스를 안 잡고
    (`NoFocus`/`TabFocus`) InlinePlayer(`StrongFocus`)가 대신 받는 구조라, 이 위임이
    깨지면 자막 단축키 C/[/]/\\ 가 전부 죽는다. 그래서 도달성 자체를 고정한다.
    """

    @pytest.fixture
    def host(self, qapp_instance):
        # 상세화면처럼 플레이어 밖에도 포커스 대상이 있는 창을 만든다.
        w = QWidget()
        lay = QVBoxLayout(w)
        edit = QLineEdit()
        p = InlinePlayer()
        p.setMinimumSize(640, 360)
        lay.addWidget(edit)
        lay.addWidget(p)
        w.resize(700, 500)
        w.show()
        QTest.qWaitForWindowExposed(w)
        yield p, edit
        p.stop()
        w.hide()
        w.deleteLater()

    def _nudges(self, player) -> list[int]:
        seen: list[int] = []
        player.subtitle_offset_changed.connect(seen.append)
        return seen

    def test_영상_클릭_후_괄호키가_오프셋을_바꾼다(self, host):
        player, edit = host
        player.set_lyrics(_track())
        seen = self._nudges(player)
        edit.setFocus()
        QTest.mouseClick(
            player._video_view.viewport(), Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier, QPoint(200, 100),
        )
        assert QApplication.focusWidget() is player
        QTest.keyClick(player, Qt.Key.Key_BracketRight)
        assert seen == [250]

    def test_컨트롤바_버튼_클릭_후에도_괄호키가_동작한다(self, host):
        # 버튼은 TabFocus라 자신은 포커스를 안 갖지만, 클릭이 InlinePlayer로 올라가야 한다.
        player, edit = host
        player.set_lyrics(_track())
        seen = self._nudges(player)
        edit.setFocus()
        QTest.mouseClick(player._bar._btn_play, Qt.MouseButton.LeftButton)
        assert QApplication.focusWidget() is player
        QTest.keyClick(player, Qt.Key.Key_BracketRight)
        assert seen == [250]

    def test_플레이어_밖에_포커스가_있으면_도달하지_않는다(self, host):
        # 경계 확인: 검색창 등에 포커스가 있으면 ']'는 그 위젯의 입력이다.
        player, edit = host
        player.set_lyrics(_track())
        seen = self._nudges(player)
        edit.setFocus()
        QTest.keyClick(edit, Qt.Key.Key_BracketRight)
        assert seen == []
        assert edit.text() == "]"
