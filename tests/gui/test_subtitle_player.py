"""플레이어 자막 배선 검증 — 💬 버튼 활성 조건, 현재 줄 갱신, 오프셋 조작.

실제 미디어 없이 InlinePlayer의 자막 상태 API만 두드린다(재생은 하지 않는다).
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QKeyEvent, QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget

from gui.widgets.lyrics_overlay import LyricsCue, LyricsOverlay, LyricsTrack
from gui.widgets.video_player import InlinePlayer


@pytest.fixture(autouse=True)
def isolated_subtitle_settings(monkeypatch):
    """이 모듈의 어떤 테스트도 실사용 ``data/config.yaml`` 을 건드리지 않게 한다.

    `_nudge_*` 는 500ms 디바운스 타이머를 걸고, 타이머가 살아남아 만료되면
    `settings.save_setting` 이 **실제 설정 파일**에 값을 쓴다. 실제로 연속 실행마다
    `subtitle_font_scale` 이 1.77 → 1.87 → 1.97 로 누적됐고, 오염된 값을 다음 실행이
    시작값으로 읽어 5건이 깨졌다. 저장을 무력화하고 시작값도 기본값으로 고정한다
    (설정 파일의 실제 상태와 무관하게 결정적으로 돌도록).
    """
    import config.settings as settings

    monkeypatch.setattr(settings, "save_setting", lambda *_a, **_k: None)
    monkeypatch.setattr(settings, "SUBTITLE_FONT_SCALE", LyricsOverlay.FONT_SCALE_DEFAULT)
    monkeypatch.setattr(settings, "SUBTITLE_BOTTOM_RATIO", LyricsOverlay.BOTTOM_RATIO_DEFAULT)


@pytest.fixture
def player(qapp_instance, isolated_subtitle_settings):
    # isolated_subtitle_settings 를 명시적으로 요구한다 — InlinePlayer 는 생성 시점에
    # 설정값을 읽으므로 픽스처 순서가 뒤바뀌면 격리가 무의미해진다.
    p = InlinePlayer()
    p.resize(800, 450)
    yield p
    p.stop()
    # 남은 타이머가 테스트 종료 후(다른 모듈의 이벤트 루프에서) 발화하지 않게 정리한다.
    p._prefs_save_timer.stop()
    p._transient_timer.stop()
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

    def test_쉼표_마침표_키도_대괄호와_동일하게_동작한다(self, player):
        """`,`/`.`는 `[`/`]`의 별칭 — 편집 프로그램에서 익숙한 키 배치를 추가로 지원."""
        player.set_lyrics(_track())
        _key(player, Qt.Key.Key_Period)
        assert player._track.offset_ms == 250
        _key(player, Qt.Key.Key_Comma)
        _key(player, Qt.Key.Key_Comma)
        assert player._track.offset_ms == -250

    def test_가사가_없으면_쉼표_마침표_키도_무시된다(self, player):
        seen: list[int] = []
        player.subtitle_offset_changed.connect(seen.append)
        _key(player, Qt.Key.Key_Period)
        _key(player, Qt.Key.Key_Comma)
        assert seen == []

    def test_공개_setter로_절대값을_지정할_수_있다(self, player):
        """노래 탭 등 플레이어 밖에서 절대 오프셋을 지정하는 공개 API."""
        player.set_lyrics(_track())
        seen: list[int] = []
        player.subtitle_offset_changed.connect(seen.append)
        player.set_subtitle_offset_ms(1500)
        assert player._track.offset_ms == 1500
        assert seen == [1500]

    def test_트랙이_없으면_공개_setter는_아무일도_하지_않는다(self, player):
        player.set_subtitle_offset_ms(1500)   # 예외 없이 무시


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

    def test_영상_클릭_후_마침표키도_오프셋을_바꾼다(self, host):
        player, edit = host
        player.set_lyrics(_track())
        seen = self._nudges(player)
        edit.setFocus()
        QTest.mouseClick(
            player._video_view.viewport(), Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier, QPoint(200, 100),
        )
        assert QApplication.focusWidget() is player
        QTest.keyClick(player, Qt.Key.Key_Period)
        assert seen == [250]


def _key_mod(player, key: int, mods) -> None:
    player.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, mods))


class TestSubtitleScaleAndPosition:
    def test_ctrl_위아래가_크기를_바꾼다(self, player):
        player.set_lyrics(_track())
        before = player._subtitle.font_scale
        _key_mod(player, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
        assert player._subtitle.font_scale == pytest.approx(before + 0.1)
        _key_mod(player, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
        assert player._subtitle.font_scale == pytest.approx(before)

    def test_맨_위아래는_여전히_볼륨이다(self, player):
        """회귀: 수정키 분기를 넣다가 볼륨 단축키를 깨뜨리기 쉽다."""
        player.set_lyrics(_track())
        before_scale = player._subtitle.font_scale
        vol_before = player._audio.volume()
        _key_mod(player, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
        assert player._subtitle.font_scale == before_scale
        assert player._audio.volume() != pytest.approx(vol_before)

    def test_ctrl_shift_위아래가_위치를_바꾼다(self, player):
        """회귀: Ctrl+Shift 도 Ctrl 비트가 켜져 있어 분기 순서가 틀리면 크기가 바뀐다."""
        player.set_lyrics(_track())
        scale_before = player._subtitle.font_scale
        pos_before = player._subtitle.bottom_ratio
        mods = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        _key_mod(player, Qt.Key.Key_Up, mods)
        assert player._subtitle.bottom_ratio == pytest.approx(pos_before + 0.02)
        assert player._subtitle.font_scale == scale_before

    def test_분리창에도_현재값이_반영된다(self, player):
        player.set_lyrics(_track())
        _key_mod(player, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
        player._enter_fullscreen()
        assert player._fs_win.subtitle.font_scale == pytest.approx(
            player._subtitle.font_scale
        )
        player._exit_fullscreen()


def _wheel(widget, up: bool, mods) -> None:
    """실제 QWheelEvent 를 위젯에 보낸다(핸들러 직접 호출이 아니다)."""
    # PyQt6 시그니처는 globalPos 도 QPointF 를 요구한다(mapToGlobal 은 QPoint 를 반환).
    ev = QWheelEvent(
        QPointF(10, 10), QPointF(widget.mapToGlobal(QPoint(10, 10))),
        QPoint(0, 0), QPoint(0, 120 if up else -120),
        Qt.MouseButton.NoButton, mods, Qt.ScrollPhase.NoScrollPhase, False,
    )
    QApplication.sendEvent(widget, ev)


class TestSubtitleWheel:
    def test_ctrl_휠이_크기를_바꾼다(self, player):
        player.set_lyrics(_track())
        before = player._subtitle.font_scale
        _wheel(player, True, Qt.KeyboardModifier.ControlModifier)
        assert player._subtitle.font_scale == pytest.approx(before + 0.1)

    def test_ctrl_shift_휠이_위치를_바꾼다(self, player):
        player.set_lyrics(_track())
        before = player._subtitle.bottom_ratio
        mods = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        _wheel(player, True, mods)
        assert player._subtitle.bottom_ratio == pytest.approx(before + 0.02)

    def test_영상_위에서_굴린_휠이_플레이어까지_도달한다(self, player):
        """회귀: QGraphicsView 가 휠을 삼키면 핸들러가 멀쩡해도 조용히 죽는다."""
        player.resize(800, 450)
        player.show()
        QTest.qWaitForWindowExposed(player)
        player.set_lyrics(_track())
        before = player._subtitle.font_scale
        _wheel(player._video_view.viewport(), True, Qt.KeyboardModifier.ControlModifier)
        assert player._subtitle.font_scale == pytest.approx(before + 0.1)
        player.hide()

    def test_전체화면_영상_위에서_굴린_휠도_도달한다(self, player):
        """회귀: _FullscreenWindow 는 자체 _VideoView(_vw)를 갖고 있어 InlinePlayer의
        viewport 필터 분기만으로는 안 걸린다 — _fs_win._vw.viewport() 도 같은 함정에
        빠진다(Ctrl+휠로 자막 크기를 키우는 게 가장 중요한 화면인데 조용히 죽었었다)."""
        player.resize(800, 450)
        player.show()
        QTest.qWaitForWindowExposed(player)
        player.set_lyrics(_track())
        player._enter_fullscreen()
        before = player._subtitle.font_scale
        _wheel(player._fs_win._vw.viewport(), True, Qt.KeyboardModifier.ControlModifier)
        assert player._subtitle.font_scale == pytest.approx(before + 0.1)
        player._exit_fullscreen()
        player.hide()

    def test_pip_영상_위에서_굴린_휠도_도달한다(self, player):
        """회귀: PiP 는 `_vw` 의 WA_TransparentForMouseEvents(창 드래그용) 덕분에
        히트테스트가 viewport 를 건너뛰어 '우연히' 동작했다. viewport 로 곧장 온 휠에는
        폴백이 없어(델타 0.0) 드래그 구현을 바꾸면 전체화면과 똑같이 조용히 죽는다."""
        player.resize(800, 450)
        player.show()
        QTest.qWaitForWindowExposed(player)
        player.set_lyrics(_track())
        player._enter_pip()
        before = player._subtitle.font_scale
        _wheel(player._pip_win._vw.viewport(), True, Qt.KeyboardModifier.ControlModifier)
        assert player._subtitle.font_scale == pytest.approx(before + 0.1)
        player._exit_pip()
        player.hide()


class TestSubtitlePrefsPersistence:
    def test_연속_조절이_한_번만_저장된다(self, player, monkeypatch):
        """휠은 이벤트가 쏟아지므로 500ms 디바운스 후 1회만 기록한다."""
        from PyQt6.QtTest import QTest
        import config.settings as settings

        saved: list[tuple] = []
        monkeypatch.setattr(settings, "save_setting", lambda k, v: saved.append((k, v)))

        player.set_lyrics(_track())
        for _ in range(5):
            player._nudge_subtitle_scale(0.1)
        assert saved == []                 # 아직 디바운스 중
        QTest.qWait(700)
        keys = [k for k, _ in saved]
        assert keys.count("subtitle_font_scale") == 1

    def test_초기화가_기본값으로_되돌린다(self, player):
        player.set_lyrics(_track())
        player._nudge_subtitle_scale(0.5)
        player._nudge_subtitle_bottom(0.1)
        player._reset_subtitle_prefs()
        assert player._subtitle.font_scale == LyricsOverlay.FONT_SCALE_DEFAULT
        assert player._subtitle.bottom_ratio == LyricsOverlay.BOTTOM_RATIO_DEFAULT

    def test_저장값은_소수점_둘째_자리로_자른다(self, player, monkeypatch):
        """회귀: 0.1 누적으로 생긴 1.9700000000000002 가 config.yaml 에 그대로 박혔다."""
        import config.settings as settings

        saved: dict = {}
        monkeypatch.setattr(settings, "save_setting", lambda k, v: saved.__setitem__(k, v))
        player._subtitle_font_scale = 1.9700000000000002
        player._subtitle_bottom_ratio = 0.30000000000000004
        player._flush_subtitle_prefs()
        assert saved["subtitle_font_scale"] == 1.97
        assert saved["subtitle_bottom_ratio"] == 0.3

    def test_반복_조절이_부동소수_찌꺼기를_남기지_않는다(self, player):
        for _ in range(3):
            player._nudge_subtitle_scale(0.1)
        assert player._subtitle_font_scale == 1.3
        for _ in range(3):
            player._nudge_subtitle_bottom(0.02)
        assert player._subtitle_bottom_ratio == 0.16


class TestSavedPrefsAtStartup:
    """C1 회귀: 생성자가 설정값을 필드에만 담고 오버레이에 밀어 넣지 않았다.

    그래서 config 에 2.0 이 저장돼 있어도 화면 자막은 1.0 크기로 뜨고, 첫 Ctrl+휠에서
    보이는 크기가 1.0 → 2.1 로 튀었다.
    """

    def test_저장된_크기_위치가_인라인_오버레이에_반영된다(
        self, qapp_instance, isolated_subtitle_settings, monkeypatch
    ):
        import config.settings as settings

        monkeypatch.setattr(settings, "SUBTITLE_FONT_SCALE", 2.0)
        monkeypatch.setattr(settings, "SUBTITLE_BOTTOM_RATIO", 0.30)
        p = InlinePlayer()
        try:
            assert p._subtitle.font_scale == pytest.approx(2.0)
            assert p._subtitle.bottom_ratio == pytest.approx(0.30)
        finally:
            p.stop()
            p._prefs_save_timer.stop()
            p._transient_timer.stop()
            p.deleteLater()

    def test_기본값이면_그대로_기본값이다(self, player):
        assert player._subtitle.font_scale == LyricsOverlay.FONT_SCALE_DEFAULT
        assert player._subtitle.bottom_ratio == LyricsOverlay.BOTTOM_RATIO_DEFAULT


class TestAdjustFeedback:
    """I2 회귀: 조절 피드백이 인라인 상태 라벨에만 있어 전체화면·PiP 에서는 보이지 않았다.

    가사 줄이 안 뜨는 구간에서 조절하면 화면에 아무 변화가 없어(설계 §3.8) 먹었는지
    알 수 없다 — 그래서 세 창이 모두 갖고 있는 오버레이가 문구를 직접 그린다.
    """

    def test_전체화면_오버레이에_문구가_뜬다(self, player):
        player.set_lyrics(_track())
        player._enter_fullscreen()
        player._nudge_subtitle_scale(0.1)
        assert player._fs_win.subtitle.notice_text == "자막 크기 110%"
        player._exit_fullscreen()

    def test_pip_오버레이에_문구가_뜬다(self, player):
        player.set_lyrics(_track())
        player._enter_pip()
        player._nudge_subtitle_bottom(0.02)
        assert player._pip_win.subtitle.notice_text == "자막 위치 12%"
        player._exit_pip()

    def test_인라인_오버레이에도_문구가_뜬다(self, player):
        player._nudge_subtitle_scale(0.1)
        assert player._subtitle.notice_text == "자막 크기 110%"

    def test_문구는_시간이_지나면_사라진다(self, player):
        player._show_transient("자막 크기 110%", ms=10)
        QTest.qWait(150)
        assert player._subtitle.notice_text == ""
        assert player._status_lbl.isHidden() is True

    def test_진행_중이던_안내_문구를_복원한다(self, player):
        """M3 회귀: 임시 문구가 '스트림 URL 가져오는 중…'을 덮고 지워 버렸다."""
        player._status_lbl.setText("스트림 URL 가져오는 중…")
        player._status_lbl.show()
        player._show_transient("자막 크기 110%", ms=10)
        assert player._status_lbl.text() == "자막 크기 110%"
        QTest.qWait(150)
        assert player._status_lbl.text() == "스트림 URL 가져오는 중…"
        assert player._status_lbl.isHidden() is False


class TestResetMenuReachability:
    """I3 회귀: 조절은 아무 영상에서나 되는데 초기화 메뉴는 싱크 가사가 있을 때만 열렸다.

    비(非)노래 영상에서 크기를 3.0 까지 올리면 그 값이 전역으로 저장되는데, 되돌릴
    방법이 없었다. 값이 기본값이 아니면 가사가 없어도 메뉴를 연다(초기화 항목만).
    """

    def test_가사가_없어도_값이_바뀌었으면_메뉴가_열린다(self, player):
        player._nudge_subtitle_scale(0.5)      # 가사 없는 영상에서 조절
        assert player._bar._btn_cc.isEnabled() is True
        menu = player._bar._build_subtitle_menu()
        assert menu is not None
        assert [a.text() for a in menu.actions()] == ["자막 크기·위치 초기화"]
        menu.deleteLater()

    def test_기본값이고_가사도_없으면_메뉴가_안_열린다(self, player):
        assert player._bar._btn_cc.isEnabled() is False
        assert player._bar._build_subtitle_menu() is None

    def test_가사가_있으면_오프셋_항목도_함께_나온다(self, player):
        player.set_lyrics(_track())
        menu = player._bar._build_subtitle_menu()
        labels = [a.text() for a in menu.actions()]
        assert "자막 크기·위치 초기화" in labels
        assert any("0.25초" in t for t in labels)
        menu.deleteLater()

    def test_초기화하면_다시_비활성으로_돌아간다(self, player):
        player._nudge_subtitle_scale(0.5)
        player._reset_subtitle_prefs()
        assert player._bar._btn_cc.isEnabled() is False

    def test_분리창_바에도_같은_조건이_전달된다(self, player):
        player._nudge_subtitle_scale(0.5)
        player._enter_fullscreen()
        assert player._fs_win.bar._btn_cc.isEnabled() is True
        assert player._fs_win.bar._build_subtitle_menu() is not None
        player._exit_fullscreen()
