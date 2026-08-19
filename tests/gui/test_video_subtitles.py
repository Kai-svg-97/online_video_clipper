"""영상 자막 — 두 트랙 동시 표시·언어 선택·자동 번역의 GUI 계약.

지키는 것:
* 자막 **두 칸**을 각각 고르고 **동시에** 보여 준다(원어 + 모국어).
* 대사가 없는 구간에서는 아무것도 뜨지 않는다(가사와 달리 끝 시각이 있다).
* 목록·내려받기는 네트워크라 결과가 늦게 온다 — 그 사이 다른 트랙/영상으로 넘어갔으면
  **늦게 온 결과는 버린다**.
* 전체화면·PiP 창에서도 같은 자막이 보인다(바 신호는 외부에서 배선해야 동작한다).
"""
from __future__ import annotations

import pytest

from gui.widgets.lyrics_overlay import LyricsOverlay
from gui.widgets.player.controls import _ControlBar
from gui.widgets.subtitle_track import SubtitleCue, SubtitleTrack
from gui.widgets.video_player import InlinePlayer
from infrastructure.subtitle.youtube_subtitles import SubtitleTrackInfo


@pytest.fixture(autouse=True)
def _no_config_writes(monkeypatch):
    """실사용 config.yaml을 건드리지 않는다."""
    import config.settings as settings
    monkeypatch.setattr(settings, "save_setting", lambda *a, **k: None)
    monkeypatch.setattr(settings, "VIDEO_SUBTITLE_LANG_1", "", raising=False)
    monkeypatch.setattr(settings, "VIDEO_SUBTITLE_LANG_2", "", raising=False)


def _track(*cues, offset_ms=0) -> SubtitleTrack:
    return SubtitleTrack([SubtitleCue(*c) for c in cues], offset_ms=offset_ms)


class TestSubtitleTrack:
    def test_구간_안에서만_보인다(self):
        track = _track((1000, 2000, "안녕"))

        assert track.text_at(999) == ""
        assert track.text_at(1000) == "안녕"
        assert track.text_at(1999) == "안녕"
        assert track.text_at(2000) == ""      # 끝나면 사라진다

    def test_대사_사이_빈_구간에는_아무것도_없다(self):
        """가사는 다음 줄까지 떠 있지만 영상 자막은 그러면 안 된다."""
        track = _track((0, 1000, "첫째"), (5000, 6000, "둘째"))

        assert track.text_at(3000) == ""

    def test_보정값만큼_밀린다(self):
        track = _track((1000, 2000, "안녕"), offset_ms=500)

        assert track.text_at(1200) == ""
        assert track.text_at(1600) == "안녕"

    def test_보정값은_한계까지만(self):
        track = _track((0, 1, "x"), offset_ms=10**9)

        assert track.offset_ms == 30_000

    def test_파서_출력을_그대로_받는다(self):
        track = SubtitleTrack.from_tuples([(0, 1000, "a"), (1000, 2000, "")])

        assert len(track) == 1        # 빈 텍스트는 버린다


class TestOverlayDualLines:
    def test_두_줄을_함께_보여_준다(self, qtbot):
        overlay = LyricsOverlay()
        qtbot.addWidget(overlay)

        overlay.set_subtitle_texts("Hello", "안녕하세요")

        assert overlay.subtitle_texts == ("Hello", "안녕하세요")

    def test_가사와_영상_자막은_서로를_지우지_않는다(self, qtbot):
        """둘 다 켜 두면 네 줄까지 나올 수 있다 — 어느 쪽도 다른 쪽을 밀어내지 않는다."""
        from gui.widgets.lyrics_overlay import LyricsCue

        overlay = LyricsOverlay()
        qtbot.addWidget(overlay)
        overlay.set_cue(LyricsCue(start_ms=0, original="가사", translation="번역"))

        overlay.set_subtitle_texts("Hello", "안녕")

        assert overlay.current_text == ("가사", "번역")
        assert overlay.subtitle_texts == ("Hello", "안녕")


class TestControlBarMenu:
    def test_자막이_없으면_버튼이_비활성(self, qtbot):
        bar = _ControlBar()
        qtbot.addWidget(bar)

        bar.set_video_subtitle_tracks([])

        assert not bar._btn_vsub.isEnabled()
        assert "없습니다" in bar._btn_vsub.toolTip()

    def test_트랙이_있으면_켜진다(self, qtbot):
        bar = _ControlBar()
        qtbot.addWidget(bar)

        bar.set_video_subtitle_tracks([SubtitleTrackInfo("ko", "한국어", "u", "json3", False)])

        assert bar._btn_vsub.isEnabled()

    def test_선택하면_글리프로_상태가_보인다(self, qtbot):
        bar = _ControlBar()
        qtbot.addWidget(bar)
        bar.set_video_subtitle_tracks([SubtitleTrackInfo("ko", "한국어", "u", "json3", False)])

        bar.set_video_subtitle_selection(0, "sub:ko:")

        assert bar._btn_vsub.text() == "CC"


class TestPlayerSelection:
    def _player(self, qtbot) -> InlinePlayer:
        player = InlinePlayer()
        qtbot.addWidget(player)
        player._video_url = "https://youtu.be/abc"
        player._vsub_available = [
            SubtitleTrackInfo("en", "English", "https://x/en", "json3", True),
            SubtitleTrackInfo("ko", "한국어", "https://x/ko", "json3", False),
        ]
        for bar in player._all_bars():
            bar.set_video_subtitle_tracks(player._vsub_available)
        return player

    def test_두_칸에_서로_다른_언어를_켤_수_있다(self, qtbot, monkeypatch):
        player = self._player(qtbot)
        asked: list = []
        monkeypatch.setattr(player, "_fetch_video_subtitle",
                            lambda slot, base: asked.append((slot, base.lang)))

        player._select_video_subtitle(0, "auto:en:")
        player._select_video_subtitle(1, "sub:ko:")

        assert asked == [(0, "en"), (1, "ko")]
        assert player._vsub_keys == ["auto:en:", "sub:ko:"]

    def test_끄면_그_칸만_비운다(self, qtbot, monkeypatch):
        player = self._player(qtbot)
        monkeypatch.setattr(player, "_fetch_video_subtitle", lambda *a: None)
        player._select_video_subtitle(0, "auto:en:")
        player._vsub_tracks[0] = _track((0, 1000, "hi"))

        player._select_video_subtitle(0, "")

        assert player._vsub_keys[0] == "" and player._vsub_tracks[0] is None

    def test_번역만_골라도_트랙이_잡힌다(self, qtbot, monkeypatch):
        """'번역만 골랐는데 아무 일도 없다'가 되지 않아야 한다."""
        player = self._player(qtbot)
        asked: list = []
        monkeypatch.setattr(player, "_fetch_video_subtitle",
                            lambda slot, base: asked.append((slot, base.lang)))

        player._translate_video_subtitle(0, "ko")

        assert player._vsub_langs[0] == "ko"
        assert asked == [(0, "en")]    # 자동 생성 트랙을 기준으로 삼는다

    def test_번역_대상이_내려받기에_실린다(self, qtbot, monkeypatch):
        """번역은 트랙의 변형이다 — 내려받기에 대상 언어가 실려야 한다."""
        player = self._player(qtbot)
        made: list = []
        # 워커를 띄우지 않고 '무엇을 받으러 가는지'만 확인한다(네트워크 금지).
        monkeypatch.setattr(
            player, "_start_subtitle_fetch",
            lambda slot, track_info: made.append(track_info),
        )
        player._vsub_langs[0] = "ko"

        player._fetch_video_subtitle(0, player._vsub_available[0])

        assert made and made[0].translate_to == "ko"

    def test_늦게_온_결과는_버린다(self, qtbot, monkeypatch):
        """다른 트랙을 고른 뒤 도착한 자막이 화면을 덮으면 안 된다."""
        player = self._player(qtbot)
        monkeypatch.setattr(player, "_fetch_video_subtitle", lambda *a: None)
        player._select_video_subtitle(0, "sub:ko:")

        player._on_video_subtitle_cues(0, "auto:en:", [(0, 1000, "늦은 결과")])

        assert player._vsub_tracks[0] is None

    def test_받은_자막이_화면에_붙는다(self, qtbot, monkeypatch):
        player = self._player(qtbot)
        monkeypatch.setattr(player, "_fetch_video_subtitle", lambda *a: None)
        player._select_video_subtitle(0, "sub:ko:")

        player._on_video_subtitle_cues(0, "sub:ko:", [(0, 5000, "안녕")])

        assert player._vsub_tracks[0] is not None
        assert player._subtitle.subtitle_texts[0] == "안녕"

    def test_영상이_바뀌면_이전_자막을_지운다(self, qtbot, monkeypatch):
        player = self._player(qtbot)
        monkeypatch.setattr(player, "_fetch_video_subtitle", lambda *a: None)
        player._select_video_subtitle(0, "sub:ko:")
        player._on_video_subtitle_cues(0, "sub:ko:", [(0, 5000, "안녕")])

        player._clear_video_subtitles()

        assert player._vsub_tracks == [None, None]
        assert player._subtitle.subtitle_texts == ("", "")

    def test_지난번_언어를_다음_영상에도_이어_켠다(self, qtbot, monkeypatch):
        player = self._player(qtbot)
        asked: list = []
        monkeypatch.setattr(player, "_fetch_video_subtitle",
                            lambda slot, base: asked.append((slot, base.lang)))
        player._vsub_pref_lang = ["ko", ""]

        player._restore_preferred_subtitles()

        assert asked == [(0, "ko")]

    def test_목록_결과가_다른_영상_것이면_버린다(self, qtbot):
        player = self._player(qtbot)

        player._on_video_subtitle_list("https://youtu.be/other", [])

        assert len(player._vsub_available) == 2   # 그대로


class TestPositionUpdate:
    def test_재생_위치에_맞춰_두_줄이_함께_바뀐다(self, qtbot):
        player = InlinePlayer()
        qtbot.addWidget(player)
        player._vsub_tracks = [
            _track((0, 2000, "Hello"), (3000, 5000, "Bye")),
            _track((0, 2000, "안녕"), (3000, 5000, "잘 가")),
        ]

        player._apply_video_subtitle_position(1000)
        assert player._subtitle.subtitle_texts == ("Hello", "안녕")

        player._apply_video_subtitle_position(4000)
        assert player._subtitle.subtitle_texts == ("Bye", "잘 가")

    def test_대사가_없는_구간에서는_비운다(self, qtbot):
        player = InlinePlayer()
        qtbot.addWidget(player)
        player._vsub_tracks = [_track((0, 1000, "Hello")), None]

        player._apply_video_subtitle_position(500)
        player._apply_video_subtitle_position(2000)

        assert player._subtitle.subtitle_texts == ("", "")
