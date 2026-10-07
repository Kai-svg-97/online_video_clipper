"""통계 화면(A6) — 처음 보일 때 집계, 채널 행 상한(+더 보기), 테마 변경은 다시 칠하기만.

배치 5 계획(.omc/research/perf/test_plan.md 5.2)대로다. 기대하는 구현 계약:

- 생성자는 집계 핸들러를 부르지 않는다. 첫 표시(showEvent)에 1회, 재표시에는 부르지 않는다.
- 채널 행은 `StatsPanel.CHANNEL_ROWS_MAX`개까지만 만들고(objectName `statsChannelRow`),
  넘으면 "더 보기"(objectName `statsMoreChannels`)가 보인다. 누르면 **다음 묶음만** 붙는다.
- 테마 슬롯 `_on_theme_changed(tokens)`는 핸들러를 부르지 않고 기존 행 위젯을 재사용한 채
  색만 바꾼다. 숨은 상태에서는 아무것도 하지 않고, 표시되는 순간 현재 테마로 칠한다.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from application.library.dtos import (
    CategoryStatDTO,
    ChannelCategoryStatDTO,
    ChannelStatDTO,
    LibraryStatsDTO,
)
from gui.panels.stats_panel import StatsPanel
from gui.themes.manager import ThemeManager
from gui.themes.tokens import PRESETS

ROW_NAME = "statsChannelRow"
MORE_NAME = "statsMoreChannels"


def _rows_max() -> int:
    """행 상한 — 구현 전에는 속성이 없어 AttributeError로 실패한다(기능 부재)."""
    return StatsPanel.CHANNEL_ROWS_MAX


def _channel(i: int) -> ChannelStatDTO:
    return ChannelStatDTO(
        channel_name=f"채널{i:04d}",
        total=1000 - i,
        categories=[
            ChannelCategoryStatDTO(category_id=None, category_path="IT > News", count=1)
        ],
        channel_url="",
    )


def _dto(n_channels: int) -> LibraryStatsDTO:
    return LibraryStatsDTO(
        total_videos=10,
        total_duration_sec=3600,
        watched_count=1,
        favorite_count=2,
        category_stats=[CategoryStatDTO(name="IT", count=3)],
        total_downloads=4,
        total_download_bytes=1024,
        channel_stats=[_channel(i) for i in range(n_channels)],
    )


@pytest.fixture
def isolated_theme(qapp_instance):
    """싱글턴 ThemeManager를 일회용으로 갈아 끼운다(패널의 연결이 전역에 남지 않게)."""
    saved = ThemeManager._instance
    ThemeManager._instance = None
    ThemeManager.instance()
    try:
        yield ThemeManager.instance()
    finally:
        ThemeManager._instance = saved


def _make(qtbot, isolated_theme, n: int):
    handler = MagicMock()
    handler.handle.return_value = _dto(n)
    panel = StatsPanel(handler)
    qtbot.addWidget(panel)
    return panel, handler


def _show(qtbot, panel) -> None:
    panel.show()
    qtbot.waitExposed(panel)
    QApplication.processEvents()


def _rows(panel) -> list[QWidget]:
    return [w for w in panel.findChildren(QWidget, ROW_NAME)]


def _row_name(row: QWidget) -> str:
    for lbl in row.findChildren(QLabel):
        if lbl.text().startswith("채널"):
            return lbl.text()
    for btn in row.findChildren(QPushButton):
        if btn.text().startswith("채널"):
            return btn.text()
    raise AssertionError("행에서 채널 이름을 찾지 못했다")


def _more(panel):
    return panel.findChild(QPushButton, MORE_NAME)


def _other_preset(current):
    """현재와 행 색(bg_elevated·border_muted)이 다른 프리셋."""
    for tokens in PRESETS.values():
        if (
            tokens.bg_elevated != current.bg_elevated
            and tokens.border_muted != current.border_muted
        ):
            return tokens
    raise AssertionError("색이 다른 프리셋이 없다")


class TestLazyAggregation:
    def test_construction_does_not_aggregate(self, qtbot, isolated_theme):
        panel, handler = _make(qtbot, isolated_theme, 3)
        QApplication.processEvents()
        QApplication.processEvents()
        assert handler.handle.call_count == 0

    def test_first_show_aggregates_once_and_reshow_does_not(self, qtbot, isolated_theme):
        panel, handler = _make(qtbot, isolated_theme, 3)
        _show(qtbot, panel)
        assert handler.handle.call_count == 1
        panel.hide()
        panel.show()
        QApplication.processEvents()
        assert handler.handle.call_count == 1

    def test_refresh_button_aggregates_again(self, qtbot, isolated_theme):
        panel, handler = _make(qtbot, isolated_theme, 3)
        _show(qtbot, panel)
        btn = next(
            b for b in panel.findChildren(QPushButton) if b.text() == "새로고침"
        )
        qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)
        assert handler.handle.call_count == 2

    def test_hidden_theme_change_does_not_aggregate(self, qtbot, isolated_theme):
        """숨은 상태의 테마 변경은 조회도, 예외도 없다."""
        panel, handler = _make(qtbot, isolated_theme, 3)
        other = _other_preset(isolated_theme.current())
        panel._on_theme_changed(other)
        QApplication.processEvents()
        assert handler.handle.call_count == 0

    def test_hidden_theme_change_then_show_paints_current_theme(
        self, qtbot, isolated_theme, monkeypatch
    ):
        panel, handler = _make(qtbot, isolated_theme, 3)
        other = _other_preset(isolated_theme.current())
        monkeypatch.setattr(isolated_theme, "current", lambda: other)
        panel._on_theme_changed(other)
        _show(qtbot, panel)
        rows = _rows(panel)
        assert rows, "행이 만들어지지 않았다"
        assert other.bg_elevated in rows[0].styleSheet()


class TestRowLimit:
    @pytest.mark.parametrize("which", ["zero", "max", "max_plus_1", "400"])
    def test_row_count_and_more_button(self, qtbot, isolated_theme, which):
        mx = _rows_max()
        n = {"zero": 0, "max": mx, "max_plus_1": mx + 1, "400": 400}[which]
        panel, _ = _make(qtbot, isolated_theme, n)
        _show(qtbot, panel)
        assert len(_rows(panel)) == min(n, mx)
        more = _more(panel)
        if n > mx:
            assert more is not None and more.isVisible()
        else:
            assert more is None or not more.isVisible()

    def test_more_adds_only_next_batch_in_dto_order(self, qtbot, isolated_theme):
        mx = _rows_max()
        n = 400
        panel, _ = _make(qtbot, isolated_theme, n)
        _show(qtbot, panel)
        qtbot.mouseClick(_more(panel), Qt.MouseButton.LeftButton)
        QApplication.processEvents()
        rows = _rows(panel)
        assert len(rows) == min(n, 2 * mx)  # 전부가 아니라 다음 묶음만
        assert _row_name(rows[0]) == "채널0000"
        assert _row_name(rows[-1]) == f"채널{len(rows) - 1:04d}"
        assert [_row_name(r) for r in rows] == [f"채널{i:04d}" for i in range(len(rows))]

    def test_more_hides_when_exhausted(self, qtbot, isolated_theme):
        mx = _rows_max()
        n = mx + 10
        panel, _ = _make(qtbot, isolated_theme, n)
        _show(qtbot, panel)
        qtbot.mouseClick(_more(panel), Qt.MouseButton.LeftButton)
        QApplication.processEvents()
        assert len(_rows(panel)) == n
        more = _more(panel)
        assert more is None or not more.isVisible()


class TestThemeRepaintOnly:
    def test_theme_slot_reuses_rows_and_recolors(self, qtbot, isolated_theme, monkeypatch):
        panel, handler = _make(qtbot, isolated_theme, 5)
        _show(qtbot, panel)
        rows = _rows(panel)
        assert rows
        ids_before = [id(w) for w in rows]
        calls_before = handler.handle.call_count
        other = _other_preset(isolated_theme.current())
        # 슬롯이 인자를 무시하고 ThemeManager.current()를 읽는 구현도 허용한다.
        monkeypatch.setattr(isolated_theme, "current", lambda: other)
        panel._on_theme_changed(other)
        QApplication.processEvents()
        assert handler.handle.call_count == calls_before
        assert [id(w) for w in _rows(panel)] == ids_before
        assert other.bg_elevated in _rows(panel)[0].styleSheet()

    def test_theme_changed_signal_does_not_aggregate(self, qtbot, isolated_theme):
        """실제 시그널 경로 — `theme_changed`를 방출해도 다시 조회하지 않는다."""
        panel, handler = _make(qtbot, isolated_theme, 5)
        _show(qtbot, panel)
        calls_before = handler.handle.call_count
        isolated_theme._apply_tokens(
            _other_preset(isolated_theme.current()), save=False, animate=False
        )
        QApplication.processEvents()
        assert handler.handle.call_count == calls_before


class TestCategorySelected:
    def test_category_link_emits_category_selected(self, qtbot, isolated_theme):
        from uuid import uuid4

        cid = uuid4()
        handler = MagicMock()
        dto = _dto(1)
        dto.channel_stats[0].categories[0] = ChannelCategoryStatDTO(
            category_id=cid, category_path="IT > News", count=1
        )
        handler.handle.return_value = dto
        panel = StatsPanel(handler)
        qtbot.addWidget(panel)
        _show(qtbot, panel)
        link = next(b for b in panel.findChildren(QPushButton) if "IT > News" in b.text())
        with qtbot.waitSignal(panel.category_selected, timeout=2000) as blocker:
            qtbot.mouseClick(link, Qt.MouseButton.LeftButton)
        assert blocker.args == [cid]
