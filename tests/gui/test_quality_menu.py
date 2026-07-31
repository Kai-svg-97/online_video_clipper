"""다운로드·재생 화질 메뉴가 영상이 실제로 제공하는 화질만 보여주는지 검증한다.

배경: 최대 1080p인 영상에도 4K 선택지가 나열됐다. 다운로드 포맷 문자열은
`height<=N` 이라 최대치를 넘는 항목은 같은 파일을 받으므로 무의미하다.
"""
from __future__ import annotations

import pytest

from gui.widgets.video_player import _ControlBar, _HEIGHT_CACHE, _cache_heights


@pytest.fixture
def bar(qtbot):
    b = _ControlBar()
    qtbot.addWidget(b)
    return b


def _menu_labels(bar) -> list[str]:
    """다운로드 메뉴를 열지 않고 항목 라벨만 얻는다(exec 은 모달이라 못 쓴다)."""
    from PyQt6.QtWidgets import QMenu

    labels: list[str] = []
    orig_exec = QMenu.exec

    def fake_exec(self, *args, **kwargs):
        for act in self.actions():
            sub = act.menu()
            if sub is not None:
                labels.extend(a.text() for a in sub.actions())
        return None

    QMenu.exec = fake_exec          # type: ignore[method-assign]
    try:
        bar.open_download_menu()
    finally:
        QMenu.exec = orig_exec      # type: ignore[method-assign]
    return labels


class TestDownloadMenuFiltering:
    def test_unknown_heights_shows_full_ladder(self, bar):
        """조회 실패·미확인이면 예전처럼 전체 목록 — 다운로드를 막지 않는다."""
        bar.set_available_heights(None)
        labels = _menu_labels(bar)
        assert any("2160p" in x for x in labels)
        assert any("1080p" in x for x in labels)

    def test_fhd_video_hides_4k(self, bar):
        bar.set_available_heights([1080, 720, 480, 360, 240, 144])
        labels = _menu_labels(bar)
        assert not any("2160p" in x for x in labels), "FHD 영상에 4K가 나열됐다"
        assert any("1080p" in x for x in labels)
        assert any("720p" in x for x in labels)

    def test_low_res_video_hides_everything_above(self, bar):
        bar.set_available_heights([360, 240, 144])
        labels = _menu_labels(bar)
        assert not any(q in x for x in labels for q in ("2160p", "1080p", "720p", "480p"))
        assert any("360p" in x for x in labels)

    def test_best_option_always_present_and_shows_max(self, bar):
        bar.set_available_heights([1080, 720])
        labels = _menu_labels(bar)
        assert "최고 화질  (1080p)" in labels

    def test_audio_options_unaffected(self, bar):
        bar.set_available_heights([360])
        labels = _menu_labels(bar)
        assert "MP3" in labels and "M4A" in labels

    def test_vertical_video_keeps_standard_ladder(self, bar):
        """세로 영상은 높이가 1920처럼 잡힌다 — 표준 화질이 사라지면 안 된다."""
        bar.set_available_heights([1920, 1280, 854, 640])
        labels = _menu_labels(bar)
        for q in ("1080p", "720p", "480p", "360p"):
            assert any(q in x for x in labels), f"{q} 가 빠졌다"


class TestPlaybackQualityMenu:
    def test_playback_menu_filters_too(self, bar, monkeypatch):
        from PyQt6.QtWidgets import QMenu

        seen: list[str] = []
        monkeypatch.setattr(QMenu, "exec", lambda self, *a, **k: None)
        orig_add = QMenu.addAction

        def spy(self, *args, **kwargs):
            act = orig_add(self, *args, **kwargs)
            if args and isinstance(args[0], str):
                seen.append(args[0])
            return act

        monkeypatch.setattr(QMenu, "addAction", spy)
        bar.set_available_heights([720, 480, 360])
        bar._show_quality_menu()

        assert not any("1080p" in x for x in seen), "재생 메뉴에 없는 화질이 떴다"
        assert any("720p" in x for x in seen)
        assert any("자동" in x for x in seen)


class TestHeightCache:
    def test_cache_is_bounded(self):
        _HEIGHT_CACHE.clear()
        for i in range(80):
            _cache_heights(f"https://youtu.be/v{i}", [1080])
        assert len(_HEIGHT_CACHE) <= 64
        # 최근 항목은 남아 있어야 한다
        assert "https://youtu.be/v79" in _HEIGHT_CACHE

    def test_blank_url_not_cached(self):
        _HEIGHT_CACHE.clear()
        _cache_heights("", [1080])
        assert not _HEIGHT_CACHE


class TestDownloadBusyState:
    def test_button_disabled_while_probing(self, bar):
        bar.set_download_busy(True)
        assert not bar._btn_dl.isEnabled()
        bar.set_download_busy(False)
        assert bar._btn_dl.isEnabled()
