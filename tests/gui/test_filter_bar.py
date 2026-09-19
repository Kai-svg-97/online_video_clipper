"""복합 필터 막대 — 값 변환과 신호.

엔진에는 처음부터 있었는데 **화면에서 넘기는 곳이 없어** 쓸 수 없던 필터다. 이 막대가
그 연결이라, 여기서 보는 것은 "고른 것이 뷰모델이 받는 값으로 정확히 바뀌는가"다.

새로 생기는 함정 둘:

1. **초기화가 신호를 여섯 번 내면 조회도 여섯 번 나간다.** 칸마다 신호를 내는 구조라
   한꺼번에 되돌릴 때 막아야 한다.
2. **걸린 필터를 접힌 상태에서도 알 수 있어야 한다.** 그러지 않으면 "왜 영상이 몇 개
   없지"의 원인을 찾을 길이 없다.
"""

from __future__ import annotations

import pytest

from gui.panels.library.filter_bar import FilterBar


@pytest.fixture
def bar(qtbot):
    w = FilterBar()
    qtbot.addWidget(w)
    return w


def _pick(combo, key: str) -> None:
    combo.setCurrentIndex(combo.findData(key))


class TestDefaults:
    def test_처음에는_아무것도_안_걸려_있다(self, bar):
        assert bar.active_count() == 0
        assert bar.summary() == ""

    def test_기본값은_전부_제한_없음이다(self, bar):
        f = bar.filters()
        assert f["published_from"] == ""
        assert f["channel_name"] == ""
        assert f["downloaded"] is None
        assert f["watched"] is None
        assert f["min_duration_sec"] is None
        assert f["max_duration_sec"] is None
        assert f["favorite_only"] is False


class TestValues:
    def test_날짜_프리셋이_날짜로_바뀐다(self, bar):
        _pick(bar._date, "7d")
        assert bar.filters()["published_from"]          # 비어 있지 않다
        assert bar.filters()["published_to"] == ""      # 끝은 열어 둔다

    def test_길이_프리셋이_초로_바뀐다(self, bar):
        _pick(bar._duration, "long")
        f = bar.filters()
        assert f["min_duration_sec"] == 1200
        assert f["max_duration_sec"] is None

    def test_다운로드_여부가_불리언으로_바뀐다(self, bar):
        _pick(bar._download, "no")
        assert bar.filters()["downloaded"] is False

    def test_채널은_앞뒤_공백을_턴다(self, bar):
        bar._channel.setText("  침착맨  ")
        assert bar.filters()["channel_name"] == "침착맨"

    def test_뷰모델이_받는_이름과_맞는다(self, bar):
        """`set_advanced_filters(**filters())`로 그대로 넘어가야 한다."""
        from gui.view_models.library_vm import LibraryViewModel

        import inspect

        params = set(inspect.signature(LibraryViewModel.set_advanced_filters).parameters)
        assert set(bar.filters()) <= params


class TestActiveCount:
    def test_고른_만큼_센다(self, bar):
        _pick(bar._date, "30d")
        _pick(bar._duration, "short")
        bar._channel.setText("채널")
        bar._favorite.setChecked(True)
        assert bar.active_count() == 4

    def test_전체를_고르면_세지_않는다(self, bar):
        _pick(bar._date, "30d")
        _pick(bar._date, "all")
        assert bar.active_count() == 0

    def test_공백뿐인_채널은_세지_않는다(self, bar):
        bar._channel.setText("   ")
        assert bar.active_count() == 0

    def test_무엇으로_좁혔는지_한_줄로_말한다(self, bar):
        """목록이 비었을 때 왜 비었는지 알려 주는 근거다."""
        _pick(bar._date, "7d")
        _pick(bar._download, "yes")
        assert "최근 1주" in bar.summary()
        assert "받아 둔 것만" in bar.summary()


class TestSignals:
    def test_값을_바꾸면_알린다(self, bar, qtbot):
        with qtbot.waitSignal(bar.changed, timeout=1000):
            _pick(bar._date, "7d")

    def test_초기화는_신호를_한_번만_낸다(self, bar, qtbot):
        """칸마다 내면 같은 목록을 여섯 번 읽는다."""
        _pick(bar._date, "7d")
        _pick(bar._duration, "long")
        _pick(bar._download, "yes")
        _pick(bar._watched, "no")
        bar._channel.setText("채널")
        bar._favorite.setChecked(True)

        emitted: list = []
        bar.changed.connect(lambda: emitted.append(1))
        bar.reset()

        assert len(emitted) == 1

    def test_초기화하면_전부_풀린다(self, bar):
        _pick(bar._date, "7d")
        bar._channel.setText("채널")
        bar._favorite.setChecked(True)

        bar.reset()

        assert bar.active_count() == 0
        assert bar.filters()["published_from"] == ""
