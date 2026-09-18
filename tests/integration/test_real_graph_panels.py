"""진짜 조립 루트 + 진짜 SQLite 로 화면을 띄워 본다.

## 왜 목(mock)으로는 부족한가

`tests/gui/`의 패널 테스트는 뷰모델을 가짜로 바꾼다. 그래서 **화면 안쪽 논리**는
잘 잡지만, "조립 루트가 만든 진짜 뷰모델과 화면이 서로 맞물리는가"는 못 잡는다.
이번 세션에서 실제로 새어 나간 것들이 전부 그 틈이었다:

* 다운로드 카드가 DTO에 없는 속성을 읽어 **앱이 통째로 죽었다**(가짜 DTO를 쓰던
  테스트는 통과했다).
* 라이브러리가 51번째 영상부터 보여주지 않았다(`load_next_page()`를 아무도 안 불렀다).
* 게이트에 걸린 다운로드가 0%로 떠 멈춘 것처럼 보였다.

셋 다 **진짜 그래프로 화면을 띄워 보고서야** 드러났다. 그 검증을 임시 스크립트로
두면 세션이 끝날 때 사라지므로, 여기에 자산으로 남긴다.

## 이 파일이 지키는 것

조립 루트가 만든 뷰모델을 그대로 받아 실제 패널을 띄우고, **사용자가 보는 결과**를
확인한다. 값 계산이 맞는지는 각 기능의 단위 테스트가 본다.
"""

from __future__ import annotations

from datetime import time as dtime

import pytest

from domain.library.aggregates import VideoAggregate
from domain.library.entities import Category
from domain.library.value_objects import Duration, VideoUrl
from infrastructure.persistence.database import Database
from infrastructure.persistence.sqlite_video_repository import SqliteVideoRepository


@pytest.fixture
def db(tmp_path):
    """임시 DB — 실사용 라이브러리를 건드리지 않는다."""
    d = Database(path=tmp_path / "panels.db")
    d.initialize()
    return d


@pytest.fixture
def graph(db, qtbot):
    """진짜 조립 루트."""
    import dataclasses  # noqa: PLC0415

    from bootstrap import build_app_graph  # noqa: PLC0415 (무거운 임포트)

    g = build_app_graph(db)
    yield g
    # 종료 시 실행 중 QThread가 남으면 Qt가 프로세스를 죽인다(CLAUDE.md).
    # 하나가 터져도 나머지를 계속 정리한다 — 중단하면 남은 워커가 프로세스를 끌어내린다.
    for field in dataclasses.fields(g.view_models):
        vm = getattr(g.view_models, field.name, None)
        shutdown = getattr(vm, "shutdown", None)
        if callable(shutdown):
            try:
                shutdown()
            except Exception:  # noqa: BLE001 - 정리 경로는 멈추지 않는다
                pass


# ──────────────────────────────────────────────────────────────────
# 설정 — 음성 인식 모델 선택
# ──────────────────────────────────────────────────────────────────
class TestSettingsWithRealGraph:
    @pytest.fixture
    def panel(self, graph, qtbot):
        from gui.panels.settings_panel import SettingsPanel  # noqa: PLC0415

        p = SettingsPanel(subtitle_vm=graph.view_models.subtitle)
        qtbot.addWidget(p)
        return p

    def test_모델_선택이_진짜_뷰모델과_맞물린다(self, panel, graph):
        """콤보가 뜨고, 지금 설정된 값이 실제로 선택돼 있다."""
        assert panel._asr_model_combo.count() == 3
        assert (
            panel._asr_model_combo.currentData()
            == graph.view_models.subtitle.transcribe_model_key
        )

    def test_고른_모델의_설명과_보유_안내가_채워진다(self, panel):
        assert panel._asr_model_note.text()
        assert panel._asr_installed_lbl.text()

    def test_설정_화면을_열어도_추론_엔진이_올라오지_않는다(self, panel):
        """`faster_whisper`는 ctranslate2·onnxruntime까지 끌고 올라온다(수백 MB).

        전사를 한 번도 쓰지 않는 사용자가 설정 화면을 여는 것만으로 그 값을 치르면
        안 된다. 모델 목록·용량 판정을 파일 기반으로 둔 이유가 이것이다.
        """
        import sys  # noqa: PLC0415

        heavy = [
            m for m in ("faster_whisper", "ctranslate2", "onnxruntime")
            if m in sys.modules
        ]
        assert heavy == []


# ──────────────────────────────────────────────────────────────────
# 다운로드 — 게이트에 걸린 작업을 화면이 어떻게 말하는가
# ──────────────────────────────────────────────────────────────────
class TestDownloadGateWithRealGraph:
    @pytest.fixture
    def vm(self, graph, monkeypatch):
        v = graph.view_models.download
        # 진짜로 받으러 가지 않는다. 라이브 확인도 네트워크라 끈다.
        monkeypatch.setattr(v, "_launch", lambda jid: None)
        monkeypatch.setattr(v, "_live_status_fn", None, raising=False)
        # 예약 시간대를 닫아 게이트가 실제로 붙들게 만든다(정오 고정).
        from config import settings as cfg  # noqa: PLC0415
        import gui.view_models.download_vm as dvm  # noqa: PLC0415

        monkeypatch.setattr(cfg, "DOWNLOAD_WINDOW_ENABLED", True, raising=False)
        monkeypatch.setattr(cfg, "DOWNLOAD_WINDOW_START", 23, raising=False)
        monkeypatch.setattr(cfg, "DOWNLOAD_WINDOW_END", 7, raising=False)
        frozen = type("T", (), {"time": lambda _s=None: dtime(12, 0)})()
        monkeypatch.setattr(
            dvm, "datetime", type("D", (), {"now": staticmethod(lambda: frozen)})
        )
        return v

    @pytest.fixture
    def panel(self, vm, qtbot):
        from gui.panels.download_panel import DownloadPanel  # noqa: PLC0415

        p = DownloadPanel(vm)
        qtbot.addWidget(p)
        for i in range(3):
            vm.start_download(f"https://youtu.be/gate{i:07d}", f"영상 {i}")
        p.refresh()
        return p

    def test_시간대가_닫히면_하나도_시작하지_않는다(self, panel, vm):
        assert vm.waiting_count == 3
        assert vm.recording_count == 0

    def test_기다리는_이유를_화면이_말한다(self, panel):
        """0%로만 떠 있으면 고장과 구분이 안 된다."""
        assert panel._waiting_lbl.isHidden() is False
        assert "23시~7시" in panel._waiting_lbl.text()

    def test_카드가_대기_중으로_그려진다(self, panel):
        from gui.panels.download_panel import _HistoryModel  # noqa: PLC0415

        model = panel._list.model()
        waiting = sum(
            1 for r in range(model.rowCount())
            if model.data(model.index(r, 0), _HistoryModel.IsWaitingRole)
        )
        assert waiting == 3

    def test_취소하면_대기에서_빠진다(self, panel, vm):
        """그전에는 멈출 길이 없어 앱을 꺼야 했다."""
        target = sorted(vm.waiting_ids)[0]

        vm.cancel_download(target)
        panel.refresh()

        assert target not in vm.waiting_ids
        assert vm.waiting_count == 2
        assert "2건" in panel._waiting_lbl.text()

    def test_시간대가_열리면_풀리고_안내가_사라진다(self, panel, vm, monkeypatch):
        from config import settings as cfg  # noqa: PLC0415

        started: list = []
        monkeypatch.setattr(vm, "_launch", lambda jid: started.append(jid))
        monkeypatch.setattr(cfg, "DOWNLOAD_WINDOW_ENABLED", False, raising=False)

        vm._pump()
        panel.refresh()

        assert vm.waiting_count == 0
        assert len(started) == 3
        assert panel._waiting_lbl.isHidden() is True


# ──────────────────────────────────────────────────────────────────
# 라이브러리 — 51번째 영상부터 보이는가
# ──────────────────────────────────────────────────────────────────
class TestLibraryPaginationWithRealGraph:
    TOTAL = 60          # 한 쪽(50)을 넘겨 다음 쪽이 필요한 수

    @pytest.fixture
    def category_id(self, db, graph):
        """영상 60개를 한 카테고리에 담는다 — 기본 필터가 '카테고리에 담긴 것만'이다."""
        repo = SqliteVideoRepository(db)
        cat = Category.create(name="테스트")
        repo.save_category(cat)
        for i in range(self.TOTAL):
            agg = VideoAggregate.create(
                url=VideoUrl(f"https://youtu.be/pg{i:09d}"),
                title=f"영상 {i:03d}",
                category_id=cat.id,
            )
            agg.update_metadata(duration=Duration(120))
            repo.save(agg)
        return cat.id

    @pytest.fixture
    def panel(self, graph, category_id, qtbot):
        from gui.panels.library_panel import LibraryPanel  # noqa: PLC0415

        p = LibraryPanel(vm=graph.view_models.library)
        qtbot.addWidget(p)
        p.resize(1200, 900)
        # **띄워야 한다** — 보이지 않는 위젯은 배치가 계산되지 않아 스크롤 범위가
        # 0으로 남고, 그러면 무한 스크롤 경로를 아예 밟지 못한다.
        p.show()
        qtbot.waitExposed(p)
        graph.view_models.library.set_category_filter(category_id)
        qtbot.waitUntil(lambda: len(graph.view_models.library.videos) > 0, timeout=5000)
        return p

    def test_첫_쪽은_한_쪽만_싣는다(self, panel, graph):
        """메모리 규칙 — 전체를 한 번에 올리지 않는다."""
        from config.settings import DEFAULT_PAGE_SIZE  # noqa: PLC0415

        assert len(graph.view_models.library.videos) == DEFAULT_PAGE_SIZE
        assert graph.view_models.library.has_more is True

    def test_바닥까지_내리면_나머지가_실린다(self, panel, graph, qtbot):
        """여기서 50에 멈춰 있었다 — 다음 쪽을 부르는 곳이 아무 데도 없었다."""
        vm = graph.view_models.library
        view = panel._view_stack.currentWidget()
        bar = view.verticalScrollBar()
        qtbot.waitUntil(lambda: bar.maximum() > 0, timeout=5000)

        bar.setValue(bar.maximum())

        qtbot.waitUntil(lambda: len(vm.videos) >= self.TOTAL, timeout=5000)
        assert vm.has_more is False

    def test_이어_붙일_뿐_앞_쪽을_버리지_않는다(self, panel, graph, qtbot):
        vm = graph.view_models.library
        first = vm.videos[0].id
        bar = panel._view_stack.currentWidget().verticalScrollBar()
        qtbot.waitUntil(lambda: bar.maximum() > 0, timeout=5000)

        bar.setValue(bar.maximum())

        qtbot.waitUntil(lambda: len(vm.videos) >= self.TOTAL, timeout=5000)
        assert vm.videos[0].id == first
