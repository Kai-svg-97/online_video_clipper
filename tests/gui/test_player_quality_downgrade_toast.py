"""병합 폴백 화질 강등 토스트 — 영상당 한 번, 병합 폴백·로컬 파일일 때만."""

from __future__ import annotations

import pytest

from gui.widgets.video_player import InlinePlayer

_PATH = "C:/videos/merged.mp4"


@pytest.fixture()
def player(qapp_instance, qtbot):
    p = InlinePlayer()
    qtbot.addWidget(p)
    p._video_url = "https://www.youtube.com/watch?v=x"
    yield p
    p._remux_url = ""
    p.stop()


@pytest.fixture()
def toasts(monkeypatch):
    calls: list[tuple] = []
    # 쓰는 쪽 모듈을 패치한다.
    monkeypatch.setattr(
        "gui.widgets.player.mixins.stream_source.show_toast",
        lambda *a, **k: calls.append(a),
    )
    return calls


def _setup(player, *, remux: bool = False, quality: str = "1080p"):
    player._prefer_remux = remux
    player._current_quality_short = quality


class TestQualityDowngradeToast:
    def test_병합_폴백에서_낮은_화질이면_한_번_알린다(self, player, toasts):
        _setup(player)
        player._on_stream_ready(_PATH, "360p", True, 0)
        assert len(toasts) == 1

    def test_같은_영상에서_다시_불러도_한_번만(self, player, toasts):
        _setup(player)
        player._on_stream_ready(_PATH, "360p", True, 0)
        player._on_stream_ready(_PATH, "360p", True, 0)
        assert len(toasts) == 1

    def test_리셋_후에는_다시_알릴_수_있다(self, player, toasts):
        _setup(player)
        player._on_stream_ready(_PATH, "360p", True, 0)
        player._reset_stream_mode()
        _setup(player)  # 리셋이 _prefer_remux를 True로 되돌리므로 병합 폴백 상태를 다시 만든다
        player._on_stream_ready(_PATH, "360p", True, 0)
        assert len(toasts) == 2

    def test_remux_선호면_알리지_않는다(self, player, toasts):
        _setup(player, remux=True)
        player._on_stream_ready(_PATH, "360p", True, 0)
        assert toasts == []

    def test_로컬_파일이_아니면_알리지_않는다(self, player, toasts):
        _setup(player)
        player._on_stream_ready("http://direct/video.mp4", "360p", False, 0)
        assert toasts == []

    def test_상한을_채웠으면_알리지_않는다(self, player, toasts):
        _setup(player, quality="360p")
        player._on_stream_ready(_PATH, "360p", True, 0)
        assert toasts == []

    def test_auto면_알리지_않는다(self, player, toasts):
        _setup(player, quality="auto")
        player._on_stream_ready(_PATH, "360p", True, 0)
        assert toasts == []
