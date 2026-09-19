"""저장된 검색 — 막대 복원과 저장용 값.

여기서 고정하는 함정은 **무엇을 저장하느냐**다. 화면이 `filters()`(값으로 푼 것)를
저장하면 "최근 1주"가 저장한 그 주로 얼어붙는다. 저장에는 `condition_keys()`(프리셋
키)를 써야 하고, 되부를 때 오늘 기준으로 다시 푼다.

되부르기는 조건이 예닐곱 개라 **신호를 한 번만** 내야 한다 — 칸마다 내면 되부르기
한 번에 목록 조회가 예닐곱 번 나간다.
"""

from __future__ import annotations

import pytest

from domain.library.saved_search import SavedSearch
from gui.panels.library.filter_bar import FilterBar


@pytest.fixture
def bar(qtbot):
    w = FilterBar()
    qtbot.addWidget(w)
    return w


def _pick(combo, key: str) -> None:
    combo.setCurrentIndex(combo.findData(key))


class TestConditionKeys:
    def test_저장에는_프리셋_키를_준다(self, bar):
        """값으로 저장하면 '최근 1주'가 저장한 그 주로 얼어붙는다."""
        _pick(bar._date, "7d")
        _pick(bar._duration, "long")

        keys = bar.condition_keys()

        assert keys["date_key"] == "7d"
        assert keys["duration_key"] == "long"
        assert "published_from" not in keys      # 푼 값이 섞이면 안 된다

    def test_조회에는_푼_값을_준다(self, bar):
        """같은 상태에서 `filters()`는 엔진이 쓰는 값이어야 한다."""
        _pick(bar._date, "7d")
        assert bar.filters()["published_from"]

    def test_채널은_앞뒤_공백을_턴다(self, bar):
        bar._channel.setText("  침착맨 ")
        assert bar.condition_keys()["channel_name"] == "침착맨"

    def test_저장_키가_커맨드와_맞는다(self, bar):
        import inspect

        from application.library.saved_search_commands import SaveSearchCommand

        params = set(inspect.signature(SaveSearchCommand).parameters)
        assert set(bar.condition_keys()) <= params


class TestApplySaved:
    def test_막대가_저장된_대로_복원된다(self, bar):
        saved = SavedSearch(
            name="내 검색", date_key="30d", duration_key="short",
            download_key="yes", watched_key="no",
            channel_name="침착맨", favorite_only=True,
        )

        bar.apply_saved(saved)

        assert bar.condition_keys() == {
            "date_key": "30d",
            "duration_key": "short",
            "download_key": "yes",
            "watched_key": "no",
            "channel_name": "침착맨",
            "favorite_only": True,
        }

    def test_신호를_한_번만_낸다(self, bar):
        """칸마다 내면 되부르기 한 번에 조회가 예닐곱 번 나간다."""
        emitted: list = []
        bar.changed.connect(lambda: emitted.append(1))

        bar.apply_saved(SavedSearch(date_key="7d", duration_key="long",
                                    channel_name="채널", favorite_only=True))

        assert len(emitted) == 1

    def test_모르는_키는_전체로_떨어진다(self, bar):
        """앱 버전을 오르내리며 프리셋이 바뀌어도 되부르기가 죽지 않아야 한다."""
        bar.apply_saved(SavedSearch(date_key="지난주쯤", duration_key="적당히"))

        keys = bar.condition_keys()
        assert keys["date_key"] == "all"
        assert keys["duration_key"] == "all"

    def test_되부른_뒤_걸린_개수가_맞는다(self, bar):
        bar.apply_saved(SavedSearch(date_key="7d", channel_name="채널"))
        assert bar.active_count() == 2

    def test_빈_검색을_되부르면_전부_풀린다(self, bar):
        _pick(bar._date, "7d")
        bar._favorite.setChecked(True)

        bar.apply_saved(SavedSearch())

        assert bar.active_count() == 0


class TestSaveButton:
    def test_저장_버튼이_신호를_낸다(self, bar, qtbot):
        with qtbot.waitSignal(bar.save_requested, timeout=1000):
            bar._save.click()
