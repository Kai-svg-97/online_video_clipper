"""설정 화면의 자막 색인 섹션 — 시작/중지 토글과 결과 표시.

수백 건을 훑는 긴 작업이라 **그만둘 수 있는지**와 **지금 뭐 하는 중인지 보이는지**가
핵심이다. 그리고 뷰모델이 없는 진입점에서도 설정 화면은 열려야 한다.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QObject, pyqtSignal

from application.library.subtitle_commands import BulkIndexResult
from application.library.subtitle_queries import SubtitleCoverageDTO
from gui.panels.settings_panel import SettingsPanel


class _VM(QObject):
    bulk_progress = pyqtSignal(int, int, str)
    bulk_finished = pyqtSignal(object)

    def __init__(self, indexed=3, total=10):
        super().__init__()
        self._coverage = SubtitleCoverageDTO(indexed_videos=indexed, total_videos=total)
        self.is_bulk_running = False
        self.started = 0
        self.stopped = 0

    def coverage(self):
        return self._coverage

    def start_bulk_index(self):
        self.started += 1
        self.is_bulk_running = True
        return True

    def stop_bulk_index(self):
        self.stopped += 1


@pytest.fixture
def panel(qtbot):
    vm = _VM()
    p = SettingsPanel(subtitle_vm=vm)
    qtbot.addWidget(p)
    p.vm = vm            # type: ignore[attr-defined]
    return p


class TestCoverage:
    def test_현황을_한_줄로_보여준다(self, panel):
        text = panel._sub_cover_lbl.text()
        assert "10개 중 3개" in text
        assert "남은 7개" in text

    def test_뷰모델이_없으면_섹션을_만들지_않는다(self, qtbot):
        """다른 진입점에서 연 설정 화면도 열려야 한다."""
        p = SettingsPanel()
        qtbot.addWidget(p)
        assert not hasattr(p, "_sub_index_btn")


class TestStartStop:
    def test_버튼이_색인을_시작한다(self, panel):
        panel._sub_index_btn.click()
        assert panel.vm.started == 1
        assert panel._sub_index_btn.text() == "중지"
        # isVisible()은 창이 표시되지 않은 테스트에서 늘 False라 쓸 수 없다.
        # 우리가 고정하려는 것은 '진행률 막대를 명시적으로 띄웠는가'다.
        assert panel._sub_index_bar.isHidden() is False

    def test_돌고_있을_때_다시_누르면_중지한다(self, panel):
        panel._sub_index_btn.click()      # 시작
        panel._sub_index_btn.click()      # 중지
        assert panel.vm.stopped == 1
        assert not panel._sub_index_btn.isEnabled()

    def test_진행_상황이_보인다(self, panel):
        panel.vm.bulk_progress.emit(7, 40, "어떤 영상")
        assert panel._sub_index_bar.value() == 7
        assert panel._sub_index_bar.maximum() == 40
        assert "어떤 영상" in panel._sub_index_status.text()


class TestResult:
    def test_끝나면_집계를_알린다(self, panel):
        panel.vm.bulk_finished.emit(BulkIndexResult(indexed=12, no_subtitle=3))
        text = panel._sub_index_status.text()
        assert "12개 색인" in text
        assert "3개는 자막 없음" in text

    def test_중단되면_그렇게_알린다(self, panel):
        panel.vm.bulk_finished.emit(BulkIndexResult(indexed=2, stopped=True))
        assert "중단됨" in panel._sub_index_status.text()

    def test_실패하면_로그를_보라고_알린다(self, panel):
        panel.vm.bulk_finished.emit(None)
        assert "오류" in panel._sub_index_status.text()

    def test_끝나면_버튼이_되돌아온다(self, panel):
        panel._sub_index_btn.click()
        panel.vm.bulk_finished.emit(BulkIndexResult(indexed=1))
        assert panel._sub_index_btn.text() == "전체 자막 색인 시작"
        assert panel._sub_index_btn.isEnabled()

    def test_끝나면_현황을_다시_읽는다(self, panel):
        panel.vm._coverage = SubtitleCoverageDTO(indexed_videos=10, total_videos=10)
        panel.vm.bulk_finished.emit(BulkIndexResult(indexed=7))
        assert "남은 0개" in panel._sub_cover_lbl.text()
